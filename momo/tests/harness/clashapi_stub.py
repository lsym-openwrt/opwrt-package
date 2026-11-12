#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试专用：模拟 sing-box Clash API，用于验证 momo 分组驱动逻辑。

仅在开发机运行（可用完整标准库）；目标设备上的 momo 不依赖本文件。

  GET  /proxies                        -> {"proxies": {...}}
  GET  /proxies/<name>                 -> 单个 proxy
  GET  /proxies/<name>/delay?url=&timeout=  -> {"delay": ms} / 503
  GET  /group/<name>/delay?url=&timeout=    -> {"成员": ms, ...}（仅可用成员）
  PUT  /proxies/<name>  {"name": "..."} -> 204，记录切换日志
  GET  /__state                        -> 内部状态（含 select_log）
  POST /__control                      -> 注入 {"delays": {...}} / {"now": {组: 成员}}
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, unquote, urlparse

STATE = {
    "proxies": {},
    "delays": {},
    "select_log": [],
    "builtin_delay": 1,
}


def member_delay(name, depth=0):
    if depth > 4:
        return None
    if name in STATE["delays"]:
        return STATE["delays"][name]
    info = STATE["proxies"].get(name)
    if isinstance(info, dict) and info.get("type") == "Selector":
        return member_delay(info.get("now"), depth + 1)
    if name in ("direct", "block"):
        return STATE["builtin_delay"]
    return None


def proxy_view(name, info):
    return {
        "type": info.get("type", "Selector"), "name": name,
        "udp": True, "history": [], "now": info.get("now"),
        "all": list(info.get("all", [])),
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, OSError):
            return {}

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/__state":
            return self._send(200, STATE)
        if path == "/proxies":
            return self._send(200, {"proxies": dict(
                (k, proxy_view(k, v)) for k, v in STATE["proxies"].items())})
        if path.startswith("/proxies/"):
            name = path[len("/proxies/"):]
            if name.endswith("/delay"):
                name = name[:-len("/delay")]
                delay = member_delay(name)
                if delay is None:
                    return self._send(503, {"message": "An error occurred in the delay test"})
                return self._send(200, {"delay": delay})
            info = STATE["proxies"].get(name)
            if info is None:
                return self._send(404, {"message": "Resource not found"})
            return self._send(200, proxy_view(name, info))
        if path.startswith("/group/") and path.endswith("/delay"):
            tag = path[len("/group/"):-len("/delay")]
            info = STATE["proxies"].get(tag)
            if info is None:
                return self._send(404, {"message": "Resource not found"})
            result = {}
            for member in info.get("all", []):
                delay = member_delay(member)
                if delay is not None:
                    result[member] = delay
            return self._send(200, result)
        return self._send(404, {"message": "Resource not found"})

    def do_PUT(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if not path.startswith("/proxies/"):
            return self._send(404, {"message": "Resource not found"})
        name = path[len("/proxies/"):]
        info = STATE["proxies"].get(name)
        if info is None:
            return self._send(404, {"message": "Resource not found"})
        if info.get("type") != "Selector":
            return self._send(400, {"message": "Must be a Selector"})
        target = self._body().get("name")
        if target not in info.get("all", []):
            return self._send(400, {"message": "Selector update error: not found"})
        info["now"] = target
        STATE["select_log"].append({"group": name, "name": target})
        self.send_response(204)
        self.end_headers()

    def do_POST(self):
        if unquote(urlparse(self.path).path) != "/__control":
            return self._send(404, {"message": "Resource not found"})
        payload = self._body()
        if isinstance(payload.get("delays"), dict):
            STATE["delays"].update(payload["delays"])
        if isinstance(payload.get("now"), dict):
            for group, member in payload["now"].items():
                info = STATE["proxies"].get(group)
                if isinstance(info, dict):
                    info["now"] = member
        if isinstance(payload.get("builtin_delay"), int):
            STATE["builtin_delay"] = payload["builtin_delay"]
        if payload.get("clear_log"):
            STATE["select_log"] = []
        return self._send(200, {"ok": True})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--port-file", default="")
    ap.add_argument("--state", default="")
    args = ap.parse_args()
    if args.state and os.path.isfile(args.state):
        try:
            with open(args.state, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            for key in ("proxies", "delays"):
                if isinstance(loaded.get(key), dict):
                    STATE[key] = loaded[key]
        except (OSError, ValueError):
            pass
    server = HTTPServer(("127.0.0.1", args.port), Handler)
    if args.port_file:
        with open(args.port_file, "w", encoding="utf-8") as f:
            f.write(str(server.server_address[1]))
    sys.stdout.write("ready %s\n" % server.server_address[1])
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
