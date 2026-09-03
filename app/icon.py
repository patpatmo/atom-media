"""纯 Python 图标生成器。

不依赖 Pillow / 图片工具，在 Web 服务请求 favicon / apple-touch-icon 时
动态生成 PNG/ICO，解决浏览器与 iOS“添加到主屏幕”对 PNG 图标的兼容问题。
设计元素与 web/icon.svg 保持一致：深色圆角底板 + 青蓝原子轨道。
"""
import math
import struct
import zlib
from functools import lru_cache


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if v < lo else hi if v > hi else v


def _rounded_rect_coverage(x, y, cx, cy, hw, hh, radius):
    """圆角矩形有符号距离的近似覆盖度，负值在矩形内部。"""
    qx = abs(x - cx) - (hw - radius)
    qy = abs(y - cy) - (hh - radius)
    ax, ay = max(qx, 0.0), max(qy, 0.0)
    outside = math.sqrt(ax * ax + ay * ay)
    inside = min(max(qx, qy), 0.0)
    sdf = outside + inside - radius
    return _clamp(0.5 - sdf, 0.0, 1.0)


def _circle_coverage(x, y, cx, cy, radius):
    return _clamp(radius - math.hypot(x - cx, y - cy) + 0.5, 0.0, 1.0)


def _ellipse_ring_coverage(x, y, cx, cy, rx, ry, angle_deg, width):
    """抗锯齿椭圆描边覆盖度。"""
    ang = math.radians(angle_deg)
    dx, dy = x - cx, y - cy
    # 旋转到椭圆局部坐标
    lx = dx * math.cos(ang) + dy * math.sin(ang)
    ly = -dx * math.sin(ang) + dy * math.cos(ang)

    a = lx / rx if rx else 0.0
    b = ly / ry if ry else 0.0
    g = math.sqrt(a * a + b * b)
    if g < 1e-9:
        return 0.0

    # 到椭圆边界的近似像素距离
    grad_x = (lx / (rx * rx)) / g if rx else 0.0
    grad_y = (ly / (ry * ry)) / g if ry else 0.0
    grad = math.sqrt(grad_x * grad_x + grad_y * grad_y)
    if grad < 1e-9:
        return 0.0
    dist = abs(g - 1.0) / grad
    half = width / 2.0
    return _clamp(half - dist + 0.5, 0.0, 1.0)


def _composite(pix, rgb, alpha):
    """source-over 合成，rgb 与 alpha 均为 0~1。"""
    if alpha <= 0:
        return
    r, g, b = rgb
    if pix[3] <= 0:
        pix[0], pix[1], pix[2], pix[3] = r, g, b, _clamp(alpha)
        return
    dst_a = pix[3]
    out_a = alpha + dst_a * (1.0 - alpha)
    if out_a <= 0:
        pix[:] = [0.0, 0.0, 0.0, 0.0]
        return
    pix[0] = (r * alpha + pix[0] * dst_a * (1.0 - alpha)) / out_a
    pix[1] = (g * alpha + pix[1] * dst_a * (1.0 - alpha)) / out_a
    pix[2] = (b * alpha + pix[2] * dst_a * (1.0 - alpha)) / out_a
    pix[3] = _clamp(out_a)


def _draw_circle(canvas, w, h, cx, cy, radius, rgb, alpha=1.0):
    for y in range(h):
        for x in range(w):
            cov = _circle_coverage(x + 0.5, y + 0.5, cx, cy, radius)
            if cov > 0.01:
                _composite(canvas[y * w + x], rgb, cov * alpha)


def _draw_ellipse_ring(canvas, w, h, cx, cy, rx, ry, angle_deg, width, rgb, alpha=1.0):
    for y in range(h):
        for x in range(w):
            cov = _ellipse_ring_coverage(x + 0.5, y + 0.5, cx, cy, rx, ry, angle_deg, width)
            if cov > 0.01:
                _composite(canvas[y * w + x], rgb, cov * alpha)


def _render_icon_canvas(size: int):
    """按 size×size 渲染 Atom Media 图标（圆角底板样式）。size 建议 180/64/32。"""
    w = h = size
    canvas = [[0.0, 0.0, 0.0, 0.0] for _ in range(w * h)]
    s = size / 512.0
    cx = cy = 256.0 * s
    dark_a = (0.024, 0.039, 0.063)
    dark_b = (0.012, 0.023, 0.039)

    # 深色圆角底板
    hw = hh = 232.0 * s
    radius = 116.0 * s
    for y in range(h):
        for x in range(w):
            cov = _rounded_rect_coverage(x + 0.5, y + 0.5, cx, cy, hw, hh, radius)
            if cov <= 0.01:
                continue
            t = min(math.hypot((x + 0.5) - cx, (y + 0.5) - cy) / (hw * 1.15), 1.0)
            r = dark_a[0] * (1 - t) + dark_b[0] * t
            g = dark_a[1] * (1 - t) + dark_b[1] * t
            b = dark_a[2] * (1 - t) + dark_b[2] * t
            pix = canvas[y * w + x]
            pix[0], pix[1], pix[2], pix[3] = r, g, b, _clamp(cov)

    # 外圈光晕
    _draw_circle(canvas, w, h, cx, cy, 70.0 * s, (0.133, 0.906, 0.933), 0.08)

    # 原子核：外层青蓝 + 内层亮核
    _draw_circle(canvas, w, h, cx, cy, 46.0 * s, (0.035, 0.71, 0.84), 1.0)
    _draw_circle(canvas, w, h, cx, cy, 24.0 * s, (0.82, 0.98, 1.0), 1.0)

    # 三条电子轨道
    rx, ry = 172.0 * s, 64.0 * s
    orbits = [
        (0, (0.133, 0.906, 0.933), 13.0 * s),
        (60, (0.025, 0.71, 0.83), 10.0 * s),
        (120, (0.035, 0.57, 0.70), 9.0 * s),
    ]
    for ang, color, width in orbits:
        _draw_ellipse_ring(canvas, w, h, cx, cy, rx, ry, ang, width, color, 0.95)

    # 三个电子
    electrons = [
        (0, 19.0 * s, (0.85, 0.98, 1.0)),
        (60, 16.0 * s, (0.70, 0.95, 0.99)),
        (120, 14.0 * s, (0.55, 0.90, 0.96)),
    ]
    for ang, er, color in electrons:
        ex = cx + rx * math.cos(math.radians(ang))
        ey = cy + rx * math.sin(math.radians(ang))
        _draw_circle(canvas, w, h, ex, ey, er, color, 1.0)

    return canvas


def _canvas_to_png(canvas, w, h):
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        for x in range(w):
            pix = canvas[y * w + x]
            raw.append(round(_clamp(pix[0]) * 255))
            raw.append(round(_clamp(pix[1]) * 255))
            raw.append(round(_clamp(pix[2]) * 255))
            raw.append(round(_clamp(pix[3]) * 255))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


@lru_cache(maxsize=8)
def render_icon_png(size: int = 180) -> bytes:
    canvas = _render_icon_canvas(size)
    return _canvas_to_png(canvas, size, size)


@lru_cache(maxsize=8)
def render_icon_ico(size: int = 64) -> bytes:
    """生成包含 PNG 的 ICO 文件，兼容传统 /favicon.ico 请求。"""
    png_data = render_icon_png(size)
    header = struct.pack("<HHH", 0, 1, 1)
    # width/height 为 0 表示 256，但这里只生成不超过 64 的小尺寸，直接用 size
    entry = struct.pack(
        "<BBBBHHII",
        size & 0xff, size & 0xff, 0, 0, 1, 32, len(png_data), 22
    )
    return header + entry + png_data
