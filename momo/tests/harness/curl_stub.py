#!/usr/bin/env python3
"""curl 桩：按 MOMO_CURL_MAP (url -> 本地文件) 返回订阅内容。

映射值可以是字符串（所有 UA 都返回它），也可以是 dict（按 UA 区分）：
    {"https://x/sub": {"clash.meta": "<file>", "*": "<file>"}}
指定 UA 不在 dict 里也没有 "*" 时返回 22（等价 curl -f 遇到 404）。
每次请求的 UA 追加到 $MOMO_TEST_ROOT/curl_ua.log，供断言 UA 试探顺序。
"""
import json
import os
import sys

from pathutil import winpath


def main():
    args = sys.argv[1:]
    out = None
    header = None
    url = None
    ua = ""
    i = 0
    while i < len(args):
        if args[i] == "-o":
            out = args[i + 1]
            i += 2
        elif args[i] == "-D":
            header = args[i + 1]
            i += 2
        elif args[i] in ("-s", "-f", "-L", "-X", "-A", "-m", "--connect-timeout", "--retry"):
            # -X/-A/-m/--connect-timeout/--retry 后跟参数，其余是开关
            if args[i] == "-A" and i + 1 < len(args):
                ua = args[i + 1]
            if args[i] in ("-X", "-A", "-m", "--connect-timeout", "--retry") and i + 1 < len(args):
                i += 2
            else:
                i += 1
        elif args[i].startswith("-"):
            i += 1
        else:
            url = args[i]
            i += 1
    map_path = os.environ.get("MOMO_CURL_MAP", "")
    mapping = {}
    if map_path and os.path.isfile(map_path):
        with open(map_path, "r", encoding="utf-8") as f:
            mapping = json.load(f)
    root = os.environ.get("MOMO_TEST_ROOT", "")
    if root:
        try:
            with open(winpath(root + "/curl_ua.log"), "a", encoding="utf-8") as f:
                f.write("%s\t%s\n" % (ua, url))
        except OSError:
            pass
    if url not in mapping:
        return 22
    entry = mapping[url]
    if isinstance(entry, dict):
        entry = entry.get(ua) or entry.get("*")
        if not entry:
            return 22
    with open(winpath(entry), "rb") as f:
        body = f.read()
    if header:
        with open(winpath(header), "w", encoding="utf-8") as f:
            f.write("HTTP/1.1 200 OK\r\nsubscription-userinfo: upload=1024; download=2048; total=10737418240; expire=1893456000\r\n\r\n")
    if out:
        with open(winpath(out), "wb") as f:
            f.write(body)
    else:
        sys.stdout.buffer.write(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
