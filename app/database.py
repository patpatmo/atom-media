"""SQLite 存储层（标准库 sqlite3，无 ORM，零外部依赖）。

每个线程持有一个独立连接（waitress 线程池 + 调度线程），开启 WAL 模式，
在树莓派 SD 卡上也能获得不错的读写表现。
"""
import json
import os
import sqlite3
import threading

from . import config, series

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS media (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    title          TEXT NOT NULL,
    original_title TEXT DEFAULT '',
    type           TEXT NOT NULL DEFAULT 'movie',      -- movie | tv
    year           TEXT DEFAULT '',
    rating         REAL,
    director       TEXT DEFAULT '',
    actors         TEXT DEFAULT '',
    overview       TEXT DEFAULT '',
    cover          TEXT DEFAULT '',
    backdrop       TEXT DEFAULT '',
    genres         TEXT DEFAULT '',                    -- JSON 数组字符串
    file_path      TEXT UNIQUE,                        -- 本地视频文件绝对路径
    file_size      INTEGER DEFAULT 0,
    play_url       TEXT DEFAULT '',                    -- 无本地文件时的在线播放地址
    status         TEXT NOT NULL DEFAULT 'unscraped',  -- unscraped | scraped | failed
    source         TEXT DEFAULT '',                    -- tmdb | manual | filename
    tmdb_id        INTEGER,
    series_key     TEXT DEFAULT '',
    series_title   TEXT DEFAULT '',
    season         INTEGER,
    episode        INTEGER,
    added_at       TEXT DEFAULT (datetime('now','localtime')),
    updated_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_media_status ON media(status);
CREATE INDEX IF NOT EXISTS idx_media_type ON media(type);
CREATE INDEX IF NOT EXISTS idx_media_series_key ON media(series_key);

CREATE TABLE IF NOT EXISTS categories (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS media_category (
    media_id    INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    PRIMARY KEY (media_id, category_id)
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

DEFAULT_CATEGORIES = ("已看", "想看", "收藏")

_MEDIA_FIELDS = {
    "title", "original_title", "type", "year", "rating", "director", "actors",
    "overview", "cover", "backdrop", "genres", "file_path", "file_size",
    "play_url", "status", "source", "tmdb_id",
    "series_key", "series_title", "season", "episode",
}


# ---------- 连接 ----------
def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_db() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = _connect()
        _local.conn = conn
    return conn


def query(sql: str, params=()):
    return get_db().execute(sql, params).fetchall()


def queryone(sql: str, params=()):
    return get_db().execute(sql, params).fetchone()


def execute(sql: str, params=()) -> int:
    conn = get_db()
    cur = conn.execute(sql, params)
    conn.commit()
    return cur.lastrowid


def _ensure_series_columns(conn):
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(media)").fetchall()}
    additions = [
        ("series_key", "TEXT DEFAULT ''"),
        ("series_title", "TEXT DEFAULT ''"),
        ("season", "INTEGER"),
        ("episode", "INTEGER"),
    ]
    for name, definition in additions:
        if name not in cols:
            conn.execute(f"ALTER TABLE media ADD COLUMN {name} {definition}")


def sync_series_fields(media_id: int):
    """根据最新标题/tmdb_id/文件路径重新计算并写回剧集字段。"""
    row = queryone("SELECT * FROM media WHERE id = ?", (media_id,))
    if not row or row["type"] != "tv":
        return
    d = dict(row)
    d["file_name"] = os.path.basename(d.get("file_path") or "")
    meta = series.series_meta(d)
    execute(
        "UPDATE media SET series_key = ?, series_title = ?, season = ?, episode = ? WHERE id = ?",
        (meta["series_key"], meta["series_title"], meta["season"], meta["episode"], media_id),
    )


def init_db():
    conn = _connect()
    try:
        conn.executescript(SCHEMA)
        _ensure_series_columns(conn)

        # 对旧库中缺失剧集字段的记录做一次性回填
        rows = conn.execute(
            "SELECT * FROM media WHERE type='tv' AND (series_key IS NULL OR series_key = '')"
        ).fetchall()
        for row in rows:
            d = dict(row)
            d["file_name"] = os.path.basename(d.get("file_path") or "")
            meta = series.series_meta(d)
            conn.execute(
                "UPDATE media SET series_key=?, series_title=?, season=?, episode=? WHERE id=?",
                (meta["series_key"], meta["series_title"], meta["season"], meta["episode"], d["id"]),
            )

        for name in DEFAULT_CATEGORIES:
            conn.execute("INSERT OR IGNORE INTO categories(name) VALUES(?)", (name,))
        conn.commit()
    finally:
        conn.close()


# ---------- 行序列化 ----------
def _parse_genres(d: dict) -> dict:
    g = d.get("genres")
    if isinstance(g, str) and g:
        try:
            d["genres"] = json.loads(g)
        except Exception:
            d["genres"] = [s for s in g.split(",") if s]
    elif not g:
        d["genres"] = []
    return d


def _row_to_dict(row) -> dict:
    d = dict(row)
    cats = d.pop("_cats", None)
    cat_ids = d.pop("_cat_ids", None)
    _parse_genres(d)
    d["categories"] = [s for s in (cats or "").split(",") if s]
    d["category_ids"] = [int(x) for x in (cat_ids or "").split(",") if x]
    return d


# ---------- media CRUD ----------
def create_media(**fields) -> int:
    data = {k: v for k, v in fields.items() if k in _MEDIA_FIELDS and v is not None}
    if isinstance(data.get("genres"), list):
        data["genres"] = json.dumps(data["genres"], ensure_ascii=False)
    if not data.get("title"):
        raise ValueError("title 不能为空")
    cols = ", ".join(data.keys())
    marks = ", ".join("?" for _ in data)
    mid = execute(f"INSERT INTO media({cols}) VALUES({marks})", tuple(data.values()))
    if data.get("type") == "tv":
        sync_series_fields(mid)
    return mid


def update_media(media_id: int, **fields):
    data = {k: v for k, v in fields.items() if k in _MEDIA_FIELDS}
    if isinstance(data.get("genres"), list):
        data["genres"] = json.dumps(data["genres"], ensure_ascii=False)
    if not data:
        return
    set_sql = ", ".join(f"{k} = ?" for k in data)
    execute(
        f"UPDATE media SET {set_sql}, updated_at = datetime('now','localtime') WHERE id = ?",
        (*data.values(), media_id),
    )
    sync_series_fields(media_id)


def delete_media(media_id: int):
    execute("DELETE FROM media WHERE id = ?", (media_id,))


def get_media(media_id: int):
    row = queryone("SELECT * FROM media WHERE id = ?", (media_id,))
    if not row:
        return None
    d = _parse_genres(dict(row))
    d["category_ids"] = [
        r["category_id"]
        for r in query("SELECT category_id FROM media_category WHERE media_id = ?", (media_id,))
    ]
    return d


def media_by_path(path: str):
    return queryone("SELECT * FROM media WHERE file_path = ?", (path,))


def list_media(search=None, mtype=None, category_id=None, status=None,
               sort=None, limit=500):
    where, params = [], []
    if search:
        like = f"%{search}%"
        where.append("(m.title LIKE ? OR m.original_title LIKE ? OR m.file_path LIKE ?)")
        params += [like, like, like]
    if mtype in ("movie", "tv"):
        where.append("m.type = ?")
        params.append(mtype)
    if status:
        vals = [s.strip() for s in status.split(",") if s.strip()]
        if vals:
            where.append("m.status IN (%s)" % ",".join("?" * len(vals)))
            params += vals
    if category_id:
        where.append(
            "EXISTS (SELECT 1 FROM media_category mc2 JOIN categories c2 "
            "ON c2.id = mc2.category_id WHERE mc2.media_id = m.id AND c2.id = ?)"
        )
        params.append(category_id)

    order = {
        "rating": "m.rating IS NULL, m.rating DESC, m.id DESC",
        "year": "m.year DESC, m.id DESC",
        "title": "m.title COLLATE NOCASE ASC",
        "added": "m.id DESC",
    }.get(sort, "m.id DESC")

    sql = (
        "SELECT m.*, "
        "GROUP_CONCAT(DISTINCT c.name) AS _cats, "
        "GROUP_CONCAT(DISTINCT mc.category_id) AS _cat_ids "
        "FROM media m "
        "LEFT JOIN media_category mc ON mc.media_id = m.id "
        "LEFT JOIN categories c ON c.id = mc.category_id "
        + ("WHERE " + " AND ".join(where) + " " if where else "")
        + f"GROUP BY m.id ORDER BY {order} LIMIT ?"
    )
    params.append(int(limit))
    return [_row_to_dict(r) for r in query(sql, params)]


def _category_entity_counts():
    """返回按“电影/剧集整体”统计的 (movie_cat, series_cat)。

    电影按 media_id 计一次；剧集按 series_key 计一次，
    同一剧的多集即使都打了同一标签也只算 1 次。
    """
    media_rows = query(
        "SELECT id, type, title, file_path, tmdb_id, status, series_key FROM media"
    )
    pairs = query("SELECT media_id, category_id FROM media_category")

    type_by_id = {}
    tvkey_by_id = {}
    for row in media_rows:
        d = dict(row)
        type_by_id[d["id"]] = d["type"]
        if d["type"] == "tv":
            key = d.get("series_key") or series.series_meta(d)["series_key"]
            tvkey_by_id[d["id"]] = key

    movie_cat = {}
    series_cat = {}
    for mid, cid in pairs:
        cid = int(cid)
        mtype = type_by_id.get(mid)
        if mtype == "movie":
            movie_cat.setdefault(cid, set()).add(mid)
        elif mtype == "tv":
            key = tvkey_by_id.get(mid)
            if key:
                series_cat.setdefault(cid, set()).add(key)
    return movie_cat, series_cat


def stats() -> dict:
    media_rows = query(
        "SELECT id, type, title, file_path, tmdb_id, status, series_key FROM media"
    )
    movie = 0
    tv_keys = set()
    scraped = unscraped = failed = 0
    for row in media_rows:
        d = dict(row)
        if d["type"] == "movie":
            movie += 1
        else:
            key = d.get("series_key") or series.series_meta(d)["series_key"]
            tv_keys.add(key)
        status = d.get("status")
        if status == "scraped":
            scraped += 1
        elif status == "unscraped":
            unscraped += 1
        elif status == "failed":
            failed += 1

    return {
        "total": movie + len(tv_keys),
        "movie": movie,
        "tv": len(tv_keys),
        "scraped": scraped,
        "unscraped": unscraped,
        "failed": failed,
        "categories": list_categories(),
    }


# ---------- categories ----------
def list_categories():
    rows = query("SELECT id, name FROM categories ORDER BY id")
    movie_cat, series_cat = _category_entity_counts()
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "count": len(movie_cat.get(r["id"], set()))
                     + len(series_cat.get(r["id"], set())),
        }
        for r in rows
    ]


def get_or_create_category(name: str) -> int:
    row = queryone("SELECT id FROM categories WHERE name = ?", (name,))
    if row:
        return row["id"]
    return execute("INSERT INTO categories(name) VALUES(?)", (name,))


def delete_category(cid: int):
    execute("DELETE FROM categories WHERE id = ?", (cid,))


def toggle_media_category(media_id: int, category_id: int) -> bool:
    """已存在则移除，不存在则添加；返回是否为新增。"""
    exists = queryone(
        "SELECT 1 AS x FROM media_category WHERE media_id = ? AND category_id = ?",
        (media_id, category_id),
    )
    if exists:
        execute("DELETE FROM media_category WHERE media_id = ? AND category_id = ?",
                (media_id, category_id))
        return False
    execute("INSERT OR IGNORE INTO media_category(media_id, category_id) VALUES(?, ?)",
            (media_id, category_id))
    return True


# ---------- settings ----------
def get_setting(key: str, default: str = "") -> str:
    row = queryone("SELECT value FROM settings WHERE key = ?", (key,))
    return row["value"] if row else default


def set_setting(key: str, value: str):
    execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
