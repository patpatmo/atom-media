"""剧集归组与季/集解析。

供媒体库把同一部剧的每一集合并成一张“剧集卡片”，
点击后按季/集选择播放。
"""
import os
import re
from functools import lru_cache

try:
    from guessit import guessit as _guessit
except Exception:
    _guessit = None

# SxxExx / Sxx / Season x / 第x季 / 第x集
_STD_EP = re.compile(r"[sS](\d{1,2})[eE](\d{1,3})")
_CN_EP = re.compile(r"第\s*(\d{1,4})\s*[集话]")
_SEASON_ONLY = re.compile(r"[sS](\d{1,2})(?![eE0-9])|Season\s*(\d{1,4})|第\s*(\d{1,4})\s*季")

_YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_TAG_CLEAN = re.compile(
    r"(?:^|[ ._-])(?:1080p?|720p?|2160p?|4k|web-?dl|webrip|blu-?ray|bdrip|hdtv|"
    r"remux|h\.?26[45]|x26[45]|hevc|aac|ddp?|dts(-hd)?|hdr10?|10bit|60fps|proper|"
    r"repack|internal|amzn|nf|dsnp|atvp)(?:$|[ ._-])",
    re.IGNORECASE,
)


def _clean_title(value: str) -> str:
    value = value.replace(".", " ").replace("_", " ").replace("-", " ")
    value = _YEAR_RE.sub(" ", value)
    value = _TAG_CLEAN.sub(" ", value)
    value = re.sub(r"\s+", " ", value).strip(" -–—·~[]()")
    return value


def _normalize_key(title: str) -> str:
    return re.sub(r"[\W_]+", "", title.lower())


def _series_meta_impl(item: dict) -> dict:
    """返回 {series_key, series_title, season, episode, episode_label}。"""
    title = (item.get("title") or "").strip()
    fp = item.get("file_path") or ""
    source = (item.get("file_name") or os.path.basename(fp) or title)

    season = None
    episode = None
    marker_pos = None
    guessed_title = None

    # 优先用 guessit 从文件名智能识别
    if _guessit is not None:
        try:
            info = _guessit(source) or {}
            if info.get("season") is not None:
                season = int(info["season"])
            if info.get("episode") is not None:
                episode = int(info["episode"])
            guessed_title = str(info.get("title") or "").strip()
        except Exception:
            pass

    if season is None or episode is None:
        m = _STD_EP.search(source)
        if m:
            if season is None:
                season = int(m.group(1))
            if episode is None:
                episode = int(m.group(2))
            marker_pos = m.start()
        else:
            m = _CN_EP.search(source)
            if m:
                if episode is None:
                    episode = int(m.group(1))
                marker_pos = m.start()
                sm = _SEASON_ONLY.search(source[:marker_pos] if marker_pos is not None else source)
                if sm and season is None:
                    season = int(next((g for g in sm.groups() if g is not None), 0) or 0)

    # 优先用数据库里的剧名（刮削后通常每一集都是同一部剧名）
    series_title = None
    if title and not _STD_EP.search(title) and not _CN_EP.search(title):
        series_title = title.strip()
    elif guessed_title:
        series_title = guessed_title
    elif marker_pos is not None:
        series_title = _clean_title(source[:marker_pos])
    else:
        series_title = title or _clean_title(source)

    # 从文件名切出的剧名可能带年份/发布标记，做一次清理
    series_title = _clean_title(series_title) or (title or "未知剧集")

    # 如果刮削后有 tmdb_id，用它作为更稳定的归组主键
    tmdb_id = item.get("tmdb_id")
    if tmdb_id:
        series_key = f"tmdb:{tmdb_id}"
    else:
        series_key = _normalize_key(series_title) or f"file:{_normalize_key(os.path.splitext(os.path.basename(fp))[0])}"

    episode_label = f"第 {episode} 集" if episode else ""
    season_label = f"第 {season} 季" if season else "单季/未识别"

    return {
        "series_key": series_key,
        "series_title": series_title,
        "season": season,
        "episode": episode,
        "episode_label": episode_label,
        "season_label": season_label,
    }


@lru_cache(maxsize=8192)
def _series_meta_cached(fp: str, file_name: str, title: str, tmdb_id):
    return _series_meta_impl({
        "file_path": fp,
        "file_name": file_name,
        "title": title,
        "tmdb_id": tmdb_id,
    })


def series_meta(item: dict) -> dict:
    """带缓存的剧集元数据解析，避免大量分集重复跑 GuessIt。"""
    fp = item.get("file_path") or ""
    file_name = item.get("file_name") or os.path.basename(fp) or ""
    return _series_meta_cached(
        fp,
        file_name,
        item.get("title") or "",
        item.get("tmdb_id"),
    )
