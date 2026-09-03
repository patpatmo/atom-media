"""Atom Media — Web 服务入口（Flask + waitress）。

接口设计详见 README.md「API 一览」。
"""
import logging
import mimetypes
import os
import shutil
import threading
import time

from flask import (Flask, abort, jsonify, redirect, request, send_file,
                   send_from_directory)
from werkzeug.exceptions import HTTPException
from werkzeug.utils import safe_join

from . import __version__, config, database, icon, scanner, scraper, subtitles

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("atom.main")

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")

app = Flask(__name__, static_folder=None)
try:
    app.json.ensure_ascii = False
except Exception:
    app.config["JSON_AS_ASCII"] = False

# 补充常见容器格式的 MIME，保证 <video> 直连播放响应头正确
for _ext, _mime in {
    ".mkv": "video/x-matroska",
    ".ts": "video/mp2t",
    ".m2ts": "video/mp2t",
    ".avi": "video/x-msvideo",
    ".mov": "video/quicktime",
    ".rmvb": "application/vnd.rn-realmedia-vbr",
}.items():
    mimetypes.add_type(_mime, _ext)


# ---------- 统一错误输出（JSON） ----------
@app.errorhandler(HTTPException)
def _http_error(e: HTTPException):
    return jsonify({"error": e.description}), e.code


@app.errorhandler(Exception)
def _internal_error(e: Exception):
    log.exception("内部错误: %s", e)
    return jsonify({"error": f"服务器内部错误: {e}"}), 500


# ---------- 序列化 ----------
def _serialize(d: dict) -> dict:
    fp = d.get("file_path")
    d["file_name"] = os.path.basename(fp) if fp else ""
    if fp and os.path.isfile(fp):
        d["url"] = f"/api/stream/{d['id']}"
        d["file_exists"] = True
    else:
        d["url"] = d.get("play_url") or ""
        d["file_exists"] = False
    return d


# ---------- 静态页面 ----------
@app.get("/")
@app.get("/index.html")
def index():
    return send_from_directory(WEB_DIR, "index.html")


# 现代浏览器使用 SVG；老浏览器 / iOS 使用后端动态生成的 PNG/ICO
@app.get("/favicon.svg")
@app.get("/icon.svg")
def icons():
    return send_from_directory(WEB_DIR, "icon.svg")


@app.get("/favicon.ico")
def favicon_ico():
    return icon.render_icon_ico(64), 200, {
        "Content-Type": "image/x-icon",
        "Cache-Control": "no-cache",
    }


@app.get("/favicon.png")
def favicon_png():
    return icon.render_icon_png(32), 200, {
        "Content-Type": "image/png",
        "Cache-Control": "no-cache",
    }


@app.get("/apple-touch-icon.png")
def apple_touch_icon():
    # 优先使用用户放置的静态 PNG；兼容误命名的 apple-touch-icon.png.png
    for name in ("apple-touch-icon.png", "apple-touch-icon.png.png"):
        candidate = os.path.join(WEB_DIR, name)
        if os.path.isfile(candidate):
            return send_from_directory(WEB_DIR, name, mimetype="image/png")
    return icon.render_icon_png(180), 200, {
        "Content-Type": "image/png",
        "Cache-Control": "no-cache",
    }


@app.get("/manifest.webmanifest")
def webmanifest():
    path = os.path.join(WEB_DIR, "manifest.webmanifest")
    with open(path, "rb") as f:
        return f.read(), 200, {
            "Content-Type": "application/manifest+json",
            "Cache-Control": "public, max-age=3600",
        }


@app.get("/posters/<path:name>")
def posters(name: str):
    return send_from_directory(config.POSTER_DIR, os.path.basename(name))


# ---------- 健康 / 系统 ----------
@app.get("/api/health")
def api_health():
    return jsonify({"ok": True, "service": "atom-media", "version": __version__})


def _cpu_percent():
    """读取 /proc/stat 计算 CPU 占用；非 Linux 平台返回 None。"""
    try:
        def snap():
            with open("/proc/stat", "r") as f:
                parts = f.readline().split()[1:]
            vals = [int(x) for x in parts[:8]]
            idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
            return idle, sum(vals)

        i1, t1 = snap()
        time.sleep(0.12)
        i2, t2 = snap()
        dt = t2 - t1
        return round((1 - (i2 - i1) / dt) * 100, 1) if dt > 0 else None
    except Exception:
        return None


@app.get("/api/system")
def api_system():
    target = config.MEDIA_DIR if os.path.isdir(config.MEDIA_DIR) else config.DATA_DIR
    display_path = config.MEDIA_DIR_LABEL if target == config.MEDIA_DIR else config.DATA_DIR
    try:
        du = shutil.disk_usage(target)
        disk = {"total": du.total, "used": du.used, "free": du.free, "path": display_path}
    except Exception:
        disk = {"total": 0, "used": 0, "free": 0, "path": display_path}
    return jsonify({"cpu": _cpu_percent(), "disk": disk, "db": database.stats()})


@app.get("/api/stats")
def api_stats():
    return jsonify(database.stats())


# ---------- 影片 CRUD ----------
@app.get("/api/media")
def api_media_list():
    q = request.args
    try:
        limit = min(max(int(q.get("limit", 500)), 1), 2000)
    except (TypeError, ValueError):
        limit = 500
    cat = (q.get("category") or "").strip()
    items = database.list_media(
        search=(q.get("search") or "").strip() or None,
        mtype=(q.get("type") or "").strip() or None,
        category_id=int(cat) if cat.isdigit() else None,
        status=(q.get("status") or "").strip() or None,
        sort=(q.get("sort") or "").strip() or None,
        limit=limit,
    )
    return jsonify({"total": len(items), "items": [_serialize(i) for i in items]})


@app.get("/api/media/<int:media_id>")
def api_media_get(media_id: int):
    item = database.get_media(media_id)
    if not item:
        abort(404, "条目不存在")
    return jsonify(_serialize(item))


@app.post("/api/media")
def api_media_create():
    """手动添加。body: {title, type?, year?, url?, scrape?} 或 {path: 相对媒体目录路径}"""
    body = request.get_json(silent=True) or {}
    rel = (body.get("path") or "").strip().lstrip("/\\")
    if rel:
        full = safe_join(os.path.abspath(config.MEDIA_DIR), rel)
        if not full or not os.path.isfile(full):
            abort(400, "路径无效或文件不存在")
        if database.media_by_path(full):
            abort(409, "该文件已在库中")
        title, year, mtype = scraper.parse_filename(os.path.basename(full))
        mid = database.create_media(
            title=body.get("title") or title,
            year=body.get("year") or year or "",
            type=body.get("type") or mtype,
            file_path=full,
            file_size=os.path.getsize(full),
            status="unscraped", source="filename",
        )
    else:
        title = (body.get("title") or "").strip()
        if not title:
            abort(400, "缺少 title 或 path")
        mid = database.create_media(
            title=title, year=body.get("year") or "",
            type=body.get("type") or "movie",
            play_url=body.get("url") or "",
            status="unscraped", source="manual",
        )

    item = database.get_media(mid)
    if body.get("scrape"):
        try:
            item = scraper.scrape_item(item)
        except Exception as e:
            item = database.get_media(mid)
            item["warning"] = str(e)
    return jsonify(_serialize(item)), 201


@app.patch("/api/media/<int:media_id>")
def api_media_update(media_id: int):
    body = request.get_json(silent=True) or {}
    allowed = {"title", "original_title", "type", "year", "rating",
               "director", "actors", "overview", "cover", "play_url"}
    data = {k: v for k, v in body.items() if k in allowed}
    if not data:
        abort(400, "没有可更新的字段")
    database.update_media(media_id, **data)
    item = database.get_media(media_id)
    if not item:
        abort(404, "条目不存在")
    return jsonify(_serialize(item))


@app.delete("/api/media/<int:media_id>")
def api_media_delete(media_id: int):
    item = database.get_media(media_id)
    if not item:
        abort(404, "条目不存在")
    database.delete_media(media_id)
    return jsonify({"deleted": media_id})


# ---------- 分类标签 ----------
@app.get("/api/categories")
def api_categories():
    return jsonify({"categories": database.list_categories()})


@app.post("/api/categories")
def api_category_create():
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        abort(400, "分类名称不能为空")
    if len(name) > 24:
        abort(400, "分类名称过长（≤24 字符）")
    cid = database.get_or_create_category(name)
    return jsonify({"id": cid, "name": name}), 201


@app.delete("/api/categories/<int:cid>")
def api_category_delete(cid: int):
    if not database.queryone("SELECT id FROM categories WHERE id = ?", (cid,)):
        abort(404, "分类不存在")
    database.delete_category(cid)
    return jsonify({"deleted": cid})


@app.post("/api/media/<int:media_id>/categories")
def api_media_category_toggle(media_id: int):
    """切换影片与分类的绑定关系。body: {id} 或 {name}"""
    body = request.get_json(silent=True) or {}
    if not database.get_media(media_id):
        abort(404, "条目不存在")
    if body.get("id") is not None and str(body["id"]).isdigit():
        cid = int(body["id"])
    elif body.get("name"):
        name = str(body["name"]).strip()
        if not name:
            abort(400, "分类名称不能为空")
        cid = database.get_or_create_category(name)
    else:
        abort(400, "缺少分类 id 或 name")
    added = database.toggle_media_category(media_id, cid)
    item = database.get_media(media_id)
    return jsonify({"added": added, "category_ids": item["category_ids"]})


# ---------- 扫描 ----------
@app.post("/api/scan")
def api_scan():
    body = request.get_json(silent=True) or {}
    return jsonify(scanner.scan_media_dir(prune=body.get("prune")))


# ---------- 刮削 ----------
@app.get("/api/scraper/unscraped")
def api_unscraped():
    items = database.list_media(status="unscraped,failed", limit=500)
    return jsonify({"total": len(items), "items": [_serialize(i) for i in items]})


@app.get("/api/scrape/search")
def api_scrape_search():
    title = (request.args.get("title") or "").strip()
    if not title:
        abort(400, "缺少 title 参数")
    year = (request.args.get("year") or "").strip() or None
    mtype = request.args.get("type") or "movie"
    try:
        return jsonify(scraper.search(title, year, mtype))
    except scraper.ScraperError as e:
        abort(422, str(e))


@app.post("/api/scrape/<int:media_id>")
def api_scrape_one(media_id: int):
    body = request.get_json(silent=True) or {}
    item = database.get_media(media_id)
    if not item:
        abort(404, "条目不存在")
    try:
        updated = scraper.scrape_item(
            item,
            tmdb_id=body.get("tmdb_id"),
            mtype=body.get("type"),
            title=body.get("title"),
            year=body.get("year"),
        )
        return jsonify(_serialize(updated))
    except scraper.ScraperError as e:
        return jsonify({"error": str(e), "media": _serialize(database.get_media(media_id))}), 422


@app.post("/api/scrape/batch")
def api_scrape_batch():
    items = database.list_media(status="unscraped,failed", limit=200)
    ok = fail = 0
    errors = []
    for it in items:
        try:
            scraper.scrape_item(it)
            ok += 1
        except Exception as e:
            fail += 1
            errors.append({"id": it["id"], "title": it["title"], "error": str(e)})
            log.warning("批量刮削失败 #%s %s: %s", it["id"], it["title"], e)
    return jsonify({"success": ok, "failed": fail, "errors": errors})


# ---------- 设置 ----------
@app.get("/api/settings")
def api_settings_get():
    key, source = scraper.get_api_key()
    masked = ""
    if key:
        masked = (key[:4] + "****" + key[-4:]) if len(key) > 8 else "****"
    return jsonify({
        "tmdb_api_key": masked,
        "api_key_source": source or "",
        "poster_cache": scraper.poster_cache_enabled(),
        "tmdb_lang": config.TMDB_LANG,
        "media_dir": config.MEDIA_DIR_LABEL,
        "media_dir_container": config.MEDIA_DIR,
        "scan_interval_minutes": config.SCAN_INTERVAL_MINUTES,
        "nfo_write": config.NFO_WRITE,
    })


@app.post("/api/settings")
def api_settings_set():
    body = request.get_json(silent=True) or {}
    if "tmdb_api_key" in body:
        database.set_setting("tmdb_api_key", str(body["tmdb_api_key"]).strip())
    if "poster_cache" in body:
        on = body["poster_cache"] in (True, 1, "1", "true", "True", "on")
        database.set_setting("poster_cache", "1" if on else "0")
    return api_settings_get()


# ---------- 文件目录浏览 ----------
@app.get("/api/files")
def api_files():
    rel = (request.args.get("path") or "").replace("\\", "/").strip("/")
    base = os.path.abspath(config.MEDIA_DIR)
    if not os.path.isdir(base):
        abort(404, f"媒体目录不存在: {config.MEDIA_DIR}")

    if rel in ("", "."):
        full = base
    else:
        full = safe_join(base, rel)
        if not full:
            abort(400, "非法路径")
        if not os.path.isdir(full):
            abort(404, "目录不存在")

    entries = []
    try:
        with os.scandir(full) as it:
            for e in it:
                if e.name.startswith("."):
                    continue
                try:
                    is_dir = e.is_dir()
                    size = 0 if is_dir else e.stat().st_size
                except OSError:
                    continue
                ext = os.path.splitext(e.name)[1].lower()
                entries.append({
                    "name": e.name,
                    "path": f"{rel}/{e.name}" if rel else e.name,
                    "is_dir": is_dir,
                    "size": size,
                    "ext": ext,
                    "is_video": (not is_dir) and ext in config.VIDEO_EXTS,
                })
    except PermissionError:
        abort(403, "没有读取该目录的权限")

    entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))

    videos = [en for en in entries if en["is_video"]]
    if videos:
        paths = [os.path.join(full, en["name"]) for en in videos]
        marks = ",".join("?" * len(paths))
        known = {
            r["file_path"]: r["id"]
            for r in database.query(
                f"SELECT id, file_path FROM media WHERE file_path IN ({marks})", paths
            )
        }
        for en in videos:
            en["media_id"] = known.get(os.path.join(full, en["name"]))

    parent = None
    if rel:
        p = os.path.dirname(rel)
        parent = p if p else ""

    return jsonify({
        "root": os.path.basename(base) or base,
        "media_dir": config.MEDIA_DIR_LABEL,
        "media_dir_container": config.MEDIA_DIR,
        "path": rel,
        "parent": parent,
        "entries": entries,
    })


# ---------- 外部软字幕（浏览器 <track> + WebVTT） ----------
@app.get("/api/media/<int:media_id>/subtitles")
def api_media_subtitles(media_id: int):
    item = database.get_media(media_id)
    if not item:
        abort(404, "条目不存在")
    sub_paths = subtitles.find_subtitles(item)
    result = []
    for idx, path in enumerate(sub_paths):
        name = os.path.basename(path)
        lang = subtitles.guess_language(name)
        result.append({
            "index": idx,
            "name": name,
            "lang": lang,
            "label": (("中文" if lang == "zh" else
                        "English" if lang == "en" else
                        "日本語" if lang == "ja" else
                        "한국어" if lang == "ko" else name)),
            "url": f"/api/subtitles/{media_id}/{idx}",
        })
    return jsonify({"subtitles": result})


@app.get("/api/subtitles/<int:media_id>/<int:index>")
def api_subtitle_file(media_id: int, index: int):
    item = database.get_media(media_id)
    if not item:
        abort(404, "条目不存在")
    sub_paths = subtitles.find_subtitles(item)
    if index < 0 or index >= len(sub_paths):
        abort(404, "字幕文件不存在")
    vtt = subtitles.convert_file_to_vtt(sub_paths[index])
    if not vtt.strip():
        abort(415, "字幕文件无法转换为 WebVTT")
    return vtt, 200, {
        "Content-Type": "text/vtt; charset=utf-8",
        "Cache-Control": "no-cache",
    }


# ---------- 视频流（HTTP Range 直连播放，无转码） ----------
@app.get("/api/stream/<int:media_id>")
def api_stream(media_id: int):
    item = database.get_media(media_id)
    if not item:
        abort(404, "条目不存在")
    fp = item.get("file_path")
    if fp and os.path.isfile(fp):
        mime = mimetypes.guess_type(fp)[0] or "application/octet-stream"
        return send_file(fp, mimetype=mime, conditional=True)  # conditional=True 支持 Range
    if item.get("play_url"):
        return redirect(item["play_url"])
    abort(404, "视频文件不存在或已被移除")


# ---------- 定时扫描调度 ----------
def _start_scheduler():
    minutes = config.SCAN_INTERVAL_MINUTES
    if not minutes or minutes <= 0:
        return

    def _loop():
        while True:
            time.sleep(minutes * 60)
            try:
                result = scanner.scan_media_dir()
                log.info("定时扫描完成: %s", result)
            except Exception:
                log.exception("定时扫描失败")

    threading.Thread(target=_loop, daemon=True, name="atom-scheduler").start()
    log.info("定时扫描已开启：每 %.1f 分钟", minutes)


def main():
    os.makedirs(config.DATA_DIR, exist_ok=True)
    os.makedirs(config.POSTER_DIR, exist_ok=True)
    database.init_db()
    _start_scheduler()
    log.info(
        "Atom Media v%s 启动: http://0.0.0.0:%s | 媒体目录: %s | 数据目录: %s",
        __version__, config.PORT, config.MEDIA_DIR, config.DATA_DIR,
    )
    from waitress import serve
    serve(app, host="0.0.0.0", port=config.PORT,
          threads=config.WAITRESS_THREADS, channel_timeout=300, ident="atom-media")


if __name__ == "__main__":
    main()
