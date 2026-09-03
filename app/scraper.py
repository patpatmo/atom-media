"""元数据刮削模块：TMDb（免费公开 API）+ 文件名智能解析。

- 严格使用官方 API，不爬取网页，规避法律风险；
- 豆瓣无公开 API，默认不集成（可通过 TMDB_API_BASE 反代解决网络问题）。
"""
import json
import logging
import os
import re

import requests

from . import config, database

log = logging.getLogger("atom.scraper")


class ScraperError(Exception):
    """刮削失败（未配置 Key、未找到条目等）。"""


# ---------- 文件名解析 ----------
_TAG_SPLIT = re.compile(
    r"(1080[pi]?|720[pi]?|2160[pi]?|4k|web-?dl|webrip|blu-?ray|bdrip|hdtv|remux|"
    r"h\.?26[45]|x26[45]|hevc|aac|ddp?|dts(-hd)?|truehd|atmos|10bit|hdr(10\+)?|"
    r"dolby.?vision|60fps|extended|remastered|uncut|unrated|proper|repack|internal|"
    r"amzn|nf|dsnp|atvp|hmax|it|hybrid|dualaudio|mandarin|chinese|subs?)",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")
_TV_RE = re.compile(r"[sS]\d{1,2}[eE]\d{1,3}|第\s*\d+\s*[季集话]|Season\s*\d+", re.IGNORECASE)


def parse_filename(filename: str):
    """从视频文件名解析 (标题猜测, 年份, movie/tv)。"""
    base = os.path.splitext(os.path.basename(filename))[0]
    name = base.replace(".", " ").replace("_", " ")
    mtype = "tv" if _TV_RE.search(name) else "movie"
    year = None
    m = _YEAR_RE.search(name)
    if m:
        year = m.group(1)
        name = name[: m.start()] + " " + name[m.end():]
    name = _TAG_SPLIT.split(name, maxsplit=1)[0]
    name = re.sub(r"\s+", " ", name).strip(" -–—~·[]()")
    return (name or base), year, mtype


# ---------- TMDb API ----------
def get_api_key():
    """返回 (key, 来源)；环境变量优先于 Web 界面保存的设置。"""
    if config.TMDB_API_KEY:
        return config.TMDB_API_KEY, "env"
    key = (database.get_setting("tmdb_api_key") or "").strip()
    if key:
        return key, "db"
    return "", None


def poster_cache_enabled() -> bool:
    if os.environ.get("POSTER_CACHE") is not None:
        return config.POSTER_CACHE
    return config.POSTER_CACHE or database.get_setting("poster_cache") == "1"


def _tmdb_get(path: str, **params) -> dict:
    key, _ = get_api_key()
    if not key:
        raise ScraperError("未配置 TMDb API Key，请在环境变量 TMDB_API_KEY 或刮削中心设置")
    params.update({"api_key": key, "language": config.TMDB_LANG})
    url = f"{config.TMDB_API_BASE}/{path.lstrip('/')}"
    try:
        r = requests.get(url, params=params, timeout=config.REQUEST_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        raise ScraperError(f"TMDb 请求失败：{e.__class__.__name__}（可检查 TMDB_API_BASE 网络）") from e


def _img(path, size: str = "w500") -> str:
    return f"{config.TMDB_IMAGE_BASE}/{size}{path}" if path else ""


def search(query: str, year=None, mtype: str = "movie", limit: int = 6):
    path = "search/tv" if mtype == "tv" else "search/movie"
    params = {"query": query}
    if year:
        params["year" if mtype == "movie" else "first_air_date_year"] = year
    data = _tmdb_get(path, **params)
    out = []
    for r in (data.get("results") or [])[:limit]:
        date = r.get("release_date") or r.get("first_air_date") or ""
        out.append({
            "tmdb_id": r.get("id"),
            "media_type": mtype,
            "title": r.get("title") or r.get("name") or query,
            "original_title": r.get("original_title") or r.get("original_name") or "",
            "date": date,
            "year": date[:4],
            "rating": round(r.get("vote_average") or 0, 1),
            "overview": (r.get("overview") or "").strip(),
            "poster": _img(r.get("poster_path")),
        })
    return out


def details(tmdb_id: int, mtype: str = "movie") -> dict:
    path = ("tv/" if mtype == "tv" else "movie/") + str(tmdb_id)
    d = _tmdb_get(path, append_to_response="credits")
    credits = d.get("credits") or {}
    actors = " / ".join(a.get("name", "") for a in (credits.get("cast") or [])[:5])
    directors = [c.get("name", "") for c in (credits.get("crew") or [])
                 if c.get("job") == "Director"]
    if mtype == "tv" and not directors:
        directors = [c.get("name", "") for c in (d.get("created_by") or [])]
    date = d.get("release_date") or d.get("first_air_date") or ""
    return {
        "title": d.get("title") or d.get("name") or "",
        "original_title": d.get("original_title") or d.get("original_name") or "",
        "year": date[:4],
        "rating": round(d.get("vote_average") or 0, 1),
        "director": ", ".join(x for x in directors if x)[:120],
        "actors": actors,
        "overview": (d.get("overview") or "").strip(),
        "poster": _img(d.get("poster_path")),
        "backdrop": _img(d.get("backdrop_path"), "w780"),
        "genres": [g.get("name", "") for g in (d.get("genres") or [])],
        "tmdb_id": tmdb_id,
        "source": "tmdb",
    }


# ---------- 海报本地缓存 ----------
def cache_poster(media_id: int, url: str) -> str:
    os.makedirs(config.POSTER_DIR, exist_ok=True)
    ext = os.path.splitext(url.split("?")[0])[1] or ".jpg"
    local = f"{media_id}{ext}"
    dest = os.path.join(config.POSTER_DIR, local)
    if not os.path.exists(dest):
        r = requests.get(url, timeout=config.REQUEST_TIMEOUT)
        r.raise_for_status()
        tmp = dest + ".tmp"
        with open(tmp, "wb") as f:
            f.write(r.content)
        os.replace(tmp, dest)
    return f"/posters/{local}"


# ---------- NFO（Kodi/Jellyfin 兼容）----------
def write_nfo(item: dict):
    if not config.NFO_WRITE:
        return
    fp = item.get("file_path")
    if not fp or not os.path.isfile(fp):
        return
    from xml.sax.saxutils import escape

    try:
        root = "episodedetails" if item.get("type") == "tv" else "movie"
        actors = [a.strip() for a in (item.get("actors") or "").split("/") if a.strip()]
        lines = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            f"<{root}>",
            f"  <title>{escape(item.get('title') or '')}</title>",
            f"  <originaltitle>{escape(item.get('original_title') or '')}</originaltitle>",
            f"  <year>{escape(str(item.get('year') or ''))}</year>",
            f"  <rating>{item.get('rating') if item.get('rating') is not None else ''}</rating>",
            f"  <outline>{escape(item.get('overview') or '')}</outline>",
            f"  <plot>{escape(item.get('overview') or '')}</plot>",
            f"  <director>{escape(item.get('director') or '')}</director>",
            f"  <uniqueid type=\"tmdb\" default=\"true\">{item.get('tmdb_id') or ''}</uniqueid>",
        ]
        for a in actors:
            lines.append(f"  <actor><name>{escape(a)}</name></actor>")
        lines.append(f"</{root}>")
        with open(os.path.splitext(fp)[0] + ".nfo", "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except OSError as e:
        log.warning("NFO 写入失败 (%s): %s", fp, e)


# ---------- 单条目刮削入口 ----------
def scrape_item(item: dict, tmdb_id=None, mtype=None, title=None, year=None) -> dict:
    """对单条媒体执行刮削并写库；失败抛出 ScraperError。"""
    mtype = mtype or item.get("type") or "movie"

    if tmdb_id:
        info = details(int(tmdb_id), mtype)
    else:
        q = (title or item.get("title") or "").strip()
        y = year or item.get("year") or None
        if not q:
            raise ScraperError("缺少可用于搜索的标题")
        results = search(q, y, mtype)
        if not results and y:
            results = search(q, None, mtype)  # 忽略年份再试一次
        if not results:
            database.update_media(item["id"], status="failed")
            raise ScraperError(f"未在 TMDb 找到与「{q}」匹配的条目")
        info = details(results[0]["tmdb_id"], mtype)

    poster = info.get("poster") or ""
    if poster and poster_cache_enabled():
        try:
            poster = cache_poster(item["id"], poster)
        except Exception as e:
            log.warning("海报缓存失败，回退在线地址: %s", e)

    database.update_media(
        item["id"],
        status="scraped",
        source=info["source"],
        tmdb_id=info["tmdb_id"],
        title=info["title"] or item.get("title"),
        original_title=info["original_title"],
        type=mtype,
        year=info["year"],
        rating=info["rating"],
        director=info["director"],
        actors=info["actors"],
        overview=info["overview"],
        cover=poster,
        backdrop=info["backdrop"],
        genres=info["genres"],
    )
    updated = database.get_media(item["id"])
    write_nfo(updated)
    log.info("刮削成功: #%s %s (%s)", item["id"], updated["title"], updated["year"])
    return updated
