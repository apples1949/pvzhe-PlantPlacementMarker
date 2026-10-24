# -*- coding: utf-8 -*-
"""实机自检：把本 Mod 的两个诊断开关临时打开 → 启动游戏（尽量直接进沙盒场景）→
等 Mod 自己把整屏存成 PNG → 关游戏 → 还原配置。

为什么这样做：本机 `SetForegroundWindow` 拉不起后台窗口，外部截图+点击会点到别的程序；
但**游戏内的 Mod 可以给自己的视口截图**，于是验证闭环变成"跑一次 + 看一张图"。

用法（会弹出游戏窗口，建议在没人用电脑时跑）：
    python tools/selfcheck_launch.py
    python tools/selfcheck_launch.py --scene res://Scene/Sandbox/SandboxScreen.tscn
"""
import hashlib
import json
import os
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # mods/PlantPlacementMarker
WORK = os.path.dirname(os.path.dirname(BASE))
EXE = os.path.join(WORK, "植物大战僵尸杂交版发布版0.31.0.Csharp.exe")
UD = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"),
                  "Godot", "app_userdata", "植物大战僵尸杂交版")
LOG = os.path.join(UD, "logs", "godot.log")
SHOT = os.path.join(UD, "PlantPlacementMarker_shot.png")
MOD_ID = "plantplacementmarker"
SETTINGS = os.path.join(UD, "ModSettings",
                        hashlib.sha256(MOD_ID.encode()).hexdigest() + ".json")
DEFAULT_SCENE = ""   # 本机构建禁用了 path overrides（传场景路径会直接 abort），只能正常启动

DEBUG_VALUES = {"enabled": True, "style": "circle", "thickness": "normal",
                "showCenterCross": True, "color": "#FFFFFF",
                "debugShowGrid": True, "debugScreenshot": True,
                "debugSmoke": True, "enableLog": True}


def read_settings():
    if not os.path.isfile(SETTINGS):
        return None
    try:
        return json.load(open(SETTINGS, encoding="utf-8"))
    except Exception:
        return None


def write_settings(values):
    os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
    payload = {"version": 1, "modId": MOD_ID, "values": values}
    with open(SETTINGS, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def tail(path, n=40):
    if not os.path.isfile(path):
        return "(no log)"
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - 12000))
        return f.read().decode("utf-8", "replace")[-3000:]


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    scene = DEFAULT_SCENE
    for a in sys.argv[1:]:
        if a.startswith("--scene="):
            scene = a.split("=", 1)[1]
        elif a.startswith("--scene"):
            i = sys.argv.index(a)
            if i + 1 < len(sys.argv):
                scene = sys.argv[i + 1]

    if not os.path.isfile(EXE):
        print("找不到游戏 exe:", EXE)
        return 2

    backup = read_settings()
    print("原配置:", json.dumps(backup, ensure_ascii=False) if backup else "(无，将新建)")

    if os.path.isfile(SHOT):
        os.remove(SHOT)

    write_settings(DEBUG_VALUES)
    print("已临时写入诊断配置 ->", SETTINGS)

    args = [EXE] + ([scene] if scene else [])
    proc = subprocess.Popen(args, cwd=os.path.dirname(EXE))
    print("已启动:", " ".join(args))

    shot_ok = False
    deadline = time.time() + 60
    while time.time() < deadline:
        time.sleep(2)
        if os.path.isfile(SHOT) and os.path.getsize(SHOT) > 1000:
            shot_ok = True
            break
        if proc.poll() is not None:
            print("游戏进程已退出，code=", proc.returncode)
            break

    print("截图:", shot_ok, ("->" + SHOT) if shot_ok else "(未生成)")
    print("--- 日志尾部 ---")
    print(tail(LOG))

    try:
        proc.terminate()
        time.sleep(2)
        if proc.poll() is None:
            proc.kill()
    except Exception as e:
        print("关游戏失败:", repr(e))

    # 收尾：还原配置 + 清 boot journal（强杀会留下 inProgress，导致下次进零 Mod 安全模式）
    if backup is None:
        try:
            os.remove(SETTINGS)
        except Exception:
            pass
    else:
        write_settings(backup.get("values", {}))
    for f in ("mod_boot_journal.json", "mod_last_good.json"):
        p = os.path.join(UD, "Mods", f)
        if os.path.isfile(p):
            try:
                os.remove(p)
                print("已删", f)
            except Exception:
                pass
    print("已还原配置")
    return 0 if shot_ok else 1


if __name__ == "__main__":
    sys.exit(main())
