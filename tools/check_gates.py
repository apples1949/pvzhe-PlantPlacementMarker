# -*- coding: utf-8 -*-
"""种植位置标识 · 离线闸门（不开游戏就能验的部分，一次跑完）。

覆盖 7 项：
  1  mod.json 可解析、id/entry/api 正确、resources 与包内一致
  2  Runtime/ 只有 ModAssembly.dll（多文件会被整包拒收）
  3  编译产物 md5 == Runtime/ModAssembly.dll md5
  4  dist 里的 .pmod 条目 == ['mod.json','Runtime/ModAssembly.dll']，且与装机包字节一致
  5  mod.json 的 settings 通过**宿主自己的** ValidateDefinitions（settings-validate 工具）
  6  装机目录 enabled_mods.json 里含本 Mod id
  7  DLL 里能搜到关键符号（防"构建成功但代码没进去"）
  8  预览脚本里的比例常量与 C# 源码一致（防"预览是假的"）

用法：python tools/check_gates.py
退出码 0 = 全过。
"""
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
WORKSPACE = os.path.dirname(os.path.dirname(BASE))
MOD_ID = "plantplacementmarker"
MOD_NAME = "PlantPlacementMarker"
ENTRY = "PlantPlacementMarkerEntry"
DLL_BIN = os.path.join(BASE, "runtime_src", "bin", "Release", "JTYPlantPlacementMarker.dll")
DLL_PKG = os.path.join(BASE, "Runtime", "ModAssembly.dll")
PMOD = os.path.join(BASE, "dist", MOD_NAME + ".pmod")
SRC = os.path.join(BASE, "runtime_src", "PlantPlacementMarkerEntry.cs")
PREVIEW = os.path.join(HERE, "preview_marker.py")
PREVIEW_MAP = os.path.join(HERE, "preview_on_map.py")
UD = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"),
                  "Godot", "app_userdata", "植物大战僵尸杂交版")
HOST = os.path.join(WORKSPACE, "data_PlantsVsZombies_windows_x86_64")
VALIDATOR = os.path.join(WORKSPACE, "pvz-hybrid-mod-skills", "tools",
                         "settings-validate", "bin", "Release", "ValidateSettings.dll")

fails = []


def md5(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


def md5_sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def ok(n, msg):
    print("  [OK]   %d. %s" % (n, msg))


def bad(n, msg):
    print("  [FAIL] %d. %s" % (n, msg))
    fails.append(n)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print("== 种植位置标识 离线闸门 ==")

    # ---- 1 mod.json
    try:
        man = json.load(open(os.path.join(BASE, "mod.json"), encoding="utf-8"))
    except Exception as e:
        bad(1, "mod.json 解析失败：%r" % e)
        return 1
    problems = []
    if man.get("id") != MOD_ID:
        problems.append("id != " + MOD_ID)
    if man.get("runtimeEntryType") != ENTRY:
        problems.append("runtimeEntryType != " + ENTRY)
    if man.get("runtimeApiVersion") != 3:
        problems.append("runtimeApiVersion != 3")
    if man.get("runtimeAssembly") != "Runtime/ModAssembly.dll":
        problems.append("runtimeAssembly 不是字面量 Runtime/ModAssembly.dll")
    if [r.lower() for r in man.get("resources", [])] != ["runtime/modassembly.dll"]:
        problems.append("resources 应恰为 [Runtime/ModAssembly.dll]")
    keys = [s.get("key") for s in man.get("settings", [])]
    need = {"enabled", "style", "thickness", "showCenterCross", "color", "enableLog"}
    if not need.issubset(set(keys)):
        problems.append("缺少配置项：%s" % (need - set(keys)))
    enums = [s for s in man.get("settings", []) if s.get("type") == "enum"]
    for s in enums:
        vals = [o.get("value") for o in s.get("options", [])]
        if not vals or len(set(vals)) != len(vals):
            problems.append("enum %s 的 options 为空或重复" % s.get("key"))
    if problems:
        bad(1, "mod.json：" + "；".join(problems))
    else:
        ok(1, "mod.json 合法（id/entry/api/resources/%d 个配置项/%d 个下拉）"
           % (len(keys), len(enums)))

    # ---- 2 Runtime 目录
    names = sorted(os.listdir(os.path.join(BASE, "Runtime")))
    if names != ["ModAssembly.dll"]:
        bad(2, "Runtime/ 内容异常：%s" % names)
    else:
        ok(2, "Runtime/ 只含 ModAssembly.dll")

    # ---- 3 编译产物 == 打包用 DLL
    if not (os.path.isfile(DLL_BIN) and os.path.isfile(DLL_PKG)):
        bad(3, "缺少编译产物或 Runtime DLL")
    else:
        a, b = md5(DLL_BIN), md5(DLL_PKG)
        if a != b:
            bad(3, "编译产物与 Runtime/ModAssembly.dll 不一致（%s vs %s）" % (a, b))
        else:
            ok(3, "编译产物 == Runtime/ModAssembly.dll（%s）" % a)

    # ---- 4 pmod 结构 + 装机一致
    if not os.path.isfile(PMOD):
        bad(4, "dist 下没有 pmod")
    else:
        with zipfile.ZipFile(PMOD) as z:
            nl = z.namelist()
        inst = os.path.join(UD, "Mods", MOD_NAME + ".pmod")
        sub = []
        if sorted(nl) != ["Runtime/ModAssembly.dll", "mod.json"]:
            sub.append("条目异常 %s" % nl)
        if nl[0] != "mod.json":
            sub.append("mod.json 不在第 0 个条目")
        if not os.path.isfile(inst):
            sub.append("装机目录没有该 pmod")
        elif md5(inst) != md5(PMOD):
            sub.append("装机包与 dist 不一致")
        if sub:
            bad(4, "pmod：" + "；".join(sub))
        else:
            ok(4, "pmod 结构正确且与装机包字节一致（%s，%d B）" % (md5(PMOD)[:12], os.path.getsize(PMOD)))

    # ---- 5 宿主 settings 校验
    if not (os.path.isfile(VALIDATOR) and os.path.isdir(HOST)):
        bad(5, "找不到 ValidateSettings.dll 或宿主目录")
    else:
        p = subprocess.run(["dotnet", VALIDATOR, HOST, os.path.join(BASE, "mod.json")],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=180)
        if p.returncode != 0:
            bad(5, "宿主校验未通过：%s" % ((p.stdout or "") + (p.stderr or "")).strip()[-300:])
        else:
            ok(5, "宿主 ValidateDefinitions 通过")

    # ---- 6 已启用
    try:
        en = json.load(open(os.path.join(UD, "Mods", "enabled_mods.json"), encoding="utf-8"))
        if MOD_ID in en.get("enabledIds", []):
            ok(6, "enabled_mods.json 含 %s" % MOD_ID)
        else:
            bad(6, "enabled_mods.json 未启用 %s（游戏里不会加载）" % MOD_ID)
    except Exception as e:
        bad(6, "读 enabled_mods.json 失败：%r" % e)

    # ---- 7 DLL 关键符号
    if os.path.isfile(DLL_PKG):
        blob = open(DLL_PKG, "rb").read()
        need_syms = ["PlantPlacementMarkerEntry", "MarkerPainter", "IsBattleScene",
                     "RebuildCells", "CanPacketPlant", "CanvasItemAddPolyline",
                     "CanvasItemSetParent", "GetMapGridPosFromMouse", "packetPickControl", "RowColumn"]
        missing = [s for s in need_syms
                   if s.encode("utf-8") not in blob and s.encode("utf-16-le") not in blob]
        if missing:
            bad(7, "DLL 里缺少符号：%s" % missing)
        else:
            ok(7, "DLL 关键符号齐全（%d 项，%d B）" % (len(need_syms), len(blob)))

    # ---- 8 预览常量 == C# 常量
    try:
        cs = open(SRC, encoding="utf-8").read()
        pv = open(PREVIEW, encoding="utf-8").read()
        pairs = [  # (C# 片段, 预览片段, 说明)
            ("0.17f", "(0.17", "圆环最小半径系数"),
            ("0.11f", "0.11 * p", "圆环脉动幅度系数"),
            ("0.119f", "0.119", "十字半长系数"),
            ("0.158f", "0.158", "四角内缩系数"),
            ("0.14f", "0.14", "角标臂长系数"),
            ("0.07f", "0.07", "圆角半径系数"),
            ("0.08f", "0.08 * p", "四角内移系数"),
            ("0.42f", "0.42", "行列交点十字半长系数"),
        ]
        pvmap = open(PREVIEW_MAP, encoding="utf-8").read() if os.path.isfile(PREVIEW_MAP) else ""
        miss = [(d, c, p) for c, p, d in pairs if c not in cs or p not in pv]
        if miss:
            bad(8, "预览与源码常量不一致：%s" % [d for d, _, _ in miss])
        else:
            # 真实地图预览里的"图形比例"也必须同源（它自己的格子基准来自地图 .tres）
            ratios = ["0.17 + 0.11 * p", "unit * 0.119", "0.158", "0.14", "unit * 0.07",
                      "unit * 0.08 * p", "unit * 0.42"]
            miss2 = [r for r in ratios if r not in pvmap]
            if miss2:
                bad(8, "preview_on_map.py 与源码比例不一致：%s" % miss2)
            else:
                ok(8, "两份预览共 %d+%d 个比例常量与 C# 源码一致" % (len(pairs), len(ratios)))
    except Exception as e:
        bad(8, "常量比对失败：%r" % e)

    # ---- 9 构建指纹：产物必须"是这个源码编出来的"
    stamp_path = os.path.join(BASE, "runtime_src", "build_stamp.json")
    if not os.path.isfile(stamp_path):
        bad(9, "缺少 runtime_src/build_stamp.json（用 build_and_install.py 重新编译一次即可生成）")
    else:
        try:
            stamp = json.load(open(stamp_path, encoding="utf-8"))
            cur = {}
            srcdir = os.path.join(BASE, "runtime_src")
            for name in sorted(os.listdir(srcdir)):
                if name.endswith(".cs") or name.endswith(".csproj"):
                    cur[name] = md5_sha256(os.path.join(srcdir, name))
            cur["mod.json"] = md5_sha256(os.path.join(BASE, "mod.json"))
            stale = [k for k, v in cur.items() if stamp.get("sources", {}).get(k) != v]
            missing = [k for k in stamp.get("sources", {}) if k not in cur]
            dll_now = md5_sha256(DLL_PKG)
            if stale or missing:
                bad(9, "源码比产物新（产物是旧源码编的）：变更/新增=%s 已删=%s → 重新编译" % (stale, missing))
            elif stamp.get("dllMd5") != dll_now:
                bad(9, "构建指纹与 Runtime DLL 不一致：stamp=%s dll=%s → 重新编译"
                    % (str(stamp.get("dllMd5"))[:12], dll_now[:12]))
            else:
                ok(9, "构建指纹匹配（源码 %d 个文件 + mod.json，dllMd5=%s，modVersion=%s）"
                   % (len(cur) - 1, dll_now[:12], stamp.get("modVersion")))
        except Exception as e:
            bad(9, "构建指纹校验失败：%r" % e)

    print()
    if fails:
        print("结果：%d 项未通过 -> %s" % (len(fails), fails))
        return 1
    print("结果：9 项全部通过（实机观感仍需人工确认）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
