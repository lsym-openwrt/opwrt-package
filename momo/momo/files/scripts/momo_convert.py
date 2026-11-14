#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""momo 订阅/节点/YAML -> sing-box 1.14+ 配置转换器（无第三方依赖）。

移植自 xinggaoya/sing-box-windows 的订阅解析与配置生成链：
  parser.rs            -> 输入识别、URI / Clash YAML / JSON 节点提取
  config_generator.rs  -> 节点归一化、去重、分组注入
  config_validator.rs  -> 写盘前用 sing-box check 校验
输出骨架改为 momo 专用模板（momo-base.json），补齐 momo 依赖的
inbound / fakeip DNS / route 结构，之后仍由 momo 原有 mixin -> format -> check -> run 链路接管。

远程规则集：转换时对 gh-proxy / testingcf.jsdelivr / fastly.jsdelivr / ghfast
四个镜像并行下载 geosite-cn.srs 前 80KB 实测耗时，按 80KB/s 硬阈值选出最快源，
再把 geosite/geoip 两条 rule_set 写入 profile（详见 RULESET_MIRRORS 注释）。

用法：
  momo_convert.py --input FILE [--in-place | --output FILE] [--template FILE]
  momo_convert.py --check

支持的订阅格式（自动识别，同一套链路）：
  * Clash / Mihomo YAML —— 含「序列与父键同缩进」、Tab 缩进、跨行 flow 列表、
    锚点 &a / 合并键 <<: *a、proxy-providers（远程节点池）、proxy-groups、rules
  * Clash JSON / 裸 JSON 节点数组 / 任意包裹层级的节点对象
  * sing-box 原生配置（逐字节透传，缺 momo 骨架时自动补齐）
  * SIP008（shadowsocks 订阅标准，servers[]）
  * Surge / Loon 的 [Proxy] + [Proxy Group]
  * Quantumult X 的 [server_local] + [policy]
  * 分享链接列表：vmess / vless / trojan / trojan-go / ss（含 SIP002 plugin）/
    ssr（仅作提示，内核已移除）/ hysteria / hysteria2 / hy2 / tuic / anytls /
    snell / socks5 / http(s) / ssh
  * 以上任意格式的 base64 包裹（含多层嵌套、URL-safe、缺 padding、CRLF）
"""
from __future__ import annotations

import argparse
import base64
import binascii
import ipaddress
import json
import os
import re
import subprocess
import sys
import tempfile
import time

VERSION = "1.4.1"
DEFAULT_TEMPLATE = "/etc/momo/converter/momo-base.json"
DEFAULT_CONF = "/etc/momo/converter/converter.conf"

TAG_AUTO = "auto"
TAG_PROXY = "proxy"
TAG_DIRECT = "direct"
TAG_BLOCK = "block"
RESERVED_TAGS = {TAG_AUTO, TAG_PROXY, TAG_DIRECT, TAG_BLOCK}

# Clash/Mihomo 分组语义默认值（mihomo 官方文档 url-test/fallback/load-balance）
DEFAULT_TEST_URL = "http://cp.cloudflare.com/generate_204"
DEFAULT_INTERVAL = 300          # 秒
DEFAULT_TOLERANCE = 50          # 毫秒，仅当候选快出容差才切换，抑制抖动
DEFAULT_TIMEOUT = 5000          # 毫秒
GROUP_TYPES = {"url-test": "url-test", "urltest": "url-test",
               "health-check": "url-test", "fallback": "fallback",
               "load-balance": "load-balance", "loadbalance": "load-balance",
               "select": "select", "selector": "select", "relay": "select"}
LB_STRATEGIES = {"round-robin", "consistent-hashing", "sticky-sessions"}
# GLOBAL 是 mihomo 内置策略名；订阅自己声明同名分组时由 assign_group_tags 让位
GROUP_BUILTIN_NAMES = {"DIRECT": TAG_DIRECT, "REJECT": TAG_BLOCK,
                       "GLOBAL": TAG_AUTO, "direct": TAG_DIRECT,
                       "block": TAG_BLOCK}

# parser.rs:is_supported_outbound_type + 本项目新增的 socks/http URI 支持
SUPPORTED_TYPES = {
    "vless", "vmess", "trojan", "shadowsocks", "shadowsocksr", "socks", "http",
    "hysteria", "hysteria2", "tuic", "anytls", "snell", "wireguard", "tailscale",
    "ssh", "direct", "selector", "urltest", "block",
}
# 能直接进 sing-box 1.14 outbounds 的节点类型。shadowsocksr / wireguard / tailscale
# 不在其中：前者 1.6 移除，后者 1.13 改为 endpoint，写进 outbounds 会让内核 FATAL。
PROXY_TYPES = {
    "vless", "vmess", "trojan", "shadowsocks", "socks", "http",
    "hysteria", "hysteria2", "tuic", "anytls", "snell", "ssh",
}
# 内核已经删掉、但订阅里仍大量存在的协议：解析出来只为给出明确跳过原因
REMOVED_TYPES = {
    "shadowsocksr": "ShadowsocksR 已在 sing-box 1.6 移除，无法转换",
    "wireguard": "WireGuard 在 sing-box 1.13 改为 endpoint，订阅链接无法直接生成出站",
}

# 订阅链接里可能出现的全部 scheme（含只用于提示跳过的）
URI_SCHEMES = {
    "vmess", "vless", "trojan", "trojan-go", "ss", "ssr", "hysteria", "hysteria2", "hy2",
    "tuic", "anytls", "snell", "socks", "socks5", "socks5h", "http", "https", "ssh",
    "wireguard", "wg", "juicity", "naive+https", "naive+quic",
}
# 明确不支持（sing-box 没有对应出站）的 scheme -> 原因
UNSUPPORTED_SCHEMES = {
    "wireguard": REMOVED_TYPES["wireguard"],
    "wg": REMOVED_TYPES["wireguard"],
    "juicity": "sing-box 不支持 juicity 协议",
    "naive+https": "sing-box 不支持 naiveproxy 协议",
    "naive+quic": "sing-box 不支持 naiveproxy 协议",
}
MOMO_INBOUND_TAGS = {"dns-in", "redirect-in", "tproxy-in", "tun-in"}
MOMO_FAKEIP_TAG = "fake-ip-dns-server"

# --------------------------------------------------------------------------
# 远程规则集镜像测速选源（转换订阅时自动执行）
# 国内网络无法直连 raw.githubusercontent.com：转换时对 4 个镜像真实下载
# geosite-cn.srs 前 80KB，按实测耗时排序 + 80KB/s 硬阈值筛选，geosite/geoip
# 两个 rule-set 一律使用选出的镜像（jsdelivr 系自动推导对应仓库路径）。
# --------------------------------------------------------------------------
RULESET_MIRRORS = [
    {"name": "gh-proxy",  "host": "gh-proxy.com",           "kind": "prefix"},
    {"name": "testingcf", "host": "testingcf.jsdelivr.net", "kind": "jsdelivr"},
    {"name": "fastly",    "host": "fastly.jsdelivr.net",    "kind": "jsdelivr"},
    {"name": "ghfast",    "host": "ghfast.top",             "kind": "prefix"},
]
DEFAULT_MIRROR = "gh-proxy"
RULESET_TARGETS = {
    "geosite": {"tag": "geosite-cn", "repo": "SagerNet/sing-geosite",
                "branch": "rule-set", "file": "geosite-cn.srs"},
    "geoip":   {"tag": "geoip-cn",   "repo": "SagerNet/sing-geoip",
                "branch": "rule-set", "file": "geoip-cn.srs"},
}
# SagerNet 官方 .srs 仓库（按 kind 分流）。meta-rules-dat 的 geosite/geoip 内容
# 与这里同名同源，是「Clash provider -> sing-box rule_set」最可靠的等价映射。
SRS_REPOS = {
    "geosite": {"repo": "SagerNet/sing-geosite", "branch": "rule-set"},
    "geoip":   {"repo": "SagerNet/sing-geoip",   "branch": "rule-set"},
}
# 高置信度标准 geosite/geoip 名（离线时无法 HEAD 校验，仅注入这些，避免 404 让内核 FATAL）
SRS_KNOWN = {
    "geosite": {
        "cn", "private", "youtube", "google", "github", "apple", "microsoft", "telegram",
        "tiktok", "netflix", "paypal", "binance", "okx", "steam", "twitter", "facebook",
        "instagram", "spotify", "disney", "openai", "onedrive", "category-ai-!cn",
        "category-cryptocurrency", "geolocation-!cn", "category-ads-all", "geolocation-cn",
    },
    "geoip": {"cn", "private", "telegram", "google", "netflix", "twitter", "facebook", "apple"},
}
DEFAULT_MIN_SPEED = 80          # KB/s 硬阈值：低于此值直接淘汰
DEFAULT_PROBE_TIMEOUT = 8       # 每个探测的超时上限（秒）
PROBE_RANGE = "0-81919"         # geosite-cn.srs 前 80KB 真实内容
PROBE_MAX_BYTES = 81920         # 防御镜像忽略 Range 返回整包，撑爆路由器 tmpfs
MIN_PROBE_BYTES = 4096          # 低于此字节数视为错误页/空响应，不算成功
SRS_MAGIC = b"SRS"              # .srs 二进制规则集文件头，识别劫持页/HTML 错误页

TRUE_WORDS = {"1", "true", "yes", "on"}
FALSE_WORDS = {"0", "false", "no", "off"}


class ConvertError(Exception):
    def __init__(self, message, code=2):
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------------------
# 通用工具（对应 parser.rs 的 helper 函数）
# --------------------------------------------------------------------------
def normalize_text(raw):
    if isinstance(raw, bytes):
        text = raw.decode("utf-8", "replace")
    else:
        text = raw
    text = text.lstrip("\ufeff")
    out = []
    for ch in text:
        if ch in "\u200b\u200c\u200d":
            continue
        if ord(ch) < 32 and ch not in "\n\r\t":
            continue
        out.append(ch)
    return "".join(out)


def parse_boolish(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    v = str(value).strip().lower()
    if v in TRUE_WORDS:
        return True
    if v in FALSE_WORDS:
        return False
    return None


def csv_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(x).strip() for x in value if str(x).strip()]
    return [x.strip() for x in str(value).split(",") if x.strip()]


# sing-box 的 vmess.security 只认这几个值；Surge/Loon/QuantumultX 习惯把
# shadowsocks 的 cipher 名（chacha20-ietf-poly1305、aes-256-gcm）填在同一列，
# 直接透传会让内核 FATAL（unsupported security type），必须先归一化。
VMESS_SECURITY_ALIASES = {
    "chacha20-ietf-poly1305": "chacha20-poly1305",
    "chacha20-poly1305": "chacha20-poly1305",
    "aes-128-gcm": "aes-128-gcm",
    "auto": "auto", "none": "none", "zero": "zero",
}


def normalize_vmess_security(value):
    v = str(value or "").strip().lower()
    if not v:
        return "auto"
    return VMESS_SECURITY_ALIASES.get(v, "auto")


def b64decode_relaxed(value):
    """对应 parser.rs:base64_decode_relaxed：容忍缺 padding / URL-safe。"""
    if value is None:
        return None
    s = re.sub(r"\s+", "", str(value))
    if not s:
        return None
    rem = len(s) % 4
    if rem:
        s += "=" * (4 - rem)
    for candidate in (s, s.replace("-", "+").replace("_", "/")):
        try:
            raw = base64.b64decode(candidate, validate=True)
        except (binascii.Error, ValueError):
            continue
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
    return None


def looks_like_subscription(text):
    """粗判这段文本是否「像订阅」，用于决定要不要再做一层 base64 解码。

    覆盖：Clash/Mihomo YAML 键、Surge/Loon/QuantumultX 的 [Section]、
    任意已知 scheme 的分享链接、JSON 订阅（sing-box/Clash/SIP008/节点数组）。
    """
    if not text:
        return False
    if re.search(r"(?m)^\s*(proxies|proxy-groups|proxy-providers)\s*:", text):
        return True
    if re.search(r"(?mi)^\s*\[(proxy|proxy group|server_local|server_remote|policy|"
                 r"server|general)\]\s*$", text):
        return True
    low = text.lower()
    for scheme in URI_SCHEMES:
        if ("%s://" % scheme) in low:
            return True
    head = text.lstrip()
    if head.startswith("{") or head.startswith("["):
        try:
            json.loads(head)
            return True
        except ValueError:
            return False
    return False


def decode_whole_base64(text):
    """整段 base64 订阅（subscription_service.rs:try_decode_base64_to_text）。"""
    stripped = text.strip()
    if not stripped or len(stripped) < 8:
        return None
    decoded = b64decode_relaxed(stripped)
    if decoded and looks_like_subscription(decoded):
        return decoded
    # 部分机场会在 URI 前拼前缀后再 base64（上游的兜底路径）
    cleaned = stripped
    for scheme in URI_SCHEMES:
        cleaned = cleaned.replace("%s://" % scheme, "")
    if cleaned != stripped:
        decoded = b64decode_relaxed(cleaned)
        if decoded and looks_like_subscription(decoded):
            return decoded
    return None


def base64_layers(text, max_layers=3):
    """逐层解 base64，返回 [第一层, 第二层, ...]。

    订阅被套两层 base64 的情况真实存在（机场 CDN 二次编码）。这里不预判内容，
    只负责把能成功解出来的层全部列出，交给格式识别逐层尝试 —— 解错的层不会
    被任何格式认领，最终仍然回落到原文，因此不会误吞正常配置。
    """
    layers = []
    current = str(text or "").strip()
    for _ in range(max_layers):
        decoded = b64decode_relaxed(current)
        if not decoded:
            break
        decoded = decoded.strip()
        if not decoded or decoded == current:
            break
        layers.append(decoded)
        current = decoded
    return layers


def parse_host_port(hostport):
    """兼容 IPv6 字面量 [2001:db8::1]:8388。"""
    s = str(hostport or "").strip()
    if s.startswith("["):
        end = s.find("]")
        if end < 0:
            return None
        server = s[1:end]
        rest = s[end + 1:]
        if not rest.startswith(":"):
            return None
        port_raw = rest[1:]
    else:
        if ":" not in s:
            return None
        server, port_raw = s.rsplit(":", 1)
    server = server.strip()
    try:
        port = int(port_raw.strip())
    except ValueError:
        return None
    if not server or not (1 <= port <= 65535):
        return None
    return server, port


def pct_decode(value, plus_as_space=False):
    """percent-decode 的轻量实现。

    OpenWrt 把 urllib 拆成独立包 python3-urllib（不在 python3-light 里），
    为避免新增依赖，这里用标准库中最基础的类型自行实现。
    """
    s = str(value or "")
    out = bytearray()
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "%" and i + 2 < len(s) and re.fullmatch(r"[0-9a-fA-F]{2}", s[i + 1:i + 3]):
            out.append(int(s[i + 1:i + 3], 16))
            i += 3
        elif ch == "+" and plus_as_space:
            out.append(32)
            i += 1
        elif ord(ch) < 128:
            out.append(ord(ch))
            i += 1
        else:
            out.extend(ch.encode("utf-8"))
            i += 1
    return out.decode("utf-8", "replace")


def split_uri(uri):
    """极简 URI 解析，覆盖 scheme://user:pass@host:port/path?query#fragment。"""
    m = re.match(r"^([A-Za-z][A-Za-z0-9+.-]*)://(.*)$", str(uri or ""), re.S)
    if not m:
        return None
    scheme, rest = m.group(1).lower(), m.group(2)
    rest, _, fragment = rest.partition("#")
    rest, _, query = rest.partition("?")
    netloc, _, path = rest.partition("/")
    path = "/" + path if path or "/" in rest else ""
    if "@" in netloc:
        userinfo, hostport = netloc.rsplit("@", 1)
        username, _, password = userinfo.partition(":")
    else:
        username, password, hostport = "", "", netloc
    if hostport.startswith("["):
        end = hostport.find("]")
        if end < 0:
            return None
        host = hostport[1:end]
        tail = hostport[end + 1:]
        port = int(tail[1:]) if tail.startswith(":") and tail[1:].isdigit() else None
    elif ":" in hostport:
        host, _, port_raw = hostport.rpartition(":")
        port = int(port_raw) if port_raw.isdigit() else None
    else:
        host, port = hostport, None
    return {
        "scheme": scheme, "host": host.lower(), "port": port,
        "username": username, "password": password,
        "netloc": netloc, "path": path, "query": query, "fragment": fragment,
    }


def parse_query(query_string):
    result = {}
    for part in (query_string or "").split("&"):
        if not part:
            continue
        key, _, value = part.partition("=")
        result[pct_decode(key, True)] = pct_decode(value, True)
    return result


def decode_tag(fragment):
    return pct_decode(fragment or "").strip()


def default_tag(scheme, host, port):
    return "%s-%s:%s" % (scheme, host, port)


def query_get(query, *keys):
    for key in keys:
        if key in query and str(query[key]).strip():
            return str(query[key]).strip()
    return ""


def insecure_from_query(query):
    """allowInsecure / insecure 两种命名（parser.rs:read_insecure_from_query）。"""
    v = parse_boolish(query.get("allowInsecure", query.get("insecure")))
    return bool(v)


def build_basic_tls(server, sni, insecure, alpn=None):
    tls = {
        "enabled": True,
        "server_name": sni or server,
        "insecure": bool(insecure),
    }
    alpn_list = csv_list(alpn)
    if alpn_list:
        tls["alpn"] = alpn_list
    return tls


# Mihomo 的 client-fingerprint 缺省为空 = 不伪造 TLS 指纹；"none" 显式关闭。
# sing-box 的 utls 官方标注不推荐且默认禁用，这里只在显式给出有效指纹时才启用，
# 避免把「没写指纹」的节点强行加 chrome 指纹，导致握手变慢/被服务端限速/拒绝。
UTLS_DISABLE_WORDS = {"none", "disable", "disabled", "off", "false", "0", ""}


def build_utls_tls(server, sni, fingerprint, insecure, alpn=None):
    tls = build_basic_tls(server, sni, insecure, alpn)
    fp = (fingerprint or "").strip().lower()
    if fp and fp not in UTLS_DISABLE_WORDS:
        tls["utls"] = {"enabled": True, "fingerprint": fp}
    return tls


def normalize_duration(value):
    v = str(value or "").strip()
    return v + "s" if v.isdigit() else v


def normalize_public_key(value):
    """sing-box 1.14 的 reality.public_key 要求无 padding 的 base64（RawStdEncoding）。"""
    return str(value or "").strip().rstrip("=")


def normalize_short_id(value):
    """reality.short_id 必须是偶数位十六进制字符串（Go encoding/hex）。"""
    s = str(value or "").strip()
    return s if s and len(s) % 2 == 0 and re.fullmatch(r"[0-9a-fA-F]+", s) else ""


def is_ip_literal(value):
    try:
        ipaddress.ip_address(str(value).strip())
        return True
    except ValueError:
        return False


def transport_from_query(query):
    """URI query -> sing-box transport。上游只做 ws，此处补齐 grpc/http/httpupgrade。"""
    network = query_get(query, "type", "network")
    if network == "ws":
        t = {"type": "ws"}
        path = query_get(query, "path")
        host = query_get(query, "host")
        if path:
            t["path"] = path
        if host:
            t["headers"] = {"Host": host}
        return t
    if network == "grpc":
        service = query_get(query, "serviceName", "service_name", "path")
        return {"type": "grpc", "service_name": service} if service else {"type": "grpc"}
    if network in ("http", "h2"):
        t = {"type": "http"}
        host = query_get(query, "host")
        path = query_get(query, "path")
        if host:
            t["host"] = csv_list(host)
        if path:
            t["path"] = path
        return t
    if network == "httpupgrade":
        t = {"type": "httpupgrade"}
        host = query_get(query, "host")
        path = query_get(query, "path")
        if host:
            t["host"] = host
        if path:
            t["path"] = path
        return t
    return None


# --------------------------------------------------------------------------
# 节点 URI 解析（parser.rs 的 parse_*_uri 系列）
# --------------------------------------------------------------------------
def decode_b64_loose(text):
    """宽松 base64 解码：忽略空白/换行，兼容 URL-safe 字母表与缺失的 padding。"""
    s = re.sub(r"\s+", "", str(text or ""))
    if not s or not re.fullmatch(r"[A-Za-z0-9+/=_-]+", s):
        return ""
    s = s.replace("-", "+").replace("_", "/").rstrip("=")
    s += "=" * (-len(s) % 4)
    try:
        return base64.b64decode(s.encode("ascii")).decode("utf-8", "replace")
    except Exception:
        return ""


def restore_b64_authority(uri):
    """还原「整段 base64 的 userinfo」写法。

    Shadowrocket / 部分机场把 `uuid@host:port`（或 `method:pass@host:port`）整段
    base64 后直接拼参数：`vless://<base64>?tls=1&remark=xxx`。split_uri 会把这段
    当成主机名，节点直接被判为无法解析。解出来能还原成 host:port 才替换，
    普通 `scheme://host:port` 与 `user@host` 两种写法都不会命中这里。
    """
    m = re.match(r"(?i)^([a-z][a-z0-9+.-]*)://([A-Za-z0-9+/=_-]+)([?#].*)?$",
                 str(uri or "").strip(), re.S)
    if not m:
        return uri
    scheme, blob, tail = m.group(1), m.group(2), m.group(3) or ""
    if len(blob) < 16:
        return uri
    decoded = decode_b64_loose(blob)
    if "@" not in decoded or ":" not in decoded.rsplit("@", 1)[1]:
        return uri
    return "%s://%s%s" % (scheme, decoded.strip(), tail)


def parse_uri_common(uri, default_port):
    p = split_uri(restore_b64_authority(uri))
    if not p or not p["host"]:
        return None
    port = p["port"] if p["port"] is not None else default_port
    user = pct_decode(p["username"]).strip()
    password = pct_decode(p["password"]).strip()
    query = parse_query(p["query"])
    # Shadowrocket 用 ?remark= 代替 #fragment 写节点名
    tag = (decode_tag(p["fragment"]) or str(query.get("remark") or "").strip()
           or default_tag(p["scheme"], p["host"], port))
    return {
        "scheme": p["scheme"],
        "host": p["host"],
        "port": port,
        "user": user,
        "password": password,
        "query": query,
        "tag": tag,
    }


def parse_vless_uri(uri):
    u = parse_uri_common(uri, 443)
    if not u:
        return None
    # Shadowrocket 会写成 `vless://auto:<uuid>@host:port`，auto 只是加密占位
    uuid = u["user"]
    if uuid.lower() in ("", "auto", "none", "tls") and u["password"]:
        uuid = u["password"]
    if not uuid:
        return None
    q = u["query"]
    node = {
        "tag": u["tag"], "type": "vless", "server": u["host"],
        "server_port": u["port"], "uuid": uuid,
    }
    flow = query_get(q, "flow")
    if not flow:
        # Shadowrocket 用 xtls=1/2 表示 XTLS 流控，1=direct、2=vision
        xtls = str(q.get("xtls") or "").strip()
        flow = {"1": "xtls-rprx-direct", "2": "xtls-rprx-vision"}.get(xtls, "")
    if flow:
        node["flow"] = flow
    security = query_get(q, "security").lower()
    if not security:
        # 老写法没有 security=，用 tls=1 与 reality 公钥（pbk）反推
        if query_get(q, "pbk"):
            security = "reality"
        elif str(q.get("tls") or "").strip().lower() in ("1", "true", "tls", "reality"):
            security = "tls"
    sni = query_get(q, "sni", "servername")
    fp = query_get(q, "fp")
    if security == "reality":
        # sing-box 1.14 的 reality 客户端强制要求 uTLS（内核报错：uTLS is required by
        # reality client）。reality 的 ClientHello 伪装正是靠 uTLS 引擎生成，指纹缺省 chrome。
        tls = build_utls_tls(u["host"], sni, fp or "chrome", False)
        reality = {"enabled": True}
        pbk = normalize_public_key(query_get(q, "pbk"))
        sid = normalize_short_id(query_get(q, "sid"))
        if pbk:
            reality["public_key"] = pbk
        if sid:
            reality["short_id"] = sid
        tls["reality"] = reality
        node["tls"] = tls
    elif security == "tls" or sni:
        node["tls"] = build_utls_tls(
            u["host"], sni, fp, insecure_from_query(q), query_get(q, "alpn") or None
        )
    transport = transport_from_query(q)
    if transport:
        node["transport"] = transport
    packet = query_get(q, "packetEncoding", "packet_encoding")
    if packet:
        node["packet_encoding"] = packet
    return node


def parse_trojan_uri(uri):
    u = parse_uri_common(uri, 443)
    if not u or not u["user"]:
        return None
    q = u["query"]
    sni = query_get(q, "sni", "peer", "servername")
    node = {
        "tag": u["tag"], "type": "trojan", "server": u["host"],
        "server_port": u["port"], "password": u["user"],
        "tls": build_utls_tls(u["host"], sni, query_get(q, "fp"),
                              insecure_from_query(q), query_get(q, "alpn") or None),
    }
    transport = transport_from_query(q)
    if transport:
        node["transport"] = transport
    return node


def parse_hysteria2_uri(uri):
    u = parse_uri_common(uri, 443)
    if not u or not u["user"]:
        return None
    q = u["query"]
    sni = query_get(q, "sni", "peer", "servername")
    insecure = parse_boolish(q.get("insecure"))
    node = {
        "tag": u["tag"], "type": "hysteria2", "server": u["host"],
        "server_port": u["port"], "password": u["user"],
        "tls": build_basic_tls(u["host"], sni, bool(insecure), query_get(q, "alpn") or None),
    }
    obfs = query_get(q, "obfs")
    if obfs:
        ob = {"type": obfs}
        obpw = query_get(q, "obfs-password", "obfs_password")
        if obpw:
            ob["password"] = obpw
        node["obfs"] = ob
    for key, field in (("upmbps", "up_mbps"), ("downmbps", "down_mbps"),
                       ("up", "up_mbps"), ("down", "down_mbps")):
        value = query_get(q, key)
        if value.isdigit():
            node[field] = int(value)
    for key in ("bbr_profile",):
        value = query_get(q, key)
        if value:
            node[key] = value
    value = parse_boolish(q.get("disable_chrome_parrot"))
    if value is not None:
        node["disable_chrome_parrot"] = value
    for key in ("hop_interval", "hop_interval_max"):
        value = query_get(q, key)
        if value:
            node[key] = normalize_duration(value)
    value = parse_boolish(q.get("fastopen"))
    if value is not None:
        node["tcp_fast_open"] = value
    mport = query_get(q, "mport")
    if mport:
        node["server_ports"] = [p.strip().replace("-", ":") for p in mport.split(",") if p.strip()]
    return node


def parse_tuic_uri(uri):
    u = parse_uri_common(uri, 443)
    if not u or not u["user"]:
        return None
    q = u["query"]
    sni = query_get(q, "sni", "servername")
    insecure = parse_boolish(q.get("insecure"))
    node = {
        "tag": u["tag"], "type": "tuic", "server": u["host"],
        "server_port": u["port"], "uuid": u["user"],
        "tls": build_basic_tls(u["host"], sni, bool(insecure), query_get(q, "alpn") or None),
    }
    if u["password"]:
        node["password"] = u["password"]
    for key, field in (("congestion_control", "congestion_control"),
                       ("udp_relay_mode", "udp_relay_mode"),
                       ("heartbeat", "heartbeat"), ("network", "network")):
        value = query_get(q, key)
        if value:
            node[field] = normalize_duration(value) if field == "heartbeat" else value
    for key in ("udp_over_stream", "zero_rtt_handshake"):
        value = parse_boolish(q.get(key))
        if value is not None:
            node[key] = value
    return node


def parse_anytls_uri(uri):
    u = parse_uri_common(uri, 443)
    if not u or not u["user"]:
        return None
    q = u["query"]
    sni = query_get(q, "sni", "servername")
    insecure = parse_boolish(q.get("insecure"))
    node = {
        "tag": u["tag"], "type": "anytls", "server": u["host"],
        "server_port": u["port"], "password": u["user"],
        "tls": build_basic_tls(u["host"], sni, bool(insecure), query_get(q, "alpn") or None),
    }
    for key in ("idle_session_check_interval", "idle_session_timeout"):
        value = query_get(q, key)
        if value:
            node[key] = normalize_duration(value)
    value = query_get(q, "min_idle_session")
    if value.isdigit():
        node["min_idle_session"] = int(value)
    return node


def parse_snell_uri(uri):
    u = parse_uri_common(uri, 8388)
    if not u or not u["user"]:
        return None
    q = u["query"]
    node = {
        "tag": u["tag"], "type": "snell", "server": u["host"],
        "server_port": u["port"], "psk": u["user"],
    }
    value = query_get(q, "version")
    if value.isdigit():
        node["version"] = int(value)
    # 注意：sing-box 1.14 的 snell outbound 没有 obfs 字段，写入会导致内核拒绝整份配置。
    # URI 里的 obfs / obfs-host 属于 Clash 侧语义，此处按上游"忽略不支持字段"的约定丢弃。
    return node


def parse_hysteria_uri(uri):
    """hysteria v1 分享链接（hysteria://）。

    与 hysteria2 不是同一协议，不能混用；sing-box 1.14 仍保留 hysteria 出站，
    但字段名不同（auth_str / up_mbps / down_mbps / obfs）。
    """
    u = parse_uri_common(uri, 443)
    if not u:
        return None
    q = u["query"]
    sni = query_get(q, "peer", "sni", "servername")
    node = {
        "tag": u["tag"], "type": "hysteria", "server": u["host"],
        "server_port": u["port"],
        "tls": build_basic_tls(u["host"], sni, insecure_from_query(q),
                               query_get(q, "alpn") or "h3"),
    }
    auth = query_get(q, "auth", "auth_str")
    if auth:
        node["auth_str"] = auth
    for key, field in (("upmbps", "up_mbps"), ("downmbps", "down_mbps"),
                       ("up", "up_mbps"), ("down", "down_mbps")):
        value = query_get(q, key)
        if value.isdigit() and field not in node:
            node[field] = int(value)
    obfs = query_get(q, "obfs")
    if obfs:
        node["obfs"] = obfs
    return node


def parse_ssr_uri(uri):
    """ShadowsocksR 分享链接（ssr:// 整段 base64url）。

    sing-box 1.6 起移除 SSR 出站，这里解析成节点只为在转换报告里给出明确原因，
    而不是让整条订阅静默少几个节点。
    """
    raw = uri.strip()[len("ssr://"):].strip()
    decoded = b64decode_relaxed(raw)
    if not decoded:
        return None
    main, _, query = decoded.partition("/?")
    if not query:
        main, _, query = decoded.partition("?")
    parts = main.split(":")
    if len(parts) < 6:
        return None
    host = parts[0].strip()
    try:
        port = int(parts[1])
    except ValueError:
        return None
    protocol, method, obfs, tail = parts[2], parts[3], parts[4], ":".join(parts[5:])
    password = b64decode_relaxed(tail.split("/")[0]) or ""
    params = parse_query(query)
    tag = b64decode_relaxed(params.get("remarks", "")) or default_tag("ssr", host, port)
    node = {
        "tag": tag, "type": "shadowsocksr", "server": host, "server_port": port,
        "method": method, "password": password,
        "protocol": protocol, "obfs": obfs,
    }
    proto_param = b64decode_relaxed(params.get("protoparam", ""))
    obfs_param = b64decode_relaxed(params.get("obfsparam", ""))
    if proto_param:
        node["protocol_param"] = proto_param
    if obfs_param:
        node["obfs_param"] = obfs_param
    return node


def parse_trojan_go_uri(uri):
    """trojan-go 链接：协议仍是 trojan，区别只在传输层参数写法。"""
    u = parse_uri_common(uri, 443)
    if not u or not u["user"]:
        return None
    q = u["query"]
    node = {"tag": u["tag"], "type": "trojan", "server": u["host"],
            "server_port": u["port"], "password": u["user"],
            "tls": build_utls_tls(u["host"], query_get(q, "sni", "peer"), query_get(q, "fp"),
                                  insecure_from_query(q), query_get(q, "alpn") or None)}
    transport = transport_from_query(q)
    if transport:
        node["transport"] = transport
    return node


def parse_ssh_uri(uri):
    u = parse_uri_common(uri, 22)
    if not u or not u["user"]:
        return None
    q = u["query"]
    node = {"tag": u["tag"], "type": "ssh", "server": u["host"],
            "server_port": u["port"], "user": u["user"]}
    key = query_get(q, "private_key", "privatekey")
    if key:
        node["private_key"] = key
    elif u["password"]:
        node["password"] = u["password"]
    host_key = query_get(q, "host_key", "hostkey")
    if host_key:
        node["host_key"] = host_key
    return node


def parse_vmess_uri(uri):
    payload = uri.strip()[len("vmess://"):].strip()
    decoded = b64decode_relaxed(payload)
    if not decoded:
        return None
    try:
        v = json.loads(decoded)
    except (ValueError, TypeError):
        return None
    if not isinstance(v, dict):
        return None
    server = str(v.get("add") or "").strip()
    uuid = str(v.get("id") or "").strip()
    if not server or not uuid:
        return None
    try:
        port = int(str(v.get("port", 443)))
    except ValueError:
        port = 443
    tag = str(v.get("ps") or "").strip() or "vmess-%s:%s" % (server, port)
    try:
        alter_id = int(str(v.get("aid", 0)))
    except ValueError:
        alter_id = 0
    node = {
        "tag": tag, "type": "vmess", "server": server, "server_port": port,
        "uuid": uuid, "security": normalize_vmess_security(v.get("scy")),
        "alter_id": alter_id,
    }
    if str(v.get("tls") or "").lower() in ("tls", "reality", "xtls"):
        sni = str(v.get("sni") or v.get("host") or "")
        insecure = v.get("allowInsecure", v.get("insecure", False))
        if isinstance(insecure, str):
            insecure = bool(parse_boolish(insecure))
        alpn = v.get("alpn")
        if isinstance(alpn, list):
            alpn = ",".join(str(x) for x in alpn)
        # 仅当显式给了 fp 才启用 utls，避免给没写指纹的节点硬加 chrome 指纹
        node["tls"] = build_utls_tls(server, sni, str(v.get("fp") or ""),
                                     bool(insecure), alpn)
    net = str(v.get("net") or "").strip().lower()
    path = str(v.get("path") or "")
    vhost = str(v.get("host") or "")
    if net == "ws":
        t = {"type": "ws"}
        if path:
            t["path"] = path
        if vhost:
            t["headers"] = {"Host": vhost}
        node["transport"] = t
    elif net == "grpc":
        service = path or str(v.get("serviceName") or v.get("servicename") or "")
        node["transport"] = {"type": "grpc", "service_name": service} if service \
            else {"type": "grpc"}
    elif net in ("h2", "http"):
        t = {"type": "http"}
        if vhost:
            t["host"] = csv_list(vhost)
        if path:
            t["path"] = path
        node["transport"] = t
    elif net == "httpupgrade":
        t = {"type": "httpupgrade"}
        if vhost:
            t["host"] = vhost
        if path:
            t["path"] = path
        node["transport"] = t
    return node


def ss_plugin_fields(plugin):
    """SIP002 的 plugin 参数 -> sing-box shadowsocks 的 plugin / plugin_opts。

    只映射 sing-box 原生支持的两个插件（obfs-local / v2ray-plugin）；
    其余（shadow-tls、kcptun 等）sing-box 无法承载，直接丢弃而不是写坏配置。
    """
    text = pct_decode(plugin or "").strip()
    if not text:
        return {}
    parts = [p.strip() for p in text.split(";") if p.strip()]
    if not parts:
        return {}
    name = parts[0].lower()
    opts = ";".join(parts[1:])
    if name in ("obfs-local", "simple-obfs", "obfs"):
        return {"plugin": "obfs-local", "plugin_opts": opts} if opts else {"plugin": "obfs-local"}
    if name == "v2ray-plugin":
        return {"plugin": "v2ray-plugin", "plugin_opts": opts} if opts else {"plugin": "v2ray-plugin"}
    return {}


def parse_ss_uri(uri):
    raw = uri.strip()[len("ss://"):].strip()
    if not raw:
        return None
    body, _, fragment = raw.partition("#")
    tag = decode_tag(fragment) or "shadowsocks"
    main, _, query = body.partition("?")
    query_obj = parse_query(query)

    def build(method, password, hostport):
        hp = parse_host_port(hostport)
        if not hp:
            return None
        server, port = hp
        node = {"tag": tag, "type": "shadowsocks", "server": server,
                "server_port": port, "method": method, "password": password}
        node.update(ss_plugin_fields(query_obj.get("plugin")))
        return node

    if "@" in main:
        left, hostport = main.rsplit("@", 1)
        left = left.strip()
        if ":" in left:
            method, password = left.split(":", 1)
            method, password = pct_decode(method).strip(), pct_decode(password).strip()
        else:
            decoded = b64decode_relaxed(left) or ""
            if ":" not in decoded:
                return None
            method, password = decoded.split(":", 1)
            method, password = method.strip(), password.strip()
        if not method or not password:
            return None
        return build(method, password, hostport)
    decoded = b64decode_relaxed(main)
    if not decoded or "@" not in decoded:
        return None
    left, hostport = decoded.rsplit("@", 1)
    if ":" not in left:
        return None
    method, password = left.split(":", 1)
    method, password = method.strip(), password.strip()
    if not method or not password:
        return None
    return build(method, password, hostport)


def parse_socks_http_uri(uri, typ, default_port=0):
    u = parse_uri_common(uri, default_port or (1080 if typ == "socks" else 80))
    if not u:
        return None
    node = {"tag": u["tag"], "type": typ, "server": u["host"], "server_port": u["port"]}
    if u["user"]:
        node["username"] = u["user"]
    if u["password"]:
        node["password"] = u["password"]
    return node


def parse_plain_http_uri(uri):
    # 纯 URL（订阅链接）不应被误判成 http 节点：必须显式带端口或 userinfo
    p = split_uri(uri)
    if not p or (p["port"] is None and not p["username"]):
        return None
    return parse_socks_http_uri(uri, "http", 443 if p["scheme"] == "https" else 80)


URI_PARSERS = {
    "vmess": lambda u: parse_vmess_uri(u),
    "vless": parse_vless_uri,
    "trojan": parse_trojan_uri,
    "trojan-go": parse_trojan_go_uri,
    "ss": parse_ss_uri,
    "ssr": parse_ssr_uri,
    "hysteria": parse_hysteria_uri,
    "hysteria2": parse_hysteria2_uri,
    "hy2": parse_hysteria2_uri,
    "tuic": parse_tuic_uri,
    "anytls": parse_anytls_uri,
    "snell": parse_snell_uri,
    "socks": lambda u: parse_socks_http_uri(u, "socks"),
    "socks5": lambda u: parse_socks_http_uri(u, "socks"),
    "socks5h": lambda u: parse_socks_http_uri(u, "socks"),
    "http": parse_plain_http_uri,
    "https": parse_plain_http_uri,
    "ssh": parse_ssh_uri,
}


def uri_scheme(uri):
    line = str(uri or "").strip()
    return line.split("://", 1)[0].lower() if "://" in line else ""


def convert_uri(uri):
    line = uri.strip()
    if not line or line.startswith("#"):
        return None
    parser = URI_PARSERS.get(uri_scheme(line))
    if not parser:
        return None
    try:
        return parser(line)
    except (ValueError, KeyError, AttributeError, IndexError):
        return None


# --------------------------------------------------------------------------
# 极简 Clash YAML 子集解析（无 PyYAML 依赖）
# --------------------------------------------------------------------------
def strip_yaml_comment(line):
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1].isspace()):
            return line[:i]
    return line


_YAML_ESCAPES = {
    "0": "\0", "a": "\a", "b": "\b", "t": "\t", "n": "\n", "v": "\v",
    "f": "\f", "r": "\r", "e": "\x1b", '"': '"', "\\": "\\", "/": "/",
    " ": " ", "N": "\u0085", "_": "\u00a0", "L": "\u2028", "P": "\u2029",
}


def unescape_yaml_double(text):
    """还原双引号标量里的 YAML 转义。

    机场模板常把国旗写成 `"\\U0001F1ED\\U0001F1F0香港02"`，不解码节点名就会
    原样显示成 `\\U0001F1ED...`（面板上一整排 "[下载] v6U0001F1F8..." 就是这么来的）。
    """
    out, i, n = [], 0, len(text)
    while i < n:
        ch = text[i]
        if ch != "\\" or i + 1 >= n:
            out.append(ch)
            i += 1
            continue
        nxt = text[i + 1]
        if nxt in _YAML_ESCAPES:
            out.append(_YAML_ESCAPES[nxt])
            i += 2
            continue
        width = {"x": 2, "u": 4, "U": 8}.get(nxt)
        if width:
            hexpart = text[i + 2:i + 2 + width]
            if len(hexpart) == width and re.fullmatch(r"[0-9A-Fa-f]+", hexpart):
                try:
                    out.append(chr(int(hexpart, 16)))
                except ValueError:
                    pass
                else:
                    i += 2 + width
                    continue
        out.append(ch)
        i += 1
    return "".join(out)


def yaml_scalar(value):
    v = str(value).strip()
    if not v:
        return None
    if len(v) >= 2 and v.startswith('"') and v.endswith('"'):
        return unescape_yaml_double(v[1:-1])
    if len(v) >= 2 and v.startswith("'") and v.endswith("'"):
        return v[1:-1].replace("''", "'")
    low = v.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "~"):
        return None
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        return [yaml_scalar(x) for x in split_flow_items(inner)] if inner else []
    if v.startswith("{") and v.endswith("}"):
        inner = v[1:-1].strip()
        d = {}
        if inner:
            for part in split_flow_items(inner):
                k, _, val = part.partition(":")
                if k.strip():
                    d[k.strip().strip("\"'")] = yaml_scalar(val)
        return d
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    if re.fullmatch(r"-?\d+\.\d+", v):
        return float(v)
    return v


def is_list_item(text):
    return text == "-" or text.startswith("- ")


def yaml_tokens(content):
    """切分为 (缩进, 去注释文本)。Tab 统一按 4 空格展开（YAML 禁止 Tab 缩进，
    但机场导出的配置经常带 Tab，直接按 1 列算会让整段缩进关系错乱）。"""
    tokens = []
    for raw in content.splitlines():
        line = raw.replace("\t", "    ")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        stripped = line.strip()
        if stripped in ("---", "..."):
            continue
        line = strip_yaml_comment(line)
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        tokens.append((indent, line.strip()))
    return tokens


def split_yaml_key(text):
    """切分 `key: value`，兼容 `"geosite:cn":` 这种键里带冒号的引号写法。"""
    text = (text or "").strip()
    if not text:
        return None, ""
    if text[0] in "\"'":
        endq = text.find(text[0], 1)
        if endq > 0:
            rest = text[endq + 1:].lstrip()
            if rest.startswith(":"):
                return text[1:endq], rest[1:].strip()
            return text[1:endq], ""
    idx = text.find(":")
    if idx < 0:
        return None, ""
    return text[:idx].strip().strip("\"'"), text[idx + 1:].strip()


def looks_like_map_start(text):
    """判断一行（或 `- ` 之后的内容）是 `key: value` 还是纯标量。

    URL（`http://a`）、`DOMAIN,x,proxy` 这类规则行都不算映射，避免把节点/规则
    误解析成 {键: 值} 而丢内容。
    """
    t = (text or "").strip()
    if not t:
        return False
    if t[0] in "\"'":
        endq = t.find(t[0], 1)
        if endq < 0:
            return False
        rest = t[endq + 1:].lstrip()
        return rest.startswith(":") and (len(rest) == 1 or rest[1] in " \t")
    m = re.match(r"^[^:]+:(\s|$)", t)
    return bool(m)


BLOCK_SCALAR_MARKS = ("|", "|-", "|+", ">", ">-", ">+")


def flow_balanced(text):
    """判断 `[...]` / `{...}` 的括号是否已配平（忽略引号内字符）。"""
    depth, quote = 0, None
    for ch in text:
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
    return depth <= 0


def collect_flow(tokens, i, total, first):
    """把跨多行书写的 flow 列表/映射拼成一行。

    部分生成器会把 `proxies: [` 之后的对象分多行写：
        proxies: [
          {name: a, ...},
          {name: b, ...}
        ]
    逐行解析会把每行当成独立语句而全丢，这里先按括号配平把整段收进来。
    """
    text = first
    while i < total and not flow_balanced(text):
        text += " " + tokens[i][1]
        i += 1
    return text, i


def parse_yaml_subset(content):
    """容错版 YAML 子集解析（OpenWrt 上没有 PyYAML）。

    关键约束：**任何一段写坏都不能拖累后面的段**。
    订阅里 `nameserver-policy` 少一格缩进、或键里带冒号这类小毛病极其常见，
    老实现的 parse_map 一遇到失步就 break，整份文档从那段开始全部丢弃 ——
    proxy-groups / rules 全丢，表现为「分组为空、规则不生效、节点取不到」。
    这里改成逐顶层键解析 + 失步强制恢复：子块解析结束后一律跳到下一个顶层键。

    同时按 YAML 规范支持「序列与父键同缩进」：
        proxies:
        - name: xxx      # 机场模板常见写法，缩进 0 与 proxies 对齐
    """
    tokens = yaml_tokens(content)
    total = len(tokens)
    if not total:
        return {}

    def parse_map(i, indent):
        result = {}
        while i < total and tokens[i][0] == indent and not is_list_item(tokens[i][1]):
            key, value = split_yaml_key(tokens[i][1])
            if key is None:
                i += 1          # 脏行（无冒号）：跳过，继续本层
                continue
            i += 1
            if value in BLOCK_SCALAR_MARKS:
                # 块标量：把后续更深缩进的行原样收进来，不再当键值解析
                chunks = []
                while i < total and tokens[i][0] > indent:
                    chunks.append(tokens[i][1])
                    i += 1
                result[key] = "\n".join(chunks)
            elif value:
                if value[0] in "[{" and not flow_balanced(value):
                    value, i = collect_flow(tokens, i, total, value)
                result[key] = yaml_scalar(value)
            elif i < total and (tokens[i][0] > indent or
                                (tokens[i][0] == indent and is_list_item(tokens[i][1]))):
                child, i = parse_block(i, tokens[i][0])
                result[key] = child
            else:
                result[key] = None
        return result, i

    def parse_list(i, indent):
        result = []
        while i < total and tokens[i][0] == indent and is_list_item(tokens[i][1]):
            line = tokens[i][1]
            rest = line[1:].strip()
            i += 1
            if not rest:
                if i < total and tokens[i][0] > indent:
                    child, i = parse_block(i, tokens[i][0])
                    result.append(child)
                else:
                    result.append(None)
            elif rest.startswith(("{", "[")) or not looks_like_map_start(rest):
                # flow 写法 `{...}` / `[...]` 与 `- ss://xxx`、`- 1.2.3.4`、
                # `- DOMAIN,x,proxy` 之类纯标量
                if rest[0] in "[{" and not flow_balanced(rest):
                    rest, i = collect_flow(tokens, i, total, rest)
                result.append(yaml_scalar(rest))
            else:
                key, value = split_yaml_key(rest)
                item = {}
                if value in BLOCK_SCALAR_MARKS:
                    chunks = []
                    while i < total and tokens[i][0] > indent:
                        chunks.append(tokens[i][1])
                        i += 1
                    item[key] = "\n".join(chunks)
                elif value:
                    item[key] = yaml_scalar(value)
                else:
                    # 首键的值是嵌套 mapping（`- reality-opts:` 换行接子键）时，
                    # 子块缩进比「键所在列」更深，兄弟键与键同列。
                    # 旧实现只认「子块是序列」，遇到这种条目 item 变成残缺 dict →
                    # 整个节点被丢弃，且 i 停在兄弟键上，后续同层条目全部失步丢失。
                    key_col = indent + len(line) - len(line.lstrip("- "))
                    if i < total and tokens[i][0] > key_col:
                        child, i = parse_block(i, tokens[i][0])
                        item[key] = child
                    elif i < total and tokens[i][0] > indent and is_list_item(tokens[i][1]):
                        child, i = parse_block(i, tokens[i][0])
                        item[key] = child
                    else:
                        item[key] = None
                # 同一个元素后续的键（`- name: x` 换行后的 type/server/...）
                if i < total and tokens[i][0] > indent and not is_list_item(tokens[i][1]):
                    extra, i = parse_map(i, tokens[i][0])
                    for k, v in extra.items():
                        item.setdefault(k, v)
                result.append(item)
        return result, i

    def parse_block(i, indent):
        if i < total and is_list_item(tokens[i][1]):
            return parse_list(i, indent)
        return parse_map(i, indent)

    base = tokens[0][0]
    document = {}
    i = 0
    while i < total:
        indent, text = tokens[i]
        if indent != base or is_list_item(text):
            i += 1
            continue
        key, value = split_yaml_key(text)
        if key is None:
            i += 1
            continue
        i += 1
        if value in BLOCK_SCALAR_MARKS:
            chunks = []
            while i < total and tokens[i][0] > base:
                chunks.append(tokens[i][1])
                i += 1
            document[key] = "\n".join(chunks)
            continue
        if value:
            if value[0] in "[{" and not flow_balanced(value):
                value, i = collect_flow(tokens, i, total, value)
            document[key] = yaml_scalar(value)
            continue
        # 子块：比 base 更深，或与 base 同缩进的序列（YAML 允许序列与键对齐）
        if i < total and (tokens[i][0] > base or
                          (tokens[i][0] == base and is_list_item(tokens[i][1]))):
            try:
                child, consumed = parse_block(i, tokens[i][0])
            except Exception:
                child, consumed = None, i
            document[key] = child
            # 恢复：无论子块是否提前中断，都推进到下一个顶层键，绝不丢后续段
            k = max(consumed, i)
            while k < total and tokens[k][0] > base:
                k += 1
            while k < total and tokens[k][0] == base and is_list_item(tokens[k][1]):
                k += 1
            i = k
        else:
            document[key] = None
    return document


def split_flow_items(text):
    """按顶层逗号切分 {...} 内容，忽略引号与嵌套 {} / [] 内的逗号。"""
    out, buf, depth, quote = [], [], 0, None
    for ch in text:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            buf.append(ch)
            continue
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
        if ch == "," and depth <= 0:
            out.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out


def expand_yaml_aliases(content):
    """展开 Mihomo 模板常用的 YAML 锚点和 <<: *NAME 合并键（仅 flow map 锚点）。

    OpenWrt 无 PyYAML：这里只做文本级展开，收集 `&NAME {...}`，再把独立行
    `<<: *NAME` 与行内 flow map 中的 `<<: *NAME` 替换为锚点键值。
    标量别名（filter: *HK 等）保持原样，不影响节点与分组提取。
    """
    anchors = {}
    for line in content.splitlines():
        clean = strip_yaml_comment(line).rstrip()
        m = re.search(r"&([A-Za-z0-9_-]+)\s+(\{.*)$", clean)
        if m:
            anchors[m.group(1)] = m.group(2).strip()

    # 块状锚点：`auto_select: &auto_select` 换行后跟一整段 mapping。
    # 机场模板几乎都这么写（type/url/interval/use/exclude-filter 全在里面），
    # 不展开就会丢掉 url-test 语义、use 限定和 exclude-filter 排除项。
    block_anchors = {}
    lines = content.splitlines()
    for idx, line in enumerate(lines):
        clean = strip_yaml_comment(line).rstrip()
        m = re.search(r"^(\s*)[^\s:][^:]*:\s*&([A-Za-z0-9_-]+)\s*$", clean)
        if not m:
            continue
        key_indent = len(m.group(1))
        body, body_indent = [], None
        for nxt in lines[idx + 1:]:
            if not nxt.strip() or nxt.lstrip().startswith("#"):
                continue
            ind = len(nxt) - len(nxt.lstrip(" "))
            if ind <= key_indent:
                break
            if body_indent is None:
                body_indent = ind
            body.append((ind, strip_yaml_comment(nxt).rstrip()))
        if body and body_indent is not None:
            block_anchors[m.group(2)] = [(ind - body_indent, txt.strip()) for ind, txt in body]

    if not anchors and not block_anchors:
        return content

    def anchor_items(name):
        value = anchors.get(name, "")
        if value.startswith("{") and value.endswith("}"):
            return split_flow_items(value[1:-1])
        return []

    out = []
    for raw in content.splitlines():
        m = re.match(r"^(\s*)<<:\s*\*([A-Za-z0-9_-]+)\s*$", raw)
        if m and block_anchors.get(m.group(2)):
            base = m.group(1)
            for rel, txt in block_anchors[m.group(2)]:
                out.append("%s%s%s" % (base, " " * rel, txt))
            continue
        if m and anchors.get(m.group(2)):
            for part in anchor_items(m.group(2)):
                key, sep, value = part.partition(":")
                if sep and key.strip():
                    out.append("%s%s: %s" % (m.group(1), key.strip(), value.strip()))
            continue
        m = re.match(r"^(\s*-\s*)\{(.*)\}\s*$", raw)
        if m and "<<:" in m.group(2):
            inner = m.group(2)
            names = re.findall(r"<<:\s*\*([A-Za-z0-9_-]+)", inner)
            parts = [p for p in split_flow_items(inner) if not p.strip().startswith("<<:")]
            merged = []
            for name in names:
                merged += anchor_items(name)
            out.append("%s{%s}" % (m.group(1), ", ".join(merged + parts)))
            continue
        out.append(raw)
    return "\n".join(out)


def extract_yaml_section(content, key):
    """截取顶层 `key:` 段，绕开 dns/tun 等复杂段导致的整份解析中断。"""
    pattern = re.compile(r"^%s\s*:" % re.escape(key))
    out, collecting = [], False
    for line in content.splitlines():
        if not collecting:
            if pattern.match(line):
                collecting = True
                out.append(line)
            continue
        stripped = line.strip()
        if stripped and not line[0].isspace() and not stripped.startswith("-") and ":" in line:
            break
        out.append(line)
    return "\n".join(out)


def yaml_section_value(content, key):
    section = extract_yaml_section(content, key)
    if not section:
        return None
    value = parse_yaml_subset(section)
    return value.get(key) if isinstance(value, dict) else None


def clash_tls_flags(proxy):
    insecure = bool(proxy.get("skip-cert-verify") or False)
    alpn = proxy.get("alpn")
    if isinstance(alpn, list):
        alpn = [str(x) for x in alpn if str(x).strip()] or None
    elif isinstance(alpn, str):
        alpn = csv_list(alpn) or None
    else:
        alpn = None
    return insecure, alpn


def clash_transport(proxy):
    network = str(proxy.get("network") or "").lower()
    if network == "ws":
        opts = proxy.get("ws-opts") or {}
        t = {"type": "ws"}
        if isinstance(opts, dict):
            if opts.get("path"):
                t["path"] = str(opts["path"])
            headers = opts.get("headers")
            if isinstance(headers, dict) and headers:
                t["headers"] = {str(k): str(v) for k, v in headers.items()}
        return t
    if network == "grpc":
        opts = proxy.get("grpc-opts") or {}
        service = opts.get("grpc-service-name") if isinstance(opts, dict) else None
        return {"type": "grpc", "service_name": str(service)} if service else {"type": "grpc"}
    if network in ("h2", "http"):
        opts = proxy.get("h2-opts") or proxy.get("http-opts") or {}
        t = {"type": "http"}
        if isinstance(opts, dict):
            if opts.get("host"):
                t["host"] = [str(x) for x in csv_list(opts["host"])]
            if opts.get("path"):
                t["path"] = str(opts["path"])
        return t
    if network == "httpupgrade":
        opts = proxy.get("httpupgrade-opts") or {}
        t = {"type": "httpupgrade"}
        if isinstance(opts, dict):
            if opts.get("host"):
                t["host"] = str(opts["host"])
            if opts.get("path"):
                t["path"] = str(opts["path"])
        return t
    return None


def clash_tls(proxy, server, fingerprint=None, with_utls=True):
    insecure, alpn = clash_tls_flags(proxy)
    sni = str(proxy.get("sni") or proxy.get("servername") or "")
    reality = proxy.get("reality-opts")
    fp = str(proxy.get("client-fingerprint") or fingerprint or "")
    if isinstance(reality, dict):
        # sing-box 1.14 的 reality 客户端强制要求 uTLS（内核报错：uTLS is required by
        # reality client），reality 的 ClientHello 伪装靠 uTLS 引擎生成，指纹缺省 chrome。
        tls = build_utls_tls(server, sni, fp or "chrome", insecure, alpn)
    elif with_utls and fp:
        # 普通 TLS：只在显式写了 client-fingerprint 时才启用 uTLS，
        # 没写就与 Mihomo 默认一致（不伪造），避免握手变慢/被限速。
        tls = build_utls_tls(server, sni, fp, insecure, alpn)
    else:
        tls = build_basic_tls(server, sni, insecure, alpn)
    if isinstance(reality, dict):
        r = {"enabled": True}
        if reality.get("public-key"):
            r["public_key"] = normalize_public_key(reality["public-key"])
        short_id = normalize_short_id(reality.get("short-id"))
        if short_id:
            r["short_id"] = short_id
        tls["reality"] = r
    return tls


def clash_ss_plugin(proxy):
    """Clash 的 shadowsocks plugin/plugin-opts -> sing-box plugin/plugin_opts。

    Clash 用 `plugin: obfs` + `{mode: http, host: x}`，sing-box 要的是
    `obfs-local` + `obfs=http;obfs-host=x`，键名不同必须翻译，否则插件起不来。
    """
    plugin = str(proxy.get("plugin") or "").strip().lower()
    if not plugin:
        return {}
    opts = proxy.get("plugin-opts")
    if isinstance(opts, str):
        return ss_plugin_fields("%s;%s" % (plugin, opts))
    if not isinstance(opts, dict):
        opts = {}
    if plugin in ("obfs", "obfs-local", "simple-obfs"):
        mode = str(opts.get("mode") or "http").strip() or "http"
        parts = ["obfs=%s" % mode]
        if opts.get("host"):
            parts.append("obfs-host=%s" % opts["host"])
        return {"plugin": "obfs-local", "plugin_opts": ";".join(parts)}
    if plugin == "v2ray-plugin":
        parts = []
        if opts.get("mode"):
            parts.append("mode=%s" % opts["mode"])
        if opts.get("tls"):
            parts.append("tls")
        for key in ("host", "path"):
            if opts.get(key):
                parts.append("%s=%s" % (key, opts[key]))
        return {"plugin": "v2ray-plugin", "plugin_opts": ";".join(parts)} if parts \
            else {"plugin": "v2ray-plugin"}
    return {}


def clash_to_singbox(proxy):
    if not isinstance(proxy, dict):
        return None
    typ = str(proxy.get("type") or "").strip().lower()
    name = str(proxy.get("name") or "").strip()
    server = str(proxy.get("server") or "").strip()
    try:
        port = int(str(proxy.get("port")))
    except (ValueError, TypeError):
        return None
    if not name or not server or not (1 <= port <= 65535):
        return None
    base = {"tag": name, "server": server, "server_port": port}

    if typ == "vmess":
        if not proxy.get("uuid"):
            return None
        node = dict(base, type="vmess", uuid=str(proxy["uuid"]),
                    security=normalize_vmess_security(proxy.get("cipher")),
                    alter_id=int(proxy.get("alterId") or 0))
        # vmess 同样支持 reality（Mihomo 的 vmess over reality）：仅判断 tls 会
        # 丢掉 reality-opts / servername，导致这类节点无 TLS 而连接失败。
        if proxy.get("tls") or proxy.get("reality-opts") or proxy.get("servername"):
            node["tls"] = clash_tls(proxy, server)
    elif typ == "vless":
        if not proxy.get("uuid"):
            return None
        node = dict(base, type="vless", uuid=str(proxy["uuid"]))
        if proxy.get("flow"):
            node["flow"] = str(proxy["flow"])
        if proxy.get("tls") or proxy.get("reality-opts"):
            node["tls"] = clash_tls(proxy, server)
    elif typ == "trojan":
        if not proxy.get("password"):
            return None
        node = dict(base, type="trojan", password=str(proxy["password"]),
                    tls=clash_tls(proxy, server, with_utls=False))
        if proxy.get("tls") is False:
            node["tls"]["enabled"] = False
    elif typ in ("ssr", "shadowsocksr"):
        # sing-box 1.6 起移除 SSR：这里保留节点信息只为在报告里明确说明原因，
        # 交给 normalize_nodes 按 REMOVED_TYPES 剔除。
        if not proxy.get("cipher") or not proxy.get("password"):
            return None
        node = dict(base, type="shadowsocksr", method=str(proxy["cipher"]),
                    password=str(proxy["password"]))
        for src, dst in (("protocol", "protocol"), ("obfs", "obfs"),
                         ("protocol-param", "protocol_param"),
                         ("obfs-param", "obfs_param")):
            if proxy.get(src):
                node[dst] = str(proxy[src])
        return node
    elif typ == "hysteria":
        node = dict(base, type="hysteria", tls=clash_tls(proxy, server, with_utls=False))
        auth = proxy.get("auth-str") or proxy.get("auth_str") or proxy.get("auth") \
            or proxy.get("password")
        if auth:
            node["auth_str"] = str(auth)
        for key, field in (("up", "up_mbps"), ("down", "down_mbps")):
            try:
                node[field] = int(str(proxy[key]))
            except (KeyError, ValueError, TypeError):
                pass
        if proxy.get("obfs"):
            node["obfs"] = str(proxy["obfs"])
        return node
    elif typ == "ss":
        if not proxy.get("cipher") or not proxy.get("password"):
            return None
        node = dict(base, type="shadowsocks", method=str(proxy["cipher"]),
                    password=str(proxy["password"]))
        node.update(clash_ss_plugin(proxy))
    elif typ in ("hysteria2", "hy2"):
        if not proxy.get("password"):
            return None
        node = dict(base, type="hysteria2", password=str(proxy["password"]),
                    tls=clash_tls(proxy, server, with_utls=False))
        for key, field in (("up", "up_mbps"), ("down", "down_mbps")):
            try:
                node[field] = int(str(proxy[key]))
            except (KeyError, ValueError, TypeError):
                pass
        if proxy.get("obfs"):
            ob = {"type": str(proxy["obfs"])}
            if proxy.get("obfs-password"):
                ob["password"] = str(proxy["obfs-password"])
            node["obfs"] = ob
    elif typ == "tuic":
        if not proxy.get("uuid"):
            return None
        node = dict(base, type="tuic", uuid=str(proxy["uuid"]),
                    tls=clash_tls(proxy, server, with_utls=False))
        if proxy.get("password"):
            node["password"] = str(proxy["password"])
        for key, field in (("congestion-controller", "congestion_control"),
                           ("udp-relay-mode", "udp_relay_mode"),
                           ("reduce-rtt", "reduce_rtt")):
            if key in proxy:
                node[field] = proxy[key]
        if "disable-sni" in proxy and isinstance(node["tls"], dict):
            node["tls"]["disable_sni"] = bool(proxy["disable-sni"])
    elif typ == "anytls":
        if not proxy.get("password"):
            return None
        node = dict(base, type="anytls", password=str(proxy["password"]),
                    tls=clash_tls(proxy, server, with_utls=False))
        for key, field in (("idle-session-check-interval", "idle_session_check_interval"),
                           ("idle-session-timeout", "idle_session_timeout")):
            if proxy.get(key):
                node[field] = normalize_duration(str(proxy[key]))
    elif typ == "snell":
        if not proxy.get("psk"):
            return None
        node = dict(base, type="snell", psk=str(proxy["psk"]))
        if proxy.get("version"):
            node["version"] = int(proxy["version"])
    elif typ in ("socks5", "socks"):
        node = dict(base, type="socks")
        if proxy.get("username"):
            node["username"] = str(proxy["username"])
        if proxy.get("password"):
            node["password"] = str(proxy["password"])
    elif typ == "http":
        node = dict(base, type="http")
        if proxy.get("username"):
            node["username"] = str(proxy["username"])
        if proxy.get("password"):
            node["password"] = str(proxy["password"])
    else:
        return None
    transport = clash_transport(proxy)
    if transport and node["type"] in ("vmess", "vless", "trojan"):
        node["transport"] = transport
    if proxy.get("packet-encoding") and node["type"] in ("vmess", "vless"):
        node["packet_encoding"] = str(proxy["packet-encoding"])
    return node


# --------------------------------------------------------------------------
# Clash/Mihomo proxy-groups -> momo 分组规则
# --------------------------------------------------------------------------
def clamp_int(value, default, low, high):
    try:
        n = int(str(value).strip())
    except (ValueError, TypeError, AttributeError):
        return default
    return max(low, min(high, n))


def normalize_group_members(value):
    """members / use 列表；兼容 YAML 子集把 "节点:8388" 误判为单键 map。"""
    if isinstance(value, str):
        raw = [x.strip() for x in value.split(",")]
    elif isinstance(value, (list, tuple)):
        raw = []
        for item in value:
            if isinstance(item, str):
                raw.append(item.strip())
            elif isinstance(item, dict) and len(item) == 1 \
                    and not any(v not in (None, "", False) for v in item.values()):
                raw.append(str(list(item)[0]).strip())
    else:
        raw = []
    out = []
    for name in raw:
        name = str(name).strip().strip("\"'")
        if name and name not in out:
            out.append(name)
    return out


def parse_proxy_groups(raw):
    """把 proxy-groups 归一化为 momo 侧规则（不产生内核 urltest/url-test 出站）。"""
    result = []
    if not isinstance(raw, list):
        return result
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        typ = GROUP_TYPES.get(str(item.get("type") or "select").strip().lower(), "select")
        hc = item.get("health-check") if isinstance(item.get("health-check"), dict) else {}
        url = str(item.get("url") or hc.get("url") or DEFAULT_TEST_URL).strip()
        interval = clamp_int(item.get("interval", hc.get("interval")), DEFAULT_INTERVAL, 5, 86400)
        tolerance = clamp_int(item.get("tolerance"), DEFAULT_TOLERANCE, 0, 60000)
        timeout = clamp_int(item.get("timeout"), DEFAULT_TIMEOUT, 100, 60000)
        strategy = str(item.get("strategy") or "round-robin").strip().lower()
        if strategy not in LB_STRATEGIES:
            strategy = "round-robin"
        members = normalize_group_members(item.get("proxies"))
        members += normalize_group_members(item.get("use"))
        include_all = bool(item.get("include-all") or item.get("include-all-proxies")
                           or item.get("include-all-providers"))
        result.append({
            "name": name, "tag": "", "type": typ, "url": url,
            "interval": interval, "tolerance": tolerance, "timeout": timeout,
            "strategy": strategy, "lazy": bool(item.get("lazy", True)),
            "expected_status": str(item.get("expected-status") or hc.get("expected-status") or ""),
            "members_raw": members, "include_all": include_all,
            "filter": str(item.get("filter") or ""),
            "exclude_filter": str(item.get("exclude-filter") or ""),
            "members": [], "source": "subscription",
        })
    return result


# mihomo filter 是 Go regexp（` 分隔多段 OR）；机场模板常见 `*HK` 这类非法正则
# （mihomo 编译失败退化为不过滤=全量）。这里正则优先，失败时降级为剥 `*` 的
# 不敏感子串匹配并补常见地区别名，保证中文节点名的订阅也能正确分组。
REGION_FILTER_ALIASES = {
    "hk": ("hk", "香港", "hongkong", "hong kong"),
    "jp": ("jp", "日本", "japan"),
    "tw": ("tw", "台湾", "taiwan"),
    "sg": ("sg", "新加坡", "狮城", "singapore"),
    "us": ("us", "美国", "unitedstates", "united states"),
    "kr": ("kr", "韩国", "korea"),
}


def _move_inline_flags(body):
    """把散落在表达式中间的全局内联标志 (?i)(?m)(?s) 移到开头。

    mihomo（Go regexp）允许内联标志出现在任意位置，Python 的 re 却要求
    全局标志必须在表达式开头，否则抛「global flags not at the start」。
    机场地区 filter 几乎都写成 ``(?=.*(香港|…|(?i)Hong))…`` 这种，直接
    compile 会失败并误走关键字降级（永远不命中 -> 回退全量节点）。
    """
    inline = re.findall(r"\(\?[ims]+\)", body)
    if not inline:
        return body, False
    body2 = re.sub(r"\(\?[ims]+\)", "", body)
    letters = "".join(sorted(set("".join(re.findall(r"[ims]", "".join(inline))))))
    return "(?" + letters + ")" + body2, True


def filter_terms(pattern):
    """解析 mihomo filter/exclude-filter -> [(compiled_regex, None) | (None, keyword)]。"""
    terms = []
    for part in str(pattern or "").split("`"):
        part = part.strip()
        if not part:
            continue
        flags, body = re.IGNORECASE, part
        m = re.match(r"^\(\?([a-z]+)\)", body)
        if m:
            fs = m.group(1)
            flags = (re.IGNORECASE if "i" in fs else 0) | \
                    (re.MULTILINE if "m" in fs else 0)
            body = body[m.end():]
        try:
            terms.append((re.compile(body, flags), None))
            continue
        except re.error:
            pass
        # Go regexp 允许内联标志在任意位置，Python re 不允许：先移动再试一次。
        moved, changed = _move_inline_flags(body)
        if changed:
            try:
                terms.append((re.compile(moved, flags), None))
                continue
            except re.error:
                pass
        kw = body.strip("*").strip().lower()
        if not kw:
            continue
        terms.append((None, kw))
        terms.extend((None, alias) for alias in REGION_FILTER_ALIASES.get(kw, ()))
    return terms


def filter_hit(terms, name):
    for rx, kw in terms:
        if rx is not None:
            if rx.search(name):
                return True
        elif kw and kw in name.lower():
            return True
    return False


def assign_group_tags(groups, node_tags):
    """保留 auto/proxy/direct/block 与节点 tag，订阅分组同名时自动改名。"""
    used = set(RESERVED_TAGS) | set(node_tags)
    # 订阅自己声明了同名分组（如 GLOBAL）时，分组名优先，内置别名让位，
    # 避免把 GLOBAL 改名成 group-GLOBAL；没有同名分组时仍按内置语义解析。
    declared = {str(g.get("name") or "").strip() for g in groups}
    name_map = {k: v for k, v in GROUP_BUILTIN_NAMES.items() if k not in declared}
    out = []
    for g in groups:
        tag = g["name"]
        if tag in used or tag in name_map:
            base = "group-" + tag
            n = 2
            tag = base
            while tag in used:
                tag = "%s-%d" % (base, n)
                n += 1
        used.add(tag)
        name_map.setdefault(g["name"], tag)
        out.append(dict(g, tag=tag))
    return out, name_map


def resolve_group_members(groups, name_map, tag_map, node_tags):
    node_set = set(node_tags)
    for g in groups:
        raw = list(g["members_raw"])
        # 触发 filter 筛选的两种形态：
        #   1) include-all（含 include-all-proxies/providers）：全部节点 + filter
        #   2) use 引用 provider（如 use: [Airport-1, Airport-2]）+ filter：
        #      provider 节点已平铺进 node_tags，provider 名本身无法匹配节点，
        #      若不筛就会因为 members 为空而 fallback 全量。mihomo 语义下
        #      use+filter 就是从这些 provider 的节点里按 filter 筛，这里等价
        #      于「全部节点 + filter」。
        has_filter = bool(g.get("filter") or g.get("exclude_filter"))
        if g["include_all"] or has_filter:
            pool = list(node_tags)
            # include-all / use + filter：按 mihomo 语义筛选节点；全不命中时回退全量
            # （与 mihomo filter 编译失败的行为一致，绝不让组变空）
            terms = filter_terms(g.get("filter"))
            if terms:
                filtered = [t for t in pool if filter_hit(terms, t)]
                if not filtered:
                    # filter 与节点命名体系不匹配（如 *AdMisc 而节点是中文地区名）：
                    # 记录到报告里，便于面板/日志暴露「这组为什么是全量」。
                    g["filter_miss"] = str(g.get("filter"))
                pool = filtered or list(node_tags)
            ex = filter_terms(g.get("exclude_filter"))
            if ex:
                kept = [t for t in pool if not filter_hit(ex, t)]
                pool = kept or pool
            raw += pool
        members, seen = [], set()
        for name in raw:
            if name in name_map:
                cand = name_map[name]
            elif name in tag_map:
                cand = tag_map[name]
            elif name in node_set:
                cand = name
            else:
                continue
            if cand in seen or cand == g["tag"] or cand == TAG_PROXY:
                continue
            seen.add(cand)
            members.append(cand)
        # 订阅只写 use/proxy-providers（本项目无 provider）或成员名全部无法解析时，
        # 保底使用全部节点，绝不退化成 direct 让流量静默绕过代理
        if not members:
            members = list(node_tags)
        g["members"] = members
        g["explicit_builtin"] = any(m in (TAG_DIRECT, TAG_BLOCK) for m in members)
    return groups


def find_group_cycle(by_tag):
    graph = {}
    for tag, g in by_tag.items():
        graph[tag] = [m for m in g["members"]
                      if m == TAG_AUTO or m in by_tag]
    state = {}

    def walk(node, path):
        state[node] = 1
        path.append(node)
        for nxt in graph.get(node, []):
            if state.get(nxt) == 1:
                return path[path.index(nxt):] + [nxt]
            if state.get(nxt, 0) == 0:
                found = walk(nxt, path)
                if found:
                    return found
        path.pop()
        state[node] = 2
        return None

    for tag in graph:
        if state.get(tag, 0) == 0:
            cycle = walk(tag, [])
            if cycle:
                return cycle
    return None


def drop_group_cycles(groups):
    """sing-box selector 不允许环；按订阅顺序剔除造成回边的成员引用。"""
    by_tag = {g["tag"]: g for g in groups if g["tag"] != TAG_AUTO}
    dropped = []
    for _ in range(len(groups) + 2):
        cycle = find_group_cycle(by_tag)
        if not cycle:
            break
        src, dst = cycle[-2], cycle[-1]
        g = by_tag.get(src)
        if not g:
            break
        g["members"] = [m for m in g["members"] if m != dst]
        if not g["members"]:
            g["members"] = [TAG_AUTO]
        dropped.append("%s -> %s" % (src, dst))
    return dropped


def make_default_auto_group(node_tags):
    return {
        "name": TAG_AUTO, "tag": TAG_AUTO, "type": "url-test",
        "url": DEFAULT_TEST_URL, "interval": DEFAULT_INTERVAL,
        "tolerance": DEFAULT_TOLERANCE, "timeout": DEFAULT_TIMEOUT,
        "strategy": "round-robin", "lazy": True, "expected_status": "",
        "members_raw": [], "include_all": False,
        "members": list(node_tags), "source": "default",
    }


# --------------------------------------------------------------------------
# proxy-providers：Mihomo 模板把节点放在远程 provider 里，proxies 只有 direct
# --------------------------------------------------------------------------
PROVIDER_REPORT = {}
# 订阅里的分流规则与 rule-providers。extract_nodes 顺带采集，供主流程生成
# route 规则；URI 列表 / sing-box 原生配置下保持空。
CLASH_EXTRA = {"rules": [], "rule-providers": {}}
# 格式层自己产生的跳过原因（无法解析的链接、内核已移除的协议……）。
# 与 normalize_nodes 的节点级 skipped 合并后一起出现在转换报告里。
EXTRACT_SKIPS = []


def provider_cache_key(url):
    """纯 Python 稳定哈希，避免依赖 OpenWrt 拆包的 hashlib。"""
    h = 5381
    for ch in url:
        h = ((h * 33) ^ ord(ch)) & 0xFFFFFFFF
    return "%08x" % h


def provider_urls(doc):
    raw = doc.get("proxy-providers") if isinstance(doc, dict) else None
    if isinstance(raw, dict):
        items = list(raw.values())
    elif isinstance(raw, list):
        items = raw
    else:
        items = []
    urls = []
    for item in items:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip().strip("\"'")
        if url.startswith(("http://", "https://")) and url not in urls:
            urls.append(url)
    return urls


def provider_ua_map(doc):
    """每个 provider 可自带 UA：`ua:` / `user-agent:` / `header: {User-Agent: ...}`。

    Mihomo 规范用 header，不少机场图省事直接写 ua，两种都吃下来；
    provider 默认按 Clash.Meta 取，机场据此下发 Clash YAML（节点/分组最全）。
    """
    raw = doc.get("proxy-providers") if isinstance(doc, dict) else None
    if isinstance(raw, dict):
        items = list(raw.values())
    elif isinstance(raw, list):
        items = raw
    else:
        items = []
    mapping = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip().strip("\"'")
        if not url.startswith(("http://", "https://")):
            continue
        ua = ""
        for key in ("ua", "user-agent", "user_agent"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                ua = value.strip()
                break
        if not ua:
            header = item.get("header")
            if isinstance(header, dict):
                for hkey, hvalue in header.items():
                    if str(hkey).lower() == "user-agent" and str(hvalue).strip():
                        ua = str(hvalue).strip()
                        break
        if ua:
            mapping[url] = ua
    return mapping


def fetch_provider_bodies(urls, conf, ua_map=None):
    """并行下载 + 持久缓存；下载失败回退过期缓存，保证断网时仍可启动。"""
    cache_dir = str(conf.get("MOMO_CONVERTER_PROVIDER_CACHE") or "").strip() \
        or "/etc/momo/converter/providers"
    ttl = clamp_int(conf.get("MOMO_CONVERTER_PROVIDER_TTL"), 21600, 0, 604800)
    timeout = clamp_int(conf.get("MOMO_CONVERTER_PROVIDER_TIMEOUT"), 12, 2, 60)
    curl = str(conf.get("MOMO_CONVERTER_PROVIDER_CURL") or "curl").strip() or "curl"
    # provider 的 UA 决定机场下发什么格式：Clash.Meta 拿 YAML；个别机场只认自家
    # 客户端 UA（v2rayN / Shadowrocket），可用 provider 内的 ua/header 覆盖。
    default_ua = str(conf.get("MOMO_CONVERTER_PROVIDER_UA") or "clash.meta").strip() \
        or "clash.meta"
    ua_map = ua_map if isinstance(ua_map, dict) else {}
    bodies, pending = {}, []
    for url in urls:
        path = os.path.join(cache_dir, provider_cache_key(url) + ".txt")
        try:
            if os.path.isfile(path) and (ttl <= 0 or time.time() - os.path.getmtime(path) < ttl):
                with open(path, "rb") as f:
                    bodies[url] = f.read()
                continue
        except OSError:
            pass
        pending.append((url, path))
    if not pending:
        return bodies
    # curl -o 要写进缓存目录，必须先把目录建好，否则首轮全部下载失败
    try:
        os.makedirs(cache_dir, exist_ok=True)
        try:
            os.chmod(cache_dir, 0o755)
        except OSError:
            pass
    except OSError:
        pass

    procs = []
    for url, path in pending:
        out = path + ".part"
        ua = str(ua_map.get(url) or default_ua)
        cmd = [curl, "-s", "-f", "-m", str(timeout), "--connect-timeout", "3",
               "-L", "-A", ua, "-o", out, url]
        try:
            procs.append((url, path, out, subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)))
        except OSError:
            pass
    deadline = time.time() + timeout + 3
    for url, path, out, proc in procs:
        try:
            proc.wait(timeout=max(0.1, deadline - time.time()))
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
                proc.wait()
            except OSError:
                pass
        data = None
        if proc.returncode == 0:
            try:
                with open(out, "rb") as f:
                    data = f.read()
            except OSError:
                pass
        if data and len(data) <= 4 * 1024 * 1024:
            try:
                os.makedirs(cache_dir, exist_ok=True)
                try:
                    os.chmod(cache_dir, 0o755)
                except OSError:
                    pass
                fd, tmp = tempfile.mkstemp(prefix=".momo-prov-", dir=cache_dir)
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                try:
                    os.chmod(tmp, 0o600)
                except OSError:
                    pass
                os.replace(tmp, path)
            except OSError:
                pass
            bodies[url] = data
        else:
            try:
                with open(path, "rb") as f:
                    bodies[url] = f.read()
            except OSError:
                pass
        try:
            os.unlink(out)
        except OSError:
            pass
    return bodies


def collect_provider_nodes(doc, conf):
    """下载并解析每个 provider，返回合并后的节点；失败只记报告、不抛异常。"""
    global PROVIDER_REPORT
    urls = provider_urls(doc)
    maxn = clamp_int(conf.get("MOMO_CONVERTER_PROVIDER_MAX"), 16, 1, 64)
    urls = urls[:maxn]
    report = {"total": len(urls), "ok": 0, "failed": 0, "nodes": 0}
    PROVIDER_REPORT = report
    if not urls:
        return []
    bodies = fetch_provider_bodies(urls, conf, provider_ua_map(doc))
    nodes = []
    for url in urls:
        raw = bodies.get(url)
        sub = None
        if raw:
            try:
                sub, _fmt, _groups = extract_nodes(raw, conf, allow_providers=False)
            except Exception:
                sub = None
        if sub:
            nodes.extend(sub)
            report["ok"] += 1
        else:
            report["failed"] += 1
    report["nodes"] = len(nodes)
    return nodes


# --------------------------------------------------------------------------
# 输入识别与节点提取（parser.rs:extract_nodes_from_subscription）
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# 「客户端配置」型订阅：Surge / Loon / Quantumult X 的纯文本配置
#
# 机场除了 Clash 订阅，普遍同时提供这三种格式。它们的节点行语义一致：
#   名称 = 协议, 主机, 端口, 参数...
# 只是参数有的写 k=v（Surge/QuantumultX），有的靠位置（Loon）。
# 这里统一成 sing-box 出站，让用户粘哪种都能用。
# --------------------------------------------------------------------------
TEXT_PROFILE_SECTIONS = {"proxy", "proxy group", "server_local", "server_remote",
                         "server", "policy", "general"}
SURGE_TYPE_ALIASES = {
    "ss": "ss", "shadowsocks": "ss", "vmess": "vmess", "vless": "vless",
    "trojan": "trojan", "hysteria2": "hysteria2", "hy2": "hysteria2",
    "hysteria": "hysteria", "snell": "snell", "socks5": "socks5",
    "socks": "socks5", "http": "http", "https": "http", "tuic": "tuic",
    "anytls": "anytls",
}
QX_TYPE_ALIASES = {
    "shadowsocks": "ss", "ss": "ss", "vmess": "vmess", "vless": "vless",
    "trojan": "trojan", "hysteria2": "hysteria2", "hysteria": "hysteria",
    "socks5": "socks5", "http": "http", "anytls": "anytls",
}
GROUP_KIND_ALIASES = {
    "select": "select", "static": "select", "manual": "select",
    "url-test": "url-test", "url-latency-benchmark": "url-test",
    "fallback": "fallback", "load-balance": "load-balance",
    "round-robin": "load-balance", "ssid": "select",
}


def split_config_args(text):
    """按顶层逗号切分配置行参数，保留引号内部的逗号。"""
    return [p.strip() for p in split_flow_items(str(text or "")) if p.strip()]


def strip_quotes(text):
    s = str(text or "").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def bool_arg(value, default=False):
    if value is None or value == "":
        return default
    v = parse_boolish(value)
    return default if v is None else v


def text_profile_transport(kv):
    network = str(kv.get("transport") or kv.get("network") or "").lower()
    obfs = str(kv.get("obfs") or "").lower()
    if obfs in ("ws", "wss"):
        network = "ws"
    if network == "ws" or bool_arg(kv.get("ws")):
        t = {"type": "ws"}
        path = kv.get("ws-path") or kv.get("path") or kv.get("obfs-uri")
        if path:
            t["path"] = path
        host = kv.get("host") or kv.get("obfs-host")
        if not host:
            for item in re.split(r"[|,]", kv.get("ws-headers") or ""):
                key, _, value = item.partition(":")
                if key.strip().lower() == "host" and value.strip():
                    host = value.strip()
        if host:
            t["headers"] = {"Host": host}
        return t
    if network == "grpc":
        service = kv.get("grpc-service-name") or kv.get("service-name") or kv.get("path")
        return {"type": "grpc", "service_name": service} if service else {"type": "grpc"}
    if network in ("h2", "http"):
        t = {"type": "http"}
        if kv.get("host"):
            t["host"] = csv_list(kv["host"])
        if kv.get("path"):
            t["path"] = kv["path"]
        return t
    return None


def text_profile_tls(host, kv, utls=True, default_insecure=False):
    sni = (kv.get("sni") or kv.get("tls-name") or kv.get("peer")
           or kv.get("tls-host") or kv.get("obfs-host") or host)
    insecure = bool_arg(kv.get("skip-cert-verify"), default_insecure)
    if kv.get("tls-verification") not in (None, ""):
        insecure = not bool_arg(kv.get("tls-verification"), True)
    alpn = kv.get("alpn") or None
    if utls:
        return build_utls_tls(host, sni, kv.get("client-fingerprint") or "", insecure, alpn)
    return build_basic_tls(host, sni, insecure, alpn)


def text_profile_node(typ, name, host, port, kv, positional):
    """把一行客户端配置（协议无关部分已拆好）拼成 sing-box 出站。"""
    if not host or not (1 <= port <= 65535):
        return None
    tag = kv.get("tag") or name or default_tag(typ, host, port)
    base = {"tag": tag, "server": host, "server_port": port}
    first = positional[0] if positional else ""

    if typ == "ss":
        method = kv.get("encrypt-method") or kv.get("method") or first
        password = kv.get("password") or (positional[1] if len(positional) > 1 else "")
        if not method or not password:
            return None
        node = dict(base, type="shadowsocks", method=method, password=password)
        obfs = str(kv.get("obfs") or "").lower()
        if obfs in ("http", "tls"):
            node["plugin"] = "obfs-local"
            opts = "obfs=%s" % obfs
            if kv.get("obfs-host"):
                opts += ";obfs-host=%s" % kv["obfs-host"]
            node["plugin_opts"] = opts
        return node

    if typ == "vmess":
        uuid = kv.get("username") or kv.get("uuid") \
            or (positional[1] if len(positional) > 1 else first)
        if not uuid:
            return None
        cipher = kv.get("encrypt-method") or kv.get("method") or "auto"
        try:
            alter_id = int(str(kv.get("alterid") or kv.get("alter-id") or 0))
        except ValueError:
            alter_id = 0
        if bool_arg(kv.get("vmess-aead")):
            alter_id = 0
        node = dict(base, type="vmess", uuid=uuid,
                    security=normalize_vmess_security(cipher), alter_id=alter_id)
        if bool_arg(kv.get("tls")) or bool_arg(kv.get("over-tls")) \
                or str(kv.get("obfs") or "").lower() == "wss":
            node["tls"] = text_profile_tls(host, kv)
        transport = text_profile_transport(kv)
        if transport:
            node["transport"] = transport
        return node

    if typ == "vless":
        uuid = kv.get("username") or kv.get("uuid") or first
        if not uuid:
            return None
        node = dict(base, type="vless", uuid=uuid)
        if kv.get("flow"):
            node["flow"] = kv["flow"]
        if bool_arg(kv.get("tls")) or bool_arg(kv.get("over-tls")):
            node["tls"] = text_profile_tls(host, kv)
        transport = text_profile_transport(kv)
        if transport:
            node["transport"] = transport
        return node

    if typ == "trojan":
        password = kv.get("password") or first
        if not password:
            return None
        node = dict(base, type="trojan", password=password,
                    tls=text_profile_tls(host, kv, utls=False))
        if kv.get("tls") not in (None, "") and not bool_arg(kv.get("tls"), True):
            node["tls"]["enabled"] = False
        transport = text_profile_transport(kv)
        if transport:
            node["transport"] = transport
        return node

    if typ == "hysteria2":
        password = kv.get("password") or kv.get("auth") or first
        if not password:
            return None
        node = dict(base, type="hysteria2", password=password,
                    tls=text_profile_tls(host, kv, utls=False))
        for key, field in (("up", "up_mbps"), ("down", "down_mbps"),
                           ("upmbps", "up_mbps"), ("downmbps", "down_mbps")):
            value = str(kv.get(key) or "")
            if value.isdigit() and field not in node:
                node[field] = int(value)
        if kv.get("obfs"):
            ob = {"type": str(kv["obfs"])}
            if kv.get("obfs-password"):
                ob["password"] = kv["obfs-password"]
            node["obfs"] = ob
        return node

    if typ == "hysteria":
        node = dict(base, type="hysteria",
                    tls=text_profile_tls(host, kv, utls=False))
        auth = kv.get("auth") or kv.get("auth-str") or kv.get("password")
        if auth:
            node["auth_str"] = auth
        for key, field in (("up", "up_mbps"), ("down", "down_mbps"),
                           ("upmbps", "up_mbps"), ("downmbps", "down_mbps")):
            value = str(kv.get(key) or "")
            if value.isdigit() and field not in node:
                node[field] = int(value)
        return node

    if typ == "tuic":
        uuid = kv.get("uuid") or kv.get("username") or first
        if not uuid:
            return None
        node = dict(base, type="tuic", uuid=uuid,
                    tls=text_profile_tls(host, kv, utls=False))
        if kv.get("password"):
            node["password"] = kv["password"]
        return node

    if typ == "anytls":
        password = kv.get("password") or first
        if not password:
            return None
        return dict(base, type="anytls", password=password,
                    tls=text_profile_tls(host, kv, utls=False))

    if typ == "snell":
        psk = kv.get("psk") or first
        if not psk:
            return None
        node = dict(base, type="snell", psk=psk)
        version = str(kv.get("version") or "")
        if version.isdigit():
            node["version"] = int(version)
        return node

    if typ in ("socks5", "http"):
        node = dict(base, type="socks" if typ == "socks5" else "http")
        if kv.get("username"):
            node["username"] = kv["username"]
        if kv.get("password"):
            node["password"] = kv["password"]
        if typ == "http" and (bool_arg(kv.get("tls")) or bool_arg(kv.get("over-tls"))):
            node["tls"] = text_profile_tls(host, kv, utls=False)
        return node

    return None


def parse_surge_proxy(name, body):
    """`名称 = 协议, 主机, 端口, 参数...`（Surge / Loon 通用）。"""
    parts = split_config_args(body)
    if not parts:
        return None
    typ = SURGE_TYPE_ALIASES.get(strip_quotes(parts[0]).lower())
    if not typ:
        return None
    kv, positional = {}, []
    for part in parts[1:]:
        m = re.match(r"^([A-Za-z][A-Za-z0-9_-]*)\s*=\s*(.*)$", part)
        if m:
            kv[m.group(1).lower()] = strip_quotes(m.group(2))
        else:
            positional.append(strip_quotes(part))
    host, port = "", 0
    if positional and re.match(r"^.+:\d+$", positional[0]):
        hp = parse_host_port(positional[0])
        if hp:
            host, port = hp
            positional = positional[1:]
    elif len(positional) >= 2 and positional[1].isdigit():
        host, port = positional[0], int(positional[1])
        positional = positional[2:]
    return text_profile_node(typ, name, host, port, kv, positional)


def parse_qx_node(typ, body, label=""):
    """Quantumult X：`协议=主机:端口, 参数...`。"""
    parts = split_config_args(body)
    if not parts:
        return None
    hp = parse_host_port(parts[0])
    if not hp:
        return None
    host, port = hp
    kv = {}
    for part in parts[1:]:
        key, sep, value = part.partition("=")
        if sep:
            kv[key.strip().lower()] = strip_quotes(value)
    # Quantumult X 的 vmess 把 UUID 写在 password 里
    if typ == "vmess" and not kv.get("uuid") and kv.get("password"):
        kv["uuid"] = kv.pop("password")
    return text_profile_node(typ, kv.get("tag") or label, host, port, kv, [])


def parse_text_proxy_line(line):
    if "=" not in line:
        return None
    left, body = line.split("=", 1)
    left, body = left.strip(), body.strip()
    if not left or not body:
        return None
    low = strip_quotes(left).lower()
    if low in QX_TYPE_ALIASES:
        return parse_qx_node(QX_TYPE_ALIASES[low], body, "")
    return parse_surge_proxy(strip_quotes(left), body)


def parse_text_group(line):
    if "=" not in line:
        return None
    left, body = line.split("=", 1)
    left, body = strip_quotes(left.strip()), body.strip()
    parts = split_config_args(body)
    if not parts:
        return None
    kind = strip_quotes(parts[0]).lower()
    typ = GROUP_KIND_ALIASES.get(kind)
    name = left
    if typ is None:
        # Quantumult X：[policy] 里是 `static=组名, 成员...`
        typ = GROUP_KIND_ALIASES.get(left.lower())
        if typ is None:
            return None
        name = strip_quotes(parts[0])
        parts = parts[1:]
    else:
        parts = parts[1:]
    members = [strip_quotes(p) for p in parts
               if p and not re.match(r"^[A-Za-z][A-Za-z0-9_-]*\s*=", p)]
    if not name:
        return None
    return {
        "name": name, "tag": "", "type": typ, "url": DEFAULT_TEST_URL,
        "interval": DEFAULT_INTERVAL, "tolerance": DEFAULT_TOLERANCE,
        "timeout": DEFAULT_TIMEOUT, "strategy": "round-robin", "lazy": True,
        "expected_status": "", "members_raw": members, "include_all": False,
        "filter": "", "exclude_filter": "", "members": [], "source": "subscription",
    }


def parse_text_profile(text):
    """解析 Surge / Loon / Quantumult X 纯文本配置；不像就返回 None。"""
    nodes, groups = [], []
    section = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(";") or line.startswith("//"):
            continue
        m = re.match(r"^\[([^\]]+)\]\s*(?:[#;].*)?$", line)
        if m:
            section = m.group(1).strip().lower()
            continue
        if section not in TEXT_PROFILE_SECTIONS:
            continue
        if section in ("proxy", "server_local", "server", "server_remote"):
            node = parse_text_proxy_line(line)
            if node:
                nodes.append(node)
        elif section in ("proxy group", "policy"):
            group = parse_text_group(line)
            if group:
                groups.append(group)
    if not nodes:
        return None
    return nodes, groups


# --------------------------------------------------------------------------
# JSON 订阅里单个对象的归一化（sing-box 原生 / Clash / SIP008 三种写法）
# --------------------------------------------------------------------------
def node_from_object(obj):
    if not isinstance(obj, dict):
        return None
    typ = str(obj.get("type") or "").strip().lower()
    # sing-box 原生出站：字段名是 server_port / tag
    if typ in PROXY_TYPES and obj.get("server_port") is not None and obj.get("server"):
        node = dict(obj)
        node["tag"] = str(node.get("tag") or node.get("remarks") or node.get("name") or "")
        return node
    # Clash 写法：port + cipher/psk/password
    node = clash_to_singbox(obj)
    if node:
        return node
    # SIP008（shadowsocks 订阅标准）：server/server_port/method/password/remarks
    if obj.get("server") and (obj.get("method") and obj.get("password") is not None):
        try:
            port = int(obj.get("server_port") or obj.get("port") or 0)
        except (TypeError, ValueError):
            port = 0
        if not (1 <= port <= 65535):
            return None
        node = {
            "tag": str(obj.get("remarks") or obj.get("name") or obj.get("id") or "")
                   or "shadowsocks-%s:%s" % (obj["server"], port),
            "type": "shadowsocks", "server": str(obj["server"]), "server_port": port,
            "method": str(obj["method"]), "password": str(obj["password"]),
        }
        if obj.get("plugin"):
            node.update(ss_plugin_fields("%s;%s" % (obj["plugin"], obj.get("plugin_opts") or "")))
        return node
    return None


def json_nodes_from_value(value, nodes, groups):
    """从一个 JSON 值里尽力捞出节点，兼容任意包裹层级。"""
    if isinstance(value, dict):
        if value.get("type") or value.get("server_port"):
            node = node_from_object(value)
            if node:
                nodes.append(node)
            return
        for child in value.values():
            json_nodes_from_value(child, nodes, groups)
    elif isinstance(value, list):
        for item in value:
            json_nodes_from_value(item, nodes, groups)


def is_native_singbox_config(obj):
    return isinstance(obj, dict) and isinstance(obj.get("outbounds"), list)


def _clash_yaml_extract(candidate, conf, allow_providers):
    """Clash/Mihomo YAML -> (nodes, groups)。整份文档常在 dns/tun 段提前中断，
    因此三个关键段各自兜底取值。"""
    expanded = expand_yaml_aliases(candidate)
    doc = parse_yaml_subset(expanded)
    proxies = doc.get("proxies") if isinstance(doc, dict) else None
    if not isinstance(proxies, list):
        proxies = yaml_section_value(expanded, "proxies")
    groups_raw = doc.get("proxy-groups") if isinstance(doc, dict) else None
    if not isinstance(groups_raw, list):
        groups_raw = yaml_section_value(expanded, "proxy-groups")
    providers_raw = doc.get("proxy-providers") if isinstance(doc, dict) else None
    if providers_raw is None:
        providers_raw = yaml_section_value(expanded, "proxy-providers")
    groups = parse_proxy_groups(groups_raw)
    nodes = []
    if isinstance(proxies, list):
        for proxy in proxies:
            node = clash_to_singbox(proxy)
            if node:
                nodes.append(node)
    # 分流规则：整份文档常在 dns/tun 段提前中断，逐段兜底取值
    # 只在顶层调用采集（provider 递归解析会覆盖，必须跳过）
    if allow_providers:
        rules_raw = doc.get("rules") if isinstance(doc, dict) else None
        if not isinstance(rules_raw, list):
            rules_raw = yaml_section_value(expanded, "rules")
        rule_providers = doc.get("rule-providers") if isinstance(doc, dict) else None
        if not isinstance(rule_providers, dict):
            rule_providers = yaml_section_value(expanded, "rule-providers")
        global CLASH_EXTRA
        CLASH_EXTRA = {"rules": rules_raw if isinstance(rules_raw, list) else [],
                       "rule-providers": rule_providers
                       if isinstance(rule_providers, dict) else {}}
    # 模板型 Clash 配置：proxies 只有 direct，真实节点在 proxy-providers
    if allow_providers and conf is not None \
            and flag_enabled(conf.get("MOMO_CONVERTER_PROVIDERS"), True):
        nodes.extend(collect_provider_nodes(
            {"proxy-providers": providers_raw}, conf))
    return nodes, groups


def _json_extract(obj):
    """JSON 订阅：sing-box 原生 / Clash JSON / SIP008 / 节点数组。"""
    if isinstance(obj, dict) and is_native_singbox_config(obj):
        return None, "native", []
    nodes, groups = [], []
    if isinstance(obj, dict):
        groups = parse_proxy_groups(obj.get("proxy-groups", obj.get("proxy_groups")))
        raw = obj.get("proxies")
        if isinstance(raw, list):
            for proxy in raw:
                node = node_from_object(proxy)
                if node:
                    nodes.append(node)
            return nodes, "clash-json", groups
        raw = obj.get("servers")
        if isinstance(raw, list):
            for item in raw:
                node = node_from_object(item)
                if node:
                    nodes.append(node)
            return nodes, "sip008", groups
    json_nodes_from_value(obj, nodes, groups)
    return nodes, "nodes-json", groups


def parse_uri_lines(text):
    """URI 分享链接列表（可带行内注释/空行/CRLF）。返回 (nodes, skips)。"""
    nodes, skips, seen_skip = [], [], set()

    def note(reason):
        if len(skips) < 12 and reason not in seen_skip:
            seen_skip.add(reason)
            skips.append(reason)

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        scheme = uri_scheme(line)
        if not scheme:
            continue
        if scheme in UNSUPPORTED_SCHEMES:
            note("%s:// -> %s" % (scheme, UNSUPPORTED_SCHEMES[scheme]))
            continue
        node = convert_uri(line)
        if node:
            nodes.append(node)
        else:
            note("%s:// 链接无法解析" % scheme)
    return nodes, skips


def _extract_one(text, conf, allow_providers):
    """单次尝试：识别并提取节点。不匹配返回 None。"""
    stripped = text.strip()
    if not stripped:
        return None

    # 1) JSON 家族
    if stripped[0] in "{[":
        obj = None
        try:
            obj = json.loads(stripped)
        except ValueError:
            obj = None
        if obj is not None:
            return _json_extract(obj)

    # 2) Clash / Mihomo YAML
    if re.search(r"(?m)^\s*(proxies|proxy-groups|proxy-providers)\s*:", stripped):
        nodes, groups = _clash_yaml_extract(stripped, conf, allow_providers)
        return nodes, "clash-yaml", groups

    # 3) 只有节点列表、没有 proxies 键的 YAML（部分机场的「裸列表」导出）
    if re.match(r"^\s*-\s", stripped) and re.search(r"(?m)^\s*-\s*name\s*:", stripped) \
            and re.search(r"(?m)^\s+type\s*:", stripped):
        nodes, groups = _clash_yaml_extract("proxies:\n" + stripped, conf, allow_providers)
        return nodes, "clash-yaml-list", groups

    # 4) Surge / Loon / Quantumult X 纯文本配置
    if re.search(r"(?mi)^\s*\[(proxy|proxy group|server_local|server_remote|policy)"
                 r"\]\s*(?:[#;].*)?$", stripped):
        parsed = parse_text_profile(stripped)
        if parsed:
            nodes, groups = parsed
            return nodes, "text-profile", groups
        return None

    # 5) URI 分享链接列表
    low = stripped.lower()
    if any(("%s://" % s) in low for s in URI_SCHEMES):
        nodes, skips = parse_uri_lines(stripped)
        if skips:
            EXTRACT_SKIPS.extend(skips)
        return nodes, "uri-list", []

    return None


EXTRACT_DEPTH = 0


def extract_nodes(content, conf=None, allow_providers=True):
    """返回 (nodes, input_format, proxy_groups)。原生配置返回 (None, 'native', [])。

    支持：Clash/Mihomo YAML（含同缩进序列、锚点合并键、proxy-providers）、
    Clash JSON、sing-box JSON、SIP008、节点对象数组、Surge/Loon/Quantumult X
    文本配置、URI 链接列表、以及上述任意格式的 base64（含双层）包裹。
    """
    # provider 会递归调用本函数：只有最外层才重置跳过原因，否则子订阅
    # 会把主订阅的 format_skips 覆盖掉。
    global EXTRACT_DEPTH, EXTRACT_SKIPS
    if EXTRACT_DEPTH == 0:
        EXTRACT_SKIPS = []
    EXTRACT_DEPTH += 1
    try:
        return _extract_nodes_impl(content, conf, allow_providers)
    finally:
        EXTRACT_DEPTH -= 1


def _extract_nodes_impl(content, conf=None, allow_providers=True):
    text = normalize_text(content)
    stripped = text.strip()
    if not stripped:
        raise ConvertError("输入为空", 2)

    candidates = [(stripped, "")]
    # 整段 base64（含多层嵌套）：逐层都当成候选，哪层能被识别就用哪层
    for depth, layer in enumerate(base64_layers(stripped), 1):
        candidates.append((layer, "+base64" if depth == 1 else "+base64x%d" % depth))

    fallback = None
    for candidate, suffix in candidates:
        result = _extract_one(candidate, conf, allow_providers)
        if result is None:
            continue
        nodes, fmt, groups = result
        if nodes is None:                       # sing-box 原生配置
            return nodes, fmt, groups
        if nodes:
            return nodes, fmt + suffix, groups
        # 结构认出来了但一个节点都没提到：记下第一个，继续试下一种解包
        if fallback is None:
            fallback = (nodes, fmt + suffix, groups)
    if fallback is not None:
        return fallback
    raise ConvertError(
        "未识别的输入格式（支持 Clash/Mihomo YAML、Clash JSON、sing-box JSON、SIP008、"
        "Surge/Loon/Quantumult X、URI 链接列表、base64 订阅）", 2)


# --------------------------------------------------------------------------
# 配置生成（config_generator.rs:inject_nodes）
# --------------------------------------------------------------------------
JUNK_TAG_HINTS = ("剩余流量", "套餐到期", "距离下次", "重置剩余", "订阅到期",
                  "流量重置", "去官网", "官网更新", "到期时间", "过期时间")
LOOPBACK_SERVERS = {"127.0.0.1", "0.0.0.0", "::1", "localhost", "127.1.1.1"}


def junk_node_reason(tag, server):
    """识别机场用来展示套餐信息的占位「节点」，返回原因或 ""。"""
    low_server = str(server or "").strip().lower()
    if low_server in LOOPBACK_SERVERS or low_server.startswith("127."):
        return "占位节点（服务器指向本机 %s）" % low_server
    for hint in JUNK_TAG_HINTS:
        if hint in str(tag or ""):
            return "占位节点（%s）" % hint
    return ""


def normalize_nodes(nodes, resolver_tag="dns_resolver", tag_map=None, conf=None):
    seen = set(RESERVED_TAGS)
    result, skipped = [], []
    if tag_map is None:
        tag_map = {}
    drop_junk = True if conf is None else flag_enabled(
        conf.get("MOMO_CONVERTER_DROP_JUNK"), True)
    for idx, raw in enumerate(nodes):
        if not isinstance(raw, dict):
            skipped.append("#%d: 不是对象" % idx)
            continue
        node = dict(raw)
        typ = str(node.get("type") or "").strip()
        server = str(node.get("server") or "").strip()
        try:
            port = int(node.get("server_port"))
        except (ValueError, TypeError):
            port = 0
        # 机场常用「剩余流量 / 套餐到期 / 去官网更新」占位节点骗过客户端，
        # 它们指向 127.0.0.1 或纯文案名，参与测速会污染自动分组，直接剔除。
        if drop_junk:
            reason = junk_node_reason(str(node.get("tag") or ""), server)
            if reason:
                skipped.append("%s: %s" % (node.get("tag") or ("#%d" % idx), reason))
                continue
        if typ in REMOVED_TYPES:
            skipped.append("%s: %s" % (node.get("tag") or ("#%d" % idx), REMOVED_TYPES[typ]))
            continue
        if typ not in PROXY_TYPES:
            skipped.append("#%d: 不支持的协议 %s" % (idx, typ or "(空)"))
            continue
        if not server or server == "0.0.0.0":
            skipped.append("#%d: 服务器地址无效" % idx)
            continue
        if not (1 <= port <= 65535):
            skipped.append("#%d: 端口无效 %s" % (idx, port))
            continue
        original_tag = str(node.get("tag") or "").strip()
        tag = original_tag or "%s-%s-%d" % (typ, server, idx)
        if tag in seen:
            base_tag = tag
            n = idx
            while tag in seen:
                tag = "node-%s-%d" % (base_tag, n)
                n += 1
        seen.add(tag)
        if original_tag:
            tag_map.setdefault(original_tag, tag)
        node["tag"] = tag
        node["server"] = server
        node["server_port"] = port
        if not is_ip_literal(server) and "domain_resolver" not in node:
            # 节点域名必须用真实 DNS 解析（否则 fake-ip 会返回假 IP 导致连不上）。
            # strategy 用 prefer_ipv4 与模板 dns.strategy 一致：优先 IPv4，且 IPv4
            # 不可用时能回退 IPv6，避免纯 IPv6 节点解析失败 -> 测速无结果/延迟异常。
            node["domain_resolver"] = {"server": resolver_tag, "strategy": "prefer_ipv4"}
        result.append(node)
    return result, skipped


def proxy_selector_members(groups, node_tags):
    """主 proxy 组：全节点 + 订阅分组（+ auto，仅当它确实存在）。"""
    has_auto = any(g["tag"] == TAG_AUTO for g in groups)
    members = ([TAG_AUTO] if has_auto else []) \
        + [g["tag"] for g in groups if g["tag"] != TAG_AUTO] \
        + list(node_tags) + [TAG_DIRECT]
    seen, out = set(), []
    for tag in members:
        if tag not in seen:
            seen.add(tag)
            out.append(tag)
    return out


# --------------------------------------------------------------------------
# 远程规则集（geosite/geoip）镜像测速选源
#
# 上游 config_generator.rs:remote_rule_set_sources 把所有 rule-set 固定写成
#   https://gh-proxy.com/https://raw.githubusercontent.com/SagerNet/...
# 国内网络对 GitHub / 各加速通道的实际速度差异很大，因此转换订阅时：
#   1) 4 个候选镜像并行真实下载 geosite-cn.srs 前 80KB（curl -r 0-81919），
#      用 curl 的 time_total（含连接 + TLS + 传输）算出有效 KB/s；
#   2) 按实测耗时升序排序，>= 80KB/s 硬阈值才保留，取第一个达标的最快源；
#   3) 全部不达标取最快的实测源；全部探测失败保底 gh-proxy 默认值；
#   4) geosite/geoip 两条 rule_set 以及配置里已有的 GitHub 规则集 URL 全部
#      改写为选中的镜像（jsdelivr 系自动推导 @rule-set 仓库路径）。
#
# 安全点（真实 sing-box 1.14.4 实测）：远程 rule-set URL 不可达会让内核
# FATAL 启动失败。因此「全部探测失败（离线/被墙）」时只改写已存在的规则集，
# 不新增远程规则集，避免把原本能启动的 momo 弄坏；需要强制写入可用
# MOMO_CONVERTER_RULESET_FORCE=1。
#
# 可通过环境变量或 converter.conf 覆盖（不改任何集成文件）：
#   MOMO_CONVERTER_RULESET=1|0              总开关，默认 1
#   MOMO_CONVERTER_RULESET_MIN_SPEED=80     硬阈值 KB/s
#   MOMO_CONVERTER_RULESET_TIMEOUT=8        每个探测超时上限（秒）
#   MOMO_CONVERTER_RULESET_CURL=curl        curl 命令（自测可替换为桩）
#   MOMO_CONVERTER_RULESET_INJECT=1|0       是否补齐 geosite/geoip 两条规则集
#   MOMO_CONVERTER_RULESET_FORCE=1|0        离线时也强制写入保底 gh-proxy
# --------------------------------------------------------------------------
def flag_enabled(value, default=True):
    v = str(value if value is not None else "").strip().lower()
    if not v:
        return default
    if v in FALSE_WORDS:
        return False
    if v in TRUE_WORDS:
        return True
    return default


def mirror_url(mirror, target):
    """按镜像类型生成 URL：前缀代理 / jsdelivr @branch 两种写法。"""
    t = RULESET_TARGETS[target]
    if mirror["kind"] == "jsdelivr":
        return "https://%s/gh/%s@%s/%s" % (mirror["host"], t["repo"],
                                           t["branch"], t["file"])
    return "https://%s/https://raw.githubusercontent.com/%s/%s/%s" % (
        mirror["host"], t["repo"], t["branch"], t["file"])


def canonical_github_path(url):
    """把 4 种镜像/官方 raw URL 归一为 raw.githubusercontent.com 之后的路径。"""
    u = str(url or "")
    if not u:
        return ""
    low = u.lower()
    marker = "raw.githubusercontent.com/"
    if marker in low:
        return u[low.index(marker) + len(marker):].split("?", 1)[0].lstrip("/")
    if "jsdelivr" in low:
        m = re.search(r"/gh/([^/]+/[^@/]+)@([^/]+)/(.+)$", u, re.I)
        if m:
            return "%s/%s/%s" % (m.group(1), m.group(2), m.group(3))
    return ""


def mirror_any_url(mirror, url):
    """把任意 GitHub 规则集 URL 改写到选中的镜像；非 GitHub 返回 None。"""
    path = canonical_github_path(url)
    parts = path.split("/") if path else []
    if len(parts) < 4:
        return None
    if mirror["kind"] == "jsdelivr":
        return "https://%s/gh/%s/%s@%s/%s" % (
            mirror["host"], parts[0], parts[1], parts[2], "/".join(parts[3:]))
    return "https://%s/https://raw.githubusercontent.com/%s" % (mirror["host"], path)


def probe_command(curl_cmd, url, timeout, out_path):
    """真实下载前 80KB；-w 输出 http_code / size_download / time_total。"""
    return list(curl_cmd) + [
        "-s", "-S", "-L", "--max-time", str(timeout),
        "--connect-timeout", str(min(4, timeout)),
        "--max-filesize", str(PROBE_MAX_BYTES),
        "-r", PROBE_RANGE, "-o", out_path,
        "-w", "%{http_code} %{size_download} %{time_total}", url,
    ]


def parse_probe_output(text):
    fields = str(text or "").strip().split()
    if len(fields) < 3:
        return None
    try:
        return {"http_code": int(fields[0]), "bytes": int(float(fields[1])),
                "seconds": float(fields[2])}
    except ValueError:
        return None


def _finalize_probe(item, proc, out_path):
    """收集单个 curl 进程结果并校验，返回更新后的 item（不负责 kill）。

    调用前提是 proc.poll() 已确认进程退出，因此这里用阻塞 communicate()
    一次性读尽 stdout/stderr（进程已结束，数据必然可读，不会卡住）。
    """
    try:
        stdout, stderr = proc.communicate()
    except OSError as exc:
        item["error"] = "curl 通信失败: %s" % exc
        return item
    rc = proc.returncode
    if rc != 0:
        item["error"] = "curl 退出码 %d: %s" % (
            rc, stderr.decode("utf-8", "replace").strip()[:120])
        return item
    meta = parse_probe_output(stdout.decode("utf-8", "replace"))
    if not meta:
        item["error"] = (stderr.decode("utf-8", "replace").strip()
                         or "curl 未返回测速数据")[:160]
        return item
    item["http_code"] = meta["http_code"]
    try:
        with open(out_path, "rb") as f:
            head = f.read(3)
        real_bytes = os.path.getsize(out_path)
    except OSError:
        head, real_bytes = b"", 0
    item["bytes"] = real_bytes
    item["seconds"] = meta["seconds"]
    if meta["http_code"] not in (200, 206):
        item["error"] = "HTTP %d" % meta["http_code"]
    elif real_bytes < MIN_PROBE_BYTES:
        item["error"] = "响应内容不足 %d 字节" % MIN_PROBE_BYTES
    elif real_bytes > PROBE_MAX_BYTES:
        item["error"] = "响应超过 %d 字节（镜像忽略了 Range）" % PROBE_MAX_BYTES
    elif head != SRS_MAGIC:
        item["error"] = "不是 .srs 规则集（疑似劫持页/错误页）"
    elif meta["seconds"] <= 0:
        item["error"] = "耗时为 0"
    else:
        item["speed_kbs"] = round(real_bytes / 1024.0 / meta["seconds"], 2)
        item["ok"] = True
    return item


def probe_mirrors(conf, min_speed=DEFAULT_MIN_SPEED, only=None):
    """4 个镜像并行探测；达标即停，绝不等待慢镜像/超时镜像拖累启动。

    任意镜像速度 >= min_speed 即提前终止其余探测（杀进程回收），
    避免 ghfast 之类不可达源把整个规则集探测拖满超时时间。
    only 指定时只探测该镜像（缓存命中路径），可省去其余镜像的网络往返。
    """
    timeout = clamp_int(conf.get("MOMO_CONVERTER_RULESET_TIMEOUT"),
                        DEFAULT_PROBE_TIMEOUT, 1, 30)
    curl_cmd = str(conf.get("MOMO_CONVERTER_RULESET_CURL") or "curl").split()
    try:
        tmpdir = tempfile.mkdtemp(prefix="momo-rs-")
    except OSError:
        tmpdir = None
    mirrors = [m for m in RULESET_MIRRORS
               if only is None or m["name"] == only] or RULESET_MIRRORS
    jobs = []          # 仍在运行/待收集的进程
    results = []       # 已完成（成功或失败）的 item
    for m in mirrors:
        url = mirror_url(m, "geosite")
        out_path = os.path.join(tmpdir, m["name"] + ".part") if tmpdir else os.devnull
        item = {"name": m["name"], "host": m["host"], "probe_url": url,
                "ok": False, "bytes": 0, "seconds": 0.0, "speed_kbs": 0.0,
                "http_code": 0, "error": ""}
        try:
            proc = subprocess.Popen(probe_command(curl_cmd, url, timeout, out_path),
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as exc:
            item["error"] = "curl 启动失败: %s" % exc
            results.append(item)
            continue
        jobs.append([item, proc, out_path])

    deadline = time.time() + timeout + 1
    try:
        while jobs:
            # 每 50ms 轮询一次各进程是否退出，直到有镜像达标或全部结束
            for j in jobs[:]:
                item, proc, out_path = j
                if proc.poll() is None:
                    continue
                jobs.remove(j)
                done = _finalize_probe(item, proc, out_path)
                if done is not None:
                    results.append(done)
            if not jobs:
                break
            if any(r.get("ok") and r["speed_kbs"] >= min_speed for r in results):
                # 已达标：kill 剩余慢镜像，立即返回
                for item, proc, out_path in jobs:
                    try:
                        proc.kill()
                        proc.communicate()
                    except OSError:
                        pass
                    item["error"] = "已达标，跳过（提前终止）"
                    results.append(item)
                jobs = []
                break
            if time.time() >= deadline:
                for item, proc, out_path in jobs:
                    try:
                        proc.kill()
                        proc.communicate()
                    except OSError:
                        pass
                    item["error"] = "探测超时 (>%ds)" % timeout
                    results.append(item)
                jobs = []
                break
            time.sleep(0.05)
    finally:
        for item, proc, out_path in jobs:
            if proc.poll() is None:
                try:
                    proc.kill()
                    proc.communicate()
                except OSError:
                    pass
        if tmpdir:
            for name in (m["name"] for m in mirrors):
                try:
                    os.unlink(os.path.join(tmpdir, name + ".part"))
                except OSError:
                    pass
            try:
                os.rmdir(tmpdir)
            except OSError:
                pass
    return results


def choose_ruleset_mirror(results, min_speed):
    """按实测耗时排序 -> 80KB/s 硬阈值过滤 -> 达标最快 / 最快实测 / 保底。"""
    fallback = next((m for m in RULESET_MIRRORS if m["name"] == DEFAULT_MIRROR),
                    RULESET_MIRRORS[0])
    ok = [r for r in results if r.get("ok")]
    ok.sort(key=lambda r: (r["seconds"], -r["bytes"], r["name"]))
    if not ok:
        # 全部失败时 gh-proxy 已证实不可达：默认不改写已有 URL、不新增规则集，
        # 保持「与之前版本一致」，避免把原本可用的规则集改坏导致内核 FATAL。
        return {"mirror": fallback, "decision": "fallback-offline", "selected": None,
                "ranked": [], "inject": False, "rewrite": False}
    qualified = [r for r in ok if r["speed_kbs"] >= min_speed]
    if qualified:
        picked, decision = qualified[0], "fastest-qualified"
    else:
        picked, decision = ok[0], "fastest-below-threshold"
    mirror = next((m for m in RULESET_MIRRORS if m["name"] == picked["name"]), fallback)
    return {"mirror": mirror, "decision": decision, "selected": picked,
            "ranked": ok, "inject": True, "rewrite": True}


def _mirror_cache_path(conf):
    p = str(conf.get("MOMO_CONVERTER_RULESET_CACHE") or "").strip()
    return p or "/etc/momo/converter/ruleset_mirror.cache"


def _mirror_cache_ttl(conf):
    return clamp_int(conf.get("MOMO_CONVERTER_RULESET_CACHE_TTL"), 3600, 0, 86400 * 7)


def read_mirror_cache(conf):
    """返回未过期的缓存镜像名；无缓存/过期/损坏一律返回 None。"""
    ttl = _mirror_cache_ttl(conf)
    if ttl <= 0:
        return None
    path = _mirror_cache_path(conf)
    try:
        with open(path, "r", encoding="utf-8") as f:
            name = f.read().strip()
        age = time.time() - os.path.getmtime(path)
        if name and age < ttl:
            return name
    except OSError:
        return None
    return None


def write_mirror_cache(conf, name):
    """记录本次选中的镜像，供下次启动优先复用。失败静默忽略。"""
    if not name:
        return
    ttl = _mirror_cache_ttl(conf)
    if ttl <= 0:
        return
    path = _mirror_cache_path(conf)
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".momo-rs-cache-",
                                   dir=os.path.dirname(os.path.abspath(path)) or ".")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(name)
        os.replace(tmp, path)
    except OSError:
        pass


def apply_ruleset_mirrors(cfg, mirror, inject, rewrite=True):
    """改写已有 GitHub 规则集，并按需要补齐 geosite-cn / geoip-cn。"""
    if not isinstance(cfg, dict):
        return {"applied": False, "count": 0, "urls": {}}
    route = cfg.get("route")
    if not isinstance(route, dict):
        return {"applied": False, "count": 0, "urls": {}}
    rss = route.get("rule_set")
    if not isinstance(rss, list):
        rss = []
    urls = dict((rs.get("tag"), rs.get("url")) for rs in rss
                if isinstance(rs, dict) and rs.get("tag") and rs.get("url"))
    if not rewrite and not inject:
        return {"applied": False, "count": len(rss), "urls": urls}
    touched = 0
    if rewrite:
        for rs in rss:
            if not isinstance(rs, dict) or not canonical_github_path(rs.get("url")):
                continue
            new_url = mirror_any_url(mirror, rs["url"])
            if new_url and new_url != rs["url"]:
                rs["url"] = new_url
            rs.setdefault("type", "remote")
            rs.setdefault("format", "binary")
            rs.setdefault("update_interval", "1d")
            touched += 1
    if inject:
        existing = {rs.get("tag") for rs in rss if isinstance(rs, dict)}
        for target in ("geosite", "geoip"):
            t = RULESET_TARGETS[target]
            if t["tag"] in existing:
                continue
            rss.append({"type": "remote", "format": "binary", "tag": t["tag"],
                        "url": mirror_url(mirror, target), "update_interval": "1d"})
            touched += 1
    if not rss:
        return {"applied": False, "count": 0, "urls": {}}
    route["rule_set"] = rss
    # 1.14+ 显式 http_clients（1.16 将移除隐式默认客户端）；不写 detour 即直连下载
    clients = cfg.get("http_clients")
    if not isinstance(clients, list):
        clients = []
    if not any(isinstance(c, dict) and c.get("tag") == "default" for c in clients):
        clients.append({"tag": "default"})
    cfg["http_clients"] = clients
    for rs in rss:
        if isinstance(rs, dict) and rs.get("type") == "remote" and not rs.get("http_client"):
            rs["http_client"] = "default"
    urls = dict((rs["tag"], rs["url"]) for rs in rss
                if isinstance(rs, dict) and rs.get("tag") and rs.get("url"))
    return {"applied": touched > 0, "count": len(rss), "urls": urls}


def prepare_ruleset(conf):
    state = {"enabled": False, "decision": "disabled", "mirror": DEFAULT_MIRROR,
             "min_speed": 0, "probes": [], "selected": None, "ranked": [],
             "inject": False, "rewrite": True, "applied": False,
             "urls": {}, "count": 0}
    if not flag_enabled(conf.get("MOMO_CONVERTER_RULESET"), True):
        return state
    state["enabled"] = True
    state["min_speed"] = clamp_int(conf.get("MOMO_CONVERTER_RULESET_MIN_SPEED"),
                                   DEFAULT_MIN_SPEED, 1, 100000)
    # 缓存命中：先只探测上次选中的镜像，达标直接复用，省去其余镜像的往返
    cached = read_mirror_cache(conf)
    if cached:
        cached_probes = probe_mirrors(conf, state["min_speed"], only=cached)
        cached_ok = next((p for p in cached_probes if p.get("ok")), None)
        if cached_ok and cached_ok["speed_kbs"] >= state["min_speed"]:
            state["probes"] = cached_probes
            state["decision"] = "cached"
            state["mirror"] = cached
            state["selected"] = cached_ok
            state["ranked"] = [{"name": cached_ok["name"],
                                "seconds": cached_ok["seconds"],
                                "speed_kbs": cached_ok["speed_kbs"]}]
            state["inject"] = flag_enabled(
                conf.get("MOMO_CONVERTER_RULESET_INJECT"), True)
            state["rewrite"] = True
            state["_mirror"] = next(
                (m for m in RULESET_MIRRORS if m["name"] == cached),
                RULESET_MIRRORS[0])
            return state
    state["probes"] = probe_mirrors(conf, state["min_speed"])
    choice = choose_ruleset_mirror(state["probes"], state["min_speed"])
    force = flag_enabled(conf.get("MOMO_CONVERTER_RULESET_FORCE"), False)
    if choice.get("selected"):
        write_mirror_cache(conf, choice["selected"]["name"])
    state["decision"] = choice["decision"]
    state["mirror"] = choice["mirror"]["name"]
    state["selected"] = choice["selected"]
    state["ranked"] = [{"name": r["name"], "seconds": r["seconds"],
                        "speed_kbs": r["speed_kbs"]} for r in choice["ranked"]]
    state["inject"] = (flag_enabled(conf.get("MOMO_CONVERTER_RULESET_INJECT"), True)
                       and (choice["inject"] or force))
    state["rewrite"] = choice["rewrite"] or force
    state["_mirror"] = choice["mirror"]
    return state


def apply_ruleset(cfg, state):
    if state.get("enabled"):
        info = apply_ruleset_mirrors(cfg, state["_mirror"], state["inject"],
                                     state.get("rewrite", True))
        state["applied"] = info["applied"]
        state["urls"] = info["urls"]
        state["count"] = info["count"]
    # 模板 rules/dns.rules 引用了 geosite-cn/geoip-cn；若规则集定义未注入成功
    # （总开关关闭 / 离线探测失败且未 FORCE），引用悬空会让 sing-box check
    # 直接 FATAL，此时移除引用规则降级为无分流，保证 momo 仍能启动。
    prune_missing_rule_sets(cfg)


def prune_missing_rule_sets(cfg):
    """移除引用了未定义 rule_set 的 route/dns 规则。"""
    defined = {rs.get("tag") for rs in (cfg.get("route") or {}).get("rule_set") or []
               if isinstance(rs, dict) and rs.get("tag")}
    for section in ("route", "dns"):
        sec = cfg.get(section)
        if not isinstance(sec, dict) or not isinstance(sec.get("rules"), list):
            continue
        sec["rules"] = [r for r in sec["rules"]
                        if not (isinstance(r, dict) and r.get("rule_set")
                                and not set(r["rule_set"]) <= defined)]


# --------------------------------------------------------------------------
# 订阅分流规则（rules + rule-providers）-> sing-box route 规则
#
# mihomo 的 rule-providers 指向 MetaCubeX/meta-rules-dat 的 geosite/geoip
# yaml/mrs（Clash 专用格式，sing-box 不认），但同一份内容在 SagerNet 官方
# sing-geosite / sing-geoip 仓库有等价 .srs，按名称确定性映射后走镜像下载；
# 识别不了的 provider（如自定义 fakeip 过滤表）跳过对应 RULE-SET，流量由
# final 兜底，绝不因此中断转换。
# --------------------------------------------------------------------------
def mirror_repo_url(mirror, repo, branch, file):
    """任意 GitHub 仓库文件 -> 选定镜像的 URL。"""
    if mirror.get("kind") == "jsdelivr":
        return "https://%s/gh/%s@%s/%s" % (mirror["host"], repo, branch, file)
    return "https://%s/https://raw.githubusercontent.com/%s/%s/%s" % (
        mirror["host"], repo, branch, file)


def srs_url(kind, name, mirror):
    """(geosite|geoip, name) -> 官方 .srs 镜像 URL。"""
    repo = SRS_REPOS.get(kind)
    if not repo or not name:
        return ""
    return mirror_repo_url(mirror, repo["repo"], repo["branch"],
                           "%s-%s.srs" % (kind, name))


# provider URL 里出现这些片段即可判定 kind；兼容 /geo/、/geo-lite/、/ruleset/、
# 以及裸目录（geosite/xxx.yaml）等各种仓库布局。
PROVIDER_KIND_RE = re.compile(
    r"(?:^|/)(geosite|geoip)/([^/\s]+?)\.(?:mrs|yaml|yml|txt|list|metadb|db|json)"
    r"(?:[?#].*)?$", re.IGNORECASE)
# 无法从 URL 判定时，按 provider 名后缀猜 kind（xxx_domain / xxx_ip 这类常见约定）
PROVIDER_SUFFIX_KINDS = (("_domain", "geosite"), ("-domain", "geosite"),
                         ("_ip", "geoip"), ("-ip", "geoip"))


def normalize_srs_name(name):
    """geosite/geoip 名字归一：小写、去空白、仅保留安全字符（! @ 是合法名的一部分）。"""
    n = str(name or "").strip().strip("\"'").lower()
    n = re.sub(r"\s+", "", n)
    return n if re.fullmatch(r"[a-z0-9!@._+-]{1,64}", n or "") else ""


def provider_srs_candidate(provider, behavior=""):
    """单个 provider -> (kind, name)。识别不了返回 ("", "")，绝不抛异常。"""
    if not isinstance(provider, dict):
        return "", ""
    url = str(provider.get("url") or "")
    m = PROVIDER_KIND_RE.search(url.replace("\\", "/"))
    if m:
        kind = m.group(1).lower()
        name = normalize_srs_name(m.group(2))
        if name:
            return kind, name
    # URL 无法判定：按 behavior 决定 kind（classical 混合型无法等价映射，跳过）
    b = str(behavior or provider.get("behavior") or "").lower()
    kind = {"domain": "geosite", "ipcidr": "geoip"}.get(b, "")
    if not kind:
        return "", ""
    return kind, ""


def srs_reachable(urls, conf, enabled=True):
    """并行 HEAD 校验 .srs 是否真实存在（404 直接导致 sing-box FATAL，必须预检）。"""
    if not urls or not enabled:
        return None          # None = 未校验，调用方按置信度名单兜底
    curl = conf.get("MOMO_CONVERTER_RULESET_CURL") or "curl"
    timeout = clamp_int(conf.get("MOMO_CONVERTER_RULESET_VERIFY_TIMEOUT"), 6, 2, 30)
    procs = {}
    for u in urls:
        try:
            procs[u] = subprocess.Popen(
                [curl, "-sI", "-L", "-m", str(timeout), "-o", os.devnull,
                 "-w", "%{http_code}", u],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except Exception:
            procs[u] = None
    ok = set()
    for u, p in procs.items():
        if p is None:
            continue
        try:
            code = (p.communicate(timeout=timeout + 4)[0] or b"").decode(errors="replace").strip()
            if code.startswith(("2", "3")):
                ok.add(u)
        except Exception:
            pass
    return ok


def verify_rule_set_urls(urls, conf, timeout=None):
    """并行 HEAD 校验 .srs 可达性；内核对下载失败的 rule_set 会 FATAL，必须预检。"""
    if not urls:
        return set()
    timeout = clamp_int(timeout or conf.get("MOMO_CONVERTER_RULESET_VERIFY_TIMEOUT"),
                        6, 2, 30)
    curl = conf.get("MOMO_CONVERTER_RULESET_CURL") or "curl"
    procs = {}
    for u in urls:
        try:
            procs[u] = subprocess.Popen(
                [curl, "-sI", "-m", str(timeout), "-o", os.devnull, "-w", "%{http_code}", u],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except Exception:
            procs[u] = None
    ok = set()
    for u, p in procs.items():
        if p is None:
            continue
        try:
            code = (p.communicate(timeout=timeout + 5)[0] or b"").decode(errors="replace").strip()
            if code.startswith(("2", "3")):
                ok.add(u)
        except Exception:
            pass
    return ok


def parse_clash_condition(parts):
    """单条条件（TYPE,arg...）-> sing-box rule 字段 dict，识别不了返回 {}。

    只处理与 sing-box 语义可一一对应的类型；AND/OR/NOT 由上层递归展开，
    PROCESS-NAME / IP-ASN / SCRIPT 等无等价物的类型返回 {} 让整条规则被跳过。
    """
    ctype = str(parts[0] or "").upper()
    arg = str(parts[1] if len(parts) > 1 else "").strip().strip("\"'")
    if not ctype:
        return {}
    simple = {"DOMAIN": "domain", "DOMAIN-SUFFIX": "domain_suffix",
              "DOMAIN-KEYWORD": "domain_keyword", "DOMAIN-REGEX": "domain_regex"}
    if ctype in simple:
        if not arg:
            return {}
        # Clash 允许 DOMAIN-SUFFIX 写前导点，sing-box 不接受
        return {simple[ctype]: [arg.lstrip(".") if ctype == "DOMAIN-SUFFIX" else arg]}
    if ctype in ("IP-CIDR", "IP-CIDR6"):
        return {"ip_cidr": [arg]} if "/" in arg else {}
    if ctype == "SRC-IP-CIDR":
        return {"source_ip_cidr": [arg]} if "/" in arg else {}
    if ctype in ("DST-PORT", "SRC-PORT"):
        nums = []
        for piece in str(arg).split("/"):
            piece = piece.strip()
            if piece.isdigit() and 0 < int(piece) < 65536:
                nums.append(int(piece))
            elif "-" in piece:
                a, _, b = piece.partition("-")
                if a.strip().isdigit() and b.strip().isdigit():
                    loop = range(int(a), int(b.strip()) + 1)
                    nums.extend([n for n in loop if 0 < n < 65536][:256])
        if not nums:
            return {}
        return {("port" if ctype == "DST-PORT" else "source_port"): nums}
    if ctype == "NETWORK":
        net = arg.lower()
        return {"network": net} if net in ("tcp", "udp") else {}
    if ctype == "GEOIP":
        name = normalize_srs_name(arg)
        return {"__geoip__": name} if name else {}
    if ctype == "GEOSITE":
        name = normalize_srs_name(arg)
        return {"__geosite__": name} if name else {}
    if ctype == "RULE-SET":
        # provider 名允许中文/标点，tag 另行安全化
        return {"__provider__": arg} if arg else {}
    return {}


# 无等价能力、必须整条跳过的条件类型（出现在 AND/OR 里会让整条失效）
UNSUPPORTED_CONDITIONS = {"PROCESS-NAME", "PROCESS-PATH", "PROCESS-NAME-REGEX",
                          "PROCESS-PATH-REGEX", "IP-ASN", "SCRIPT", "SRC-GEOIP",
                          "SRC-IP-ASN", "INNER", "IN-TYPE", "IN-USER", "IN-NAME",
                          "SUB-RULE", "CELLULAR-RADIO", "RULE-SET-NAME"}

POLICY_ALIASES = {"DIRECT": TAG_DIRECT, "REJECT": TAG_BLOCK,
                  "REJECT-DROP": TAG_BLOCK, "REJECT-DROP-QUIC": TAG_BLOCK,
                  "PASS": "", "COMPATIBLE": TAG_DIRECT}
# 中文/emoji 订阅里 DIRECT/REJECT 的常见写法（这些名字通常不作为分组存在）
DIRECT_HINTS = ("直连", "直接", "走直连", "国内直连", "中国大陆", "大陆", "国内",
                "🇨🇳", "direct", "bypass")
BLOCK_HINTS = ("拒绝", "拦截", "广告拦截", "reject", "block", "adblock")


def policy_hint(display):
    """按名字语义猜 DIRECT/REJECT/未知（未知 = 应当是代理分组）。"""
    low = str(display or "").strip().lower()
    if not low:
        return None
    for h in DIRECT_HINTS:
        if h in low:
            return TAG_DIRECT
    for h in BLOCK_HINTS:
        if h in low:
            return TAG_BLOCK
    return None


def strip_wrapping_parens(text):
    """剥掉整体包裹的一层括号：`(A,B)` -> `A,B`；括号不闭合时原样返回。"""
    s = str(text or "").strip()
    while s.startswith("(") and s.endswith(")"):
        depth, ok = 0, True
        for i, ch in enumerate(s):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0 and i != len(s) - 1:
                    ok = False
                    break
        if not ok:
            break
        s = s[1:-1].strip()
    return s


def split_top_level(text, sep=","):
    """按顶层分隔符切分，忽略括号内的分隔符（AND/OR 规则里很常见）。"""
    out, buf, depth, quote = [], [], 0, ""
    for ch in str(text):
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch == sep and depth == 0:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    out.append("".join(buf))
    return [p.strip() for p in out]


def iter_logical_children(expr):
    """从 `((A),(B))` 里取出各子条件文本（只剥一层，避免把内层括号吃掉）。"""
    body = strip_wrapping_parens(str(expr or "").strip())
    return [c for c in split_top_level(body) if c]


def build_clash_condition(text, ctx):
    """把一条（可能是逻辑组合的）Clash 条件文本转成 sing-box 规则字段。

    ctx: {"provider": fn(name)->tag|"", "geosite": fn(name)->tag|"", "geoip": fn(name)->tag|""}
    返回 dict（不带 outbound）或 {} 表示无法转换。
    """
    text = strip_wrapping_parens(text)
    parts = split_top_level(text)
    if not parts:
        return {}
    ctype = parts[0].upper()
    if ctype in ("AND", "OR", "NOT"):
        if len(parts) < 2:
            return {}
        subs = []
        for child in iter_logical_children(parts[1]):
            cond = build_clash_condition(child, ctx)
            if not cond:
                # AND 里任一条件不可表达 -> 整条失效；OR/NOT 里丢掉这一支仍可降级
                if ctype == "AND":
                    return {}
                continue
            subs.append(cond)
        if not subs:
            return {}
        if ctype == "NOT":
            return {"type": "logical", "mode": "and",
                    "rules": [{"type": "logical", "mode": "or", "rules": subs,
                               "invert": True}]}
        return {"type": "logical", "mode": ctype.lower(), "rules": subs}
    if ctype in UNSUPPORTED_CONDITIONS:
        return {}
    cond = parse_clash_condition(parts)
    if not cond:
        return {}
    if "__provider__" in cond:
        tag = ctx["provider"](cond["__provider__"])
        return {"rule_set": [tag]} if tag else {}
    if "__geosite__" in cond:
        tag = ctx["geosite"](cond["__geosite__"])
        return {"rule_set": [tag]} if tag else {}
    if "__geoip__" in cond:
        tag = ctx["geoip"](cond["__geoip__"])
        return {"rule_set": [tag]} if tag else {}
    return cond


def clash_rules_source(doc_sections):
    """从任意来源取 rules / rule-providers，兼容 flow 列表与 YAML 块两种写法。"""
    rules, providers = [], {}
    for value in doc_sections:
        if isinstance(value, list):
            rules = [str(x) for x in value if isinstance(x, (str, int, float))]
            continue
        if isinstance(value, dict):
            if isinstance(value.get("rules"), list):
                rules = [str(x) for x in value["rules"] if isinstance(x, (str, int, float))]
            if isinstance(value.get("rule-providers"), dict):
                providers.update(value["rule-providers"])
    return rules, providers


def convert_clash_rules(raw_rules, raw_providers, name_map, mirror, conf,
                        srs_ok=None, max_rules=None):
    """订阅 rules 段 -> (route_rules, rule_set_defs, final_tag)。

    设计约束（面对任意/混乱订阅都要能出可用配置）：
    * provider 无法映射成官方 .srs 时，跳过引用它的规则，绝不放 404 URL 进配置；
    * 策略组在本订阅里不存在时，退化为 proxy，不让流量静默直连；
    * 未知条件类型、PASS、无法表达的 AND 子条件一律丢弃，不让整份转换失败。
    """
    providers = raw_providers if isinstance(raw_providers, dict) else {}
    items = [str(r) for r in (raw_rules or []) if isinstance(r, str)]
    limit = clamp_int(max_rules if max_rules is not None
                      else conf.get("MOMO_CONVERTER_RULES_MAX"), 512, 16, 4096)
    out, rs_defs, final = [], {}, None
    dropped = []

    def want(kind, name):
        """按需登记一个标准规则集；返回 tag 或 ""。"""
        name = normalize_srs_name(name)
        if not name:
            return ""
        tag = "%s-%s" % (kind, name)
        tag = re.sub(r"[^A-Za-z0-9_!@.-]", "_", tag)
        if tag in rs_defs:
            return tag if rs_defs[tag] else ""
        url = srs_url(kind, name, mirror)
        keep = True
        if srs_ok is None:
            keep = name in SRS_KNOWN[kind]
        else:
            keep = url in srs_ok
        if not url or not keep:
            rs_defs[tag] = None
            return ""
        rs_defs[tag] = {"type": "remote", "format": "binary", "tag": tag,
                        "url": url, "update_interval": "1d"}
        return tag

    resolved = {}          # provider 名 -> 最终 rule_set tag（"" 表示无法映射）

    def provider_tag(provider):
        key = str(provider)
        if key in resolved:
            return resolved[key]
        tag = ""
        info = providers.get(key)
        if info is None:
            # 订阅里直接写 RULE-SET,<geosite名>,<策略>（没有 provider 定义）也常见
            tag = want("geosite", key) or want("geoip", key)
        else:
            kind, name = provider_srs_candidate(info)
            if kind:
                tag = want(kind, name)
        resolved[key] = tag
        return tag

    def policy_tag(p):
        raw = str(p or "").strip().strip("\"'")
        up = raw.upper()
        if up in POLICY_ALIASES:
            return POLICY_ALIASES[up]
        tag = name_map.get(raw)
        if tag:
            return tag
        # 组名大小写/空白不一致时放宽匹配一次
        low = raw.lower()
        for name, mapped in name_map.items():
            if str(name).strip().lower() == low:
                return mapped
        # 订阅里根本不存在这个策略：先按语义猜 DIRECT/REJECT，其余按代理处理，
        # 避免「直连」类别名被误判成代理让国内流量绕远端节点。
        hint = policy_hint(raw)
        return hint if hint else None

    ctx = {"provider": provider_tag,
           "geosite": lambda n: want("geosite", n),
           "geoip": lambda n: want("geoip", n)}

    for item in items:
        text = item.strip().strip("\"'")
        if not text or text.startswith("#"):
            continue
        parts = split_top_level(text)
        head = parts[0].upper() if parts else ""
        if head == "MATCH":
            tag = policy_tag(parts[1] if len(parts) > 1 else "")
            if tag:
                final = tag
            continue
        if head in ("AND", "OR", "NOT"):
            cond = build_clash_condition(text, ctx)
            target = parts[2] if len(parts) > 2 else ""
            tag = policy_tag(target)
            if cond and tag is None:
                tag = TAG_PROXY
            if cond and tag:
                cond["outbound"] = tag
                out.append(cond)
            else:
                dropped.append(text[:60])
            continue
        # 普通规则：<TYPE>,<arg>,<policy>[,no-resolve]
        if len(parts) < 3:
            dropped.append(text[:60])
            continue
        cond = build_clash_condition(",".join(parts[:2]) if len(parts) >= 3 else text, ctx)
        target = parts[2]
        if target.lower() in ("no-resolve", "src"):
            # 该写法缺少策略列，位置不合法，丢弃
            dropped.append(text[:60])
            continue
        tag = policy_tag(target)
        if tag is None:
            tag = TAG_PROXY          # 策略组不存在 -> 仍走代理，避免静默直连
        if tag == "":
            continue                 # PASS
        if not cond:
            dropped.append(text[:60])
            continue
        cond["outbound"] = tag
        out.append(cond)

    # 去重 + 截断：订阅里常有整段重复（多个规则源合并导出）
    seen, uniq = set(), []
    for rule in out:
        key = json.dumps(rule, sort_keys=True, ensure_ascii=False)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(rule)
    if len(uniq) > limit:
        dropped.extend(["超出条数上限裁掉 %d 条" % (len(uniq) - limit)])
        uniq = uniq[:limit]
    defs = [v for v in rs_defs.values() if v]
    # 同一 rule_set 定义了多次（别名/provider 名复用）时只保留一份
    dedup, seen_tag = [], set()
    for d in defs:
        if d["tag"] in seen_tag:
            continue
        seen_tag.add(d["tag"])
        dedup.append(d)
    return uniq, dedup, final, dropped


def ruleset_report(state):
    if not state.get("enabled"):
        return {"enabled": False, "decision": state.get("decision", "disabled")}
    return {
        "enabled": True, "decision": state["decision"], "mirror": state["mirror"],
        "min_speed_kbs": state["min_speed"], "selected": state["selected"],
        "ranked": state["ranked"],
        "probes": [{k: r[k] for k in ("name", "host", "ok", "bytes", "seconds",
                                      "speed_kbs", "http_code", "error")}
                   for r in state["probes"]],
        "inject": state["inject"], "rewrite": state.get("rewrite", True),
        "applied": state["applied"], "rule_set_count": state["count"],
        "urls": state["urls"],
    }


def sanitize_direct_only(cfg):
    """把配置改造成「纯直连」：去掉一切依赖代理的东西。

    fake-ip 必须一起拆掉：没有代理时给出 198.18.0.0/16 的假 IP，
    连接会指向一个没人接管的地址，表现就是「DNS 有结果但网页打不开」。
    """
    dns = cfg.get("dns") if isinstance(cfg.get("dns"), dict) else {}
    cfg["dns"] = dns
    # fake-ip 服务端要留着（momo 启动检查硬性要求存在），但绝不能有规则把查询导过去：
    # 没有代理时发 198.18.x.x 的假 IP，连接会指向没人接管的地址。
    servers = [s for s in dns.get("servers") or [] if isinstance(s, dict)]
    dns["servers"] = servers
    fake_tags = {s.get("tag") for s in servers if s.get("type") == "fakeip" and s.get("tag")}
    local_tag = None
    for srv in servers:
        if srv.get("type") in ("udp", "tcp", "local") and srv.get("tag"):
            srv.pop("detour", None)      # 没有代理，DNS 只能直连解析
            local_tag = local_tag or srv["tag"]
    for srv in servers:
        if srv.get("detour") in ("__PROXY__", TAG_PROXY, TAG_AUTO):
            srv.pop("detour", None)
    dns["rules"] = []
    if local_tag:
        dns["final"] = local_tag
    elif dns.get("final") in fake_tags:
        dns.pop("final", None)
    dns.pop("independent_cache", None)

    cfg["outbounds"] = [
        {"type": "direct", "tag": TAG_DIRECT},
        {"type": "block", "tag": TAG_BLOCK},
        {"type": "selector", "tag": TAG_PROXY, "outbounds": [TAG_DIRECT],
         "default": TAG_DIRECT},
    ]

    route = cfg.get("route") if isinstance(cfg.get("route"), dict) else {}
    cfg["route"] = route
    # 只留嗅探与 DNS 劫持：分流规则依赖外部规则集，下载不通就会 check 失败
    route["rules"] = [r for r in route.get("rules") or []
                      if isinstance(r, dict) and r.get("action") in ("sniff", "hijack-dns")]
    route.pop("rule_set", None)
    route["final"] = TAG_DIRECT
    if local_tag:
        route["default_domain_resolver"] = local_tag
    return cfg


def build_safe_mode_config(template, clash_api=None):
    """无可用节点时的安全模式配置：全局直连，保证不断网。

    订阅过期、机场只发占位节点（"订阅套餐已过期" / 127.0.0.1:6666）、
    provider 全部下载失败时，过去直接返回非 0，原文件留在盘上，
    momo 把这份 YAML 当配置解析 -> "DNS inbound not found" -> 内核退出 -> 整网断流。
    这里退化成一份内核能过 check 的配置：DNS 走真实解析、路由全直连。
    代理不可用是事实，但上网不能跟着一起挂。
    """
    cfg = json.loads(json.dumps(template)) if isinstance(template, dict) else {}
    cfg = sanitize_direct_only(cfg)
    if clash_api:
        exp = cfg.setdefault("experimental", {})
        ca = exp.get("clash_api") if isinstance(exp.get("clash_api"), dict) else {}
        exp["clash_api"] = ca
        if not ca.get("external_controller"):
            ca["external_controller"] = clash_api
    return cfg


def build_config(nodes, template, groups=None, clash_api=None):
    """所有分组一律生成 selector，绝不生成内核 urltest（自动模式由 momo 侧驱动）。"""
    if not isinstance(template, dict):
        raise ConvertError("模板不是 JSON 对象", 3)
    cfg = json.loads(json.dumps(template))  # 深拷贝，避免污染模板
    tags = [n["tag"] for n in nodes]
    groups = list(groups) if groups is not None else []
    if not groups:
        groups = [make_default_auto_group(tags)]
    has_auto = any(g["tag"] == TAG_AUTO for g in groups)
    fallback = [TAG_AUTO] if has_auto else (list(tags) or [TAG_DIRECT])

    outbounds = []
    for g in groups:
        members = list(g.get("members") or []) or fallback
        # 分流选择组默认选中列表第一个（订阅本意），运行时不再自动改
        ob = {"type": "selector", "tag": g["tag"], "outbounds": members,
              "default": members[0]}
        outbounds.append(ob)
    proxy_members = proxy_selector_members(groups, tags)
    outbounds.append({
        "type": "selector", "tag": TAG_PROXY,
        "outbounds": proxy_members,
        "default": TAG_AUTO if TAG_AUTO in proxy_members else proxy_members[0],
    })
    outbounds.append({"type": "direct", "tag": TAG_DIRECT})
    outbounds.append({"type": "block", "tag": TAG_BLOCK})
    outbounds.extend(nodes)
    cfg["outbounds"] = outbounds

    if clash_api:
        exp = cfg.setdefault("experimental", {})
        ca = exp.get("clash_api")
        if not isinstance(ca, dict):
            ca = {}
            exp["clash_api"] = ca
        if not ca.get("external_controller"):
            ca["external_controller"] = clash_api

    route = cfg.setdefault("route", {})
    route["final"] = TAG_PROXY
    dns = cfg.setdefault("dns", {})
    for server in dns.get("servers", []):
        if isinstance(server, dict) and server.get("detour") == "__PROXY__":
            server["detour"] = TAG_PROXY
    dns_tags = [s.get("tag") for s in dns.get("servers", [])
                if isinstance(s, dict) and s.get("tag")]
    if dns.get("final") not in dns_tags:
        remote = next((s["tag"] for s in dns.get("servers", [])
                       if isinstance(s, dict) and s.get("detour") == TAG_PROXY and s.get("tag")), None)
        dns["final"] = remote or (dns_tags[-1] if dns_tags else "dns_remote")
    return cfg


def prune_group_members(groups, node_tags):
    """坏节点被 sing-box check 隔离后，同步清理分组里的悬空引用。"""
    allowed = set(node_tags) | {TAG_AUTO, TAG_PROXY, TAG_DIRECT, TAG_BLOCK} \
        | {g["tag"] for g in groups}
    for g in groups:
        g["members"] = [m for m in g["members"] if m in allowed] or [TAG_AUTO]
    return groups


# --------------------------------------------------------------------------
# momo 绑定骨架自愈
#
# momo 内核启动前会硬性检查四个 inbound（dns-in/redirect-in/tproxy-in/tun-in）
# 与 fakeip DNS server，缺失直接 "Check failed" + "Exit."，整机断网。
# 但订阅是别人的：机场给的 sing-box 原生配置、Clash 转换后的第三方模板、
# 手写配置，都不会带 momo 的 inbound 标签。这里统一补齐（缺什么加什么，
# 已有同类型 inbound 就改名复用而不是新建），保证任何来源的配置都能启动。
# --------------------------------------------------------------------------
SCAFFOLD_ORDER = ("dns-in", "redirect-in", "tproxy-in", "tun-in")

# 旧版 DNS server address 协议 -> 新版 type
LEGACY_DNS_SCHEMES = {"tcp": "tcp", "udp": "udp", "tls": "tls", "https": "https",
                      "quic": "quic", "h3": "h3", "dhcp": "dhcp"}


def _split_dns_address(address):
    """把旧版 address 拆成 (scheme, host, port, path)。"""
    text = str(address or "").strip()
    scheme = ""
    match = re.match(r"^([A-Za-z0-9]+)://(.+)$", text)
    if match:
        scheme, text = match.group(1).lower(), match.group(2)
    if "?" in text:
        text = text.split("?", 1)[0]
    path = ""
    if "/" in text:
        text, tail = text.split("/", 1)
        path = "/" + tail
    host, port = text, None
    if text.startswith("["):
        end = text.find("]")
        if end > 0:
            host = text[1:end]
            rest = text[end + 1:]
            if rest.startswith(":") and rest[1:].isdigit():
                port = int(rest[1:])
    elif text.count(":") == 1:
        name, _, digits = text.rpartition(":")
        if digits.isdigit():
            host, port = name, int(digits)
    return scheme, host, port, path


def _migrate_dns_server(srv):
    """旧版 address 格式 -> 新版 type/server；rcode:// 返回 (None, rcode)。"""
    address = str(srv.get("address") or "").strip()
    new = {k: v for k, v in srv.items()
           if k not in ("address", "address_resolver", "strategy", "client_subnet")}
    if srv.get("address_resolver"):
        new["domain_resolver"] = srv["address_resolver"]
    low = address.lower()
    if not address:
        return new, ""
    if low == "local":
        new["type"] = "local"
        return new, ""
    if low == "fakeip":
        new["type"] = "fakeip"
        return new, ""
    if low.startswith("rcode://"):
        return None, low.split("://", 1)[1].upper()
    if low.startswith("dhcp://"):
        new["type"] = "dhcp"
        iface = address.split("://", 1)[1]
        if iface and iface != "auto":
            new["interface"] = iface
        return new, ""
    scheme, host, port, path = _split_dns_address(address)
    new["type"] = LEGACY_DNS_SCHEMES.get(scheme, "udp")
    if host:
        new["server"] = host
    if port:
        new["server_port"] = port
    if path:
        new["path"] = path
    return new, ""


def migrate_legacy_dns(cfg):
    """sing-box 1.12 起的 DNS 新格式迁移（1.14 已彻底移除旧格式）。"""
    dns = cfg.get("dns")
    if not isinstance(dns, dict):
        return []
    servers = dns.get("servers")
    if not isinstance(servers, list):
        return []
    notes = []
    legacy_fakeip = dns.get("fakeip") if isinstance(dns.get("fakeip"), dict) else None
    kept, rcode_map, changed = [], {}, False
    for srv in servers:
        if not isinstance(srv, dict) or "address" not in srv:
            kept.append(srv)
            continue
        new, rcode = _migrate_dns_server(srv)
        changed = True
        if new is None:
            tag = str(srv.get("tag") or "")
            if tag:
                rcode_map[tag] = rcode or "REFUSED"
            notes.append("移除旧格式 rcode DNS：%s（改为 dns 规则 action=predefined）" % tag)
            continue
        if new.get("type") == "fakeip" and legacy_fakeip:
            for key in ("inet4_range", "inet6_range"):
                if legacy_fakeip.get(key) and not new.get(key):
                    new[key] = legacy_fakeip[key]
        notes.append("DNS 服务器 %s 迁移为 %s 格式" % (new.get("tag") or "-", new.get("type")))
        kept.append(new)
    if not changed:
        return []
    dns["servers"] = kept
    if legacy_fakeip is not None:
        dns.pop("fakeip", None)
    # 1.12 起 dns 规则不再支持 outbound 匹配项：只用于 outbound 的条件规则直接删除，
    # 混合条件规则去掉该匹配项保留其余条件
    rule_keys = ("server", "servers", "action", "strategy", "client_subnet", "rcode",
                 "disable_cache", "rewrite_ttl", "invert", "outbound")
    migrated_rules = []
    for rule in dns.get("rules") or []:
        if isinstance(rule, dict) and "outbound" in rule:
            remaining = [k for k in rule if k not in rule_keys]
            notes.append("移除 dns 规则的 outbound 匹配项")
            if not remaining:
                continue
            rule.pop("outbound", None)
        migrated_rules.append(rule)
    if "rules" in dns:
        dns["rules"] = migrated_rules
    for rule in dns.get("rules") or []:
        if not isinstance(rule, dict) or "action" in rule:
            continue
        tag = rule.get("server")
        if tag in rcode_map:
            rule.pop("server", None)
            rule["action"] = "predefined"
            rule["rcode"] = rcode_map[tag]
    if dns.get("final") in rcode_map:
        fallback = next((s.get("tag") for s in kept
                         if isinstance(s, dict) and s.get("tag")
                         and s.get("type") not in ("fakeip", "predefined")), None)
        if fallback:
            dns["final"] = fallback
        else:
            dns.pop("final", None)
    return notes


def migrate_legacy_outbounds(cfg):
    """删除 block/dns 特殊出站，规则改为 action reject / hijack-dns。"""
    outbounds = cfg.get("outbounds")
    if not isinstance(outbounds, list):
        return []
    special = {ob.get("tag"): ob.get("type") for ob in outbounds
               if isinstance(ob, dict) and ob.get("type") in ("block", "dns") and ob.get("tag")}
    if not special:
        return []
    notes = []
    block_tags = {t for t, ty in special.items() if ty == "block"}
    dns_tags = {t for t, ty in special.items() if ty == "dns"}
    cfg["outbounds"] = [ob for ob in outbounds
                        if not (isinstance(ob, dict) and ob.get("type") in ("block", "dns"))]
    for rule in ((cfg.get("route") or {}).get("rules") or []):
        if not isinstance(rule, dict):
            continue
        target = rule.get("outbound")
        if target in block_tags and "action" not in rule:
            rule.pop("outbound", None)
            rule["action"] = "reject"
        elif target in dns_tags and "action" not in rule:
            rule.pop("outbound", None)
            rule["action"] = "hijack-dns"
        elif isinstance(rule.get("outbound"), list):
            kept = [t for t in rule["outbound"] if t not in special]
            if kept != rule["outbound"]:
                rule["outbound"] = kept
    route = cfg.get("route") or {}
    if route.get("final") in special:
        fallback = next((ob.get("tag") for ob in cfg["outbounds"]
                         if isinstance(ob, dict) and ob.get("tag")), None)
        if fallback:
            route["final"] = fallback
    notes.append("移除特殊出站：%s" % ", ".join(sorted(special)))
    return notes


LEGACY_INBOUND_FIELDS = ("sniff", "sniff_override_destination", "domain_strategy",
                         "endpoint_independent_nat", "udp_disable_domain_unmapping",
                         "udp_connect", "resolve_timeout")


def strip_block_outbound(cfg):
    """把 block 出站及其规则引用改成规则动作 action: reject。

    type:block 是 sing-box 1.11 之前的写法，1.14 里退化成内建占位出站：
    UDP 流量被路由到它时，内核要为这条会话建 packet connection，而 block
    出站不支持监听，于是持续打印
    "listen packet connection ... outbound/block[block]: operation not permitted"，
    每条 UDP 一条 ERROR，日志几分钟就能涨到几 MB（还会拖慢日志页）。
    改成 action: reject 后不再进连接栈，行为等价（丢弃），且不刷日志。
    """
    outbounds = cfg.get("outbounds")
    if not isinstance(outbounds, list):
        return []

    block_tags = {TAG_BLOCK}
    for ob in outbounds:
        if isinstance(ob, dict) and ob.get("type") == "block" and ob.get("tag"):
            block_tags.add(ob["tag"])

    touched = 0

    # 1) 规则：outbound -> action reject
    for rule in ((cfg.get("route") or {}).get("rules") or []):
        if not isinstance(rule, dict):
            continue
        target = rule.get("outbound")
        if isinstance(target, str) and target in block_tags and "action" not in rule:
            rule.pop("outbound", None)
            rule["action"] = "reject"
            touched += 1
        elif isinstance(target, list):
            kept = [t for t in target if t not in block_tags]
            if kept != target:
                rule["outbound"] = kept or [TAG_DIRECT]
                touched += 1

    # 2) route.final 兜底
    route = cfg.get("route") or {}
    if isinstance(route.get("final"), str) and route["final"] in block_tags:
        route["final"] = TAG_DIRECT
        touched += 1

    # 3) 删除 block 出站，并清理 selector/urltest 里的引用
    kept_outbounds = [ob for ob in outbounds
                      if not (isinstance(ob, dict) and ob.get("type") == "block")]
    for ob in kept_outbounds:
        if not isinstance(ob, dict):
            continue
        members = ob.get("outbounds")
        if isinstance(members, list):
            kept = [t for t in members if t not in block_tags]
            if kept != members:
                ob["outbounds"] = kept or [TAG_DIRECT]
                if ob.get("default") in block_tags:
                    ob["default"] = ob["outbounds"][0]
                touched += 1
        elif ob.get("default") in block_tags:
            ob["default"] = TAG_DIRECT
            touched += 1

    cfg["outbounds"] = kept_outbounds
    return touched


def migrate_legacy_inbounds(cfg):
    """1.11 起 inbound 的 sniff/domain_strategy 等字段移到 route 规则动作。"""
    inbounds = cfg.get("inbounds")
    if not isinstance(inbounds, list):
        return []
    notes, override = [], False
    for ib in inbounds:
        if not isinstance(ib, dict):
            continue
        touched = [k for k in LEGACY_INBOUND_FIELDS if k in ib]
        if not touched:
            continue
        if ib.pop("sniff_override_destination", False):
            override = True
        for key in touched:
            ib.pop(key, None)
        if ib.get("users") == []:
            ib.pop("users", None)
        notes.append("inbound %s 迁移旧字段：%s" % (ib.get("tag") or "-", ",".join(touched)))
    if override:
        # 1.13+ 已没有 sniff.override_destination：由 momo 的 sniff 规则 + fake-ip 映射接管
        notes.append("旧 sniff_override_destination 由 route sniff 规则接管")
    return notes


def normalize_dns_detour(cfg):
    """detour 指向「空 direct 出站」在内核里等于没有意义，1.14 直接启动失败。

    订阅作者常写 {"type":"direct","tag":"direct"} 再让 DNS 走 detour: direct，
    新版内核要求 DNS 不写 detour（默认就是直连解析），这里去掉该字段。
    """
    dns = cfg.get("dns")
    if not isinstance(dns, dict):
        return []
    outbounds = {ob.get("tag"): ob for ob in cfg.get("outbounds") or []
                 if isinstance(ob, dict) and ob.get("tag")}
    notes = []
    for srv in dns.get("servers") or []:
        if not isinstance(srv, dict):
            continue
        target = srv.get("detour")
        ob = outbounds.get(target)
        if not isinstance(ob, dict) or ob.get("type") != "direct":
            continue
        # 只有「纯直连」才删 detour：带 override_address 等的 direct 仍有意义
        extra = [k for k in ob if k not in ("type", "tag")]
        if extra:
            continue
        srv.pop("detour", None)
        notes.append("DNS 服务器 %s 去掉指向空直连出站的 detour" % (srv.get("tag") or "-"))
    return notes


def migrate_route_actions(cfg):
    """1.11+ 规则动作：只有 outbound 字段的规则补 action: route。"""
    route = cfg.get("route")
    if not isinstance(route, dict):
        return []
    notes = []
    for rule in route.get("rules") or []:
        if not isinstance(rule, dict) or "action" in rule:
            continue
        if isinstance(rule.get("outbound"), str):
            rule["action"] = "route"
            notes.append("规则补 action=route（%s）" % rule["outbound"])
    return notes


def migrate_legacy_profile(cfg):
    """旧版 sing-box 配置整体迁移（1.14 内核只认新格式）。"""
    notes = []
    notes.extend(migrate_legacy_inbounds(cfg))
    notes.extend(migrate_legacy_outbounds(cfg))
    notes.extend(migrate_legacy_dns(cfg))
    notes.extend(normalize_dns_detour(cfg))
    notes.extend(migrate_route_actions(cfg))
    return notes



def _template_inbounds(template):
    out = {}
    for ib in (template or {}).get("inbounds") or []:
        if isinstance(ib, dict) and ib.get("tag") in MOMO_INBOUND_TAGS:
            out[ib["tag"]] = ib
    return out


def _template_dns_server(template, pred):
    for srv in ((template or {}).get("dns") or {}).get("servers") or []:
        if isinstance(srv, dict) and srv.get("tag") and pred(srv):
            return srv
    return None


def read_momo_modes(path="/etc/config/momo"):
    """极简 UCI 读取，只取 proxy 段的 tcp_mode/udp_mode；读不到返回 None。"""
    if not path or not os.path.isfile(path):
        return None
    modes, section = {}, None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("config "):
                    parts = line.split()
                    section = parts[1] if len(parts) > 1 else ""
                    continue
                if section != "proxy" or not line.startswith("option "):
                    continue
                parts = line.split(None, 2)
                if len(parts) < 3:
                    continue
                modes[parts[1]] = parts[2].strip("'\"")
    except OSError:
        return None
    return modes or None


def required_inbounds(modes=None):
    """按当前 tcp/udp 模式推导必需的 inbound；模式未知时四个全要。"""
    if not modes:
        return list(SCAFFOLD_ORDER)
    tcp = (modes.get("tcp_mode") or "").strip()
    udp = (modes.get("udp_mode") or "").strip()
    need = {"dns-in"}
    if tcp == "redirect":
        need.add("redirect-in")
    if "tproxy" in (tcp, udp):
        need.add("tproxy-in")
    if "tun" in (tcp, udp):
        need.add("tun-in")
    return [tag for tag in SCAFFOLD_ORDER if tag in need]


def _inbound_list(rule):
    value = rule.get("inbound") if isinstance(rule, dict) else None
    if isinstance(value, list):
        return value
    return [value] if isinstance(value, str) else []


def _rename_inbound_refs(cfg, old, new):
    """inbound 改名后同步路由/DNS 规则里的引用，避免悬空。

    old 为空（原配置里的 inbound 本来就没 tag）时绝不能比较：
    rule.get("inbound") 对没有该键的规则返回 None，会把所有规则误绑到新 tag。
    """
    if not old:
        return False
    changed = False
    for key in ("route", "dns"):
        section = cfg.get(key)
        if not isinstance(section, dict):
            continue
        for rule in section.get("rules") or []:
            if not isinstance(rule, dict):
                continue
            value = rule.get("inbound")
            if isinstance(value, list) and old in value:
                rule["inbound"] = [new if item == old else item for item in value]
                changed = True
            elif value == old:
                rule["inbound"] = new
                changed = True
    return changed


def _rename_dns_refs(cfg, old, new):
    if not old:
        return False
    dns = cfg.get("dns")
    if not isinstance(dns, dict):
        return False
    changed = False
    for rule in dns.get("rules") or []:
        if isinstance(rule, dict) and rule.get("server") == old:
            rule["server"] = new
            changed = True
    if dns.get("final") == old:
        dns["final"] = new
        changed = True
    for rule in dns.get("rules") or []:
        if isinstance(rule, dict) and isinstance(rule.get("servers"), list):
            if old in rule["servers"]:
                rule["servers"] = [new if item == old else item for item in rule["servers"]]
                changed = True
    return changed


def ensure_inbounds(cfg, template, modes=None):
    inbounds = cfg.get("inbounds")
    if not isinstance(inbounds, list):
        inbounds = []
        cfg["inbounds"] = inbounds
    tpl = _template_inbounds(template)
    notes = []
    for tag in required_inbounds(modes):
        existing = next((ib for ib in inbounds
                         if isinstance(ib, dict) and ib.get("tag") == tag), None)
        want = tpl.get(tag) or {}
        if isinstance(existing, dict):
            # 标签对但缺 listen_port/interface_name 时补关键字段，检查才算通过
            for key in ("listen", "listen_port", "interface_name", "address",
                        "stack", "mtu", "auto_route", "strict_route"):
                if key in want and existing.get(key) in (None, "", []):
                    existing[key] = want[key]
            continue
        if not want:
            continue
        adopt = next((ib for ib in inbounds
                      if isinstance(ib, dict) and ib.get("type") == want.get("type")
                      and ib.get("tag") not in MOMO_INBOUND_TAGS), None)
        if isinstance(adopt, dict):
            old = adopt.get("tag")
            adopt["tag"] = tag
            for key in ("listen_port", "interface_name"):
                if adopt.get(key) in (None, "", []) and key in want:
                    adopt[key] = want[key]
            _rename_inbound_refs(cfg, old, tag)
            if adopt.get("type") == "tun":
                adopt["auto_route"] = False
                adopt["strict_route"] = False
            notes.append("复用已有 %s inbound：%s -> %s" % (want.get("type"), old or "-", tag))
            continue
        inbounds.append(json.loads(json.dumps(want)))
        notes.append("补充 %s inbound（%s）" % (tag, want.get("type")))
    # tun inbound 的路由/策略路由由 momo 的 nft + ip rule 管理，内核侧必须关掉自动接管
    for ib in inbounds:
        if isinstance(ib, dict) and ib.get("tag") == "tun-in" and ib.get("type") == "tun":
            if ib.get("auto_route"):
                ib["auto_route"] = False
                notes.append("tun-in 关闭 auto_route（改由 momo 接管路由）")
            if ib.get("strict_route"):
                ib["strict_route"] = False
                notes.append("tun-in 关闭 strict_route（改由 momo 接管路由）")
    return notes


def ensure_dns(cfg, template):
    dns = cfg.get("dns")
    if not isinstance(dns, dict):
        dns = {}
        cfg["dns"] = dns
    servers = dns.get("servers")
    if not isinstance(servers, list):
        servers = []
        dns["servers"] = servers
    notes = []

    def tags():
        return {s.get("tag") for s in servers if isinstance(s, dict) and s.get("tag")}

    # 1) fake-ip 服务端：momo 的 nft fake-ip 放行/回指全依赖它的网段
    if MOMO_FAKEIP_TAG not in tags():
        adopt = next((s for s in servers
                      if isinstance(s, dict) and s.get("type") == "fakeip" and s.get("tag")), None)
        if isinstance(adopt, dict):
            old = adopt["tag"]
            adopt["tag"] = MOMO_FAKEIP_TAG
            _rename_dns_refs(cfg, old, MOMO_FAKEIP_TAG)
            notes.append("复用已有 fakeip DNS：%s -> %s" % (old, MOMO_FAKEIP_TAG))
        else:
            want = _template_dns_server(template, lambda s: s.get("tag") == MOMO_FAKEIP_TAG)
            if want:
                servers.append(json.loads(json.dumps(want)))
                notes.append("补充 fakeip DNS：%s" % MOMO_FAKEIP_TAG)

    # 2) 本地/国内解析器：route.default_domain_resolver 与 nft 都要求它能直连解析
    resolver = next((s.get("tag") for s in servers
                     if isinstance(s, dict) and s.get("type") in ("udp", "tcp", "local")
                     and not s.get("detour") and s.get("tag")), None)
    if not resolver:
        want = _template_dns_server(template, lambda s: s.get("type") in ("udp", "tcp", "local")
                                    and not s.get("detour"))
        if want and want["tag"] not in tags():
            servers.append(json.loads(json.dumps(want)))
            resolver = want["tag"]
            notes.append("补充本地 DNS 解析器：%s" % resolver)

    # 3) fake-ip 解析规则：momo 的 nft 只代理 198.18.0.0/16 与 fc00::/18。
    #    缺少这条规则时，境外域名会拿到真实（多为被污染的）IP，nft 判不出要代理，
    #    于是「域名走直连、IP 打不开」——表现为代理没按分流规则工作。
    if MOMO_FAKEIP_TAG in tags():
        rules = dns.get("rules")
        if not isinstance(rules, list):
            rules = []
            dns["rules"] = rules
        if not any(isinstance(r, dict) and r.get("server") == MOMO_FAKEIP_TAG for r in rules):
            # 插在第一条「无条件规则」之前，否则它会被前面的 catch-all 吃掉
            pos = len(rules)
            for i, rule in enumerate(rules):
                if isinstance(rule, dict) \
                        and not [k for k in rule if k not in ("action", "server", "servers")]:
                    pos = i
                    break
            rules.insert(pos, {"action": "route", "query_type": ["A", "AAAA"],
                               "server": MOMO_FAKEIP_TAG})
            notes.append("补充 fake-ip 解析规则（A/AAAA -> %s）" % MOMO_FAKEIP_TAG)

    # 4) final 必须指向存在的 server，否则整份配置无效
    if dns.get("final") not in tags():
        # 优先沿用订阅「境外域名走代理解析」的原意，别把 final 落回直连解析器：
        # 落回直连等于所有漏网域名都拿本地污染结果，且永远进不了代理
        outbounds = {ob.get("tag"): ob for ob in cfg.get("outbounds") or []
                     if isinstance(ob, dict) and ob.get("tag")}
        proxy_dns = None
        for srv in servers:
            if not isinstance(srv, dict) or not srv.get("tag"):
                continue
            if srv.get("type") in ("fakeip", "local"):
                continue
            detour = outbounds.get(srv.get("detour"))
            if isinstance(detour, dict) and detour.get("type") not in ("direct", "block"):
                proxy_dns = srv["tag"]
                break
        want = (template.get("dns") or {}).get("final")
        if want in tags() and want != resolver:
            fallback = want
        elif proxy_dns:
            fallback = proxy_dns
        else:
            fallback = resolver or MOMO_FAKEIP_TAG
        dns["final"] = fallback
        notes.append("修正 dns.final -> %s" % dns["final"])
    return notes, resolver


def ensure_route(cfg, template, resolver):
    route = cfg.get("route")
    if not isinstance(route, dict):
        route = {}
        cfg["route"] = route
    rules = route.get("rules")
    if not isinstance(rules, list):
        rules = []
        route["rules"] = rules
    notes = []

    def has(pred):
        return any(isinstance(rule, dict) and pred(rule) for rule in rules)

    if not has(lambda r: r.get("action") == "sniff"):
        rules.insert(0, {"action": "sniff"})
        notes.append("补充 sniff 规则")
    if not has(lambda r: r.get("action") == "hijack-dns"):
        pos = 1 if rules and isinstance(rules[0], dict) \
            and rules[0].get("action") == "sniff" else 0
        rules.insert(pos, {"protocol": "dns", "action": "hijack-dns"})
        notes.append("补充 dns 劫持规则")
    if not has(lambda r: "dns-in" in _inbound_list(r)):
        pos = 0
        while pos < len(rules):
            rule = rules[pos]
            if isinstance(rule, dict) and rule.get("action") in ("sniff", "hijack-dns"):
                pos += 1
                continue
            break
        rules.insert(pos, {"inbound": ["dns-in"], "action": "resolve"})
        notes.append("补充 dns-in 解析规则")
    if resolver and not isinstance(route.get("default_domain_resolver"), (dict, str)):
        route["default_domain_resolver"] = {"server": resolver, "strategy": "prefer_ipv4"}
        notes.append("补充 default_domain_resolver -> %s" % resolver)

    # final 悬空时按现有 outbound 兜底，绝不留指向不存在 tag 的 final
    outbounds = [ob for ob in cfg.get("outbounds") or [] if isinstance(ob, dict)]
    tags = {ob.get("tag") for ob in outbounds}
    if tags and route.get("final") not in tags:
        # 与内核默认一致：未指定 final 时走第一个出站；只有确实没有出站才落直连
        candidate = next((ob.get("tag") for ob in outbounds if ob.get("tag")), None)
        for preferred in ("proxy", "节点选择"):
            if preferred in tags:
                candidate = preferred
                break
        route["final"] = candidate or "direct"
        notes.append("修正 route.final -> %s" % route["final"])
    return notes


def repair_profile(cfg, template, modes=None):
    """给任意 sing-box 配置补齐 momo 骨架；返回改动说明（空列表表示无需改动）。"""
    if not isinstance(cfg, dict):
        return []
    if modes is None:
        modes = read_momo_modes()
    notes = ensure_inbounds(cfg, template, modes)
    dns_notes, resolver = ensure_dns(cfg, template)
    notes.extend(dns_notes)
    notes.extend(ensure_route(cfg, template, resolver))
    return notes


def scaffold_missing(cfg, modes=None):
    """补齐后仍然缺失的 momo 骨架项（空集合表示齐备）。"""
    in_tags = {ib.get("tag") for ib in cfg.get("inbounds") or [] if isinstance(ib, dict)}
    dns_tags = {s.get("tag") for s in (cfg.get("dns") or {}).get("servers") or []
                if isinstance(s, dict)}
    missing = set(required_inbounds(modes)) - in_tags
    if MOMO_FAKEIP_TAG not in dns_tags:
        missing.add(MOMO_FAKEIP_TAG)
    return missing


def legacy_required(cfg):
    """1.14 内核会直接拒收的旧格式特征（判不准时宁可不迁移）。"""
    dns = cfg.get("dns") if isinstance(cfg.get("dns"), dict) else {}
    for srv in dns.get("servers") or []:
        if isinstance(srv, dict) and "address" in srv:
            return True
    for rule in dns.get("rules") or []:
        if isinstance(rule, dict) and "outbound" in rule:
            return True
    for ib in cfg.get("inbounds") or []:
        if isinstance(ib, dict) and any(k in ib for k in LEGACY_INBOUND_FIELDS):
            return True
    return False


def repair_native_profile(raw, conf):
    """原生 sing-box 订阅：仅在必要时改写，返回 (新文本, 说明)。

    优先级：能不碰就不碰（逐字节透传）> 只补 momo 骨架 > 旧格式迁移。
    迁移只在检测到旧格式特征、或补齐后仍过不了内核 check 时才做，
    避免把本来合法的原生配置改得面目全非。
    """
    try:
        obj = json.loads(raw.decode("utf-8-sig", "replace"))
    except (ValueError, AttributeError):
        return None, []
    if not isinstance(obj, dict):
        return None, []
    template_path = conf.get("MOMO_CONVERTER_TEMPLATE") or DEFAULT_TEMPLATE
    if not os.path.isfile(template_path):
        template_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "..", "converter", "momo-base.json")
    try:
        template = load_template(template_path)
    except ConvertError:
        return None, []
    modes = read_momo_modes()
    singbox = conf.get("MOMO_CONVERTER_SING_BOX") or os.environ.get("MOMO_SING_BOX") \
        or ("/usr/bin/sing-box" if os.path.isfile("/usr/bin/sing-box") else None)

    def build(do_migrate):
        """返回 (state, text, notes)：clean=无需改动、ok=有改动、fail=内核拒收。"""
        cand = json.loads(json.dumps(obj))
        notes = migrate_legacy_profile(cand) if do_migrate else []
        notes = notes + repair_profile(cand, template, modes)
        if scaffold_missing(cand, modes):
            return "fail", None, []
        text = json.dumps(cand, ensure_ascii=False, indent=2) + "\n"
        if singbox and external_check(text, singbox):
            return "fail", None, []
        if not notes:
            return "clean", None, []
        return "ok", text, notes

    do_migrate = legacy_required(obj)
    state, text, notes = build(do_migrate)
    if state == "ok":
        return text, notes
    if state == "clean":
        return None, []
    if not do_migrate:
        # 兜底：检测不出旧格式，但内核确实拒收，再试一次完整迁移
        state, text, notes = build(True)
        if state == "ok":
            return text, ["内核校验未通过，已按旧格式迁移"] + notes
    return None, []


def enumerate_srs_names(raw_rules, raw_providers):
    """预扫描：列出本次订阅可能需要下载的全部 (kind, name)，供可达性校验。"""
    names = set()
    providers = raw_providers if isinstance(raw_providers, dict) else {}
    for conf_item in providers.values():
        kind, name = provider_srs_candidate(conf_item)
        if kind and name:
            names.add((kind, name))
    for item in (raw_rules or []):
        text = str(item or "")
        for kind, tag in (("geosite", "GEOSITE"), ("geoip", "GEOIP")):
            for m in re.finditer(r"\b%s\s*,\s*([^,()]+)" % tag, text, re.IGNORECASE):
                name = normalize_srs_name(m.group(1))
                if name:
                    names.add((kind, name))
        for m in re.finditer(r"\bRULE-SET\s*,\s*([^,()]+)", text, re.IGNORECASE):
            kind, name = provider_srs_candidate(providers.get(m.group(1).strip()))
            if kind and name:
                names.add((kind, name))
    return names


def compile_clash_rules(groups, name_map, conf, mirror):
    """把订阅的 rules/rule-providers 编译成可注入的 plan（含可达性校验）。"""
    raw_rules = CLASH_EXTRA.get("rules") or []
    raw_providers = CLASH_EXTRA.get("rule-providers") or {}
    if not isinstance(raw_rules, list) or not raw_rules:
        return None
    names = enumerate_srs_names(raw_rules, raw_providers)
    srs_ok = None
    if names and flag_enabled(conf.get("MOMO_CONVERTER_RULESET_VERIFY"), True):
        urls = [u for u in (srs_url(k, n, mirror) for k, n in sorted(names)) if u]
        if urls:
            srs_ok = srs_reachable(urls, conf)
    rules, defs, final, dropped = convert_clash_rules(
        raw_rules, raw_providers, name_map, mirror, conf, srs_ok=srs_ok)
    unmapped = sorted(p for p in raw_providers
                      if not provider_srs_candidate(raw_providers.get(p))[0]
                      or not provider_srs_candidate(raw_providers.get(p))[1])
    return {"rules": rules, "rule_sets": defs, "final": final,
            "dropped": dropped, "unmapped_providers": unmapped,
            "verified": srs_ok is not None}


def inject_clash_rules(cfg, plan):
    """把编译好的分流规则并入 route：紧跟私网直连之后、模板 CN 直连之前。"""
    if not plan or not cfg:
        return 0
    route = cfg.setdefault("route", {})
    rules = route.get("rules")
    if not isinstance(rules, list):
        rules = []
    if plan["rule_sets"]:
        existing = {rs.get("tag") for rs in route.get("rule_set") or []
                    if isinstance(rs, dict)}
        merged = list(route.get("rule_set") or [])
        for d in plan["rule_sets"]:
            if d["tag"] not in existing:
                merged.append(d)
                existing.add(d["tag"])
        route["rule_set"] = merged
    idx = next((i + 1 for i, r in enumerate(rules)
                if isinstance(r, dict) and r.get("ip_is_private")), len(rules))
    rules[idx:idx] = plan["rules"]
    route["rules"] = rules
    if plan.get("final") and plan["final"] not in (TAG_DIRECT, TAG_BLOCK):
        route["final"] = plan["final"]
        # DNS 走代理时跟随订阅的主分流组，避免只为 detour 保留一个多余的主组
        dns = cfg.get("dns")
        if isinstance(dns, dict):
            for server in dns.get("servers") or []:
                if isinstance(server, dict) and server.get("detour") == TAG_PROXY:
                    server["detour"] = plan["final"]
    return len(plan["rules"])


def collect_target_tags(cfg):
    """收集配置里真正被引用的出站 tag（route.final / 规则目标 / 分组嵌套）。"""
    ref = set()
    if not isinstance(cfg, dict):
        return ref
    route = cfg.get("route") or {}
    if isinstance(route, dict):
        if route.get("final"):
            ref.add(route["final"])
        for rule in (route.get("rules") or []):
            stack = [rule]
            while stack:
                cur = stack.pop()
                if not isinstance(cur, dict):
                    continue
                if cur.get("outbound"):
                    ref.add(cur["outbound"])
                if isinstance(cur.get("rules"), list):
                    stack.extend(cur["rules"])
            if isinstance(rule, dict) and rule.get("rule_set"):
                ref.update(rule["rule_set"])
    dns = cfg.get("dns") or {}
    for server in (dns.get("servers") or []) if isinstance(dns, dict) else []:
        if isinstance(server, dict) and server.get("detour"):
            ref.add(server["detour"])
    for ob in cfg.get("outbounds") or []:
        if not isinstance(ob, dict):
            continue
        for member in ob.get("outbounds") or []:
            if member != ob.get("tag"):
                ref.add(member)
    return ref


def build_group_rules(groups, node_tags, controller, secret, cfg=None):
    """供 momo_groupd.py 消费的分组规则；没有订阅分组时才补主 proxy 组。"""
    ref = collect_target_tags(cfg)
    rules = []
    need_proxy = (TAG_PROXY in ref) or not groups
    if need_proxy:
        rules.append({
            "tag": TAG_PROXY, "type": "select", "url": DEFAULT_TEST_URL,
            "interval": DEFAULT_INTERVAL, "tolerance": 0, "timeout": DEFAULT_TIMEOUT,
            "strategy": "round-robin", "lazy": True, "expected_status": "",
            "members": proxy_selector_members(groups, node_tags), "source": "momo",
            # 主组的 direct 是兼容原有结构自动补的，不能当作故障兜底静默直连
            "allow_builtin_fallback": False,
        })
    keys = ("tag", "type", "url", "interval", "tolerance", "timeout", "strategy",
            "lazy", "expected_status", "members", "source")
    for g in groups:
        # 订阅里没有、配置里也没被引用的 builtin auto 不上报，避免面板多出分组
        if g["tag"] == TAG_AUTO and TAG_AUTO not in ref:
            continue
        rule = {k: g[k] for k in keys}
        # 只有订阅里显式写了 DIRECT / REJECT 的分组，才允许全挂时切到直连/拒绝
        rule["allow_builtin_fallback"] = bool(g.get("explicit_builtin"))
        rules.append(rule)
    return {
        "version": 1,
        "generated": int(time.time()),
        "api": {"controller": controller or "", "secret": secret or ""},
        "proxy_group": TAG_PROXY if need_proxy else "",
        "groups": rules,
        "nodes": list(node_tags),
    }


def validate_config(cfg):
    errors = []
    outbounds = cfg.get("outbounds")
    if not isinstance(outbounds, list) or not outbounds:
        return ["outbounds 为空"]
    tags = []
    for ob in outbounds:
        if not isinstance(ob, dict):
            errors.append("outbound 不是对象")
            continue
        tag = ob.get("tag")
        if not tag:
            errors.append("存在无 tag 的 outbound")
        tags.append(tag)
    if len(tags) != len(set(tags)):
        errors.append("outbound tag 重复")
    tagset = set(tags)
    for ob in outbounds:
        if not isinstance(ob, dict):
            continue
        members = ob.get("outbounds", []) or []
        if ob.get("type") == "urltest":
            errors.append("分组 %s 使用了内核自动模式 urltest（应由 momo 按订阅规则驱动）"
                          % ob.get("tag"))
        for ref in members:
            if isinstance(ref, str) and ref not in tagset:
                errors.append("分组 %s 引用了不存在的 outbound: %s" % (ob.get("tag"), ref))
            if ref == ob.get("tag"):
                errors.append("分组 %s 自引用" % ob.get("tag"))
        if ob.get("type") == "selector":
            if ob.get("tag") not in RESERVED_TAGS and TAG_PROXY in members:
                errors.append("分组 %s 引用主 proxy 会形成环" % ob.get("tag"))
            if ob.get("default") and ob["default"] not in members:
                errors.append("分组 %s 的 default 不在成员中" % ob.get("tag"))
    final = cfg.get("route", {}).get("final")
    if final not in tagset:
        errors.append("route.final 指向不存在的 outbound: %s" % final)
    dns_tags = {s.get("tag") for s in cfg.get("dns", {}).get("servers", []) if isinstance(s, dict)}
    if cfg.get("dns", {}).get("final") not in dns_tags:
        errors.append("dns.final 指向不存在的 DNS server")
    inbound_tags = {i.get("tag") for i in cfg.get("inbounds", []) if isinstance(i, dict)}
    missing = MOMO_INBOUND_TAGS - inbound_tags
    if missing:
        errors.append("缺少 momo 必需的 inbound: %s" % ", ".join(sorted(missing)))
    if MOMO_FAKEIP_TAG not in dns_tags:
        errors.append("缺少 momo 必需的 fakeip DNS server: %s" % MOMO_FAKEIP_TAG)
    return errors


def isolate_invalid_nodes(template, nodes, singbox_bin):
    """逐节点用 sing-box check 探测，隔离会让整份配置失效的单节点。

    订阅里经常夹带内核不支持的协议版本或非法 REALITY 公钥；上游在
    config_validator 里是整份配置一起校验、失败即整单导入失败。这里改为
    "坏节点隔离"，保证最终配置一定可应用（config_validator 语义的增强）。
    """
    valid, dropped = [], []
    deadline = time.time() + 15  # 单次启动的隔离总预算，避免大订阅拖慢开机
    for idx, node in enumerate(nodes):
        if idx >= 60 or time.time() > deadline:
            # 预算耗尽时保留剩余节点，交由最终整份 sing-box check 兜底；
            # 绝不因为探测预算而丢掉订阅里的正常节点
            valid.append(node)
            continue
        # 探针配置不带规则集定义（template 里 geosite-cn/geoip-cn 的规则会悬空），
        # 必须先清理悬空引用，否则每次探测都会因 rule_set 未定义而失败，
        # 导致「全部节点均未通过」的假阴性。
        probe = build_config([node], template)
        prune_missing_rule_sets(probe)
        detail = external_check(json.dumps(probe, ensure_ascii=False), singbox_bin)
        if detail:
            dropped.append("%s: %s" % (node.get("tag"), detail))
        else:
            valid.append(node)
    return valid, dropped


def external_check(cfg_text, singbox_bin):
    if not singbox_bin or not os.path.isfile(singbox_bin):
        return None
    fd, tmp = tempfile.mkstemp(prefix="momo-convert-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(cfg_text)
        proc = subprocess.run([singbox_bin, "check", "-c", tmp],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8)
        if proc.returncode == 0:
            return None
        detail = (proc.stderr or proc.stdout).decode("utf-8", "replace").strip()
        detail = re.sub(r"\x1b\[[0-9;]*m", "", detail)
        return detail[:600] or "sing-box check 返回 %d" % proc.returncode
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "sing-box check 无法执行: %s" % exc
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def load_conf(path):
    conf = {
        "MOMO_CONVERTER_ENABLED": "auto",
        "MOMO_CONVERTER_VALIDATE": "1",
        "MOMO_CONVERTER_SING_BOX": "",
        "MOMO_CONVERTER_CLASH_API": "0.0.0.0:15425",
        "MOMO_GROUPD_ENABLED": "1",
        "MOMO_GROUPD_RULES": "/var/run/momo/groups.json",
        "MOMO_GROUPD_STATE": "/var/run/momo/group_state.json",
        "MOMO_GROUPD_PID": "/var/run/momo/groupd.pid",
        "MOMO_GROUPD_TICK": "2",
        "MOMO_GROUPD_HEALTH_INTERVAL": "15",
        # 远程规则集镜像测速选源（转换订阅时自动执行）
        "MOMO_CONVERTER_RULESET": "1",
        "MOMO_CONVERTER_RULESET_MIN_SPEED": str(DEFAULT_MIN_SPEED),
        "MOMO_CONVERTER_RULESET_TIMEOUT": str(DEFAULT_PROBE_TIMEOUT),
        "MOMO_CONVERTER_RULESET_CURL": "curl",
        "MOMO_CONVERTER_RULESET_INJECT": "1",
        "MOMO_CONVERTER_RULESET_FORCE": "0",
        "MOMO_CONVERTER_RULESET_CACHE": "/etc/momo/converter/ruleset_mirror.cache",
        "MOMO_CONVERTER_RULESET_CACHE_TTL": "3600",
        # proxy-providers：Mihomo 模板从远程订阅拉取节点（并行下载 + 持久缓存）
        # 原生 sing-box 订阅缺少 momo 必需 inbound/fakeip DNS 时自动补齐
        "MOMO_CONVERTER_REPAIR": "1",
        "MOMO_CONVERTER_PROVIDERS": "1",
        "MOMO_CONVERTER_PROVIDER_TIMEOUT": "12",
        "MOMO_CONVERTER_PROVIDER_TTL": "21600",
        "MOMO_CONVERTER_PROVIDER_CACHE": "/etc/momo/converter/providers",
        "MOMO_CONVERTER_PROVIDER_MAX": "16",
        "MOMO_CONVERTER_PROVIDER_CURL": "curl",
    }
    if path and os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    conf[key.strip()] = value.strip().strip("\"'")
        except OSError:
            pass
    for key in list(conf):
        if key in os.environ:
            conf[key] = os.environ[key]
    return conf


def load_template(path):
    if not path or not os.path.isfile(path):
        raise ConvertError("找不到模板文件: %s" % path, 4)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as exc:
        raise ConvertError("读取模板失败: %s" % exc, 4)


def atomic_write(path, text):
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    try:
        os.chmod(directory, 0o755)
    except OSError:
        pass
    fd, tmp = tempfile.mkstemp(prefix=".momo-convert-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        # mkstemp 默认 0600：LuCI/rpcd 会读不到、写不回配置，显式放成 0644
        try:
            os.chmod(tmp, 0o644)
        except OSError:
            pass
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def plugin_check(template_path, script_dir):
    import importlib
    required = ["json", "base64", "binascii", "ipaddress", "argparse", "re",
                "subprocess", "tempfile", "time"]
    missing = []
    for name in required:
        try:
            importlib.import_module(name)
        except ImportError:
            missing.append(name)
    info = {
        "plugin": "momo-subscription-converter",
        "version": VERSION,
        "python": sys.version.split()[0],
        "script": os.path.abspath(__file__),
        "template": template_path,
        "template_ok": os.path.isfile(template_path),
        "protocols": sorted(URI_SCHEMES),
        "group_types": sorted(set(GROUP_TYPES.values())),
        "group_driver": "momo_groupd.py (Clash API, 非内核 urltest)",
        "ruleset_mirrors": [m["name"] for m in RULESET_MIRRORS],
        "ruleset_probe": "curl -r 0-81919, %ds 上限, %dKB/s 阈值, 保底 %s" %
                         (DEFAULT_PROBE_TIMEOUT, DEFAULT_MIN_SPEED, DEFAULT_MIRROR),
        "missing_stdlib": missing,
        "ready": False,
    }
    try:
        load_template(template_path)
        info["ready"] = not missing
        if missing:
            info["error"] = "缺少 Python 标准库模块（OpenWrt 需安装 python3-light）: %s" % ",".join(missing)
    except ConvertError as exc:
        info["error"] = str(exc)
    print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0 if info["ready"] else 4


def emit_safe_mode(args, template_path, conf, fmt, skipped, resolver_tag):
    """降级出口：写一份「全局直连」的合法配置，让 momo 照常起来，返回 0。

    返回值必须是 0：convert.sh 把非 0 当「保留原文件」，而原文件是 YAML，
    内核一定 Check failed 退出，断的就是整网了。
    """
    reasons = ["未提取到可用节点（跳过 %d 项）" % len(skipped)]
    prov = dict(PROVIDER_REPORT)
    if prov:
        reasons.append("providers 共 %s 个：可用 %s / 失败 %s / 抓到节点 %s"
                       % (prov.get("total"), prov.get("ok"),
                          prov.get("failed"), prov.get("nodes")))
    try:
        template = load_template(template_path)
    except ConvertError as exc:
        print("momo-convert: %s" % exc, file=sys.stderr)
        return 2

    controller = conf.get("MOMO_CONVERTER_CLASH_API") or "0.0.0.0:15425"
    clash_cfg = template.get("experimental", {}).get("clash_api", {})
    if isinstance(clash_cfg, dict):
        controller = str(clash_cfg.get("external_controller") or controller)

    cfg = build_safe_mode_config(template, controller)
    try:
        repair_profile(cfg, template)
    except Exception as exc:
        print("momo-convert: 安全模式骨架补齐跳过: %s" % exc, file=sys.stderr)
    # 骨架补齐会把 fake-ip DNS 和 fake-ip 解析规则加回来，这里再清洗一次
    sanitize_direct_only(cfg)
    errors = validate_config(cfg)
    if errors:
        print("momo-convert: 安全模式配置校验失败: %s" % "; ".join(errors), file=sys.stderr)
        return 2

    text = json.dumps(cfg, ensure_ascii=False, indent=2) + "\n"
    singbox = conf.get("MOMO_CONVERTER_SING_BOX") or os.environ.get("MOMO_SING_BOX") \
        or ("/usr/bin/sing-box" if os.path.isfile("/usr/bin/sing-box") else None)
    if singbox:
        detail = external_check(text, singbox)
        if detail:
            print("momo-convert: 安全模式配置未通过 sing-box check: %s" % detail,
                  file=sys.stderr)
            return 2

    report = {"status": "degraded", "format": fmt, "nodes": 0,
              "skipped": skipped, "reasons": reasons,
              "clash_api": controller, "providers": dict(PROVIDER_REPORT)}
    if args.dry_run or not (args.in_place or args.output):
        sys.stdout.write(text)
        print(json.dumps(report, ensure_ascii=False))
        return 0
    target = args.input if args.in_place else args.output
    atomic_write(target, text)
    report["output"] = target
    if args.groups_out:
        # 别让守护进程拿着上一份订阅的分组规则在安全模式下乱切
        try:
            os.unlink(args.groups_out)
        except OSError:
            pass
    print(json.dumps(report, ensure_ascii=False))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="momo 订阅/节点/YAML -> sing-box 配置转换")
    ap.add_argument("--input", "-i", help="输入文件（默认 - 表示 stdin）")
    ap.add_argument("--output", "-o", help="输出文件；不指定且未用 --in-place 时输出到 stdout")
    ap.add_argument("--in-place", action="store_true", help="原子替换输入文件")
    ap.add_argument("--template", help="momo 基础配置模板")
    ap.add_argument("--conf", help="插件配置文件")
    ap.add_argument("--check", action="store_true", help="自检插件是否可正常加载")
    ap.add_argument("--dry-run", action="store_true", help="只输出转换结果，不写盘")
    ap.add_argument("--groups-out", help="写出分组驱动规则文件（供 momo_groupd.py 使用）")
    args = ap.parse_args(argv)

    conf = load_conf(args.conf or DEFAULT_CONF)
    template_path = args.template or os.environ.get("MOMO_CONVERTER_TEMPLATE") or DEFAULT_TEMPLATE
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if not os.path.isfile(template_path):
        template_path = os.path.join(script_dir, "momo-base.json")

    if args.check:
        return plugin_check(template_path, script_dir)

    enabled = conf.get("MOMO_CONVERTER_ENABLED", "auto").lower()
    if enabled in ("0", "off", "false", "no"):
        print(json.dumps({"status": "disabled"}, ensure_ascii=False))
        return 0
    if not args.input or args.input == "-":
        raw = sys.stdin.buffer.read()
    else:
        if not os.path.isfile(args.input):
            print("输入文件不存在: %s" % args.input, file=sys.stderr)
            return 2
        with open(args.input, "rb") as f:
            raw = f.read()

    global PROVIDER_REPORT, CLASH_EXTRA
    PROVIDER_REPORT = {}
    CLASH_EXTRA = {"rules": [], "rule-providers": {}}
    try:
        nodes, fmt, raw_groups = extract_nodes(raw, conf)
    except ConvertError as exc:
        print("momo-convert: %s" % exc, file=sys.stderr)
        return exc.code

    # 原生 sing-box 配置：内容完整时逐字节透传；缺少 momo 必需骨架时才补齐
    if fmt == "native":
        # 不残留上一份订阅的分组规则，避免守护进程在原生配置下误启动
        if args.groups_out and os.path.isfile(args.groups_out):
            try:
                os.unlink(args.groups_out)
            except OSError:
                pass
        repaired_text, repair_notes = (None, [])
        if flag_enabled(conf.get("MOMO_CONVERTER_REPAIR"), True):
            repaired_text, repair_notes = repair_native_profile(raw, conf)
        if repaired_text is None:
            if args.output and args.output != args.input:
                with open(args.output, "wb") as f:
                    f.write(raw)
                try:
                    os.chmod(args.output, 0o644)
                except OSError:
                    pass
            print(json.dumps({"status": "passthrough", "format": fmt}, ensure_ascii=False))
            return 0
        report = {"status": "repaired", "format": fmt, "repairs": repair_notes}
        if args.dry_run or not (args.in_place or args.output):
            report["output"] = ""
            sys.stdout.write(repaired_text)
            print(json.dumps(report, ensure_ascii=False))
            return 0
        target = args.input if args.in_place else args.output
        atomic_write(target, repaired_text)
        report["output"] = target
        print(json.dumps(report, ensure_ascii=False))
        return 0

    template = load_template(template_path)
    resolver_tag = "dns_resolver"
    for srv in template.get("dns", {}).get("servers", []):
        if isinstance(srv, dict) and srv.get("type") in ("udp", "tcp", "local") \
                and not srv.get("detour") and srv.get("tag"):
            resolver_tag = srv["tag"]
            break
    tag_map = {}
    nodes, skipped = normalize_nodes(nodes, resolver_tag, tag_map, conf)
    # 格式层的跳过原因（不支持的链接 / 内核已移除的协议）排在最前面，
    # 用户一眼能看到「为什么这个订阅少了几个节点」。
    format_skips = list(EXTRACT_SKIPS)
    if format_skips:
        skipped = format_skips + skipped
    if not nodes:
        return emit_safe_mode(args, template_path, conf, fmt, skipped, resolver_tag)

    node_tags = [n["tag"] for n in nodes]
    groups, name_map = assign_group_tags(raw_groups, node_tags)
    groups = resolve_group_members(groups, name_map, tag_map, node_tags)
    cycle_drops = drop_group_cycles(groups)
    # 订阅自带分组时不再凭空塞 builtin auto（面板会多出一组）；
    # 只有完全没有分组、或有分组/规则引用了 auto 时才需要它兜底。
    has_auto = any(g["tag"] == TAG_AUTO for g in groups)
    needs_auto = not groups or any(TAG_AUTO in (g.get("members") or []) for g in groups)
    if needs_auto and not has_auto:
        groups.insert(0, make_default_auto_group(node_tags))

    controller = conf.get("MOMO_CONVERTER_CLASH_API") or "0.0.0.0:15425"
    clash_cfg = template.get("experimental", {}).get("clash_api", {})
    if not isinstance(clash_cfg, dict):
        clash_cfg = {}
    controller = str(clash_cfg.get("external_controller") or controller)
    secret = str(clash_cfg.get("secret") or "")

    singbox = None
    if conf.get("MOMO_CONVERTER_VALIDATE", "1").lower() not in ("0", "off", "false", "no"):
        singbox = conf.get("MOMO_CONVERTER_SING_BOX") or os.environ.get("MOMO_SING_BOX") \
            or ("/usr/bin/sing-box" if os.path.isfile("/usr/bin/sing-box") else None)

    # 4 镜像真实下载测速 -> 选源 -> 把 geosite/geoip 的 URL 写进 profile
    # 任何意外（curl 缺失、文件系统异常、异常模板）都只跳过选源，绝不阻断转换
    try:
        ruleset_state = prepare_ruleset(conf)
    except Exception as exc:
        print("momo-convert: 规则集镜像选源跳过: %s" % exc, file=sys.stderr)
        ruleset_state = prepare_ruleset({"MOMO_CONVERTER_RULESET": "0"})
        ruleset_state["decision"] = "error"

    # 订阅自带的分流规则（任意来源，能转就转，转不了就降级）
    clash_plan = None
    try:
        clash_plan = compile_clash_rules(groups, name_map, conf,
                                         ruleset_state.get("_mirror")
                                         or RULESET_MIRRORS[0])
    except Exception as exc:
        print("momo-convert: 订阅分流规则转换跳过: %s" % exc, file=sys.stderr)

    for g in groups:
        if g.get("filter_miss"):
            print("momo-convert: 分组 %s 的 filter=%s 未命中任何节点，已回退为全部节点"
                  % (g["tag"], g["filter_miss"]), file=sys.stderr)

    cfg = build_config(nodes, template, groups, controller)
    repair_notes = repair_profile(cfg, template)
    inject_clash_rules(cfg, clash_plan)
    if strip_block_outbound(cfg):
        repair_notes.append("block 出站改为 action reject（避免 UDP 监听报错）")
    errors = validate_config(cfg)
    if errors:
        print("momo-convert: 生成配置校验失败: %s" % "; ".join(errors), file=sys.stderr)
        return 3
    try:
        apply_ruleset(cfg, ruleset_state)
    except Exception as exc:
        print("momo-convert: 规则集镜像写入跳过: %s" % exc, file=sys.stderr)
        prune_missing_rule_sets(cfg)  # 兜底：避免规则引用悬空导致 check 失败
    text = json.dumps(cfg, ensure_ascii=False, indent=2) + "\n"

    if singbox:
        detail = external_check(text, singbox)
        if detail:
            valid, dropped = isolate_invalid_nodes(template, nodes, singbox)
            if not valid:
                print("momo-convert: 全部节点均未通过 sing-box check，保留原文件: %s"
                      % detail, file=sys.stderr)
                return 3
            skipped.extend(dropped)
            nodes = valid
            groups = prune_group_members(groups, [n["tag"] for n in nodes])
            cfg = build_config(nodes, template, groups, controller)
            repair_profile(cfg, template)
            inject_clash_rules(cfg, clash_plan)
            errors = validate_config(cfg)
            if errors:
                print("momo-convert: 隔离后配置校验失败: %s" % "; ".join(errors), file=sys.stderr)
                return 3
            try:
                apply_ruleset(cfg, ruleset_state)  # 复用同一轮测速结果，不重复探测
            except Exception as exc:
                print("momo-convert: 规则集镜像写入跳过: %s" % exc, file=sys.stderr)
            text = json.dumps(cfg, ensure_ascii=False, indent=2) + "\n"
            detail = external_check(text, singbox)
            if detail:
                print("momo-convert: sing-box check 未通过，保留原文件: %s" % detail,
                      file=sys.stderr)
                return 3

    final_tags = [n["tag"] for n in nodes]
    rules = build_group_rules(groups, final_tags, controller, secret, cfg)
    report = {
        "status": "converted", "format": fmt, "nodes": len(nodes),
        "skipped": skipped, "outbounds": len(cfg["outbounds"]),
        "format_skips": format_skips,
        "tags": final_tags,
        "groups": [g["tag"] for g in groups],
        "group_types": dict((g["tag"], g["type"]) for g in groups),
        "cycle_drops": cycle_drops,
        "clash_api": controller,
        "ruleset": ruleset_report(ruleset_state),
        "filter_misses": [{"group": g["tag"], "filter": g["filter_miss"]}
                          for g in groups if g.get("filter_miss")],
        "clash_rules": {
            "source_rules": len(CLASH_EXTRA.get("rules") or []),
            "applied": len((clash_plan or {}).get("rules") or []),
            "rule_sets": [d["tag"] for d in (clash_plan or {}).get("rule_sets") or []],
            "final": (clash_plan or {}).get("final") or "",
            "verified": bool((clash_plan or {}).get("verified")),
            "unmapped_providers": list((clash_plan or {}).get("unmapped_providers") or [])[:12],
            "dropped": list((clash_plan or {}).get("dropped") or [])[:12],
        },
        "providers": dict(PROVIDER_REPORT),
        "repairs": repair_notes,
    }
    if args.dry_run:
        report["config"] = cfg
        report["group_rules"] = rules
        print(json.dumps(report, ensure_ascii=False))
        return 0
    if args.in_place:
        target = args.input
    elif args.output:
        target = args.output
    else:
        sys.stdout.write(text)
        return 0
    atomic_write(target, text)
    report["output"] = target
    if args.groups_out:
        try:
            atomic_write(args.groups_out,
                         json.dumps(rules, ensure_ascii=False, indent=2) + "\n")
            report["groups_out"] = args.groups_out
        except OSError as exc:
            report["groups_out_error"] = str(exc)
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ConvertError as exc:
        print("momo-convert: %s" % exc, file=sys.stderr)
        sys.exit(exc.code)
    except KeyboardInterrupt:
        sys.exit(130)
