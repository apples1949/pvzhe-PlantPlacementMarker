# -*- coding: utf-8 -*-
"""按 PlantPlacementMarkerEntry.cs 里的**同一套常量**离线预览三种样式的实际观感。

用途：进游戏前先肉眼确认比例/粗细是否合适（格子 80x98，9 列 5 行，与标准草坪一致）。
所有数字都必须与 C# 里的一致，否则预览就是假的：
  circle  r = unit*(0.17 + 0.11*p)            cross half = unit*0.119
  corners pad=0.158*cell, arm=0.14*cell, rad=unit*0.07, 内移=unit*0.08*p
  rowcol  band = Width*(0.85 + 0.3*p)         cross half = unit*0.42
"""
import os
import math
from PIL import Image, ImageDraw

SS = 3                      # 超采样
CW, CH = 80, 98             # 格子尺寸（世界单位）
NX, NY = 9, 5
STROKE = 3.0                # 粗细档位 = 标准
BAND = 22.0
TINT = (255, 255, 255)
PAD = 12                    # 画布留白

OUT = os.path.dirname(os.path.abspath(__file__))


def unit():
    return min(CW, CH)


def cell_tl(gx, gy):
    return (PAD + (gx - 1) * CW, PAD + (gy - 1) * CH)


def w(px):
    return px * SS


def draw_cross(d, c, half, width, color):
    x, y = c
    d.line([(w(x - half), w(y)), (w(x + half), w(y))], fill=color, width=int(round(w(width))))
    d.line([(w(x), w(y - half)), (w(x), w(y + half))], fill=color, width=int(round(w(width))))
    for px, py in ((x - half, y), (x + half, y), (x, y - half), (x, y + half)):
        r = w(width) / 2.0
        d.ellipse([w(px) - r, w(py) - r, w(px) + r, w(py) + r], fill=color)


def draw_ring(d, c, r, width, color, steps=96):
    x, y = c
    pts = []
    for i in range(steps + 1):
        a = 2 * math.pi * i / steps
        pts.append((w(x + math.cos(a) * r), w(y + math.sin(a) * r)))
    d.line(pts, fill=color, width=int(round(w(width))), joint="curve")


def draw_corners(d, tl, p, width, color):
    u = unit()
    padX, padY = CW * 0.158, CH * 0.158
    armX, armY = CW * 0.14, CH * 0.14
    rad = u * 0.07
    dd = u * 0.08 * p
    corners = [(tl[0] + padX, tl[1] + padY, 1, 1, math.pi, math.pi * 1.5),
               (tl[0] + CW - padX, tl[1] + padY, -1, 1, math.pi * 1.5, math.pi * 2),
               (tl[0] + padX, tl[1] + CH - padY, 1, -1, math.pi * 0.5, math.pi),
               (tl[0] + CW - padX, tl[1] + CH - padY, -1, -1, 0, math.pi * 0.5)]
    for cx, cy, sx, sy, a0, a1 in corners:
        ox, oy = sx * dd, sy * dd
        c0 = (cx + ox, cy + oy)
        pts = [(c0[0], c0[1] + sy * armY), (c0[0], c0[1] + sy * rad)]
        acx, acy = c0[0] + sx * rad, c0[1] + sy * rad
        for k in range(11):
            a = a0 + (a1 - a0) * k / 10.0
            pts.append((acx + math.cos(a) * rad, acy + math.sin(a) * rad))
        pts.append((c0[0] + sx * armX, c0[1]))
        d.line([(w(px), w(py)) for px, py in pts], fill=color, width=int(round(w(width))), joint="curve")
        for px, py in (pts[0], pts[-1]):
            r = w(width) / 2.0
            d.ellipse([w(px) - r, w(py) - r, w(px) + r, w(py) + r], fill=color)


def lawn(title):
    Wp = PAD * 2 + NX * CW
    Hp = PAD * 2 + NY * CH + 26
    img = Image.new("RGB", (w(Wp), w(Hp)), (44, 54, 38))
    d = ImageDraw.Draw(img)
    # 草地 + 网格线
    for gy in range(1, NY + 1):
        for gx in range(1, NX + 1):
            x, y = cell_tl(gx, gy)
            shade = (72, 92, 56) if (gx + gy) % 2 else (78, 99, 60)
            d.rectangle([w(x), w(y), w(x + CW), w(y + CH)], fill=shade)
            d.rectangle([w(x), w(y), w(x + CW), w(y + CH)], outline=(58, 74, 46), width=w(1))
    return img, d, Hp


def finish(img, Hp, title):
    img = img.resize((img.width // SS, img.height // SS), Image.LANCZOS)
    return img


def panel_circle(p):
    img, d, Hp = lawn("circle")
    skip = {(3, 2), (7, 4), (5, 1)}          # 模拟"不能种"的格子
    u = unit()
    r = u * (0.17 + 0.11 * p)
    for gy in range(1, NY + 1):
        for gx in range(1, NX + 1):
            if (gx, gy) in skip:
                continue
            x, y = cell_tl(gx, gy)
            c = (x + CW / 2, y + CH / 2)
            draw_ring(d, c, r, STROKE, TINT)
            draw_cross(d, c, u * 0.119, STROKE, TINT)
    return finish(img, Hp, "circle")


def panel_corners(p):
    img, d, Hp = lawn("corners")
    skip = {(3, 2), (7, 4), (5, 1)}
    u = unit()
    for gy in range(1, NY + 1):
        for gx in range(1, NX + 1):
            if (gx, gy) in skip:
                continue
            tl = cell_tl(gx, gy)
            draw_corners(d, tl, p, STROKE, TINT)
            draw_cross(d, (tl[0] + CW / 2, tl[1] + CH / 2), u * 0.119, STROKE, TINT)
    return finish(img, Hp, "corners")


def panel_rowcol(p, hover=(5, 3)):
    img, d, Hp = lawn("rowcol")
    u = unit()
    x, y = cell_tl(*hover)
    cx, cy = x + CW / 2, y + CH / 2
    band = BAND * (0.85 + 0.3 * p)
    left = PAD
    right = PAD + NX * CW
    top = PAD
    bottom = PAD + NY * CH
    fill = tuple(list(TINT) + [int(255 * 0.22)])
    edge = (255, 255, 255)
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    od.rectangle([w(left), w(cy - band / 2), w(right), w(cy + band / 2)], fill=fill)
    od.rectangle([w(cx - band / 2), w(top), w(cx + band / 2), w(bottom)], fill=fill)
    img = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")
    d = ImageDraw.Draw(img)
    ew = max(1, int(round(w(STROKE * 0.7))))
    for yy in (cy - band / 2, cy + band / 2):
        d.line([(w(left), w(yy)), (w(right), w(yy))], fill=edge, width=ew)
    for xx in (cx - band / 2, cx + band / 2):
        d.line([(w(xx), w(top)), (w(xx), w(bottom))], fill=edge, width=ew)
    draw_cross(d, (cx, cy), u * 0.42, STROKE * 1.6, TINT)
    return finish(img, Hp, "rowcol")


def main():
    for p, tag in ((0.0, "min"), (0.5, "mid"), (1.0, "max")):
        panel_circle(p).save(os.path.join(OUT, "preview_circle_%s.png" % tag))
        panel_corners(p).save(os.path.join(OUT, "preview_corners_%s.png" % tag))
        panel_rowcol(p).save(os.path.join(OUT, "preview_rowcol_%s.png" % tag))

    # 三种样式各取中间相，横向拼一张对比图
    ims = [panel_circle(0.5), panel_corners(0.5), panel_rowcol(0.5)]
    h = max(i.height for i in ims)
    gap = 16
    total = sum(i.width for i in ims) + gap * 2
    out = Image.new("RGB", (total, h), (44, 54, 38))
    x = 0
    for i in ims:
        out.paste(i, (x, 0))
        x += i.width + gap
    out.save(os.path.join(OUT, "preview_all.png"))
    print("ok ->", OUT)


if __name__ == "__main__":
    main()
