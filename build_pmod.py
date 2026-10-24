# -*- coding: utf-8 -*-
"""打包 PlantPlacementMarker.pmod（zip + 根 mod.json）。

硬护栏：
  · mod.json 必须在【根】且【唯一】
  · Runtime/ 下只允许 ModAssembly.dll
  · resources 声明必须与包内实际内容一致
  · 包内 DLL 的 md5 必须等于 runtime_src/bin/Release 的编译产物
"""
import hashlib
import json
import os
import sys
import zipfile

BASE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.join(BASE, "Runtime")
BINSRC = os.path.join(BASE, "runtime_src", "bin", "Release", "JTYPlantPlacementMarker.dll")
OUT_DIR = os.path.join(BASE, "dist")
MOD_NAME = "PlantPlacementMarker"
OUT = os.path.join(OUT_DIR, MOD_NAME + ".pmod")


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    if not os.path.isfile(os.path.join(BASE, "mod.json")):
        print("缺少 mod.json")
        return 1

    runtime_dll = os.path.join(RUNTIME, "ModAssembly.dll")
    if not os.path.isfile(runtime_dll):
        print("缺少 Runtime/ModAssembly.dll —— 先跑编译")
        return 1

    # 护栏 0：Runtime 里的 DLL 必须是最新编译产物
    if os.path.isfile(BINSRC):
        m_new, m_old = md5(BINSRC), md5(runtime_dll)
        if m_new != m_old:
            print("[护栏0] Runtime/ModAssembly.dll 与最新编译产物不一致 → 自动覆盖")
            print("       编译产物:", m_new)
            print("       Runtime/:", m_old)
            import shutil
            shutil.copyfile(BINSRC, runtime_dll)
    else:
        print("[护栏0·提示] 未找到 bin/Release 产物，直接使用现有 Runtime/ModAssembly.dll")

    man = json.load(open(os.path.join(BASE, "mod.json"), encoding="utf-8"))

    names = sorted(os.listdir(RUNTIME))
    bad = [n for n in names if n != "ModAssembly.dll"]
    if bad:
        print("Runtime/ 下有非法文件（会被整包拒收）:", bad)
        return 2

    res_dir = os.path.join(BASE, "Resources")
    art = []
    if os.path.isdir(res_dir):
        art = sorted("Resources/" + n for n in os.listdir(res_dir) if n.lower().endswith(".png"))
    actual = sorted(["Runtime/ModAssembly.dll"] + art, key=str.lower)
    declared = sorted(man.get("resources", []), key=str.lower)
    if actual != declared:
        print("resources 不一致\n  实际:", actual, "\n  声明:", declared)
        return 3

    if man.get("runtimeAssembly") != "Runtime/ModAssembly.dll":
        print("runtimeAssembly 必须恰好是字面量 Runtime/ModAssembly.dll")
        return 4
    if not isinstance(man.get("runtimeApiVersion"), int) or man.get("runtimeApiVersion") < 1:
        print("runtimeApiVersion 必须 >= 1")
        return 5
    if man.get("runtimeEntryType") != "PlantPlacementMarkerEntry":
        print("runtimeEntryType 必须是 PlantPlacementMarkerEntry")
        return 6

    os.makedirs(OUT_DIR, exist_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(os.path.join(BASE, "mod.json"), "mod.json")
        z.write(runtime_dll, "Runtime/ModAssembly.dll")
        for rel in art:
            z.write(os.path.join(BASE, rel.replace("/", os.sep)), rel)

    with zipfile.ZipFile(OUT) as z:
        nl = z.namelist()
    print("OK ->", OUT)
    print("  大小:", os.path.getsize(OUT), "字节")
    print("  内容:", nl)
    print("  包内 DLL md5:", md5(runtime_dll))
    if nl.count("mod.json") != 1 or nl[0] != "mod.json":
        print("  ⚠️ mod.json 不在根或不止一个")
        return 7
    return 0


if __name__ == "__main__":
    sys.exit(main())
