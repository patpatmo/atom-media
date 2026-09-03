# Atom Media — 轻量级影片管理器（Docker 版 · ARMv7 适配）

基于 `atom_media.html` 静态界面打造的简化版影片管理器：**影片信息刮削（TMDb）+ 分类标签管理 + 本地媒体目录扫描 + 外部软字幕加载**，不包含任何转码功能（无 FFmpeg），以 Docker 容器一键部署，严格适配 `arm32v7`。

```
最终镜像体积 ≈ 65~75MB（python:3.12-alpine ≈ 50MB + 纯 Python 依赖 ≈ 15MB），远低于 200MB 目标
运行内存占用 ≈ 40~60MB（waitress 线程池 + SQLite WAL）
```

---

## 1. 项目结构

```
atom-media/
├── Dockerfile              # arm32v7 兼容的精简镜像（Alpine）
├── docker-compose.yml      # 一键部署编排
├── requirements.txt        # 纯 Python 依赖（全部锁定，arm32v7 无需编译）
├── .dockerignore
├── app/
│   ├── main.py             # Flask Web 服务 + REST API + 定时调度
│   ├── config.py           # 全部环境变量配置
│   ├── database.py         # SQLite 存储层（标准库 sqlite3，无 ORM）
│   ├── scraper.py          # TMDb 刮削 + 文件名解析 + NFO/海报缓存
│   ├── subtitles.py        # 外部软字幕识别 + SRT/ASS→WebVTT 转换
│   └── scanner.py          # 媒体目录扫描入库
├── web/
│   ├── index.html          # 整合后的前端（原 atom_media.html 设计 + API 对接）
│   └── icon.svg            # 手写 SVG 矢量 Logo（同时作为 favicon）
└── data/                   # （运行时生成）SQLite 数据库 + 海报缓存 → 挂载为 /data
```

## 2. 快速开始

### 2.1 在树莓派 / 玩客云（arm32v7 设备）上直接运行

```bash
# 1. 上传整个 atom-media 目录到设备（如 /opt/atom-media）
cd /opt/atom-media

# 2. 准备 .env（可选，也可以之后在网页"刮削中心"里填 Key）
cat > .env <<'EOF'
TMDB_API_KEY=你的tmdb_api_key
SCAN_INTERVAL_MINUTES=60      # 每 60 分钟自动扫描，0=关闭
EOF

# 3. 修改 docker-compose.yml 中的媒体目录挂载路径
#    volumes: - /mnt/sda1/Media:/media   ← 改成你的影片目录

# 4. 构建并启动
docker compose up -d --build

# 5. 浏览器访问
http://<设备IP>:8080
```

### 2.2 在 x86 电脑上交叉构建 armv7 镜像

```bash
# 安装 QEMU 跨架构支持（一次性）
docker run --privileged --rm tonistiigi/binfmt --install armv7

# 构建 arm32v7 镜像
docker buildx build --platform linux/arm/v7 -t atom-media:latest --load .

# 导出镜像并在树莓派上加载
docker save atom-media:latest | gzip > atom-media.tar.gz
# （树莓派上）docker load < atom-media.tar.gz
```

> 也可以直接推送到镜像仓库：`docker buildx build --platform linux/arm/v7 -t <user>/atom-media:latest --push .`

### 2.3 纯 docker run（不用 compose）

```bash
docker run -d --name atom-media \
  --restart unless-stopped \
  -p 8080:8080 \
  -e TMDB_API_KEY=你的tmdb_api_key \
  -e TZ=Asia/Shanghai \
  -v /opt/atom-media/data:/data \
  -v /mnt/sda1/Media:/media \
  atom-media:latest
```

## 3. 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `PORT` | `8080` | Web 服务端口 |
| `DATA_DIR` | `/data` | 数据目录（SQLite + 海报缓存），**必须挂载持久化** |
| `MEDIA_DIR` | `/media` | 影片根目录，挂载你的 USB / Samba / NFS 路径。**前端目录栏/文件夹页显示时会优先从 mountinfo 读取宿主机 bind 源路径（如 `/DATA/Media`），读不到才显示 `MEDIA_DIR`** |
| `TMDB_API_KEY` | 空 | TMDb v3 API Key（也可在网页"刮削中心"里保存，环境变量优先） |
| `TMDB_API_BASE` | `https://api.themoviedb.org/3` | TMDb 接口地址（国内网络差时可换成反代地址） |
| `TMDB_IMAGE_BASE` | `https://image.tmdb.org/t/p` | 海报 CDN 地址（同样支持反代） |
| `TMDB_LANG` | `zh-CN` | 刮削语言 |
| `SCAN_INTERVAL_MINUTES` | `0` | 定时扫描间隔（分钟），`0` 关闭 |
| `SCRAPE_ON_SCAN` | `false` | 扫描入库后是否立即自动刮削 |
| `POSTER_CACHE` | `false` | 海报下载到 `/data/posters`（否则直接用 TMDb CDN 链接） |
| `NFO_WRITE` | `true` | 刮削成功后在视频旁生成 Kodi/Jellyfin 兼容 `.nfo` |
| `PRUNE_MISSING` | `true` | 扫描时自动清理文件已不存在的记录 |
| `WAITRESS_THREADS` | `8` | WSGI 线程数 |
| `TZ` | - | 时区，建议 `Asia/Shanghai` |

> TMDb API Key 免费申请：https://www.themoviedb.org/settings/api （注册后在 API 页面生成 v3 key）

## 4. 使用流程

1. **文件夹目录** → 点击「扫描入库」：后端递归扫描 `/media` 中所有视频文件（mp4/mkv/avi…），解析文件名（标题 / 年份 / 电影或剧集）写入 SQLite，状态为"待刮削"。
2. **极简刮削中心** → 「一键批量刮削」或逐个「手动匹配」（弹出候选列表选择）：从 TMDb 拉取标题、海报、简介、导演、演员、年份、评分、类型，写库并生成 NFO。
3. **影视库** → 海报墙展示；点击卡片直接播放（HTTP Range 流式直连，无转码）；点 ⓘ 打开详情，可切换"已看 / 想看 / 收藏"等分类标签、重新刮削、删除记录。
   - **外部软字幕**：视频同目录下若有同名 `.srt / .ass / .ssa / .vtt`（如 `Movie.zh.srt`、`Movie.ass`），播放器会自动加载为字幕轨（浏览器原生渲染，无需封装/转码），字幕菜单可切换。
4. **分类标签**：影视库筛选栏动态显示全部自定义标签（带数量），「＋ 标签」新建，悬浮标签点「×」删除；筛选 `cat:<id>` 由后端完成。
5. 「＋ 添加影片」可手动录入无本地文件的在线影片（填名称即自动刮削，播放地址可后续在详情中维护）。

## 5. API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 前端页面（`web/index.html`） |
| GET | `/api/health` | 健康检查 `{ok, version}` |
| GET | `/api/system` | CPU 占用 / 磁盘用量 / 库内统计（状态栏数据源） |
| GET | `/api/stats` | 影片统计 + 分类标签（含计数） |
| GET | `/api/media` | 影片列表。参数：`search` `type=movie\|tv` `category=<分类id>` `status` `sort=rating\|year\|title\|added` `limit` |
| GET | `/api/media/<id>` | 影片详情（含 `category_ids`） |
| POST | `/api/media` | 手动添加。`{title,type?,year?,url?,scrape?}` 或 `{path:"相对媒体目录路径"}` |
| PATCH | `/api/media/<id>` | 更新字段（title/year/overview/director/actors/play_url…） |
| DELETE | `/api/media/<id>` | 删除记录（不动磁盘文件） |
| GET | `/api/categories` | 分类标签列表 |
| POST | `/api/categories` | 新建标签 `{name}` |
| DELETE | `/api/categories/<id>` | 删除标签 |
| POST | `/api/media/<id>/categories` | 切换影片↔标签绑定 `{id}` 或 `{name}` |
| POST | `/api/scan` | 扫描入库，返回 `{found, added, pruned}` |
| GET | `/api/scraper/unscraped` | 待刮削列表（含刮削失败项） |
| GET | `/api/scrape/search` | TMDb 搜索候选。参数：`title` `year?` `type?` |
| POST | `/api/scrape/<id>` | 刮削单条。`{tmdb_id?, type?, title?, year?}` |
| POST | `/api/scrape/batch` | 批量刮削，返回 `{success, failed, errors}` |
| GET | `/api/settings` / POST | 查询/保存设置（`tmdb_api_key`、`poster_cache`） |
| GET | `/api/files?path=` | 浏览媒体目录（防路径穿越），返回子目录与视频文件（含是否已入库） |
| GET | `/api/media/<id>/subtitles` | 列出外部软字幕（同目录同名 `.srt/.ass/.ssa/.vtt`，含语言/URL） |
| GET | `/api/subtitles/<id>/<index>` | 返回转换为 WebVTT 的字幕文本，供播放器 `<track>` 加载 |
| GET | `/api/stream/<id>` | 视频流直连播放，支持 HTTP Range 拖动进度条 |
| GET | `/posters/<file>` | 本地缓存的海报（启用 `POSTER_CACHE` 后使用） |

错误统一返回 JSON：`{"error": "原因"}` + 对应 HTTP 状态码。

## 6. 数据库表结构（SQLite / WAL）

- `media` — 影片：标题、原始标题、类型、年份、评分、导演、演员、简介、封面、背景图、类型标签(JSON)、文件路径、文件大小、状态（unscraped/scraped/failed）、来源、tmdb_id、时间戳
- `categories` — 分类标签（预置：已看 / 想看 / 收藏）
- `media_category` — 影片↔标签 多对多（级联删除）
- `settings` — 运行时设置（如网页保存的 API Key）

数据库文件：`/data/atom_media.db`，备份即拷贝此文件。

## 7. 前端整合说明

原 `atom_media.html` 的视觉设计（毛玻璃卡片、青蓝主题、全部 CSS 动画）完整保留于 `web/index.html`，改动点：

- 原 `mediaData` 硬编码数组 → 改为 `GET /api/media` 动态加载，Hero Banner 展示评分最高影片；
- 原假分类按钮 → 后端动态分类标签（含自定义标签的增删、计数）；
- 原假文件列表 → `GET /api/files` 真实目录浏览 + 单文件「入库」+「扫描入库」；
- 文件夹页顶部路径显示后端读取的媒体根目录（优先显示宿主机 bind 源路径，如 `/DATA/Media`；读不到才显示 `MEDIA_DIR`）；
- 原假刮削效果 → `/api/scrape/*` 真实刮削（单条 / 批量 / 候选手动匹配）；
- 原假 CPU 状态栏 → `GET /api/system` 真实 CPU / 磁盘数据（5 秒轮询）；
- 播放 → `GET /api/stream/<id>` 流式直连；详情弹窗新增分类管理、重新刮削、删除；
- 动态内容全部采用事件委托 + HTML 转义，避免标题特殊字符导致的注入/XSS。

> 前端引用 Tailwind / Lucide 的 CDN，客户端需能访问公网；如需完全离线，可自行将这两个库下载到 `web/` 并替换 `<script src>`。

## 8. 本地开发（Windows，无需 Docker）

```bat
cd atom-media
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
set DATA_DIR=./data
set MEDIA_DIR=D:\Movies
python -m app.main
:: 打开 http://127.0.0.1:8080
```

## 9. 常见问题

- **构建时 pip 报 `[Errno -3] Try again` / 无法解析 PyPI 域名？** Dockerfile 已默认走清华镜像源；若设备 DNS 解析本身有问题（改 `/etc/docker/daemon.json` 的 `dns` 往往不生效），直接共享宿主机网络构建：`docker build --network=host -t atom-media:latest .`，compose 编排中也已内置 `build.network: host`。
- **国内访问 TMDb 失败？** 设置 `TMDB_API_BASE` / `TMDB_IMAGE_BASE` 为可达的反代地址；刮削失败会标记"上次失败"，网络恢复后可重试。
- **为什么没有豆瓣刮削？** 豆瓣无官方公开 API，网页爬取存在法律风险，按需求约束仅内置 TMDb。
- **mkv / HEVC 播放不了？** 本项目**无转码**，浏览器直连播放受编解码器限制：mp4(H.264/AAC) 兼容性最好，mkv(H.265) 在部分浏览器（Safari 新版、安卓）可播，否则请使用本地播放器直接打开文件。
- **字幕支持哪些格式？** 仅支持**外部软字幕**：与视频同目录、同主名的 `.srt / .ass / .ssa / .vtt`（例如 `Movie.zh.srt`）。后端会把 SRT/ASS 自动转成 WebVTT 供浏览器原生加载；复杂 ASS 样式会简化为纯文本字幕。**不读取视频内嵌字幕**，因为内嵌字幕抽取需要 FFmpeg，违反无转码约束。
- **批量刮削很慢？** TMDb 逐条请求（约 1 秒/条），200 条以内一次完成；可开启 `SCRAPE_ON_SCAN` 让新文件入库后自动排队刮削。
- **权限说明：** 容器默认以 root 运行（媒体容器通行做法，避免 USB/Samba 挂载目录属主导致的读写失败）。如需降权，在 compose 中添加 `user: "1000:1000"` 并确保 `/data` 对该 UID 可写。
- **某个依赖在 arm32v7 没有 wheel？** Dockerfile 已不使用 `--only-binary`，若确实遇到无 wheel 的包，pip 会自动尝试源码编译（此时需在镜像中追加 `RUN apk add --no-cache gcc musl-dev` 后重试）。

## 10. 安全提示

本服务面向可信局域网设计（家庭 NAS / 树莓派场景），未内置鉴权。如需暴露公网，请置于反向代理之后并加 Basic Auth / 访问控制。
