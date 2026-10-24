# -*- coding: utf-8 -*-
"""把标识画到**真实地图贴图**上，离线确认格子基准是否正确。

真实数据（unpack/Asset/Config/Map/Frontlawn/Config/FrontlawnMapFrontlawn.tres）：
  gridBeginPos = (260, 75)   gridSize = 默认(80, 98)   gridNum = 默认(9, 5)
  mapTexturePath = res://Asset/Texture/.../Frontlawn/Frontlawn.jpg
格子左上角（代码里的算法）= gridBeginPos + ((x-1)*80, (y-1)*98)，gridPos 从 1 开始。
若这份预览里网格线与草坪条纹对得上，说明实机也应当对齐。
"""
import os
from PIL import Image, ImageDraw

SS = 2
HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
WORK = os.path.dirname(os.path.dirname(MOD))
MAP = os.path.join(WORK, "unpack", "Asset", "Texture", "TowerDefense", "Background",
                   "TowerDefenseMap", "Frontlawn", "Frontlawn.jpg")

BX, BY = 260.0, 75.0          # gridBeginPos
CW, CH = 80.0, 98.0           # gridSize
NX, NY = 9, 5                 # gridNum
STROKE = 3.0


def draw_ring(d, cx, cy, r, width, color):
    import math
    pts = []
    for i in range(97):
        a = 2 * math.pi * i / 96
        pts.append(((cx + math.cos(a) * r) * SS, (cy + math.sin(a) * r) * SS))
    d.line(pts, fill=color, width=max(1, int(round(width * SS))), joint="curve")


def draw_cross(d, cx, cy, half, width, color):
    w = max(1, int(round(width * SS)))
    d.line([((cx - half) * SS, cy * SS), ((cx + half) * SS, cy * SS)], fill=color, width=w)
    d.line([(cx * SS, (cy - half) * SS), (cx * SS, (cy + half) * SS)], fill=color, width=w)


def cell_tl(gx, gy):
    return BX + (gx - 1) * CW, BY + (gy - 1) * CH


def main():
    base = Image.open(MAP).convert("RGB")
    img = base.resize((base.width * SS, base.height * SS), Image.LANCZOS)
    d = ImageDraw.Draw(img)

    # 1) 网格线（青），用来肉眼比对"格子"和草坪条纹
    for gx in range(1, NX + 2):
        x = BX + (gx - 1) * CW
        d.line([(x * SS, BY * SS), (x * SS, (BY + NY * CH) * SS)], fill=(0, 255, 255), width=1)
    for gy in range(1, NY + 2):
        y = BY + (gy - 1) * CH
        d.line([(BX * SS, y * SS), ((BX + NX * CW) * SS, y * SS)], fill=(0, 255, 255), width=1)

    # 2) 第 1 行的格子编号，方便对位
    for gx in range(1, NX + 1):
        x, y = cell_tl(gx, 1)
        d.text((x * SS + 3, y * SS + 2), str(gx), fill=(0, 255, 255))

    # 3) 圆圈+十字（中间相 p=0.5）
    p = 0.5
    unit = min(CW, CH)
    for gy in range(1, NY + 1):
        for gx in range(1, NX + 1):
            x, y = cell_tl(gx, gy)
            cx, cy = x + CW / 2, y + CH / 2
            draw_ring(d, cx, cy, unit * (0.17 + 0.11 * p), STROKE, (255, 255, 255))
            draw_cross(d, cx, cy, unit * 0.119, STROKE, (255, 255, 255))

    img.save(os.path.join(HERE, "preview_on_map_circle.png"))

    # 4) 四角+十字
    img2 = base.resize((base.width * SS, base.height * SS), Image.LANCZOS)
    d = ImageDraw.Draw(img2)
    for gx in range(1, NX + 2):
        x = BX + (gx - 1) * CW
        d.line([(x * SS, BY * SS), (x * SS, (BY + NY * CH) * SS)], fill=(0, 255, 255), width=1)
    for gy in range(1, NY + 2):
        y = BY + (gy - 1) * CH
        d.line([(BX * SS, y * SS), ((BX + NX * CW) * SS, y * SS)], fill=(0, 255, 255), width=1)

    import math
    for gy in range(1, NY + 1):
        for gx in range(1, NX + 1):
            x, y = cell_tl(gx, gy)
            padX, padY = CW * 0.158, CH * 0.158
            armX, armY = CW * 0.14, CH * 0.14
            rad = unit * 0.07
            dd = unit * 0.08 * p
            for cx, cy, sx, sy, a0, a1 in (
                    (x + padX, y + padY, 1, 1, math.pi, math.pi * 1.5),
                    (x + CW - padX, y + padY, -1, 1, math.pi * 1.5, math.pi * 2),
                    (x + padX, y + CH - padY, 1, -1, math.pi * 0.5, math.pi),
                    (x + CW - padX, y + CH - padY, -1, -1, 0, math.pi * 0.5)):
                c0 = (cx + sx * dd, cy + sy * dd)
                pts = [(c0[0], c0[1] + sy * armY), (c0[0], c0[1] + sy * rad)]
                acx, acy = c0[0] + sx * rad, c0[1] + sy * rad
                for k in range(11):
                    a = a0 + (a1 - a0) * k / 10.0
                    pts.append((acx + math.cos(a) * rad, acy + math.sin(a) * rad))
                pts.append((c0[0] + sx * armX, c0[1]))
                d.line([(px * SS, py * SS) for px, py in pts], fill=(255, 255, 255),
                       width=max(1, int(round(STROKE * SS))), joint="curve")
            draw_cross(d, x + CW / 2, y + CH / 2, unit * 0.119, STROKE, (255, 255, 255))
    img2.save(os.path.join(HERE, "preview_on_map_corners.png"))

    # 5) 整行整列（悬停格取第 5 列第 3 行）
    img3 = base.resize((base.width * SS, base.height * SS), Image.LANCZOS)
    d = ImageDraw.Draw(img3)
    for gx in range(1, NX + 2):
        x = BX + (gx - 1) * CW
        d.line([(x * SS, BY * SS), (x * SS, (BY + NY * CH) * SS)], fill=(0, 255, 255), width=1)
    for gy in range(1, NY + 2):
        y = BY + (gy - 1) * CH
        d.line([(BX * SS, y * SS), ((BX + NX * CW) * SS, y * SS)], fill=(0, 255, 255), width=1)

    hx, hy = cell_tl(5, 3)
    cx, cy = hx + CW / 2, hy + CH / 2
    band = 22.0 * (0.85 + 0.3 * p)
    left, right = BX, BX + NX * CW
    top, bottom = BY, BY + NY * CH
    ov = Image.new("RGBA", img3.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    od.rectangle([left * SS, (cy - band / 2) * SS, right * SS, (cy + band / 2) * SS], fill=(255, 255, 255, 56))
    od.rectangle([(cx - band / 2) * SS, top * SS, (cx + band / 2) * SS, bottom * SS], fill=(255, 255, 255, 56))
    img3 = Image.alpha_composite(img3.convert("RGBA"), ov).convert("RGB")
    d = ImageDraw.Draw(img3)
    ew = max(1, int(round(STROKE * 0.7 * SS)))
    for yy in (cy - band / 2, cy + band / 2):
        d.line([(left * SS, yy * SS), (right * SS, yy * SS)], fill=(255, 255, 255), width=ew)
    for xx in (cx - band / 2, cx + band / 2):
        d.line([(xx * SS, top * SS), (xx * SS, bottom * SS)], fill=(255, 255, 255), width=ew)
    draw_cross(d, cx, cy, unit * 0.42, STROKE * 1.6, (255, 255, 255))
    img3.save(os.path.join(HERE, "preview_on_map_rowcol.png"))
    print("ok")


if __name__ == "__main__":
    main()
