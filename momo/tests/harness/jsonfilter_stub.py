#!/usr/bin/env python3
"""最小 jsonfilter 兼容实现，仅覆盖 momo.init / hijack 使用的表达式语法。

支持：@['key']、[*]、[@['key']='value']，-i 文件输入与 -a 数组输入。
"""
import json
import re
import sys

from pathutil import winpath


def tokenize(expr):
    tokens = []
    i = 0
    while i < len(expr):
        if expr[i] == "@":
            i += 1
            continue
        m = re.match(r"\[@\['([^']+)'\]\[@='([^']*)'\]\]", expr[i:])
        if m:
            tokens.append(("contains", m.group(1), m.group(2)))
            i += m.end()
            continue
        m = re.match(r"\[@\['([^']+)'\]='([^']*)'\]", expr[i:])
        if m:
            tokens.append(("filter", m.group(1), m.group(2)))
            i += m.end()
            continue
        if expr.startswith("[*]", i):
            tokens.append(("star",))
            i += 3
            continue
        m = re.match(r"\['([^']+)'\]", expr[i:])
        if m:
            tokens.append(("key", m.group(1)))
            i += m.end()
            continue
        i += 1
    return tokens


def main():
    args = sys.argv[1:]
    infile = None
    expr = None
    array_mode = False
    i = 0
    while i < len(args):
        if args[i] == "-i":
            infile = args[i + 1]
            i += 2
        elif args[i] == "-e":
            expr = args[i + 1]
            i += 2
        elif args[i] == "-a":
            array_mode = True
            i += 1
        elif args[i] in ("-q", "-t", "-s"):
            i += 1
        else:
            i += 1
    if not expr:
        return 1
    if infile:
        with open(winpath(infile), "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        lines = [x for x in sys.stdin.read().splitlines() if x.strip()]
        vals = []
        for line in lines:
            try:
                vals.append(json.loads(line))
            except ValueError:
                vals.append(line)
        data = vals if len(vals) != 1 else vals[0]

    tokens = tokenize(expr)
    array_input = array_mode or (tokens and tokens[0][0] in ("filter", "contains"))
    values = list(data) if (array_input and isinstance(data, list)) else [data]
    for tok in tokens:
        nxt = []
        if tok[0] == "key":
            for v in values:
                if isinstance(v, dict) and tok[1] in v:
                    nxt.append(v[tok[1]])
        elif tok[0] == "star":
            for v in values:
                if isinstance(v, list):
                    nxt.extend(v)
        elif tok[0] == "filter":
            for v in values:
                if isinstance(v, dict) and str(v.get(tok[1], "")) == tok[2]:
                    nxt.append(v)
        elif tok[0] == "contains":
            for v in values:
                if isinstance(v, dict) and tok[2] in [str(x) for x in (v.get(tok[1]) or [])]:
                    nxt.append(v)
        values = nxt

    for v in values:
        if isinstance(v, str):
            print(v)
        elif v is not None:
            print(json.dumps(v, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
