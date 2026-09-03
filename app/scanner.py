"""本地媒体目录扫描入库（仅读取文件名/大小等元数据，绝不读取视频内容）。"""
import logging
import os

from . import config, database, scraper

log = logging.getLogger("atom.scanner")


def scan_media_dir(prune=None) -> dict:
    """遍历 MEDIA_DIR，将新视频文件入库（状态 unscraped）。

    prune=True 时同时删除文件已不存在的旧记录（不含手动添加的在线条目）。
    """
    if prune is None:
        prune = config.PRUNE_MISSING

    if not os.path.isdir(config.MEDIA_DIR):
        return {"found": 0, "added": 0, "pruned": 0,
                "error": f"媒体目录不存在: {config.MEDIA_DIR}"}

    found = added = 0
    for root, dirs, files in os.walk(config.MEDIA_DIR):
        dirs[:] = sorted(
            d for d in dirs
            if not d.startswith(".") and d not in config.SKIP_DIRS
        )
        for fn in sorted(files):
            ext = os.path.splitext(fn)[1].lower()
            if ext not in config.VIDEO_EXTS:
                continue
            found += 1
            full = os.path.join(root, fn)
            if database.media_by_path(full):
                continue
            try:
                size = os.path.getsize(full)
            except OSError:
                size = 0
            title, year, mtype = scraper.parse_filename(fn)
            database.create_media(
                title=title, year=year or "", type=mtype,
                file_path=full, file_size=size,
                status="unscraped", source="filename",
            )
            added += 1
            log.info("入库: %s", full)

    pruned = 0
    if prune:
        for row in database.query(
            "SELECT id, file_path FROM media WHERE file_path IS NOT NULL"
        ):
            if not os.path.isfile(row["file_path"]):
                database.delete_media(row["id"])
                pruned += 1

    log.info("扫描完成: 发现 %d 个视频, 新入库 %d, 清理失效 %d", found, added, pruned)
    return {"found": found, "added": added, "pruned": pruned}
