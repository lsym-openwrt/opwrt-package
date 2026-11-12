#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模拟 4 个规则集镜像的真实下载行为（momo_convert.py 测速选源自测用）。

环境变量：
  MOMO_CURL_SPEED_MAP  JSON: { "<host>": {"elapsed": 0.5, "bytes": 57456,
                                          "code": 206} }
                       缺失的 host = 连接失败；code 非 200/206 = HTTP 失败；
                       elapsed > --max-time = 模拟 curl 超时。
  MOMO_CURL_SPEED_LOG  每次调用追加一行 host，用于断言「原生配置不探测」。

只实现转换器实际使用的 curl 参数：-o / -w / -r / --max-time / -L 等。
"""
from __future__ import annotations

import json
import os
import sys
import time
from urllib.parse import urlsplit


def arg_value(args, flag, default=None):
    for i, a in enumerate(args):
        if a == flag and i + 1 < len(args):
            return args[i + 1]
    return default


def main():
    args = sys.argv[1:]
    url = args[-1] if args else ""
    host = urlsplit(url).netloc
    out_path = arg_value(args, "-o")
    fmt = arg_value(args, "-w", "%{http_code} %{size_download} %{time_total}")
    try:
        max_time = float(arg_value(args, "--max-time", "8"))
    except ValueError:
        max_time = 8.0
    try:
        max_size = int(arg_value(args, "--max-filesize", "81920"))
    except ValueError:
        max_size = 81920
    byte_range = arg_value(args, "-r", "")
    rng_end = 81920
    if "-" in byte_range:
        try:
            rng_end = int(byte_range.split("-", 1)[1]) + 1
        except ValueError:
            pass

    log = os.environ.get("MOMO_CURL_SPEED_LOG", "")
    if log:
        try:
            with open(log, "a", encoding="utf-8") as f:
                f.write("%s\n" % host)
        except OSError:
            pass

    try:
        mapping = json.loads(os.environ.get("MOMO_CURL_SPEED_MAP", "{}"))
    except ValueError:
        mapping = {}
    entry = mapping.get(host)
    if not isinstance(entry, dict):
        sys.stderr.write("curl: (7) Failed to connect to %s\n" % host)
        return 7

    elapsed = float(entry.get("elapsed", 0.1))
    code = int(entry.get("code", 206))
    size = int(entry.get("bytes", 57456))
    if not entry.get("ignore_range"):
        size = min(size, rng_end)
    if elapsed > max_time:
        time.sleep(max_time)
        sys.stderr.write("curl: (28) Operation timed out after %d ms\n" % int(max_time * 1000))
        return 28
    if size > max_size:
        time.sleep(min(elapsed, max_time))
        sys.stderr.write("curl: (63) Maximum file size exceeded\n")
        return 63
    time.sleep(elapsed)

    if out_path:
        try:
            with open(out_path, "wb") as f:
                # 真实 .srs 二进制文件头，供转换器识别劫持页/错误页；
                # body=html 用于模拟「HTTP 200 但返回劫持页」的场景
                fake = entry.get("body") == "html" or code not in (200, 206)
                body = (b"<html>hijacked</html>" + b"x" * size) if fake \
                    else (b"SRS" + b"x" * size)
                f.write(body[:size])
        except OSError as exc:
            sys.stderr.write("curl: (23) %s\n" % exc)
            return 23
    text = (fmt.replace("%{http_code}", str(code))
               .replace("%{size_download}", str(max(0, size)))
               .replace("%{time_total}", "%.6f" % elapsed))
    sys.stdout.write(text)
    # 模拟「curl 非零退出但仍输出 -w」的截断/写盘失败场景
    return int(entry.get("rc", 0))


if __name__ == "__main__":
    sys.exit(main())
