"""Atom Media 运行配置。

所有配置项均可通过环境变量覆盖；未设置环境变量时使用本地开发默认值，
容器内部署时由 docker-compose / docker run 显式指定。
"""
import os


def _env_bool(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def _default_data_dir() -> str:
    env = os.environ.get("DATA_DIR")
    if env:
        return env
    # 容器内默认 /data；本地开发（Windows/macOS）自动回退到项目目录下的 ./data
    if os.path.isdir("/data"):
        return "/data"
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def _mount_source(container_path: str):
    """从 /proc/self/mountinfo 读取 bind mount 的宿主机源路径。

    例：docker run -v /DATA/Media:/media，MEDIA_DIR=/media 时返回 /DATA/Media。
    非 Linux / 无法读取时返回 None，由调用方回退到容器内路径。
    """
    try:
        real = os.path.realpath(container_path)
        with open("/proc/self/mountinfo", "r", encoding="utf-8") as f:
            for line in f:
                fields = line.split()
                if len(fields) < 10 or "-" not in fields:
                    continue
                sep = fields.index("-")
                mountpoint = fields[4].replace("\\040", " ")
                source = fields[sep + 2].replace("\\040", " ")
                if mountpoint == real and source.startswith("/"):
                    return source
    except Exception:
        return None
    return None


# ---------- 目录 ----------
DATA_DIR = _default_data_dir()
MEDIA_DIR = os.environ.get("MEDIA_DIR", "/media")
# 页面展示用：优先显示宿主机 bind 源路径（例如 /DATA/Media），否则显示 MEDIA_DIR
MEDIA_DIR_LABEL = _mount_source(MEDIA_DIR) or MEDIA_DIR
DB_PATH = os.path.join(DATA_DIR, "atom_media.db")
POSTER_DIR = os.path.join(DATA_DIR, "posters")

# ---------- Web 服务 ----------
PORT = int(os.environ.get("PORT", "8080"))
WAITRESS_THREADS = int(os.environ.get("WAITRESS_THREADS", "8"))

# ---------- 极简单用户认证 ----------
AUTH_USERNAME = os.environ.get("AUTH_USERNAME", "").strip()
AUTH_PASSWORD = os.environ.get("AUTH_PASSWORD", "")
# 建议通过 docker run -e SESSION_SECRET=... 固定；未设置时自动生成并存 SQLite
SESSION_SECRET = os.environ.get("SESSION_SECRET", "").strip()

# ---------- 刮削（TMDb，免费公开 API）----------
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "").strip()
# 国内网络不佳时可指向反代地址，例如 https://tmdb.example.com/3
TMDB_API_BASE = os.environ.get("TMDB_API_BASE", "https://api.themoviedb.org/3").rstrip("/")
TMDB_IMAGE_BASE = os.environ.get("TMDB_IMAGE_BASE", "https://image.tmdb.org/t/p").rstrip("/")
TMDB_LANG = os.environ.get("TMDB_LANG", "zh-CN")
REQUEST_TIMEOUT = int(os.environ.get("SCRAPE_TIMEOUT", "10"))

# ---------- 行为开关 ----------
POSTER_CACHE = _env_bool("POSTER_CACHE")            # 海报是否下载到本地 /data/posters
SCRAPE_ON_SCAN = _env_bool("SCRAPE_ON_SCAN")        # 扫描入库后立即自动刮削
NFO_WRITE = _env_bool("NFO_WRITE", "true")          # 刮削成功后在视频旁生成 Kodi 兼容 NFO
PRUNE_MISSING = _env_bool("PRUNE_MISSING", "true")  # 扫描时清理文件已不存在的记录

try:
    SCAN_INTERVAL_MINUTES = float(os.environ.get("SCAN_INTERVAL_MINUTES", "0") or 0)
except ValueError:
    SCAN_INTERVAL_MINUTES = 0.0

# ---------- 扫描 ----------
VIDEO_EXTS = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v",
    ".mpg", ".mpeg", ".ts", ".m2ts", ".rmvb", ".3gp", ".vob", ".ogv",
}

SKIP_DIRS = {
    "$RECYCLE.BIN", "System Volume Information", "lost+found",
    "@eaDir", "#recycle", ".Trash-1000",
}
