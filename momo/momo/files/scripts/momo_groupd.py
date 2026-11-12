#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""momo 代理节点分组驱动（Clash/Mihomo 规则，不使用 sing-box 内核自动模式）。

转换器把 url-test / fallback / load-balance / select 全部生成为 selector 出站并写出
groups.json；本进程按订阅里的测速地址、间隔、容差、成员顺序，通过 Clash API
自己测速并 PUT 切换 selector，从而完全由 momo 侧驱动分组：

  url-test       取延迟最低的可用成员；仅当「候选延迟 + tolerance < 当前延迟」才抢占
  fallback       按 proxies 顺序取第一个可用成员，高优先级成员恢复即切回
  load-balance   round-robin 按间隔轮换；consistent-hashing / sticky-sessions 保持粘性
  select / 主组  手动优先：手动选中的成员只要可用就一直保留

 members 仍可随时在面板手动选择：本进程检测到 now 被外部改动即记为 manual；
 manual 可用则一直保留，一旦不可用立即切到可用成员，恢复可用后自动切回。

只依赖 Python 标准库 + curl（momo 已强制依赖 +curl），不引入 python3-urllib / PyYAML
等 OpenWrt 独立分包。任何 API 失败都只重试，绝不改动 momo 原有运行链路。

用法：
  momo_groupd.py --rules FILE [--profile FILE] [--state FILE] [--api HOST:PORT]
  momo_groupd.py --check ...
  momo_groupd.py --once --rounds N --force-full        # 自测/调试
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

VERSION = "1.1.0"
DEFAULT_RULES = "/var/run/momo/groups.json"
DEFAULT_STATE = "/var/run/momo/group_state.json"
DEFAULT_LOG = "/var/log/momo/app.log"
DEFAULT_TEST_URL = "http://cp.cloudflare.com/generate_204"
DEFAULT_INTERVAL = 300
DEFAULT_TIMEOUT = 5000
BUILTIN_FALLBACK = {"direct", "block"}


class GroupError(Exception):
    pass


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------
def log_line(path, message):
    if not path:
        return
    try:
        directory = os.path.dirname(os.path.abspath(path))
        if not os.path.isdir(directory):
            return
        with open(path, "a", encoding="utf-8") as f:
            f.write("[%s] [Group] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), message))
    except OSError:
        pass


def atomic_write(path, text):
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    try:
        os.chmod(directory, 0o755)
    except OSError:
        pass
    fd, tmp = tempfile.mkstemp(prefix=".momo-groupd-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        # mkstemp 默认 0600：显式放成 0644，避免 rpcd/LuCI 读写被拒
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


def load_json(path, default=None):
    if not path or not os.path.isfile(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def load_conf(path):
    conf = {
        "MOMO_GROUPD_ENABLED": "1",
        "MOMO_GROUPD_RULES": DEFAULT_RULES,
        "MOMO_GROUPD_STATE": DEFAULT_STATE,
        "MOMO_GROUPD_TICK": "2",
        "MOMO_GROUPD_HEALTH_INTERVAL": "15",
    }
    if path and os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, value = line.partition("=")
                        conf[key.strip()] = value.strip().strip("\"'")
        except OSError:
            pass
    for key in list(conf):
        if key in os.environ:
            conf[key] = os.environ[key]
    return conf


def int_opt(value, default, low, high):
    try:
        n = int(str(value).strip())
    except (ValueError, TypeError, AttributeError):
        return default
    return max(low, min(high, n))


def path_quote(value):
    """RFC3986 path 段编码；中文分组名走 UTF-8 百分号编码，不依赖 urllib。"""
    out = []
    for byte in str(value).encode("utf-8"):
        ch = chr(byte)
        if ("A" <= ch <= "Z") or ("a" <= ch <= "z") or ("0" <= ch <= "9") \
                or ch in "-._~":
            out.append(ch)
        else:
            out.append("%%%02X" % byte)
    return "".join(out)


def normalize_controller(value):
    c = str(value or "").strip().rstrip("/")
    if not c:
        return ""
    if c.startswith("http://") or c.startswith("https://"):
        return c
    if c.startswith(":"):
        c = "127.0.0.1" + c
    host, sep, port = c.rpartition(":")
    if not sep or not port.isdigit():
        host, port = c, "15425"
    if host in ("", "0.0.0.0", "::", "[::]", "::1"):
        host = "127.0.0.1"
    if ":" in host and not host.startswith("["):
        host = "[%s]" % host
    return "http://%s:%s" % (host, port)


def resolve_api(rules, profile_path, override):
    api = rules.get("api") if isinstance(rules.get("api"), dict) else {}
    controller = str(api.get("controller") or "")
    secret = str(api.get("secret") or "")
    if profile_path and os.path.isfile(profile_path):
        cfg = load_json(profile_path, {})
        ca = cfg.get("experimental", {}).get("clash_api", {}) if isinstance(cfg, dict) else {}
        if isinstance(ca, dict):
            if ca.get("external_controller"):
                controller = str(ca["external_controller"])
            if ca.get("secret"):
                secret = str(ca["secret"])
    if override:
        controller = override
    return normalize_controller(controller), secret


# --------------------------------------------------------------------------
# Clash API 客户端（curl；避免 OpenWrt 上 python3-urllib / http 分包依赖）
# --------------------------------------------------------------------------
class ClashAPI:
    def __init__(self, controller, secret="", curl=None):
        self.base = controller
        self.secret = secret or ""
        self.curl = curl or shutil.which("curl") or "curl"

    def _request(self, method, path, query=None, payload=None, timeout=10):
        if not self.base:
            return 0, None
        tmp = None
        cmd = [self.curl, "-sS", "-m", str(max(1, int(timeout))),
               "-w", "\n__MOMO_HTTP__%{http_code}"]
        if self.secret:
            cmd += ["-H", "Authorization: Bearer " + self.secret]
        if method == "GET":
            cmd.append("-G")
        else:
            cmd += ["-X", method]
        for key, value in (query or {}).items():
            cmd += ["--data-urlencode", "%s=%s" % (key, value)]
        if payload is not None:
            fd, tmp = tempfile.mkstemp(prefix="momo-groupd-", suffix=".json")
            with os.fdopen(fd, "w", encoding="ascii") as f:
                # ensure_ascii -> 中文 tag 走 \uXXXX，跨 Windows/Linux 命令行均不乱码
                f.write(json.dumps(payload, ensure_ascii=True))
            cmd += ["-H", "Content-Type: application/json", "--data-binary", "@" + tmp]
        cmd.append(self.base + path)
        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  timeout=max(2, int(timeout) + 4))
            text = proc.stdout.decode("utf-8", "replace")
            body, marker, code = text.rpartition("\n__MOMO_HTTP__")
            if not marker:
                return 0, None
            try:
                status = int(code.strip())
            except ValueError:
                return 0, None
            try:
                data = json.loads(body) if body.strip() else None
            except ValueError:
                data = None
            return status, data
        except (OSError, subprocess.TimeoutExpired):
            return 0, None
        finally:
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    def proxies(self):
        code, data = self._request("GET", "/proxies", timeout=8)
        if code == 200 and isinstance(data, dict) and isinstance(data.get("proxies"), dict):
            return data["proxies"]
        return None

    def group_delay(self, tag, url, timeout_ms):
        code, data = self._request(
            "GET", "/group/%s/delay" % path_quote(tag),
            {"url": url, "timeout": str(timeout_ms)},
            timeout=int(timeout_ms) / 1000.0 + 6)
        if code == 200 and isinstance(data, dict):
            return dict((k, int(v)) for k, v in data.items()
                        if isinstance(v, (int, float)) and not isinstance(v, bool))
        return {}

    def node_delay(self, tag, url, timeout_ms):
        if not tag:
            return None
        code, data = self._request(
            "GET", "/proxies/%s/delay" % path_quote(tag),
            {"url": url, "timeout": str(timeout_ms)},
            timeout=int(timeout_ms) / 1000.0 + 6)
        if code == 200 and isinstance(data, dict) and isinstance(data.get("delay"), (int, float)):
            return int(data["delay"])
        return None

    def select(self, tag, name):
        code, _ = self._request("PUT", "/proxies/%s" % path_quote(tag),
                                payload={"name": name}, timeout=8)
        return code in (200, 204)


# --------------------------------------------------------------------------
# 分组决策（mihomo 规则语义）
# --------------------------------------------------------------------------
def available_pool(members, delays, allow_builtin=False):
    """按订阅顺序取可用成员；自动切换优先真实代理节点。

    只有订阅里显式写了 DIRECT/REJECT 的分组（allow_builtin_fallback）才允许在
    全部代理节点不可用时切到直连；否则保持现状，绝不静默绕过代理。
    """
    available = [m for m in members if m in delays]
    proxies = [m for m in available if m not in BUILTIN_FALLBACK]
    if proxies:
        return proxies
    return available if allow_builtin else []


def pick(g, delays, now, st, full_round=False):
    members = g.get("members") or []
    typ = g.get("type") or "select"
    tolerance = int_opt(g.get("tolerance"), 0, 0, 60000)
    manual = st.get("manual")
    pool = available_pool(members, delays,
                          bool(g.get("allow_builtin_fallback")))
    now_ok = now in delays

    # 手动选择优先：只要能用就一直保留（故障切走后恢复可用会自动切回）
    if manual and manual in delays and manual in members:
        return manual

    if typ == "fallback":
        return pool[0] if pool else (now if now_ok else None)

    if typ == "url-test":
        if not pool:
            return None
        best = min(pool, key=lambda m: (delays[m], members.index(m)))
        if not now_ok:
            return best
        if manual:
            return now  # 手动偏好暂不可用，保持当前可用节点，不做延迟抢占
        if best != now and delays[best] + tolerance < delays[now]:
            return best
        return now

    if typ == "load-balance":
        if not pool:
            return None
        if not now_ok:
            return pool[0]
        strategy = g.get("strategy") or "round-robin"
        if strategy == "round-robin" and full_round:
            idx = int(st.get("rr") or 0)
            nxt = pool[(idx + 1) % len(pool)]
            st["rr"] = (idx + 1) % len(pool)
            return nxt
        return now  # consistent-hashing / sticky-sessions：保持粘性，故障才切换

    # select / 主 proxy 组：保持转换时写入的默认（订阅里的第一个成员），不被延迟抢占。
    # 只有在「默认项完全不可用、且订阅显式给了 direct/block 兜底」时才切兜底项，
    # 其余情况一律不动 —— 否则用户每次重启都会发现分组被自动改成了别的节点。
    if now_ok:
        return now
    if manual:
        return None                      # 有手动偏好但暂不可用：保持现状等它恢复
    if g.get("allow_builtin_fallback") and pool \
            and not any(m not in BUILTIN_FALLBACK for m in pool):
        return pool[0]                   # 全是兜底项：切 direct/reject，别静默断网
    return None


# --------------------------------------------------------------------------
# 驱动
# --------------------------------------------------------------------------
class Driver:
    def __init__(self, rules, api, state_path, log_path, health_interval):
        if not isinstance(rules, dict) or not isinstance(rules.get("groups"), list):
            raise GroupError("分组规则文件格式不正确")
        self.rules = rules
        self.api = api
        self.state_path = state_path
        self.log_path = log_path
        self.health_interval = health_interval
        self.groups = [g for g in rules["groups"] if isinstance(g, dict) and g.get("members")]
        state = load_json(state_path, {})
        if not isinstance(state, dict):
            state = {}
        if not isinstance(state.get("groups"), dict):
            state["groups"] = {}
        self.state = state
        self._last_log = {}

    def log(self, message, key=None, min_gap=0):
        if key:
            last = self._last_log.get(key, 0)
            if time.time() - last < min_gap:
                return
            self._last_log[key] = time.time()
        log_line(self.log_path, message)

    def save_state(self):
        try:
            atomic_write(self.state_path,
                         json.dumps(self.state, ensure_ascii=False, indent=2) + "\n")
        except OSError as exc:
            self.log("状态写入失败: %s" % exc, "state", 120)

    def tick(self, now_ts=None, force_full=False):
        now_ts = time.time() if now_ts is None else now_ts
        proxies = self.api.proxies()
        if proxies is None:
            self.log("Clash API 不可达或未配置，跳过本轮（不影响 momo 运行）", "api", 120)
            return 0
        changed = 0
        for g in self.groups:
            try:
                changed += self.process(g, proxies, now_ts, force_full)
            except Exception as exc:  # 单个分组异常不能拖垮整个守护进程
                self.log("分组 %s 处理异常: %s" % (g.get("tag"), exc),
                         "err-" + str(g.get("tag")), 60)
        if changed:
            self.save_state()
        return changed

    def process(self, g, proxies, now_ts, force_full):
        tag = g.get("tag")
        info = proxies.get(tag)
        if not isinstance(info, dict):
            return 0
        now = info.get("now")
        members = g.get("members") or []
        st = self.state["groups"].setdefault(tag, {
            "manual": None, "last_set": None, "next_full": 0,
            "next_health": 0, "rr": 0, "delays": {},
        })
        # 外部（面板手动选择）改动 now -> 记为手动偏好；本进程自己切换时会同步 last_set
        if st.get("last_set") and now and now != st["last_set"] and now in members:
            st["manual"] = now
            self.log("分组 %s 检测到手动选择 -> %s" % (tag, now))
        st["last_set"] = now

        interval = int_opt(g.get("interval"), DEFAULT_INTERVAL, 5, 86400)
        health_gap = min(interval, self.health_interval) if self.health_interval > 0 else 0
        url = g.get("url") or DEFAULT_TEST_URL
        timeout = int_opt(g.get("timeout"), DEFAULT_TIMEOUT, 100, 60000)
        changed = 0
        do_full = bool(force_full) or now_ts >= int(st.get("next_full") or 0)
        do_health = bool(health_gap) and now_ts >= int(st.get("next_health") or 0)

        if do_full:
            delays = self.api.group_delay(tag, url, timeout)
            if not delays:
                self.log("分组 %s 测速无可用节点，保持当前选择" % tag,
                         "no-node-" + str(tag), 300)
            st["delays"] = delays
            st["next_full"] = now_ts + interval
            st["next_health"] = now_ts + (health_gap or interval)
            target = pick(g, delays, now, st, full_round=True)
            if target and target != now and self.api.select(tag, target):
                st["last_set"] = target
                self.log("分组 %s(%s) 按订阅规则选择 -> %s" % (tag, g.get("type"), target))
                changed = 1
            return changed

        if do_health:
            st["next_health"] = now_ts + health_gap
            ok = self.api.node_delay(now, url, timeout)
            if ok is None and (g.get("type") or "select") == "select" \
                    and not g.get("allow_builtin_fallback"):
                # 分流选择组：默认选中第一个是订阅本意，即使测不到延迟也不自动改，
                # 否则用户每次重启都会发现分组被切到了别的节点。
                # 例外：订阅里显式给了 direct/block 兜底的组（allow_builtin_fallback），
                # 那种组的语义就是「全挂了好歹还有直连」，必须走下面的兜底切换。
                self.log("分组 %s 当前节点测速失败，保持默认选择 %s" % (tag, now),
                         "select-unavail-" + str(tag), 300)
            elif ok is None:
                # 当前节点不可用：立即重新测速并切到可用节点，不等下一个 interval
                delays = self.api.group_delay(tag, url, timeout)
                st["delays"] = delays
                st["next_full"] = now_ts + interval
                target = pick(g, delays, now, st, full_round=False)
                if target and target != now and self.api.select(tag, target):
                    st["last_set"] = target
                    self.log("分组 %s 当前节点不可用，立即切换 -> %s" % (tag, target))
                    changed = 1
            else:
                manual = st.get("manual")
                if manual and manual != now \
                        and self.api.node_delay(manual, url, timeout) is not None \
                        and self.api.select(tag, manual):
                    st["last_set"] = manual
                    self.log("分组 %s 手动节点恢复，切回 -> %s" % (tag, manual))
                    changed = 1
        return changed


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="momo 分组驱动（mihomo 规则，非内核自动模式）")
    ap.add_argument("--rules", help="分组规则文件 groups.json")
    ap.add_argument("--profile", help="最终 sing-box 配置（读取 clash_api 地址/密钥）")
    ap.add_argument("--state", help="状态文件")
    ap.add_argument("--conf", help="插件配置文件")
    ap.add_argument("--api", help="覆盖 Clash API 地址 HOST:PORT")
    ap.add_argument("--secret", help="覆盖 Clash API secret")
    ap.add_argument("--log", help="日志文件")
    ap.add_argument("--tick", type=int, help="主循环间隔秒")
    ap.add_argument("--health-interval", type=int, help="当前节点快速健康检查间隔秒")
    ap.add_argument("--check", action="store_true", help="自检并输出 JSON")
    ap.add_argument("--once", action="store_true", help="只执行指定轮数后退出")
    ap.add_argument("--rounds", type=int, default=1, help="--once 模式下的轮数")
    ap.add_argument("--round-delay", type=float, default=0.0, help="轮间隔秒")
    ap.add_argument("--force-full", action="store_true", help="每轮都执行完整测速（自测用）")
    ap.add_argument("--no-initial-full", action="store_true",
                    help="--once 首轮不强制完整测速，便于只验证快速健康检查路径")
    args = ap.parse_args(argv)

    conf = load_conf(args.conf)
    rules_path = args.rules or conf.get("MOMO_GROUPD_RULES") or DEFAULT_RULES
    state_path = args.state or conf.get("MOMO_GROUPD_STATE") or DEFAULT_STATE
    log_path = args.log or os.environ.get("MOMO_GROUPD_LOG") or DEFAULT_LOG
    tick = args.tick if args.tick is not None else int_opt(conf.get("MOMO_GROUPD_TICK"), 2, 1, 60)
    health = args.health_interval if args.health_interval is not None \
        else int_opt(conf.get("MOMO_GROUPD_HEALTH_INTERVAL"), 15, 0, 3600)

    rules = load_json(rules_path)
    if args.check:
        controller, secret = resolve_api(rules or {}, args.profile, args.api)
        api = ClashAPI(controller, secret)
        info = {
            "plugin": "momo-group-driver", "version": VERSION,
            "rules": rules_path, "rules_ok": isinstance(rules, dict),
            "groups": len(rules.get("groups", [])) if isinstance(rules, dict) else 0,
            "group_types": sorted({g.get("type") for g in rules.get("groups", [])})
                           if isinstance(rules, dict) else [],
            "api": controller, "api_reachable": bool(api.proxies() is not None),
            "kernel_auto_mode": False,
            "ready": False,
        }
        info["ready"] = info["rules_ok"] and bool(controller)
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0 if info["ready"] else 1

    if not isinstance(rules, dict):
        print("momo-groupd: 分组规则文件缺失或无效: %s" % rules_path, file=sys.stderr)
        return 2
    controller, secret = resolve_api(rules, args.profile, args.api)
    if args.secret is not None:
        secret = args.secret
    if not controller:
        print("momo-groupd: 未配置 clash_api.external_controller，无法驱动分组", file=sys.stderr)
        return 2
    driver = Driver(rules, ClashAPI(controller, secret), state_path, log_path, health)
    driver.log("分组驱动启动: %d 个分组, api=%s, 健康检查=%ss" %
               (len(driver.groups), controller, health))

    if args.once:
        for i in range(max(1, args.rounds)):
            driver.tick(force_full=args.force_full
                        or (i == 0 and not args.no_initial_full))
            if args.round_delay and i + 1 < args.rounds:
                time.sleep(args.round_delay)
        return 0

    while True:
        try:
            driver.tick()
        except Exception as exc:
            driver.log("主循环异常: %s" % exc, "loop", 60)
        time.sleep(tick)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except GroupError as exc:
        print("momo-groupd: %s" % exc, file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        sys.exit(130)
