#!/usr/bin/env python3
"""sing-box 命令桩：format / check / run。

check 优先调用真实 sing-box 1.14+ 二进制（环境变量 SING_BOX_REAL）；
二进制不存在时退化为 JSON 结构校验，让测试在无内核环境下也能跑。
"""
import json
import os
import subprocess
import sys

from pathutil import winpath


def config_path(args):
    if "-c" in args:
        return args[args.index("-c") + 1]
    if "-D" in args:
        return os.path.join(args[args.index("-D") + 1], "config.json")
    return None


def real_check(path, real):
    if not real or not os.path.isfile(real):
        return 0, "skipped (no sing-box binary)"
    proc = subprocess.run([real, "check", "-c", path],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    detail = (proc.stderr or proc.stdout).decode("utf-8", "replace").strip()
    return proc.returncode, detail


def main():
    args = sys.argv[1:]
    real = os.environ.get("SING_BOX_REAL", "")
    path = winpath(config_path(args))
    if not path or not os.path.isfile(path):
        print("sing-box stub: 找不到配置文件: %s" % path, file=sys.stderr)
        return 1
    if "format" in args:
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except (OSError, ValueError):
            return 1
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
            f.write("\n")
        rc, detail = real_check(path, real)
        if rc:
            print(detail, file=sys.stderr)
        return rc
    if "check" in args:
        try:
            with open(path, "r", encoding="utf-8") as f:
                json.load(f)
        except (OSError, ValueError):
            return 1
        rc, detail = real_check(path, real)
        if rc:
            print(detail, file=sys.stderr)
        return rc
    if "run" in args:
        print("sing-box stub: run simulated")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
