# 🎬 Atom Media

> 轻量级影片刮削管理器 · 无转码 · 适配 ARMv7 / 玩客云 / 树莓派

---

## ✨ 一句话介绍

基于 TMDb 的影片信息刮削 + 分类管理 + 海报墙，纯 Python 实现，Docker 一键部署。**不转码、不吃性能**，适合低功耗设备。

---

## 🚀 快速开始

### 直接运行（复制即用）

```bash
docker run -d \
  --name atom-media \
  --restart unless-stopped \
  -p 7777:8080 \
  -e TMDB_API_BASE="https://api.tmdb.org/3" \
  -v /opt/atom-media-data/data:/data \
  -v /你的影片文件夹:/media \
  ghcr.io/patpatmo/atom-media:latest
```

> 镜像由 GitHub Container Registry 托管：`ghcr.io/patpatmo/atom-media:latest`

**参数说明：**

| 参数 | 说明 |
|------|------|
| `-p 7777:8080` | 访问端口（左边可改成你喜欢的端口） |
| `-v /你的影片文件夹:/media` | **必须改**：你存放电影/电视剧的目录 |
| `-v /opt/atom-media-data/data:/data` | 数据库/缓存目录，建议保留 |

访问：`http://你的设备IP:7777`

首次打开会提示注册账号，设个密码就行。

---

## ⚙️ 完整环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PORT` | `8080` | 容器内服务端口（一般不用改） |
| `DATA_DIR` | `/data` | 数据目录（SQLite + 海报缓存） |
| `MEDIA_DIR` | `/media` | 影片根目录 |
| `TMDB_API_KEY` | 共享 Key | TMDb v3 API Key（建议自己申请替换） |
| `TMDB_API_BASE` | `https://api.themoviedb.org/3` | TMDb 接口地址（已预配可用地址） |
| `TMDB_IMAGE_BASE` | `https://image.tmdb.org/t/p` | 海报 CDN 地址 |
| `TMDB_LANG` | `zh-CN` | 刮削语言 |
| `SCAN_INTERVAL_MINUTES` | `0` | 自动扫描间隔（分钟），`0`=关闭 |
| `SCRAPE_ON_SCAN` | `false` | 扫描后是否自动刮削 |
| `POSTER_CACHE` | `false` | 是否下载海报到本地（否则直接用 CDN 链接） |
| `NFO_WRITE` | `true` | 刮削后是否生成 Kodi/Jellyfin 兼容 `.nfo` |
| `PRUNE_MISSING` | `true` | 扫描时自动清理已删除文件的记录 |
| `WAITRESS_THREADS` | `8` | WSGI 线程数 |
| `TZ` | - | 时区，建议 `Asia/Shanghai` |
| `AUTH_USERNAME` | 空 | 预置用户名（不填则首次访问时注册） |
| `AUTH_PASSWORD` | 空 | 预置密码（与上面成对使用） |
| `SESSION_SECRET` | 自动生成 | 登录态签名密钥（固定可保持重启后登录） |

---

## 🖼️ 使用流程

1. **文件夹** → 点击「扫描入库」，程序自动识别视频文件
2. **刮削中心** → 一键批量刮削，从 TMDb 拉取海报/简介/评分
3. **影视库** → 海报墙展示，点击卡片播放（浏览器直接看）
4. **分类** → 自定义标签（已看/想看/收藏）

> 支持外部软字幕：`视频同名.srt/ass` 自动加载

---

## 📦 常用命令

```bash
docker logs atom-media          # 查看日志
docker restart atom-media       # 重启
docker stop atom-media && docker rm atom-media   # 删除
```

---

## 📄 许可证

MIT © patpatmo
