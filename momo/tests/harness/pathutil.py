#!/usr/bin/env python3
"""Git Bash (MSYS) 路径 -> Windows 路径；供测试桩在 Windows 上打开配置文件。"""
import re


def winpath(path):
    if not path:
        return path
    p = str(path).replace("\\", "/")
    m = re.match(r"^/([A-Za-z])/(.*)$", p)
    if m:
        return "%s:/%s" % (m.group(1).upper(), m.group(2))
    return p
