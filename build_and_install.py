# -*- coding: utf-8 -*-
"""种植位置标识：编译 → 打包 → 装机（一条龙）。

用法：
    python build_and_install.py            # 只编译
    python build_and_install.py --install  # 编译 + 打包 + 装机 + 清解包缓存

坑位说明（照抄 HealthCooldownLine 的实战结论）：
  · dotnet build 必须显式 -p:GodotRefDir=...，否则 GodotSharp/PlantsVsZombies 解析不到；
  · TEMP/NUGET/DOTNET_CLI_HOME 重定向到工作区 .cache，避免沙箱拦截；
  · 编译前后清 dotnet.exe 残留，否则 obj/ 被锁会卡死；
  · 打包后必须核对「编译产物 md5 == 包内 DLL md5 == 装机包 md5」。
"""
import hashlib
import os
import shutil
import subprocess
import sys

_MROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(_MROOT, "_modenv.py")):
    _p = os.path.dirname(_MROOT)
    if _p == _MROOT:
        break
    _MROOT = _p
if _MROOT not in sys.path:
    sys.path.insert(0, _MROOT)
from _modenv import (  # noqa: E402
    WORKSPACE, UD, MODS_DIR, CACHE, PY, DOTNET, DOTNET_ROOT, require_ref_dir, ensure_mods,
)

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "runtime_src")
RUNTIME = os.path.join(BASE, "Runtime")
DIST = os.path.join(BASE, "dist")
MOD_NAME = "PlantPlacementMarker"
DLL_NAME = "JTYPlantPlacementMarker.dll"
LOG = os.path.join(SRC, "build_last.log")

HOME = os.path.join(WORKSPACE, ".cache", "dotnet_home")
TMPD = os.path.join(HOME, "tmp")
NUGET = os.path.join(WORKSPACE, ".cache", "nuget")

lines = []


def log(s=""):
    lines.append(str(s))



def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def write_stamp():
    """编译成功后落一份"源码指纹 + 产物哈希"，供 check_gates 第 9 项判"产物是不是本次源码的"。

    背景（2026-10-24 踩到）：源码改错 → 编译失败 → 旧 DLL 原封不动留在 Runtime/，
    而"编译产物 == Runtime DLL"这类一致性闸门照样全绿，等于**闸门在给旧包背书**。
    """
    import hashlib as _h
    import json as _j
    srcs = {}
    for name in sorted(os.listdir(SRC)):
        if name.endswith(".cs") or name.endswith(".csproj"):
            srcs[name] = _sha(os.path.join(SRC, name))
    srcs["mod.json"] = _sha(os.path.join(BASE, "mod.json"))
    stamp = {
        "modVersion": _j.load(open(os.path.join(BASE, "mod.json"), encoding="utf-8"))["version"],
        "sources": srcs,
        "dllMd5": _sha(os.path.join(RUNTIME, "ModAssembly.dll")),
    }
    out = os.path.join(SRC, "build_stamp.json")
    with open(out, "w", encoding="utf-8") as f:
        _j.dump(stamp, f, ensure_ascii=False, indent=2, sort_keys=True)
    log("[stamp] 已写构建指纹 -> %s（modVersion=%s, dllMd5=%s）"
        % (out, stamp["modVersion"], stamp["dllMd5"][:12]))


def run_compile():
    for d in (HOME, TMPD, NUGET):
        os.makedirs(d, exist_ok=True)
    env = dict(os.environ)
    env["DOTNET_ROOT"] = DOTNET_ROOT
    env["DOTNET_CLI_HOME"] = HOME
    env["TEMP"] = TMPD
    env["TMP"] = TMPD
    env["TMPDIR"] = TMPD
    env["NUGET_PACKAGES"] = NUGET
    env["DOTNET_NOLOGO"] = "1"
    env["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1"
    env["DOTNET_SKIP_FIRST_TIME_EXPERIENCE"] = "1"
    env["MSBUILDDISABLENODEREUSE"] = "1"

    csproj = next((f for f in sorted(os.listdir(SRC)) if f.endswith(".csproj")), None)
    if not csproj:
        log("[compile] %s 下找不到 .csproj" % SRC)
        return False
    cmd = [DOTNET, "build", os.path.join(SRC, csproj),
           "-c", "Release",
           "-p:GodotRefDir=" + require_ref_dir(),
           "-p:UseSharedCompilation=false", "-m:1", "-nodeReuse:false", "-v:q", "-nologo"]
    p = subprocess.run(cmd, cwd=SRC, env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=600)
    log("[compile] RC=%d" % p.returncode)
    if p.stdout:
        log(p.stdout.strip())
    if p.stderr:
        log(p.stderr.strip())
    return p.returncode == 0


def copy_dll():
    os.makedirs(RUNTIME, exist_ok=True)
    src = os.path.join(SRC, "bin", "Release", DLL_NAME)
    if not os.path.isfile(src):
        log("[copy] 未找到编译产物：" + src)
        return False
    dst = os.path.join(RUNTIME, "ModAssembly.dll")
    shutil.copyfile(src, dst)
    log("[copy] %s -> Runtime/ModAssembly.dll (%d B)" % (DLL_NAME, os.path.getsize(dst)))
    return True


def main():
    try:
        subprocess.run(["taskkill", "/F", "/IM", "dotnet.exe"], capture_output=True, timeout=30)
    except Exception:
        pass

    if not run_compile():
        log("编译失败，终止。")
        return 1
    log("[compile] OK")
    if not copy_dll():
        return 1
    write_stamp()

    if "--install" not in sys.argv:
        return 0

    p = subprocess.run([PY, os.path.join(BASE, "build_pmod.py")], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=300,
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    log("[package] RC=%d" % p.returncode)
    log((p.stdout or "").strip())
    dist = os.path.join(DIST, MOD_NAME + ".pmod")
    if p.returncode != 0 or not os.path.isfile(dist):
        log("打包失败，终止。")
        return 1

    ensure_mods()
    dst = os.path.join(MODS_DIR, MOD_NAME + ".pmod")
    shutil.copyfile(dist, dst)
    log("[install] %s (%d B)" % (dst, os.path.getsize(dst)))

    # 清解包缓存（只清本 Mod 的；先确认游戏没在跑）
    try:
        procs = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Process | Where-Object { $_.ProcessName -like '*Csharp*' -or $_.Path -like '*Csharp.exe' } | Select-Object -ExpandProperty Id"],
            capture_output=True, text=True, timeout=60)
        running = (procs.stdout or "").strip()
        if running:
            log("[cache] ⚠️ 检测到游戏进程在运行（PID: %s），跳过清缓存" % running.replace("\n", ","))
        else:
            target = os.path.join(CACHE, MOD_NAME)
            if os.path.isdir(target):
                shutil.rmtree(target, ignore_errors=True)
                log("[cache] 已清 ModsCache/%s" % MOD_NAME)
    except Exception as ex:
        log("[cache] 跳过（%r）" % ex)
    return 0


if __name__ == "__main__":
    rc = 0
    try:
        rc = main()
    except Exception as e:
        import traceback
        log("EXC: %r" % e)
        log(traceback.format_exc())
        rc = 1
    with open(LOG, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    # 控制台是 GBK 时，日志里任何非 GBK 字符都会让 print 抛 UnicodeEncodeError，
    # 脚本于是以"异常"收尾 ⇒ 明明构建+装机全成功，_build_locked.py 却报 RC=1（假失败）。
    # 与 TimeStop / WaveInfoBar 的构建脚本同款兜底：降级替换，退出码仍由 rc 决定。
    try:
        sys.stdout.reconfigure(encoding=sys.stdout.encoding or "utf-8", errors="replace")
    except Exception:
        pass
    try:
        print("\n".join(lines))
    except Exception:
        print("\n".join(lines).encode("utf-8", "replace").decode("utf-8", "replace"))
    sys.exit(rc)
