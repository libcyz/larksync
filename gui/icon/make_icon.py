"""生成应用图标：icon.png（1024）、icon.ico（Windows）、icon.icns（macOS）、前端 favicon。

改了图案后重新运行：uv run --with pillow python gui/icon/make_icon.py
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).parent
S = 2048                      # 先画 2 倍大再缩小，边缘更平滑
TOP, BOTTOM = (78, 131, 253), (36, 91, 219)   # 飞书蓝渐变
WHITE = (255, 255, 255, 255)


def draw():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # 圆角方块底，四周留 1/16 边距（macOS 图标的惯例）
    pad, radius = S // 16, S * 0.22
    gradient = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(gradient)
    for y in range(S):
        t = y / (S - 1)
        gd.line([(0, y), (S, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(TOP, BOTTOM)) + (255,))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([pad, pad, S - pad, S - pad], radius, fill=255)
    img.paste(gradient, mask=mask)

    d = ImageDraw.Draw(img)
    c = S / 2

    # 中间一张表格：白底，蓝色表头和格线
    w, h = S * 0.40, S * 0.30
    x0, y0, x1, y1 = c - w / 2, c - h / 2, c + w / 2, c + h / 2
    d.rounded_rectangle([x0, y0, x1, y1], S * 0.035, fill=WHITE)
    line = round(S * 0.018)
    head = y0 + h * 0.30
    d.rectangle([x0 + line, y0 + line, x1 - line, head], fill=TOP + (255,))
    d.rounded_rectangle([x0, y0, x1, y1], S * 0.035, outline=WHITE, width=line)
    for y in (y0 + h * 0.65,):
        d.line([(x0 + line, y), (x1 - line, y)], fill=BOTTOM + (255,), width=line)
    d.line([(c, head), (c, y1 - line)], fill=BOTTOM + (255,), width=line)

    # 外圈两段同步箭头（顺时针）
    r, width = S * 0.33, round(S * 0.055)
    box = [c - r, c - r, c + r, c + r]
    for start, end in ((205, 335), (25, 155)):
        d.arc(box, start, end, fill=WHITE, width=width)
        a = math.radians(end)
        px, py = c + r * math.cos(a), c + r * math.sin(a)
        tx, ty = -math.sin(a), math.cos(a)            # 顺时针切线方向
        nx, ny = math.cos(a), math.sin(a)             # 径向
        tip, half = S * 0.085, S * 0.065
        d.polygon([(px + tx * tip, py + ty * tip),
                   (px + nx * half - tx * 2, py + ny * half - ty * 2),
                   (px - nx * half - tx * 2, py - ny * half - ty * 2)], fill=WHITE)
    return img.resize((1024, 1024), Image.LANCZOS)


def main():
    icon = draw()
    icon.save(HERE / "icon.png")
    icon.save(HERE / "icon.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    icon.save(HERE / "icon.icns")
    favicon = HERE.parent / "frontend" / "public" / "favicon.png"
    favicon.parent.mkdir(exist_ok=True)
    icon.resize((128, 128), Image.LANCZOS).save(favicon)


if __name__ == "__main__":
    main()
