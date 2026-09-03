"""外部软字幕处理。

只负责读取视频同目录的外部字幕文件并转成 WebVTT，
供浏览器 HTML5 <track> 原生加载。不涉及封装、转码或内嵌字幕抽取。
"""
import os
import re

SUB_EXTENSIONS = {".srt", ".ass", ".ssa", ".vtt"}

# 常见中文字幕关键字（用于默认标签）
_ZH_MARKS = ("zh", "chs", "cht", "chi", "sc", "tc", "zh-cn", "zh-hans",
             "zh-hant", "chinese", "中文", "简体", "繁体", "国语", "双语", "中英")


def find_subtitles(media: dict):
    """返回媒体条目可用的外部软字幕绝对路径列表（按文件名排序）。

    匹配规则（示例，允许字幕名不包含发布标记/语言后缀）：
      Movie.2024.1080p.BluRay.x264.mkv
        → Movie.2024.zh.srt
        → Movie.chs.ass
        → Movie.2024.1080p.zh-Hans.srt
    """
    fp = media.get("file_path")
    if not fp or not os.path.isfile(fp):
        return []

    folder = os.path.dirname(fp)
    video_norm = _normalize_stem(os.path.basename(fp))
    if not video_norm:
        return []

    try:
        names = os.listdir(folder)
    except OSError:
        return []

    out = []
    for name in names:
        ext = os.path.splitext(name)[1].lower()
        if ext not in SUB_EXTENSIONS:
            continue
        sub_norm = _normalize_stem(name)
        if not sub_norm:
            continue
        # 归一化后相同，或一方是另一方子串（字幕名常省略发布组标记/年份）
        if video_norm == sub_norm or video_norm in sub_norm or sub_norm in video_norm:
            out.append(name)

    # 中文优先，其次无语言标记/其他，英文靠后；同名内按文件名稳定排序
    out.sort(key=lambda n: (_language_priority(n), n))
    return [os.path.join(folder, name) for name in out]


def _language_priority(name: str) -> int:
    lower = name.lower()
    if any(mark in lower for mark in _ZH_MARKS):
        return 0
    if re.search(r"(^|[._ -])(en|eng|english|英文)(?:$|[._ -])", lower):
        return 2
    return 1


def _normalize_stem(filename: str) -> str:
    """把字幕/视频主名去掉年份、发布标记、常见语言标记后压缩为纯小写串。"""
    stem = os.path.splitext(os.path.basename(filename))[0].lower()
    # 去掉年份
    stem = re.sub(r"(?<!\d)(?:19|20)\d{2}(?!\d)", " ", stem)
    # 去掉发布/编码标记
    stem = re.sub(
        r"(?:^|[ ._-])(?:1080p?|720p?|2160p?|4k|web-?dl|webrip|blu-?ray|bdrip|"
        r"hdtv|remux|h\.?26[45]|x26[45]|hevc|aac|ac3|dts(-hd)?|truehd|atmos|"
        r"hdr10?|10bit|60fps|proper|repack|extended|remastered|uncut|unrated|"
        r"internal|amzn|nf|dsnp|atvp|hmax|it|dual(?:\s*audio)?|multisub)(?:$|[ ._-])",
        " ", stem, flags=re.IGNORECASE,
    )
    # 去掉常见语言标记（长变体放前面，避免 zh-hans 被误拆成 zh）
    stem = re.sub(
        r"(?:^|[ ._-])(?:zh-hans|zh-hant|zh-cn|zh-tw|zh|chs|cht|chi|sc|tc|"
        r"simplified|traditional|chinese|eng|en|jpn|japanese|ja|kor|korean|ko|"
        r"中文|简体|繁体|国语|英文|中英|双语|日文|日语|韩文|韩语)(?:$|[ ._-])",
        " ", stem, flags=re.IGNORECASE,
    )
    stem = re.sub(r"[\W_]+", "", stem)
    return stem.strip()


def guess_language(filename: str) -> str:
    """从字幕文件名尽量判断语言，用于 <track> 标签和 label。"""
    lower = os.path.basename(filename).lower()
    if any(mark in lower for mark in _ZH_MARKS):
        return "zh"
    if re.search(r"(^|[._ -])(en|eng|english|英文)($|[._ -])", lower):
        return "en"
    if re.search(r"(^|[._ -])(ja|jpn|jap|jp|日文|日语)($|[._ -])", lower):
        return "ja"
    if re.search(r"(^|[._ -])(ko|kor|韩文|韩语)($|[._ -])", lower):
        return "ko"
    return "und"


def _read_text(path: str) -> str:
    """UTF-8 优先读取，兼容 GBK/GB18030、UTF-16 字幕。"""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return f.read()
    except UnicodeDecodeError:
        pass
    for enc in ("gb18030", "utf-16", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


# ---------- SRT → WebVTT ----------
def srt_to_vtt(text: str) -> str:
    if text.lstrip().startswith("WEBVTT"):
        return text
    out = ["WEBVTT", ""]
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if "-->" in line:
            # SRT 时间戳逗号 → 小数点
            line = re.sub(r"(\d+),(\d+)", r"\1.\2", line)
            out.append(line)
            i += 1
            while i < len(lines) and lines[i].strip() != "":
                out.append(lines[i])
                i += 1
            out.append("")
        else:
            i += 1
    while out and out[-1] == "":
        out.pop()
    out.append("")
    return "\n".join(out)


# ---------- ASS/SSA → WebVTT（仅提取纯文本字幕，忽略复杂样式） ----------
def _ass_timestamp_to_vtt(ts: str):
    m = re.match(r"(\d+):(\d{2}):(\d{2})[.:](\d{1,3})", ts.strip())
    if not m:
        return None
    h, mi, s = int(m.group(1)), int(m.group(2)), int(m.group(3))
    frac = m.group(4)
    if len(frac) == 2:      # ASS 使用厘秒
        ms = int(frac) * 10
    elif len(frac) == 3:    # 毫秒
        ms = int(frac)
    else:
        ms = 0
    total_ms = ((h * 3600 + mi * 60 + s) * 1000) + ms
    return (f"{total_ms // 3600000:02d}:"
            f"{total_ms % 3600000 // 60000:02d}:"
            f"{total_ms % 60000 // 1000:02d}."
            f"{total_ms % 1000:03d}")


_ASS_DIALOGUE = re.compile(r"^Dialogue:\s*(.*)$", re.IGNORECASE)


def ass_to_vtt(text: str) -> str:
    out = ["WEBVTT", ""]
    in_events = False
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped.startswith("["):
            in_events = stripped.lower() == "[events]"
            continue
        if not in_events:
            continue
        m = _ASS_DIALOGUE.match(stripped)
        if not m:
            continue
        fields = m.group(1).split(",", 9)  # 前 9 个逗号分隔 10 个固定字段
        if len(fields) < 10:
            continue
        start = _ass_timestamp_to_vtt(fields[1])
        end = _ass_timestamp_to_vtt(fields[2])
        content = fields[9]
        # 去掉 ASS 样式标签 {\...}，把 \N 转成换行
        content = re.sub(r"\{[^}]*\}", "", content)
        content = content.replace("\\N", "\n").replace("\\n", "\n")
        content = content.replace("\\h", " ")
        if not content.strip():
            continue
        if not start or not end:
            continue
        out.append(f"{start} --> {end}")
        out.extend(content.splitlines())
        out.append("")
    if len(out) <= 2:
        return ""
    return "\n".join(out)


def convert_file_to_vtt(path: str) -> str:
    """将外部字幕文件转为 WebVTT 文本；失败/无法转换返回空字符串。"""
    ext = os.path.splitext(path)[1].lower()
    try:
        text = _read_text(path)
    except Exception:
        return ""
    if ext == ".srt":
        return srt_to_vtt(text)
    if ext in (".ass", ".ssa"):
        return ass_to_vtt(text)
    if ext == ".vtt":
        if text.lstrip().startswith("WEBVTT"):
            return text
        return srt_to_vtt(text)  # 可能是扩展名写错的 SRT
    return ""
