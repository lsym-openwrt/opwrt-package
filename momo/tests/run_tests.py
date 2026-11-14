#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""momo 订阅转换集成：端到端自测 + 回归验证。

运行环境：Windows Git Bash / Linux bash + Python 3.8+（仅标准库）。
可选：真实 sing-box 1.14+ 二进制（SING_BOX_BIN 或 /tmp/momo-test/bin/sing-box.exe），
用于 `sing-box check` 校验每一份生成/应用后的配置。

运行： python tests/run_tests.py
输出： 控制台摘要 + tests/results.json
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures"
HARNESS = ROOT / "tests" / "harness"
RESULTS = ROOT / "tests" / "results.json"
SB = Path(tempfile.gettempdir()) / "momo-e2e-sandbox"
SB_WIN = str(SB).replace("\\", "/")


def msys(path):
    p = str(path).replace("\\", "/")
    m = re.match(r"^([A-Za-z]):/(.*)$", p)
    return "/%s/%s" % (m.group(1).lower(), m.group(2)) if m else p


SB_MSYS = msys(SB)
PY = sys.executable
SH = shutil.which("sh") or "sh"


def find_singbox():
    candidates = [
        os.environ.get("SING_BOX_BIN", ""),
        "/tmp/momo-test/bin/sing-box.exe",
        str(Path(tempfile.gettempdir()) / "momo-test/bin/sing-box.exe"),
        str(HARNESS / "sing-box.exe"),
        shutil.which("sing-box") or "",
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return str(Path(c).resolve()).replace("\\", "/")
    return ""


SING_BOX_REAL = find_singbox()


def write(path, content, mode=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    if mode is not None:
        try:
            os.chmod(path, mode)
        except OSError:
            pass


def copy(src, dst):
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    if str(dst).endswith(".sh") or dst.name in ("momo", "sing-box", "ucode", "jsonfilter",
                                                "curl", "utpl", "nft", "ip", "mount",
                                                "lsmod", "sysctl", "uci"):
        try:
            os.chmod(dst, 0o755)
        except OSError:
            pass


def setup_sandbox():
    if SB.exists():
        shutil.rmtree(SB, ignore_errors=True)
    for d in ["etc/momo/scripts", "etc/momo/ucode", "etc/momo/converter",
              "etc/momo/firewall", "etc/momo/profiles", "etc/momo/subscriptions",
              "etc/momo/run", "etc/init.d", "etc/config", "etc/crontabs",
              "usr/bin", "usr/share/libubox", "lib",
              "var/log/momo", "var/run/momo"]:
        (SB / d).mkdir(parents=True, exist_ok=True)

    for f in (ROOT / "momo/files/scripts").glob("*"):
        if f.is_file():
            copy(f, SB / "etc/momo/scripts" / f.name)
    for f in (ROOT / "momo/files/ucode").glob("*"):
        copy(f, SB / "etc/momo/ucode" / f.name)
    for f in (ROOT / "momo/files/converter").glob("*"):
        copy(f, SB / "etc/momo/converter" / f.name)
    for f in (ROOT / "momo/files/firewall").glob("*"):
        copy(f, SB / "etc/momo/firewall" / f.name)
    for f in HARNESS.glob("*.py"):
        copy(f, SB / "usr/bin" / f.name)

    # include.sh：只把三个根路径指向沙箱，其余逻辑逐字保留
    inc = (ROOT / "momo/files/scripts/include.sh").read_text(encoding="utf-8")
    inc = inc.replace('HOME_DIR="/etc/momo"', 'HOME_DIR="%s/etc/momo"' % SB_MSYS)
    inc = inc.replace('LOG_DIR="/var/log/momo"', 'LOG_DIR="%s/var/log/momo"' % SB_MSYS)
    inc = inc.replace('TEMP_DIR="/var/run/momo"', 'TEMP_DIR="%s/var/run/momo"' % SB_MSYS)
    write(SB / "etc/momo/scripts/include.sh", inc)

    # momo.init：只把内核路径与 crontab 路径指向沙箱
    init = (ROOT / "momo/files/momo.init").read_text(encoding="utf-8")
    init = init.replace('PROG="/usr/bin/sing-box"',
                        'PROG="%s/usr/bin/sing-box"' % SB_MSYS)
    init = init.replace('"/etc/crontabs/root"', '"%s/etc/crontabs/root"' % SB_MSYS)
    write(SB / "etc/init.d/momo", init)

    write(SB / "usr/share/libubox/jshn.sh", "# stub\n")
    write(SB / "lib/functions.sh", "# stub\n")
    write(SB / "etc/crontabs/root", "")

    stub = "#!/bin/sh\nexec \"$MOMO_PYTHON\" \"$MOMO_TEST_ROOT/usr/bin/%s\" \"$@\"\n"
    for name, script in [("sing-box", "singbox_stub.py"), ("ucode", "mixin_emulator.py"),
                         ("jsonfilter", "jsonfilter_stub.py"), ("curl", "curl_stub.py")]:
        write(SB / "usr/bin" / name, stub % script, 0o755)

    write(SB / "usr/bin/nft", """#!/bin/sh
case " $* " in *" list tables "*) echo "table inet momo";; esac
case " $* " in *" --json "*) echo '{"nftables":[]}';; esac
case " $* " in *" -f - "*) cat >/dev/null;; esac
exit 0
""", 0o755)
    write(SB / "usr/bin/ip", """#!/bin/sh
case " $* " in *" -j link show "*) echo '[{"flags":["UP"]}]';; esac
exit 0
""", 0o755)
    write(SB / "usr/bin/utpl", '#!/bin/sh\necho "# momo hijack ruleset (stub)"\n', 0o755)
    write(SB / "usr/bin/mount", "#!/bin/sh\nexit 1\n", 0o755)
    write(SB / "usr/bin/lsmod", "#!/bin/sh\nexit 1\n", 0o755)
    write(SB / "usr/bin/sysctl", "#!/bin/sh\necho 0\n", 0o755)
    write(SB / "usr/bin/uci", "#!/bin/sh\nexit 0\n", 0o755)

    write(SB / "procd_stub.sh", """procd_open_instance() { echo "OPEN $*" >> "$MOMO_TEST_ROOT/procd.log"; }
procd_set_param() { echo "SET $*" >> "$MOMO_TEST_ROOT/procd.log"; }
procd_append_param() { echo "APPEND $*" >> "$MOMO_TEST_ROOT/procd.log"; }
procd_close_instance() { echo "CLOSE" >> "$MOMO_TEST_ROOT/procd.log"; }
procd_add_reload_trigger() { :; }
extra_command() { :; }
""")

    write(SB / "run_init.sh", """#!/bin/sh
export MOMO_TEST_ROOT='%s'
export IPKG_INSTROOT='%s'
export PATH='%s/usr/bin':"$PATH"
export MOMO_PYTHON='%s'
export MOMO_CONVERTER_PY='%s/etc/momo/scripts/momo_convert.py'
export MOMO_CONVERTER_TEMPLATE='%s/etc/momo/converter/momo-base.json'
export MOMO_CONVERTER_CONF='%s/etc/momo/converter/converter.conf'
export MOMO_CONVERTER_LOG='%s/var/log/momo/app.log'
export MOMO_SING_BOX='%s'
export SING_BOX_REAL='%s'
export MOMO_CURL_MAP='%s/curl_map.json'
export MOMO_GROUPD_RULES='%s/var/run/momo/groups.json'
export MOMO_GROUPD_STATE='%s/var/run/momo/group_state.json'
export MOMO_GROUPD_PID='%s/var/run/momo/groupd.pid'
export MOMO_GROUPD_PROFILE='%s/etc/momo/run/config.json'
export MOMO_GROUPD_ENABLED="${MOMO_GROUPD_ENABLED:-0}"
export MOMO_CONVERTER_RULESET="${MOMO_CONVERTER_RULESET:-0}"
. "$MOMO_TEST_ROOT/procd_stub.sh"
. "$MOMO_TEST_ROOT/uci_stub.sh"
. "$MOMO_TEST_ROOT/etc/init.d/momo"
case "$1" in
  start) start_service; service_started ;;
  stop) cleanup ;;
  update) shift; update_subscription "$@" ;;
  *) echo "unknown mode" >&2; exit 2 ;;
esac
""" % (SB_WIN, SB_WIN, SB_MSYS, PY, SB_WIN, SB_WIN, SB_WIN,
       SB_WIN, SING_BOX_REAL, SING_BOX_REAL, SB_WIN,
       SB_WIN, SB_WIN, SB_WIN, SB_WIN))


def parse_uci(text):
    mapping = {}
    section = None
    for line in text.splitlines():
        m = re.match(r"^config\s+(\S+)(?:\s+'([^']+)')?", line.strip())
        if m:
            section = m.group(2) or m.group(1)
            continue
        m = re.match(r"^\s*(?:option|list)\s+'([^']+)'\s+'([^']*)'", line)
        if m and section:
            mapping["%s.%s" % (section, m.group(1))] = m.group(2)
    return mapping


def build_uci(overrides=None):
    text = (ROOT / "momo/files/momo.conf").read_text(encoding="utf-8")
    overrides = overrides or {}
    out = []
    section = None
    for line in text.splitlines():
        m = re.match(r"^config\s+(\S+)(?:\s+'([^']+)')?", line.strip())
        if m:
            section = m.group(2) or m.group(1)
        m2 = re.match(r"^(\s*)(option|list)\s+'([^']+)'\s+'([^']*)'(.*)$", line)
        if m2 and section and ("%s.%s" % (section, m2.group(3))) in overrides:
            line = "%s%s '%s' '%s'%s" % (m2.group(1), m2.group(2), m2.group(3),
                                         overrides["%s.%s" % (section, m2.group(3))],
                                         m2.group(5))
        out.append(line)
    text = "\n".join(out) + "\n"
    write(SB / "etc/config/momo", text)
    mapping = parse_uci(text)
    # 订阅段（原有 update_subscription 交互用）
    mapping.update({
        "sub1.name": "E2E-Subscription",
        "sub1.url": "https://example.test/sub",
        "sub1.info_url": "",
        "sub1.user_agent": "sing-box",
        "sub1.prefer": "local",
    })
    # 订阅段默认值之后再叠一层用例覆盖（sub1.user_agent 等要能被单测改写）
    mapping.update({k: v for k, v in overrides.items() if k.startswith("sub1.")})
    write(SB / "uci_map.json", json.dumps(mapping, ensure_ascii=False, indent=2))
    lines = [
        "config_load() { :; }",
        "config_get() {",
        '  __key="$2.$3"; __default="${4:-}"',
        '  case "$__key" in',
    ]
    for key, value in sorted(mapping.items()):
        safe = str(value).replace("'", "'\\''")
        lines.append("    '%s') __v='%s';;" % (key, safe))
    lines += [
        '    *) __v="$__default";;',
        "  esac",
        '  eval "$1=\\$__v"',
        "}",
        "config_get_bool() { config_get \"$@\"; }",
        'uci_remove() { echo "REMOVE $*" >> "$MOMO_TEST_ROOT/uci_calls.log"; }',
        'uci_set() { echo "SET $*" >> "$MOMO_TEST_ROOT/uci_calls.log"; }',
        'uci_commit() { echo "COMMIT $*" >> "$MOMO_TEST_ROOT/uci_calls.log"; }',
        "uci() { :; }",
    ]
    write(SB / "uci_stub.sh", "\n".join(lines) + "\n")


def reset_case(profile=None, subscription=None, curl_source=None, uci_overrides=None,
               converter_conf=None, curl_map=None):
    for f in (SB / "etc/momo/run").glob("*"):
        f.unlink()
    for f in (SB / "var/run/momo").glob("*"):
        f.unlink()
    for name in ["app.log", "core.log"]:
        write(SB / "var/log/momo" / name, "")
    for name in ["procd.log", "uci_calls.log"]:
        write(SB / name, "")
    write(SB / "etc/crontabs/root", "")
    for f in (SB / "etc/momo/profiles").glob("*"):
        f.unlink()
    for f in (SB / "etc/momo/subscriptions").glob("*"):
        f.unlink()

    overrides = {"config.enabled": "1", "config.test_profile": "1"}
    if profile:
        overrides["config.profile"] = "file:" + profile
        copy(FIX / profile, SB / "etc/momo/profiles" / profile)
    if subscription:
        overrides["config.profile"] = "subscription:sub1"
        copy(FIX / subscription, SB / "etc/momo/subscriptions/sub1.json")
    if uci_overrides:
        overrides.update(uci_overrides)
    build_uci(overrides)
    if curl_map is not None:
        write(SB / "curl_map.json", json.dumps(curl_map, ensure_ascii=False))
    else:
        write(SB / "curl_map.json", json.dumps(
            {"https://example.test/sub": str((FIX / curl_source).resolve()).replace("\\", "/")}
            if curl_source else {}, ensure_ascii=False))
    write(SB / "curl_ua.log", "")
    write(SB / "etc/momo/converter/converter.conf",
          converter_conf if converter_conf is not None
          else (ROOT / "momo/files/converter/converter.conf").read_text(encoding="utf-8"))


def run(mode, *args, **kwargs):
    env = dict(os.environ)
    env["SING_BOX_REAL"] = SING_BOX_REAL
    env["MOMO_PYTHON"] = PY
    env["MOMO_TEST_ROOT"] = SB_WIN
    env.update(kwargs.get("extra_env") or {})
    proc = subprocess.run([SH, str(SB / "run_init.sh"), mode, *args],
                          capture_output=True, text=True, env=env, timeout=180)
    return {
        "rc": proc.returncode,
        "stdout": proc.stdout.strip()[-1500:],
        "stderr": proc.stderr.strip()[-1500:],
        "app_log": (SB / "var/log/momo/app.log").read_text(encoding="utf-8", errors="replace"),
        "core_log": (SB / "var/log/momo/core.log").read_text(encoding="utf-8", errors="replace"),
        "procd_log": (SB / "procd.log").read_text(encoding="utf-8", errors="replace"),
    }


def final_config():
    p = SB / "etc/momo/run/config.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return None


def real_check(path=None):
    if not SING_BOX_REAL:
        return {"rc": None, "detail": "skipped (sing-box binary not available)"}
    p = path or str((SB / "etc/momo/run/config.json").resolve()).replace("\\", "/")
    proc = subprocess.run([SING_BOX_REAL, "check", "-c", p],
                          capture_output=True, text=True, timeout=30)
    return {"rc": proc.returncode,
            "detail": (proc.stderr or proc.stdout).strip()[:400]}


class Suite:
    def __init__(self):
        self.results = []

    def add(self, name, ok, detail, extra=None):
        entry = {"case": name, "status": "PASS" if ok else "FAIL", "detail": detail}
        if extra:
            entry.update(extra)
        self.results.append(entry)
        print("[%s] %-34s %s" % ("PASS" if ok else "FAIL", name, detail))
        return ok

    def summary(self):
        passed = sum(1 for x in self.results if x["status"] == "PASS")
        return {"total": len(self.results), "passed": passed,
                "failed": len(self.results) - passed}


# --------------------------------------------------------------------------
# 代理节点分组：转换规则 + momo 侧驱动（mihomo 规则，非内核自动模式）
# --------------------------------------------------------------------------
GROUP_DRIVER_RULES = {
    "version": 1,
    "api": {"controller": "127.0.0.1:9090", "secret": ""},
    "proxy_group": "proxy",
    "groups": [
        {"tag": "proxy", "type": "select", "url": "http://cp.cloudflare.com/generate_204",
         "interval": 300, "tolerance": 0, "timeout": 3000, "strategy": "round-robin",
         "lazy": True, "expected_status": "", "source": "momo",
         "allow_builtin_fallback": False,
         "members": ["UT", "FB", "LB", "Node-A", "Node-B", "Node-C", "direct"]},
        {"tag": "UT", "type": "url-test", "url": "http://www.gstatic.com/generate_204",
         "interval": 60, "tolerance": 20, "timeout": 3000, "strategy": "round-robin",
         "lazy": True, "expected_status": "", "source": "subscription",
         "members": ["Node-A", "Node-B", "Node-C"]},
        {"tag": "FB", "type": "fallback", "url": "http://cp.cloudflare.com/generate_204",
         "interval": 120, "tolerance": 0, "timeout": 3000, "strategy": "round-robin",
         "lazy": True, "expected_status": "", "source": "subscription",
         "members": ["Node-C", "Node-A", "Node-B"]},
        {"tag": "LB", "type": "load-balance", "url": "http://www.gstatic.com/generate_204",
         "interval": 30, "tolerance": 0, "timeout": 3000, "strategy": "round-robin",
         "lazy": True, "expected_status": "", "source": "subscription",
         "members": ["Node-A", "Node-B", "Node-C"]},
        {"tag": "FB-DIRECT", "type": "select", "url": "http://cp.cloudflare.com/generate_204",
         "interval": 300, "tolerance": 0, "timeout": 3000, "strategy": "round-robin",
         "lazy": True, "expected_status": "", "source": "subscription",
         "allow_builtin_fallback": True,
         "members": ["Node-A", "Node-B", "direct"]},
    ],
    "nodes": ["Node-A", "Node-B", "Node-C"],
}


def stub_proxies():
    return {
        "proxy": {"type": "Selector",
                  "all": ["UT", "FB", "LB", "Node-A", "Node-B", "Node-C", "direct"],
                  "now": "UT"},
        "UT": {"type": "Selector", "all": ["Node-A", "Node-B", "Node-C"], "now": "Node-A"},
        "FB": {"type": "Selector", "all": ["Node-C", "Node-A", "Node-B"], "now": "Node-B"},
        "LB": {"type": "Selector", "all": ["Node-A", "Node-B", "Node-C"], "now": "Node-A"},
        "FB-DIRECT": {"type": "Selector", "all": ["Node-A", "Node-B", "direct"],
                      "now": "Node-A"},
        "Node-A": {"type": "Shadowsocks"},
        "Node-B": {"type": "VMess"},
        "Node-C": {"type": "Trojan"},
    }


def start_clashapi_stub():
    port_file = SB / "var/run/momo/clashapi.port"
    state_file = SB / "var/run/momo/clashapi_state.json"
    if port_file.exists():
        port_file.unlink()
    write(state_file, json.dumps({
        "proxies": stub_proxies(),
        "delays": {"Node-A": 100, "Node-B": 50, "Node-C": 200},
        "select_log": [], "builtin_delay": 1,
    }, ensure_ascii=False))
    proc = subprocess.Popen(
        [PY, str(HARNESS / "clashapi_stub.py"), "--port", "0",
         "--port-file", str(port_file), "--state", str(state_file)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for _ in range(100):
        if port_file.exists() and port_file.read_text(encoding="utf-8").strip().isdigit():
            break
        time.sleep(0.05)
    port = int(port_file.read_text(encoding="utf-8").strip())
    return proc, port, "http://127.0.0.1:%d" % port


def control_api(base, payload):
    subprocess.run(["curl", "-s", "-m", "5", "-X", "POST",
                    "-H", "Content-Type: application/json",
                    "-d", json.dumps(payload), base + "/__control"],
                   capture_output=True, text=True, timeout=15)


def api_state(base):
    p = subprocess.run(["curl", "-s", "-m", "5", base + "/__state"],
                       capture_output=True, text=True, timeout=15)
    try:
        return json.loads(p.stdout)
    except ValueError:
        return {}


def last_select(state, group):
    for item in reversed(state.get("select_log", [])):
        if item.get("group") == group:
            return item.get("name")
    return None


def run_groupd(rules, state, port, *extra):
    cmd = [PY, str(ROOT / "momo/files/scripts/momo_groupd.py"),
           "--rules", str(rules), "--state", str(state),
           "--api", "127.0.0.1:%d" % port,
           "--log", str(SB / "var/log/momo/groupd.log"),
           "--once", "--rounds", "1", "--health-interval", "1", *extra]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=90)


def write_state(path, groups):
    write(path, json.dumps({"version": 1, "groups": groups}, ensure_ascii=False))


def blank_state(tag, **overrides):
    st = {"manual": None, "last_set": None, "next_full": 0,
          "next_health": 0, "rr": 0, "delays": {}}
    st.update(overrides)
    return {tag: st}


def test_group_conversion(s, env):
    out = SB / "etc/momo/run/groups_out.json"
    rules_path = SB / "var/run/momo/groups.json"
    for p in (out, rules_path):
        if p.exists():
            p.unlink()
    p = subprocess.run([PY, str(SB / "etc/momo/scripts/momo_convert.py"),
                        "-i", str(FIX / "clash_groups.yaml"), "-o", str(out),
                        "--groups-out", str(rules_path),
                        "--template", str(SB / "etc/momo/converter/momo-base.json"),
                        "--conf", str(SB / "etc/momo/converter/converter.conf")],
                       capture_output=True, text=True, env=env, timeout=120)
    try:
        report = json.loads(p.stdout)
    except ValueError:
        report = {}
    cfg = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    rules = json.loads(rules_path.read_text(encoding="utf-8")) if rules_path.exists() else {}
    outbound_types = {o.get("type") for o in cfg.get("outbounds", [])}
    selectors = [o for o in cfg.get("outbounds", []) if o.get("type") == "selector"]
    chk = real_check(str(out.resolve()).replace("\\", "/")) if out.exists() else {"rc": 1}
    s.add("group_convert_rules",
          p.returncode == 0 and report.get("nodes") == 5
          and set(report.get("group_types", {}).values())
              >= {"url-test", "fallback", "load-balance", "select"}
          and chk.get("rc") == 0,
          "订阅 4 类分组全部识别，nodes=%s groups=%d check=%s" %
          (report.get("nodes"), len(report.get("groups", [])), chk.get("rc")),
          {"report": report, "singbox_check": chk})

    s.add("group_no_kernel_urltest",
          "urltest" not in outbound_types and len(selectors) >= 9
          and all(o.get("default") in (o.get("outbounds") or []) for o in selectors),
          "所有分组均为 selector（%d 个），无内核 urltest 自动模式，default 均在成员中" %
          len(selectors))

    by_tag = {g["tag"]: g for g in rules.get("groups", [])}
    s.add("group_rule_params",
          by_tag.get("Auto-Test", {}).get("interval") == 60
          and by_tag.get("Auto-Test", {}).get("tolerance") == 20
          and by_tag.get("Auto-Test", {}).get("url") == "http://www.gstatic.com/generate_204"
          and by_tag.get("Fallback-Group", {}).get("members") == ["Node-C", "Node-A", "Node-B"]
          and by_tag.get("LB-Group", {}).get("strategy") == "round-robin"
          and by_tag.get("auto", {}).get("type") == "url-test",
          "测速地址/间隔/容差/成员顺序/负载策略按订阅原样落到规则文件")

    s.add("group_compatibility",
          bool(report.get("cycle_drops"))
          and "group-proxy" in report.get("groups", [])
          and by_tag.get("Nested-Group", {}).get("members")
              == ["Fallback-Group", "Auto-Test", "block"]
          and by_tag.get("group-proxy", {}).get("members") == ["auto", "Node-A"]
          and cfg.get("route", {}).get("final") == "Auto-Test"
          and cfg.get("experimental", {}).get("clash_api", {}).get("external_controller")
              == "0.0.0.0:15425",
          "循环引用剔除、保留 tag 改名、DIRECT/REJECT/GLOBAL 映射、未知成员丢弃、Clash API 注入")

    s.add("group_builtin_fallback_flag",
          by_tag.get("Manual-Group", {}).get("allow_builtin_fallback") is True
          and by_tag.get("auto", {}).get("allow_builtin_fallback") is False
          and by_tag.get("Auto-Test", {}).get("allow_builtin_fallback") is False,
          "仅订阅显式含 DIRECT 的分组允许全挂时兜底直连，主组/自动组不会静默绕过代理")

    # 无 proxy-groups 的订阅也要有 mihomo 默认规则的自动选择组
    p2 = subprocess.run([PY, str(SB / "etc/momo/scripts/momo_convert.py"),
                         "-i", str(FIX / "nodes_uri.txt"), "--dry-run",
                         "--template", str(SB / "etc/momo/converter/momo-base.json"),
                         "--conf", str(SB / "etc/momo/converter/converter.conf")],
                        capture_output=True, text=True, env=env, timeout=120)
    try:
        d2 = json.loads(p2.stdout)
        auto = next(g for g in d2["group_rules"]["groups"] if g["tag"] == "auto")
        default_ok = (auto["type"] == "url-test" and auto["interval"] == 300
                      and auto["tolerance"] == 50 and len(auto["members"]) == 11)
    except (ValueError, KeyError, StopIteration):
        default_ok = False
    s.add("group_default_auto", p2.returncode == 0 and default_ok,
          "无分组订阅自动生成 auto(url-test, 300s/50ms) 组，成员为全部节点")

    # 只有 use/proxy-providers 或成员全部无法解析的分组：保底用全部节点，不静默直连
    edge = SB / "etc/momo/run/edge_groups.yaml"
    write(edge, """proxies:
  - name: "N1"
    type: ss
    server: n1.example.com
    port: 8388
    cipher: aes-256-gcm
    password: p1
  - name: "N2"
    type: ss
    server: n2.example.com
    port: 8389
    cipher: aes-256-gcm
    password: p2
proxy-groups:
  - name: "Provider-Only"
    type: url-test
    use:
      - some-provider
  - name: "Cycle-X"
    type: select
    proxies:
      - Cycle-Y
  - name: "Cycle-Y"
    type: select
    proxies:
      - Cycle-X
""")
    p3 = subprocess.run([PY, str(SB / "etc/momo/scripts/momo_convert.py"),
                         "-i", str(edge), "--dry-run",
                         "--template", str(SB / "etc/momo/converter/momo-base.json"),
                         "--conf", str(SB / "etc/momo/converter/converter.conf")],
                        capture_output=True, text=True, env=env, timeout=120)
    try:
        d3 = json.loads(p3.stdout)
        r3 = {g["tag"]: g for g in d3["group_rules"]["groups"]}
        edge_ok = (r3["Provider-Only"]["members"] == ["N1", "N2"]
                   and r3["Provider-Only"]["allow_builtin_fallback"] is False
                   and "direct" not in r3["Cycle-X"]["members"] + r3["Cycle-Y"]["members"]
                   and all(o.get("default") != "direct" for o in d3["config"]["outbounds"]
                           if o.get("type") == "selector"))
    except (ValueError, KeyError, TypeError):
        edge_ok = False
    s.add("group_empty_members_no_direct", p3.returncode == 0 and edge_ok,
          "空成员分组保底使用全部节点；断环后不退化成 direct，绝不静默绕过代理")
    return rules_path


def test_group_driver(s, env, converted_rules):
    driver_rules = SB / "var/run/momo/driver_rules.json"
    driver_state = SB / "var/run/momo/driver_state.json"
    write(driver_rules, json.dumps(GROUP_DRIVER_RULES, ensure_ascii=False))
    stub, port, base = start_clashapi_stub()
    try:
        time.sleep(0.2)
        st = api_state(base)
        s.add("group_api_stub", bool(st.get("proxies")) and len(st["proxies"]) >= 7,
              "Clash API 桩就绪（proxies=%d）" % len(st.get("proxies", {})))

        # 1) url-test 按延迟 + 容差；fallback 按订阅顺序；load-balance 轮询
        write_state(driver_state, {})
        control_api(base, {"clear_log": True,
                           "delays": {"Node-A": 100, "Node-B": 50, "Node-C": 200},
                           "now": {"UT": "Node-A", "FB": "Node-B", "LB": "Node-A",
                                   "proxy": "UT"}})
        r = run_groupd(driver_rules, driver_state, port, "--force-full")
        st = api_state(base)
        s.add("group_urltest_tolerance",
              r.returncode == 0 and last_select(st, "UT") == "Node-B",
              "url-test 按测速延迟并应用容差切换 -> %s (期望 Node-B)" % last_select(st, "UT"))
        s.add("group_fallback_order",
              last_select(st, "FB") == "Node-C",
              "fallback 按订阅顺序选第一个可用节点 -> %s (期望 Node-C)" % last_select(st, "FB"))
        s.add("group_loadbalance",
              last_select(st, "LB") == "Node-B",
              "load-balance 按 strategy 轮询 -> %s (期望 Node-B)" % last_select(st, "LB"))

        # 2) 容差内不抢占，避免抖动
        write_state(driver_state, {})
        control_api(base, {"clear_log": True,
                           "delays": {"Node-A": 10, "Node-B": 25, "Node-C": 200},
                           "now": {"UT": "Node-A"}})
        run_groupd(driver_rules, driver_state, port, "--force-full")
        st = api_state(base)
        s.add("group_tolerance_no_flap",
              last_select(st, "UT") is None and st["proxies"]["UT"]["now"] == "Node-A",
              "候选未快出 tolerance(20ms) 时保持当前节点，不抖动")

        # 3) 手动选择：节点只要可用就一直保留（即使延迟最差）
        write_state(driver_state, blank_state(
            "UT", manual="Node-C", last_set="Node-C", next_full=0))
        control_api(base, {"clear_log": True,
                           "delays": {"Node-A": 1, "Node-B": 2, "Node-C": 100},
                           "now": {"UT": "Node-C"}})
        run_groupd(driver_rules, driver_state, port, "--force-full")
        st = api_state(base)
        s.add("group_manual_kept",
              last_select(st, "UT") is None and st["proxies"]["UT"]["now"] == "Node-C",
              "手动选择的节点可用时一直保留，不被自动规则覆盖")

        # 4) 手动节点不可用：立即（health 轮，不等 interval）切到可用节点
        future = time.time() + 3600
        write_state(driver_state, blank_state(
            "UT", manual="Node-C", last_set="Node-C", next_full=future, next_health=0))
        control_api(base, {"clear_log": True,
                           "delays": {"Node-A": 10, "Node-B": 20, "Node-C": None},
                           "now": {"UT": "Node-C"}})
        r4 = run_groupd(driver_rules, driver_state, port, "--no-initial-full")
        st = api_state(base)
        s.add("group_failover_immediate",
              r4.returncode == 0 and last_select(st, "UT") == "Node-A",
              "当前节点不可用时立即切到可用节点 -> %s (期望 Node-A)" % last_select(st, "UT"))

        # 5) 手动节点恢复可用：自动切回，保持"一直保留"的偏好
        write_state(driver_state, blank_state(
            "UT", manual="Node-C", last_set="Node-A", next_full=future, next_health=0))
        control_api(base, {"clear_log": True,
                           "delays": {"Node-A": 10, "Node-B": 20, "Node-C": 100},
                           "now": {"UT": "Node-A"}})
        run_groupd(driver_rules, driver_state, port, "--no-initial-full")
        st = api_state(base)
        s.add("group_manual_restore",
              last_select(st, "UT") == "Node-C",
              "手动节点恢复后自动切回 -> %s (期望 Node-C)" % last_select(st, "UT"))

        # 6) load-balance 连续轮询
        write_state(driver_state, blank_state(
            "LB", last_set="Node-A", next_full=0, next_health=future))
        control_api(base, {"clear_log": True,
                           "delays": {"Node-A": 10, "Node-B": 20, "Node-C": 30},
                           "now": {"LB": "Node-A"}})
        p6 = subprocess.run(
            [PY, str(ROOT / "momo/files/scripts/momo_groupd.py"),
             "--rules", str(driver_rules), "--state", str(driver_state),
             "--api", "127.0.0.1:%d" % port,
             "--log", str(SB / "var/log/momo/groupd.log"),
             "--once", "--rounds", "3", "--health-interval", "1", "--force-full"],
            capture_output=True, text=True, timeout=90)
        st = api_state(base)
        lb_seq = [x["name"] for x in st.get("select_log", []) if x.get("group") == "LB"]
        s.add("group_round_robin",
              p6.returncode == 0 and lb_seq == ["Node-B", "Node-C", "Node-A"],
              "round-robin 连续 3 轮按顺序切换: %s" % lb_seq)

        # 7) 全部代理节点不可用：主组不静默直连，订阅显式 DIRECT 的组才兜底
        write_state(driver_state, {})
        control_api(base, {"clear_log": True,
                           "delays": {"Node-A": None, "Node-B": None, "Node-C": None},
                           "now": {"UT": "Node-A", "proxy": "UT",
                                   "FB-DIRECT": "Node-A"}})
        run_groupd(driver_rules, driver_state, port, "--force-full")
        st = api_state(base)
        s.add("group_no_silent_direct",
              last_select(st, "proxy") is None
              and st["proxies"]["proxy"]["now"] == "UT"
              and last_select(st, "UT") is None
              and last_select(st, "FB-DIRECT") == "direct",
              "全节点不可用时主组/自动组保持原选择不静默直连；订阅显式 DIRECT 组可兜底")

        # 8) 转换器实际生成的规则文件可被守护进程加载
        p7 = subprocess.run(
            [PY, str(ROOT / "momo/files/scripts/momo_groupd.py"),
             "--check", "--rules", str(converted_rules),
             "--api", "127.0.0.1:%d" % port, "--state", str(driver_state)],
            capture_output=True, text=True, timeout=60)
        try:
            info = json.loads(p7.stdout)
        except ValueError:
            info = {}
        s.add("groupd_plugin_load",
              p7.returncode == 0 and info.get("ready") is True
              and info.get("api_reachable") is True
              and info.get("kernel_auto_mode") is False,
              "插件加载 ready=%s groups=%s api=%s" %
              (info.get("ready"), info.get("groups"), info.get("api")))

        # 8) groupd.sh 加载器 start/stop 不阻断、pid 可管
        loader_env = dict(env)
        loader_env.update({
            "MOMO_GROUPD_ENABLED": "1",
            "MOMO_GROUPD_RULES": str(driver_rules),
            "MOMO_GROUPD_STATE": str(driver_state),
            "MOMO_GROUPD_PID": str(SB / "var/run/momo/groupd.pid"),
            "MOMO_GROUPD_ARGS": "--once --rounds 1 --health-interval 0 --api 127.0.0.1:%d" % port,
        })
        app_log = SB / "var/log/momo/app.log"
        write(app_log, "")
        log_before = ""
        p8 = subprocess.run([SH, str(SB / "etc/momo/scripts/groupd.sh"), "start"],
                            capture_output=True, text=True, env=loader_env, timeout=60)
        pid_file = SB / "var/run/momo/groupd.pid"
        ok8 = False
        for _ in range(60):
            log_now = app_log.read_text(encoding="utf-8", errors="replace")
            if "分组驱动启动" in log_now[len(log_before):]:
                ok8 = True
                break
            time.sleep(0.1)
        pid_written = pid_file.exists()
        pstop = subprocess.run([SH, str(SB / "etc/momo/scripts/groupd.sh"), "stop"],
                               capture_output=True, text=True, env=loader_env, timeout=30)
        s.add("groupd_loader_start_stop",
              p8.returncode == 0 and ok8 and pid_written
              and pstop.returncode == 0 and not pid_file.exists(),
              "加载器可 start/stop、写 pid 并输出启动日志，停止后清理 pid，恒不阻断 momo")
        gsh_text = (ROOT / "momo/files/scripts/groupd.sh").read_text(encoding="utf-8")
        s.add("groupd_spawn_closes_procd_lock_fd",
              "1000>&- &" in gsh_text and "</dev/null" in gsh_text,
              "groupd 派生时关闭继承的 procd flock(fd 1000) 与 stdin，"
              "否则锁被守护进程永久持有，rc.common/LuCI 状态全部阻塞")
    finally:
        stub.terminate()
        try:
            stub.wait(timeout=5)
        except subprocess.TimeoutExpired:
            stub.kill()


# --------------------------------------------------------------------------
# 远程规则集镜像：真实下载测速 -> 选源 -> 写入 profile
# --------------------------------------------------------------------------
def test_ruleset_mirrors(s, env):
    stub_py = str((SB / "usr/bin/curl_speed_stub.py").resolve()).replace("\\", "/")
    log_path = str((SB / "var/run/momo/curl_speed.log").resolve()).replace("\\", "/")
    tpl = str((SB / "etc/momo/converter/momo-base.json").resolve()).replace("\\", "/")
    conf = str((SB / "etc/momo/converter/converter.conf").resolve()).replace("\\", "/")
    base = dict(env)
    base.update({
        "MOMO_CONVERTER_RULESET": "1",
        "MOMO_CONVERTER_RULESET_CURL": "%s %s" % (PY, stub_py),
        "MOMO_CONVERTER_RULESET_MIN_SPEED": "80",
        "MOMO_CONVERTER_RULESET_TIMEOUT": "2",
        "MOMO_CURL_SPEED_LOG": log_path,
    })

    def convert(hostmap, extra=None, template=None, fixture="nodes_uri.txt"):
        e = dict(base)
        e["MOMO_CURL_SPEED_MAP"] = json.dumps(hostmap, ensure_ascii=False)
        if extra:
            e.update(extra)
        out = SB / "etc/momo/run/ruleset.json"
        if out.exists():
            out.unlink()
        log = Path(log_path)
        if log.exists():
            log.unlink()
        p = subprocess.run([PY, str(SB / "etc/momo/scripts/momo_convert.py"),
                            "-i", str(FIX / fixture), "-o", str(out),
                            "--template", template or tpl, "--conf", conf],
                           capture_output=True, text=True, env=e, timeout=120)
        try:
            rep = json.loads(p.stdout)
        except ValueError:
            rep = {}
        cfg = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
        calls = [x for x in log.read_text(encoding="utf-8").splitlines() if x] \
            if log.exists() else []
        return p, rep, cfg, calls, str(out)

    def rs_of(cfg):
        return cfg.get("route", {}).get("rule_set", []) or []

    def urls_of(cfg):
        return dict((r.get("tag"), r.get("url")) for r in rs_of(cfg)
                    if isinstance(r, dict))

    # 4 个候选（真实 GitHub 官方仓库，只是加速通道不同）
    all_fast = {
        "gh-proxy.com": {"elapsed": 1.0, "bytes": 57456, "code": 206},          # 56 KB/s
        "testingcf.jsdelivr.net": {"elapsed": 0.4, "bytes": 57456, "code": 206},  # 140 KB/s
        "fastly.jsdelivr.net": {"elapsed": 0.5, "bytes": 57456, "code": 206},    # 112 KB/s
        "ghfast.top": {"elapsed": 1.2, "bytes": 57456, "code": 206},             # 47 KB/s
    }

    # 1) 达标最快：按耗时排序 + 80KB/s 阈值淘汰后选 testingcf
    p, rep, cfg, calls, out = convert(all_fast)
    r = rep.get("ruleset", {})
    u = urls_of(cfg)
    chk = real_check(out)
    s.add("rs_probe_select_fastest",
          (p.returncode == 0 and r.get("decision") == "fastest-qualified"
           and r.get("mirror") == "testingcf"
           and r.get("ranked", [{}])[0].get("name") == "testingcf"
           and len(calls) == 4 and r.get("applied") is True
           and chk.get("rc") == 0),
          "4 镜像并行真实测速，按耗时排序后选达标最快源: %s (top=%s, rc=%s)" %
          (r.get("mirror"), (r.get("ranked") or [{}])[0].get("name"), chk.get("rc")),
          {"ruleset": r})

    s.add("rs_two_rulesets_same_mirror",
          u.get("geosite-cn") == "https://testingcf.jsdelivr.net/gh/SagerNet/sing-geosite@rule-set/geosite-cn.srs"
          and u.get("geoip-cn") == "https://testingcf.jsdelivr.net/gh/SagerNet/sing-geoip@rule-set/geoip-cn.srs"
          and cfg.get("http_clients") == [{"tag": "default"}]
          and all(x.get("http_client") == "default" for x in rs_of(cfg)),
          "geosite/geoip 两条 rule-set 均用选出镜像（jsdelivr @rule-set 路径推导），1.14+ 显式 http_clients")

    # 2) 硬阈值：最快的 testingcf 只有 40KB/s，必须被淘汰
    fastest_slow = {
        "gh-proxy.com": {"elapsed": 1.0, "bytes": 57456, "code": 206},
        "testingcf.jsdelivr.net": {"elapsed": 0.2, "bytes": 8192, "code": 206},  # 40 KB/s
        "fastly.jsdelivr.net": {"elapsed": 0.5, "bytes": 57456, "code": 206},
        "ghfast.top": {"elapsed": 1.2, "bytes": 57456, "code": 206},
    }
    p, rep, cfg, _, _ = convert(fastest_slow)
    r = rep.get("ruleset", {})
    s.add("rs_threshold_eliminates_fastest",
          (p.returncode == 0 and r.get("mirror") == "fastly"
           and r.get("ranked", [{}])[0].get("name") == "testingcf"
           and "testingcf.jsdelivr.net" not in str(urls_of(cfg))),
          "80KB/s 硬阈值淘汰「最快但只有 40KB/s」的源，改选次快达标源 fastly")

    # 3) 全部不达标 -> 退而取最快的实测源
    all_slow = dict((h, {"elapsed": t, "bytes": 20480, "code": 206}) for h, t in
                    [("gh-proxy.com", 1.0), ("testingcf.jsdelivr.net", 0.5),
                     ("fastly.jsdelivr.net", 0.8), ("ghfast.top", 1.5)])
    p, rep, cfg, _, _ = convert(all_slow)
    r = rep.get("ruleset", {})
    s.add("rs_all_below_threshold",
          p.returncode == 0 and r.get("decision") == "fastest-below-threshold"
          and r.get("mirror") == "testingcf" and r.get("inject") is True
          and "testingcf.jsdelivr.net" in str(urls_of(cfg)),
          "弱网全部不达标时退取最快实测源，仍写入 profile")

    # 4) 全部探测失败 -> 保底 gh-proxy，且不新增远程规则集（避免离线时内核 FATAL）
    p, rep, cfg, calls, out = convert({})
    r = rep.get("ruleset", {})
    chk = real_check(out)
    s.add("rs_all_fail_offline_safe",
          (p.returncode == 0 and r.get("decision") == "fallback-offline"
           and r.get("mirror") == "gh-proxy" and len(calls) == 4
           and not rs_of(cfg) and not cfg.get("http_clients")
           and chk.get("rc") == 0),
          "全部失败保底 gh-proxy 且不注入新远程规则集，转换与内核 check 均正常 (rc=%s)" %
          chk.get("rc"))

    # 5) 显式 FORCE：离线时也把 gh-proxy 默认值写进 profile
    p, rep, cfg, _, _ = convert({}, extra={"MOMO_CONVERTER_RULESET_FORCE": "1"})
    u = urls_of(cfg)
    s.add("rs_offline_force_ghproxy",
          p.returncode == 0 and rep.get("ruleset", {}).get("mirror") == "gh-proxy"
          and len(rs_of(cfg)) == 2
          and "gh-proxy.com/https://raw.githubusercontent.com/SagerNet/sing-geosite/rule-set/" in str(u.get("geosite-cn"))
          and "gh-proxy.com/https://raw.githubusercontent.com/SagerNet/sing-geoip/rule-set/" in str(u.get("geoip-cn")),
          "离线强制写入时两条规则集均为 gh-proxy 官方仓库镜像 URL")

    # 6) 已有 GitHub 规则集 URL 统一改写（含官方 raw 与另一路 jsdelivr）
    tpl_rs = SB / "etc/momo/run/template_with_ruleset.json"
    base_tpl = json.loads(Path(tpl).read_text(encoding="utf-8"))
    base_tpl["route"]["rule_set"] = [
        {"type": "remote", "format": "binary", "tag": "geosite-cn",
         "url": "https://gh-proxy.com/https://raw.githubusercontent.com/SagerNet/sing-geosite/rule-set/geosite-cn.srs"},
        {"type": "remote", "format": "binary", "tag": "geoip-cn",
         "url": "https://fastly.jsdelivr.net/gh/SagerNet/sing-geoip@rule-set/geoip-cn.srs"},
        {"type": "remote", "format": "binary", "tag": "geosite-private",
         "url": "https://raw.githubusercontent.com/SagerNet/sing-geosite/rule-set/geosite-private.srs"},
    ]
    write(tpl_rs, json.dumps(base_tpl, ensure_ascii=False, indent=2))
    p, rep, cfg, _, _ = convert(all_fast, template=str(tpl_rs))
    u = urls_of(cfg)
    s.add("rs_rewrite_existing_rulesets",
          (p.returncode == 0 and len(rs_of(cfg)) == 3
           and u.get("geosite-cn", "").startswith("https://testingcf.jsdelivr.net/gh/SagerNet/sing-geosite@rule-set/")
           and u.get("geoip-cn", "").startswith("https://testingcf.jsdelivr.net/gh/SagerNet/sing-geoip@rule-set/")
           and u.get("geosite-private", "").startswith("https://testingcf.jsdelivr.net/gh/SagerNet/sing-geosite@rule-set/geosite-private.srs")),
          "已有 GitHub 远程规则集（官方 raw / 前缀代理 / jsdelivr）全部改写到选中镜像，无重复条目")

    # 7) 离线时既不新增也不改写已有规则集（gh-proxy 已证实不可达，改了反而会 FATAL）
    p, rep, cfg, _, out = convert({}, template=str(tpl_rs))
    u = urls_of(cfg)
    original = {
        "geosite-cn": "https://gh-proxy.com/https://raw.githubusercontent.com/SagerNet/sing-geosite/rule-set/geosite-cn.srs",
        "geoip-cn": "https://fastly.jsdelivr.net/gh/SagerNet/sing-geoip@rule-set/geoip-cn.srs",
        "geosite-private": "https://raw.githubusercontent.com/SagerNet/sing-geosite/rule-set/geosite-private.srs",
    }
    chk = real_check(out)
    s.add("rs_offline_keep_existing",
          (p.returncode == 0 and u == original and not cfg.get("http_clients")
           and rep.get("ruleset", {}).get("inject") is False
           and rep.get("ruleset", {}).get("rewrite") is False
           and chk.get("rc") == 0),
          "离线保底不改写已有规则集、不注入 http_clients，配置仍可 check (rc=%s)" % chk.get("rc"))

    # 8) 单个探测超时不拖垮整体，且有超时上限
    timeout_map = dict(all_fast)
    timeout_map["ghfast.top"] = {"elapsed": 9.0, "bytes": 57456, "code": 206}
    t0 = time.time()
    p, rep, cfg, _, _ = convert(timeout_map, extra={"MOMO_CONVERTER_RULESET_TIMEOUT": "1"})
    spent = time.time() - t0
    failed = [x for x in rep.get("ruleset", {}).get("probes", []) if not x.get("ok")]
    s.add("rs_probe_timeout_capped",
          (p.returncode == 0 and spent < 4.0 and len(failed) == 1
           and failed[0]["name"] == "ghfast"
           and rep.get("ruleset", {}).get("mirror") == "testingcf"),
          "单个镜像 8s 超时上限生效，其余源正常选源 (总耗时 %.2fs)" % spent)

    # 8b) HTTP 200 但是劫持页（无 .srs 文件头）：不得当成最快源
    hijack = dict(all_fast)
    hijack["ghfast.top"] = {"elapsed": 0.01, "bytes": 20000, "code": 200, "body": "html"}
    p, rep, cfg, _, _ = convert(hijack)
    probes = dict((x["name"], x) for x in rep.get("ruleset", {}).get("probes", []))
    s.add("rs_reject_hijack_page",
          (p.returncode == 0 and rep.get("ruleset", {}).get("mirror") == "testingcf"
           and not probes.get("ghfast", {}).get("ok")
           and "srs" in probes.get("ghfast", {}).get("error", "")),
          "HTTP 200 劫持页被 .srs 文件头识别并淘汰，不会写入 profile")

    # 8c) curl 非零退出但 -w 仍报 206：必须按退出码判失败
    truncated = dict(all_fast)
    truncated["ghfast.top"] = {"elapsed": 0.01, "bytes": 57456, "code": 206, "rc": 23}
    p, rep, cfg, _, _ = convert(truncated)
    probes = dict((x["name"], x) for x in rep.get("ruleset", {}).get("probes", []))
    s.add("rs_reject_curl_nonzero",
          (p.returncode == 0 and not probes.get("ghfast", {}).get("ok")
           and "退出码 23" in probes.get("ghfast", {}).get("error", "")
           and rep.get("ruleset", {}).get("mirror") == "testingcf"),
          "curl 传输被截断（退出码非 0）时不被 -w 数据欺骗")

    # 8d) 镜像忽略 Range 返回超大包：--max-filesize 拦截，避免撑爆 tmpfs
    oversize = dict(all_fast)
    oversize["ghfast.top"] = {"elapsed": 0.01, "bytes": 200000, "code": 206,
                              "ignore_range": True}
    p, rep, cfg, _, _ = convert(oversize)
    probes = dict((x["name"], x) for x in rep.get("ruleset", {}).get("probes", []))
    s.add("rs_reject_oversize_response",
          (p.returncode == 0 and not probes.get("ghfast", {}).get("ok")
           and "退出码 63" in probes.get("ghfast", {}).get("error", "")),
          "超过 80KB 的响应被 --max-filesize 拦截，4 路并发不会写爆路由器 tmpfs")

    # 9) 关闭开关：完全不探测、配置无 rule_set
    p, rep, cfg, calls, _ = convert(all_fast, extra={"MOMO_CONVERTER_RULESET": "0"})
    s.add("rs_disabled_no_probe",
          p.returncode == 0 and not calls and not rs_of(cfg)
          and rep.get("ruleset", {}).get("enabled") is False,
          "MOMO_CONVERTER_RULESET=0 时零探测、零注入，转换行为与集成前一致")

    # 10) 原生 sing-box 配置：Python 早退，绝不触发探测
    p, rep, cfg, calls, _ = convert(all_fast, fixture="native.json")
    s.add("rs_native_no_probe",
          p.returncode == 0 and rep.get("status") == "passthrough"
          and not calls and not rs_of(cfg),
          "原生 JSON 严格透传，不执行镜像测速")

    # 11) 插件自检能报告 4 个镜像
    p = subprocess.run([SH, str(SB / "etc/momo/scripts/convert.sh"), "--check"],
                       capture_output=True, text=True, env=base, timeout=60)
    try:
        info = json.loads(p.stdout)
    except ValueError:
        info = {}
    s.add("rs_plugin_mirror_capability",
          info.get("ready") is True
          and info.get("ruleset_mirrors") == ["gh-proxy", "testingcf", "fastly", "ghfast"],
          "插件可正常加载且自检报告 4 个测速镜像与阈值")

    # 12) 只改转换器：所有集成文件都不含新能力痕迹
    integ = ["momo/files/momo.init", "momo/files/scripts/include.sh",
             "momo/files/scripts/convert.sh", "momo/files/scripts/groupd.sh",
             "momo/files/converter/converter.conf", "momo/files/converter/momo-base.json",
             "momo/files/momo.conf", "momo/Makefile"]
    touched = []
    for rel in integ:
        text = (ROOT / rel).read_text(encoding="utf-8")
        if any(k in text for k in ("jsdelivr", "gh-proxy", "RULESET_MIRROR",
                                   "MOMO_CONVERTER_RULESET", "geosite-cn.srs")):
            touched.append(rel)
    s.add("rs_only_converter_changed", not touched,
          "仅 momo_convert.py 实现镜像能力；集成文件/UCI/模板零改动 (%s)" %
          (",".join(touched) or "无"))

    # 13) 端到端：momo.init 启动链中自动转换并写入所选镜像
    reset_case(profile="nodes_uri.txt")
    r = run("start", extra_env={
        "MOMO_CONVERTER_RULESET": "1",
        "MOMO_CONVERTER_RULESET_CURL": "%s %s" % (PY, stub_py),
        "MOMO_CONVERTER_RULESET_TIMEOUT": "2",
        "MOMO_CURL_SPEED_LOG": log_path,
        "MOMO_CURL_SPEED_MAP": json.dumps(all_fast, ensure_ascii=False),
    })
    final = final_config()
    final_urls = urls_of(final or {})
    s.add("rs_e2e_start_with_mirror",
          (r["rc"] == 0 and "已自动转换" in r["app_log"]
           and "Test passed." in r["app_log"]
           and (SB / "var/run/momo/started.flag").exists()
           and "testingcf.jsdelivr.net" in str(final_urls.get("geosite-cn"))),
          "原有 start_service 链路中自动测速选源、写入 profile 并正常启动")


def main():
    setup_sandbox()
    s = Suite()

    # ---------------------------------------------------------------- 插件加载
    env = dict(os.environ)
    env.update({"MOMO_PYTHON": PY, "MOMO_TEST_ROOT": SB_WIN,
                "MOMO_CONVERTER_PY": str((SB / "etc/momo/scripts/momo_convert.py").resolve()).replace("\\", "/"),
                "MOMO_CONVERTER_TEMPLATE": str((SB / "etc/momo/converter/momo-base.json").resolve()).replace("\\", "/"),
                "MOMO_CONVERTER_CONF": str((SB / "etc/momo/converter/converter.conf").resolve()).replace("\\", "/"),
                "MOMO_CONVERTER_LOG": str((SB / "var/log/momo/app.log").resolve()).replace("\\", "/"),
                "MOMO_SING_BOX": SING_BOX_REAL,
                "SING_BOX_REAL": SING_BOX_REAL,
                # 原有回归用例默认关闭镜像测速（避免真实网络依赖），
                # 新增的镜像用例会在自己的 env 里显式打开并接桩。
                "MOMO_CONVERTER_RULESET": "0"})
    p = subprocess.run([SH, str(SB / "etc/momo/scripts/convert.sh"), "--check"],
                       capture_output=True, text=True, env=env, timeout=60)
    try:
        info = json.loads(p.stdout)
        s.add("plugin_load_check", p.returncode == 0 and info.get("ready") is True,
              "插件可加载 version=%s python=%s protocols=%d" %
              (info.get("version"), info.get("python"), len(info.get("protocols", []))))
    except ValueError:
        s.add("plugin_load_check", False, "输出非 JSON: %s %s" % (p.stdout[:120], p.stderr[:120]))

    # ------------------------------------------------------- 原生配置逐字节不变
    native_bytes = (FIX / "native.json").read_bytes()
    tmp = SB / "etc/momo/run/passthrough.json"
    write_bytes = getattr(tmp, "write_bytes", None)
    with open(tmp, "wb") as f:
        f.write(native_bytes)
    with open(SB / "etc/momo/run/config.json", "wb") as f:
        f.write(native_bytes)
    p = subprocess.run([SH, str(SB / "etc/momo/scripts/convert.sh"), str(tmp)],
                       capture_output=True, text=True, env=env, timeout=60)
    s.add("passthrough_byte_identical",
          p.returncode == 0 and tmp.read_bytes() == native_bytes,
          "原生 sing-box 配置零改动（%d bytes）" % len(native_bytes))

    # BOM / 首部空白的原生配置也必须走零改动快路径
    bom = SB / "etc/momo/run/bom.json"
    bom_bytes = b"\xef\xbb\xbf  \n" + native_bytes
    with open(bom, "wb") as f:
        f.write(bom_bytes)
    p = subprocess.run([SH, str(SB / "etc/momo/scripts/convert.sh"), str(bom)],
                       capture_output=True, text=True, env=env, timeout=60)
    s.add("passthrough_bom_identical",
          p.returncode == 0 and bom.read_bytes() == bom_bytes,
          "带 BOM 的原生配置同样零改动（快路径覆盖 BOM/空白）")

    # ------------------------------------- 原生订阅缺 momo 骨架：自动补齐而非退出
    native_obj = json.loads(native_bytes.decode("utf-8-sig"))
    broken = json.loads(json.dumps(native_obj))
    broken["inbounds"] = [ib for ib in broken.get("inbounds", [])
                          if ib.get("tag") != "dns-in"]
    broken["dns"]["servers"] = [s for s in broken["dns"]["servers"]
                                if s.get("tag") != "fake-ip-dns-server"]
    broken["route"]["rules"] = [r for r in broken["route"]["rules"]
                                if r.get("action") not in ("sniff", "hijack-dns")]
    repair_path = SB / "etc/momo/run/repair.json"
    write(repair_path, json.dumps(broken, ensure_ascii=False, indent=2) + "\n")
    write(SB / "var/log/momo/app.log", "")
    p = subprocess.run([SH, str(SB / "etc/momo/scripts/convert.sh"), str(repair_path)],
                       capture_output=True, text=True, env=env, timeout=60)
    try:
        cfg_rep = json.loads(repair_path.read_text(encoding="utf-8"))
    except ValueError:
        cfg_rep = {}
    in_tags_r = {i.get("tag") for i in cfg_rep.get("inbounds", []) if isinstance(i, dict)}
    dns_tags_r = {s_.get("tag") for s_ in cfg_rep.get("dns", {}).get("servers", [])
                  if isinstance(s_, dict)}
    rules_r = cfg_rep.get("route", {}).get("rules", [])
    chk_r = real_check(str(repair_path.resolve()).replace("\\", "/"))
    repair_log = (SB / "var/log/momo/app.log").read_text(encoding="utf-8", errors="replace")
    s.add("native_missing_inbound_repaired",
          p.returncode == 0 and "dns-in" in in_tags_r
          and "fake-ip-dns-server" in dns_tags_r
          and any(isinstance(r, dict) and r.get("action") == "hijack-dns" for r in rules_r)
          and any(isinstance(r, dict) and "dns-in" in (r.get("inbound") or []) for r in rules_r)
          and chk_r.get("rc") in (0, None)
          and "已自动补齐" in repair_log,
          "原生订阅缺 dns-in/fakeip 时自动补齐，momo Check 不再失败 (check=%s)"
          % chk_r.get("rc"), {"singbox_check": chk_r, "inbounds": sorted(in_tags_r)})

    strict_path = SB / "etc/momo/run/repair_strict.json"
    strict_bytes = json.dumps(broken, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    with open(strict_path, "wb") as f:
        f.write(strict_bytes)
    env_strict = dict(env)
    env_strict["MOMO_CONVERTER_REPAIR"] = "0"
    p = subprocess.run([SH, str(SB / "etc/momo/scripts/convert.sh"), str(strict_path)],
                       capture_output=True, text=True, env=env_strict, timeout=60)
    s.add("native_repair_switch_off",
          p.returncode == 0 and strict_path.read_bytes() == strict_bytes,
          "MOMO_CONVERTER_REPAIR=0 时严格透传，行为与集成前一致")

    # ------------------------ 旧格式原生订阅：DNS / inbound / 规则动作全套迁移
    legacy_path = SB / "etc/momo/run/native_legacy.json"
    copy(FIX / "native_legacy.json", legacy_path)
    p = subprocess.run([PY, str(SB / "etc/momo/scripts/momo_convert.py"),
                        "-i", str(legacy_path.resolve()).replace("\\", "/"), "--in-place",
                        "--template", str((SB / "etc/momo/converter/momo-base.json").resolve()).replace("\\", "/"),
                        "--conf", str((SB / "etc/momo/converter/converter.conf").resolve()).replace("\\", "/")],
                       capture_output=True, text=True, env=env, timeout=120)
    try:
        rep_l = json.loads(p.stdout)
    except ValueError:
        rep_l = {}
    try:
        cfg_l = json.loads(legacy_path.read_text(encoding="utf-8"))
    except ValueError:
        cfg_l = {}
    chk_l = real_check(str(legacy_path.resolve()).replace("\\", "/"))
    dns_srv_l = cfg_l.get("dns", {}).get("servers", [])
    in_l = cfg_l.get("inbounds", [])
    in_tags_l = {i.get("tag") for i in in_l if isinstance(i, dict)}
    dns_tags_l = {s_.get("tag") for s_ in dns_srv_l if isinstance(s_, dict)}
    s.add("legacy_native_migrated",
          p.returncode == 0 and rep_l.get("status") == "repaired"
          and dns_srv_l and all("address" not in s_ and s_.get("type") for s_ in dns_srv_l)
          and not any(k in i for i in in_l if isinstance(i, dict)
                      for k in ("sniff", "sniff_override_destination", "domain_strategy"))
          and not any("outbound" in r for r in cfg_l.get("dns", {}).get("rules", []))
          and all("action" in r for r in cfg_l.get("route", {}).get("rules", [])
                  if isinstance(r, dict) and "outbound" in r)
          and "dns-in" in in_tags_l and "fake-ip-dns-server" in dns_tags_l
          and chk_l.get("rc") in (0, None),
          "旧版 DNS/inbound/规则动作已迁移到 1.14 新格式 (check=%s, repairs=%d)"
          % (chk_l.get("rc"), len(rep_l.get("repairs") or [])),
          {"singbox_check": chk_l, "repairs": (rep_l.get("repairs") or [])[:8]})

    # 旧格式原生订阅端到端启动：补齐后 momo Check/Test 必须通过
    reset_case(profile="native_legacy.json")
    rl = run("start")
    cfg_e2e = final_config()
    chk_e2e = real_check() if cfg_e2e else {"rc": 1}
    s.add("e2e_native_legacy_start",
          rl["rc"] == 0 and "Test passed." in rl["app_log"]
          and (SB / "var/run/momo/started.flag").exists()
          and "Check failed" not in rl["app_log"]
          and chk_e2e.get("rc") in (0, None),
          "旧格式原生订阅可正常启动（不再 Check failed 退出）check=%s"
          % chk_e2e.get("rc"), {"app_log_tail": rl["app_log"][-700:]})

    src = (ROOT / "momo/files/scripts/momo_convert.py").read_text(encoding="utf-8")
    s.add("no_urllib_dependency",
          "from urllib" not in src and "import urllib" not in src,
          "不依赖 OpenWrt 独立分包 python3-urllib（python3-light 即可）")

    # --------------------------------------------------------------- 单元转换
    unit_cases = [
        ("nodes_uri.txt", 11, 0, "uri-list"),
        ("sub_base64.txt", 11, 0, "uri-list+base64"),
        ("clash.yaml", 7, 0, "clash-yaml"),
        ("clash_yaml_b64.txt", 7, 0, "clash-yaml+base64"),
        ("invalid_nodes.txt", 1, 4, "uri-list"),
        ("clash.json", 2, 0, "clash-json"),
        ("single_node.txt", 1, 0, "uri-list"),
        ("dup_nodes.txt", 3, 0, "uri-list"),
        ("partial_bad.txt", 1, 2, "uri-list"),
        # 各种订阅格式（新增）：同一套转换链路，只换输入格式
        ("clash_same_indent.yaml", 2, 0, "clash-yaml"),
        ("clash_tabs.yaml", 1, 0, "clash-yaml"),
        ("clash_nested_first.yaml", 3, 0, "clash-yaml"),
        ("surge.conf", 3, 0, "text-profile"),
        ("loon.conf", 3, 0, "text-profile"),
        ("quantumultx.conf", 3, 0, "text-profile"),
        ("sip008.json", 2, 0, "sip008"),
        ("nodes_array.json", 2, 0, "nodes-json"),
        ("uri_hysteria.txt", 3, 0, "uri-list"),
        ("uri_ssr_mixed.txt", 1, 1, "uri-list"),
        ("uri_base64_double.txt", 2, 0, "uri-list+base64x2"),
    ]
    for filename, expect_nodes, expect_skipped, expect_fmt in unit_cases:
        out = SB / "etc/momo/run/unit.json"
        if out.exists():
            out.unlink()
        p = subprocess.run([PY, str(SB / "etc/momo/scripts/momo_convert.py"),
                            "-i", str((FIX / filename).resolve()).replace("\\", "/"),
                            "-o", str(out.resolve()).replace("\\", "/"),
                            "--template", str((SB / "etc/momo/converter/momo-base.json").resolve()).replace("\\", "/"),
                            "--conf", str((SB / "etc/momo/converter/converter.conf").resolve()).replace("\\", "/")],
                           capture_output=True, text=True, env=env, timeout=120)
        try:
            report = json.loads(p.stdout)
        except ValueError:
            report = {}
        chk = real_check(str(out.resolve()).replace("\\", "/")) if out.exists() else {"rc": 1}
        ok = (p.returncode == 0 and report.get("status") == "converted"
              and report.get("nodes") == expect_nodes
              and len(report.get("skipped", [])) == expect_skipped
              and report.get("format") == expect_fmt
              and chk.get("rc") == 0)
        s.add("convert_" + filename, ok,
              "nodes=%s skipped=%s fmt=%s check=%s" % (report.get("nodes"),
                                                       len(report.get("skipped", [])),
                                                       report.get("format"), chk.get("rc")),
              {"report": report, "singbox_check": chk})

    for filename in ["bad.txt", "empty.txt"]:
        p = subprocess.run([PY, str(SB / "etc/momo/scripts/momo_convert.py"),
                            "-i", str((FIX / filename).resolve()).replace("\\", "/"),
                            "-o", str((SB / "etc/momo/run/unit.json").resolve()).replace("\\", "/"),
                            "--template", str((SB / "etc/momo/converter/momo-base.json").resolve()).replace("\\", "/")],
                           capture_output=True, text=True, env=env, timeout=60)
        s.add("reject_" + filename, p.returncode == 2,
              "异常输入被拒绝且不生成配置 (rc=%d)" % p.returncode)

    # --------------------------------------------- 代理节点分组（转换 + 驱动）
    converted_rules = test_group_conversion(s, env)
    test_group_driver(s, env, converted_rules)

    # ------------------------------------------- 远程规则集镜像测速选源
    test_ruleset_mirrors(s, env)

    # ------------------------------------------------------------ 端到端启动
    e2e = [
        ("e2e_native_regression", dict(profile="native.json"), False),
        ("e2e_uri_list", dict(profile="nodes_uri.txt"), True),
        ("e2e_base64_subscription", dict(subscription="sub_base64.txt", curl_source="sub_base64.txt"), True),
        ("e2e_clash_yaml", dict(profile="clash.yaml", curl_source="clash.yaml"), True),
        ("e2e_clash_yaml_b64", dict(profile="clash_yaml_b64.txt"), True),
        ("e2e_clash_json", dict(profile="clash.json"), True),
        ("e2e_single_node", dict(profile="single_node.txt"), True),
        ("e2e_invalid_nodes", dict(profile="invalid_nodes.txt"), True),
        ("e2e_clash_groups", dict(profile="clash_groups.yaml"), True),
    ]
    for name, kwargs, expect_converted in e2e:
        reset_case(**kwargs)
        r = run("start")
        cfg = final_config()
        started = (SB / "var/run/momo/started.flag").exists()
        test_passed = "Test passed." in r["app_log"]
        core_started = "Start." in r["app_log"] and "SET command" in r["procd_log"]
        converted = "已自动转换" in r["app_log"]
        chk = real_check() if cfg else {"rc": 1}
        ok = (r["rc"] == 0 and started and test_passed and core_started
              and converted == expect_converted and chk.get("rc") == 0
              and isinstance(cfg, dict) and len(cfg.get("outbounds", [])) >= 4)
        detail = ("started=%s test=%s procd=%s converted=%s check=%s outbounds=%s" %
                  (started, test_passed, core_started, converted, chk.get("rc"),
                   len(cfg.get("outbounds", [])) if cfg else "-"))
        s.add(name, ok, detail, {"app_log_tail": r["app_log"][-900:],
                                 "singbox_check": chk})
        if cfg:
            inbound_tags = {i.get("tag") for i in cfg.get("inbounds", [])}
            s.add(name + "_momo_contract",
                  {"dns-in", "redirect-in", "tproxy-in", "tun-in"} <= inbound_tags
                  and any(x.get("tag") == "fake-ip-dns-server" for x in cfg.get("dns", {}).get("servers", []))
                  and cfg.get("route", {}).get("final") in
                  {x.get("tag") for x in cfg.get("outbounds", [])},
                  "momo 必需 inbound / fakeip DNS / route.final 均齐备")

    # -------------------------- 端到端：分组配置应用 + 守护进程随 momo 启动
    reset_case(profile="clash_groups.yaml")
    os.environ["MOMO_GROUPD_ENABLED"] = "1"
    os.environ["MOMO_GROUPD_ARGS"] = "--once --rounds 1 --health-interval 0"
    rg = run("start")
    os.environ.pop("MOMO_GROUPD_ENABLED", None)
    os.environ.pop("MOMO_GROUPD_ARGS", None)
    cfg_g = final_config()
    rules_file = SB / "var/run/momo/groups.json"
    rules_g = json.loads(rules_file.read_text(encoding="utf-8")) if rules_file.exists() else {}
    types_g = {o.get("type") for o in cfg_g.get("outbounds", [])} if cfg_g else set()
    driver_started = False
    for _ in range(40):
        if "分组驱动启动" in (SB / "var/log/momo/app.log").read_text(
                encoding="utf-8", errors="replace"):
            driver_started = True
            break
        time.sleep(0.1)
    chk_g = real_check() if cfg_g else {"rc": 1}
    s.add("e2e_groups_applied_and_running",
          rg["rc"] == 0 and "Test passed." in rg["app_log"]
          and (SB / "var/run/momo/started.flag").exists()
          and "已自动转换" in rg["app_log"] and driver_started
          and "urltest" not in types_g
          and {"Auto-Test", "group-proxy", "auto"}
              <= {g.get("tag") for g in rules_g.get("groups", [])}
          and "proxy" not in {g.get("tag") for g in rules_g.get("groups", [])}
          and chk_g.get("rc") == 0,
          "分组订阅：自动转换 -> 应用 -> check/test/passed -> procd 启动 -> 分组驱动加载；"
          "rules=%d check=%s" % (len(rules_g.get("groups", [])), chk_g.get("rc")),
          {"app_log_tail": rg["app_log"][-900:], "singbox_check": chk_g})

    # ------------------------------------------- 原生配置回归：原有节点不被改写
    reset_case(profile="native.json")
    r = run("start")
    cfg = final_config()
    tags = {x.get("tag") for x in cfg.get("outbounds", [])} if cfg else set()
    s.add("native_profile_unchanged", "my-node" in tags and len(tags) == 5
          and "已自动转换" not in r["app_log"],
          "原有 profile 节点与出站数量保持不变 (tags=%d)" % len(tags))

    # 原生配置 + 上一轮残留规则：必须清理且守护进程绝不启动
    reset_case(profile="native.json")
    stale = SB / "var/run/momo/groups.json"
    write(stale, '{"stale": true}')
    os.environ["MOMO_GROUPD_ENABLED"] = "1"
    rn = run("start")
    os.environ.pop("MOMO_GROUPD_ENABLED", None)
    s.add("native_no_stale_group_rules",
          rn["rc"] == 0 and not stale.exists()
          and "分组驱动启动" not in rn["app_log"]
          and (SB / "var/run/momo/started.flag").exists(),
          "原生配置下残留规则被清理，即使驱动开关开启也不启动，原有启动链路不变")

    write(stale, '{"stale": true}')
    rs = run("stop")
    s.add("cleanup_removes_group_rules",
          rs["rc"] == 0 and not stale.exists(),
          "停止/重载时 cleanup 同步清理分组规则，不留下跨次运行的残留")

    # ------------------------------------------------ 异常输入：不破坏原有流程
    reset_case(profile="bad.txt")
    r = run("start")
    s.add("bad_input_graceful",
          r["rc"] == 0 and "自动转换跳过" in r["app_log"]
          and ("Check failed." in r["app_log"] or "Test failed." in r["app_log"])
          and not (SB / "var/run/momo/started.flag").exists(),
          "不可识别输入时转换跳过，momo 按原有 Check/Test 逻辑退出（无崩溃）",
          {"app_log_tail": r["app_log"][-700:]})

    # ------------------------------------------------------- 显式关闭转换插件
    reset_case(profile="nodes_uri.txt", converter_conf=(
        (ROOT / "momo/files/converter/converter.conf").read_text(encoding="utf-8")
        .replace("MOMO_CONVERTER_ENABLED=auto", "MOMO_CONVERTER_ENABLED=off")))
    r = run("start")
    s.add("converter_off_switch",
          "已自动转换" not in r["app_log"]
          and ("Check failed." in r["app_log"] or "Test failed." in r["app_log"]),
          "off 关闭后完全不介入，行为与集成前一致",
          {"app_log_tail": r["app_log"][-700:]})

    # ------------------------------------- 原有交互：update_subscription 回归
    reset_case(subscription="nodes_uri.txt", curl_source="nodes_uri.txt")
    before = (SB / "etc/momo/subscriptions/sub1.json").read_bytes()
    r = run("update", "sub1")
    after = (SB / "etc/momo/subscriptions/sub1.json").read_bytes()
    raw_expected = (FIX / "nodes_uri.txt").read_bytes()
    uci_calls = (SB / "uci_calls.log").read_text(encoding="utf-8", errors="replace")
    s.add("original_update_subscription",
          r["rc"] == 0 and after == raw_expected and "COMMIT" in uci_calls
          and "已自动转换" not in r["app_log"],
          "原有订阅更新交互保持：原始内容原样落盘、UCI 信息与调用不变")

    # ------------------------------------------- 订阅 UA：机场按 UA 下发不同格式
    def fixture(name):
        return str((FIX / name).resolve()).replace("\\", "/")

    # auto：clash.meta 拿到 HTML 报错页（该 UA 不被支持），应自动换 sing-box 拿 JSON
    reset_case(subscription="nodes_uri.txt",
               uci_overrides={"sub1.user_agent": "auto"},
               curl_map={"https://example.test/sub": {
                   "clash.meta": fixture("sub_error_page.html"),
                   "sing-box": fixture("sip008.json")}})
    r = run("update", "sub1")
    body = (SB / "etc/momo/subscriptions/sub1.json").read_bytes()
    ua_log = [l.split("\t")[0] for l in
              (SB / "curl_ua.log").read_text(encoding="utf-8", errors="replace").splitlines()
              if l.strip()]
    s.add("sub_ua_auto_fallback",
          r["rc"] == 0 and body == (FIX / "sip008.json").read_bytes()
          and ua_log == ["clash.meta", "sing-box"],
          "auto：clash.meta 返回 HTML 报错页时自动换下一个 UA，只有能解析的内容才落盘",
          {"ua_sequence": ua_log, "rc": r["rc"]})

    # 手动指定 UA：先发它，第一次就拿到能解析的内容 → 只发一次
    reset_case(subscription="nodes_uri.txt",
               uci_overrides={"sub1.user_agent": "v2rayN/6.31"},
               curl_map={"https://example.test/sub": {
                   "v2rayN/6.31": fixture("nodes_uri.txt")}})
    r = run("update", "sub1")
    body = (SB / "etc/momo/subscriptions/sub1.json").read_bytes()
    ua_log = [l.split("\t")[0] for l in
              (SB / "curl_ua.log").read_text(encoding="utf-8", errors="replace").splitlines()
              if l.strip()]
    s.add("sub_ua_pinned_first",
          r["rc"] == 0 and body == (FIX / "nodes_uri.txt").read_bytes()
          and ua_log == ["v2rayN/6.31"],
          "手动填写的 UA 优先发送，且拿到可解析内容就不再试探（只发一次请求）",
          {"ua_sequence": ua_log})

    # 钉死的 UA 被机场改了支持列表（返回 404/HTML）时，退回 auto 链而不是整次失败
    reset_case(subscription="nodes_uri.txt",
               uci_overrides={"sub1.user_agent": "sing-box"},
               curl_map={"https://example.test/sub": {
                   "sing-box": fixture("sub_error_page.html"),
                   "clash.meta": fixture("clash_same_indent.yaml")}})
    r = run("update", "sub1")
    body = (SB / "etc/momo/subscriptions/sub1.json").read_bytes()
    ua_log = [l.split("\t")[0] for l in
              (SB / "curl_ua.log").read_text(encoding="utf-8", errors="replace").splitlines()
              if l.strip()]
    s.add("sub_ua_pinned_then_auto",
          r["rc"] == 0 and body == (FIX / "clash_same_indent.yaml").read_bytes()
          and ua_log[:2] == ["sing-box", "clash.meta"],
          "钉死的 UA 失效（返回 HTML）时退回 auto 链继续尝试，订阅仍能更新",
          {"ua_sequence": ua_log})

    # 全链路失败：内容一律不可解析时保留上一份订阅、只标记 success=0
    reset_case(subscription="nodes_uri.txt",
               uci_overrides={"sub1.user_agent": "auto"},
               curl_map={"https://example.test/sub": {"*": fixture("sub_error_page.html")}})
    keep = (SB / "etc/momo/subscriptions/sub1.json").read_bytes()
    r = run("update", "sub1")
    body = (SB / "etc/momo/subscriptions/sub1.json").read_bytes()
    uci_calls = (SB / "uci_calls.log").read_text(encoding="utf-8", errors="replace")
    ua_log = [l.split("\t")[0] for l in
              (SB / "curl_ua.log").read_text(encoding="utf-8", errors="replace").splitlines()
              if l.strip()]
    s.add("sub_ua_all_fail_keeps_previous",
          r["rc"] == 0 and body == keep
          and "sub1 success 0" in uci_calls and len(ua_log) == 5,
          "所有 UA 都只拿到报错页时：订阅文件保持上一份、success=0，不写入垃圾内容",
          {"ua_sequence": ua_log, "keep": len(keep), "body": len(body), "rc": r["rc"]})

    # 迁移：旧的 user_agent=sing-box（旧版预填值）改 auto，手动填过其它值的不动
    migrate = (ROOT / "momo/files/uci-defaults/migrate.sh").read_text(encoding="utf-8")
    s.add("sub_ua_auto_migration",
          "sub_ua_migrated" in migrate and 'sub.user_agent' in migrate
          and '= "sing-box"' in migrate and "user_agent=auto" in migrate,
          "安装升级时把旧默认 UA（sing-box）迁到 auto，用户自定义 UA 保持不变")

    # ------------------------------------------------------- 默认值与接入点回归
    conf_text = (ROOT / "momo/files/momo.conf").read_text(encoding="utf-8")
    init_text = (ROOT / "momo/files/momo.init").read_text(encoding="utf-8")
    inc_text = (ROOT / "momo/files/scripts/include.sh").read_text(encoding="utf-8")
    defaults_ok = all(x in conf_text for x in [
        "option 'enabled' '0'", "option 'profile' 'file:example.json'",
        "option 'test_profile' '1'", "option 'core_only' '0'",
        "option 'tcp_mode' 'redirect'", "option 'udp_mode' 'tun'"])
    hooks_ok = ("extra_command 'update_subscription'" in init_text
                and "extra_command 'clear_logs'" in init_text
                and "config_get profile \"config\" \"profile\"" in init_text
                and "ucode -S \"$MIXIN_UC\"" in init_text
                and "$PROG -c \"$RUN_PROFILE_PATH\" format -w" in init_text
                and "json_dump" in inc_text
                and init_text.count('sh "$CONVERT_SH" "$RUN_PROFILE_PATH"') == 1)
    s.add("defaults_and_hook_minimal", defaults_ok and hooks_ok,
          "UCI 默认值、extra_command、mixin/format/check/run 链路均保持，仅新增 1 处转换钩子")

    paths_body = inc_text.split("get_paths()", 1)[-1].split("format_filesize()", 1)[0]
    s.add("groupd_hooks_minimal",
          init_text.count('sh "$GROUPD_SH" start') == 1
          and init_text.count('sh "$GROUPD_SH" stop') == 1
          and 'GROUPD_SH="$SH_DIR/groupd.sh"' in inc_text
          and "groupd" not in paths_body.lower()
          and "CONVERT_SH" not in paths_body,
          "分组驱动仅 2 处受保护钩子；get_paths()/RPC 路径输出与 UCI 选项均未变")

    luci_js = (ROOT / "luci-app-momo/htdocs/luci-static/resources/tools/momo.js").read_text(
        encoding="utf-8")
    s.add("luci_interaction_unchanged",
          "openDashboard" in luci_js
          and "external_control_ui_path" in conf_text
          and "option 'enabled' '0'" in conf_text,
          "LuCI 面板交互与 UCI 默认值保持原样（分组仍可在面板手动选择）")

    # ------------------------------------------------- 权限：RPCError 回归
    import importlib.util
    import stat as statmod

    acl = json.loads((ROOT / "luci-app-momo/root/usr/share/rpcd/acl.d/luci-app-momo.json")
                     .read_text(encoding="utf-8"))["luci-app-momo"]
    read_file, write_file = acl["read"]["file"], acl["write"]["file"]
    dirs = ["/etc/momo/profiles", "/etc/momo/subscriptions", "/etc/momo/run",
            "/etc/momo/converter", "/var/run/momo", "/var/log/momo", "/tmp/log/momo"]
    globs = ["/etc/momo/profiles/*", "/etc/momo/subscriptions/*",
             "/etc/momo/run/*", "/etc/momo/converter/*", "/var/run/momo/*",
             "/var/log/momo/*", "/tmp/log/momo/*"]
    acl_ok = (
        all("list" in read_file.get(d, []) for d in dirs)
        and all("read" in read_file.get(g, []) and "list" in read_file.get(g, [])
                for g in globs)
        and all("write" in write_file.get(g, []) for g in globs)
        and not any(k.endswith(".json") for k in read_file)
        and all(acl[group]["ubus"].get(obj) == ["*"]
                for group in ("read", "write")
                for obj in ("rc", "luci.momo", "file"))
    )
    s.add("rpcd_acl_permissions", acl_ok,
          "ACL 声明式补齐 list/read/write，覆盖非 json 订阅与 converter/规则文件")

    mk = (ROOT / "momo/Makefile").read_text(encoding="utf-8")
    luci_ucode = (ROOT / "luci-app-momo/root/usr/share/rpcd/ucode/luci.momo").read_text(
        encoding="utf-8")
    s.add("permissions_in_code_not_build",
          "chmod" not in mk
          and "fix_permissions()" in inc_text
          and "fix_permissions" in inc_text.split("prepare_files() {", 1)[-1]
          and "chmod 755" in inc_text and "chmod 644" in inc_text
          and "fix_permissions" in init_text
          and 'sh "$FIREWALL_INCLUDE_SH"' in init_text
          and "'sh', paths.debug_sh" in luci_ucode,
          "权限由 ACL 声明 + 运行期代码自愈，编译期不执行 chmod 命令")

    def load_module(name, path):
        spec = importlib.util.spec_from_file_location(name, str(path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    conv = load_module("momo_convert_perm", ROOT / "momo/files/scripts/momo_convert.py")
    groupd = load_module("momo_groupd_perm", ROOT / "momo/files/scripts/momo_groupd.py")
    perm_dir = SB / "perm"
    perm_dir.mkdir(parents=True, exist_ok=True)
    modes = []
    for mod, name in ((conv, "convert"), (groupd, "groupd")):
        p = perm_dir / (name + ".json")
        mod.atomic_write(str(p), "{}")
        modes.append(statmod.S_IMODE(p.stat().st_mode))
    s.add("atomic_write_0644",
          all(m & 0o044 == 0o044 and m & 0o111 == 0 for m in modes),
          "转换器/分组驱动原子写出的配置是 0644，LuCI(rpcd) 可读可写",
          {"modes": [oct(m) for m in modes]})

    # provider 下载 UA：机场同样按 UA 下发格式，provider 内可自覆盖
    pua = conv.provider_ua_map({"proxy-providers": {
        "p1": {"type": "http", "url": "https://a.test/1.yaml", "ua": "Shadowrocket"},
        "p2": {"type": "http", "url": "https://b.test/2.yaml",
               "header": {"User-Agent": "v2rayN/6.31"}},
        "p3": {"type": "http", "url": "https://c.test/3.yaml"},
        "p4": {"type": "http", "url": "https://d.test/4.yaml", "user-agent": "PassWall"},
    }})
    conv_src_full = (ROOT / "momo/files/scripts/momo_convert.py").read_text(encoding="utf-8")
    s.add("provider_user_agent",
          pua == {"https://a.test/1.yaml": "Shadowrocket",
                  "https://b.test/2.yaml": "v2rayN/6.31",
                  "https://d.test/4.yaml": "PassWall"}
          and 'MOMO_CONVERTER_PROVIDER_UA' in conv_src_full
          and '"-A", ua' in conv_src_full,
          "provider 自带 ua / user-agent / header.User-Agent 时按它下载，"
          "否则用 MOMO_CONVERTER_PROVIDER_UA（默认 clash.meta）",
          {"ua_map": pua})

    # ------------------------------------------------- 多格式兼容（行为级断言）
    # 机场订阅格式五花八门：Clash 同缩进序列 / Tab 缩进 / Surge / Loon /
    # Quantumult X / SIP008 / 节点数组 / 双层 base64 / 各种分享链接。
    # 这里直接调转换器的格式层，确认每种都能拿到节点而不是静默 0 节点。
    def nodes_of(name):
        raw = (FIX / name).read_bytes()
        return conv.extract_nodes(raw, {}, allow_providers=False)

    same_indent_nodes, same_indent_fmt, same_indent_groups = nodes_of("clash_same_indent.yaml")
    s.add("yaml_same_indent_sequence",
          len(same_indent_nodes) == 2 and same_indent_fmt == "clash-yaml"
          and same_indent_groups and same_indent_groups[0]["members_raw"] == ["HK-01", "JP-01"],
          "Clash 序列与父键同缩进（proxies:\\n- name:）也能解析，分组成员不丢",
          {"nodes": len(same_indent_nodes), "groups": len(same_indent_groups)})

    tab_nodes, tab_fmt, _ = nodes_of("clash_tabs.yaml")
    s.add("yaml_tab_indent",
          len(tab_nodes) == 1 and tab_fmt == "clash-yaml",
          "Tab 缩进的 Clash 配置按 4 空格归一后可解析")

    # 列表项的第一个键本身是嵌套 mapping（`- reality-opts:` 换行接 public-key），
    # 后面的兄弟键与键同列。旧实现只认「子块是序列」，这条及其后所有同层条目
    # 都会被判成脏数据丢掉（某订阅 32 条只剩 10 条）。
    nf_nodes, nf_fmt, nf_groups = nodes_of("clash_nested_first.yaml")
    nf_reality = [(n.get("tls") or {}).get("reality") or {} for n in nf_nodes]
    s.add("yaml_nested_first_key",
          len(nf_nodes) == 3 and nf_fmt == "clash-yaml"
          and [n["tag"] for n in nf_nodes] == ["SG-01", "SG-02", "JP-01"]
          and nf_reality[0].get("public_key") == "0_UOGGSOr0NZqCA-nQo-Ct0MjQPfghmBL_sh6XU5pW8"
          and nf_reality[2].get("short_id") == "e2d83572153be7ea"
          and nf_groups and nf_groups[0]["members_raw"] == ["SG-01", "SG-02", "JP-01"],
          "列表项首键是嵌套块（- reality-opts:）时节点与兄弟键都完整，"
          "后续同层条目不再失步丢弃，reality 公钥/short-id 保留",
          {"nodes": [n["tag"] for n in nf_nodes], "groups": [g["name"] for g in nf_groups]})

    # 双引号标量里的 \U0001F1ED 国旗码：机场模板常见，不解码节点名会显示成 "U0001F1ED"
    s.add("yaml_double_quoted_escape",
          conv.yaml_scalar(r'"\U0001F1ED\U0001F1F0香港02"') == "🇭🇰香港02"
          and conv.yaml_scalar(r'"a\tb"') == "a\tb"
          and conv.yaml_scalar("'it''s'") == "it's",
          "双引号标量的 \\U/\t 转义还原成真实字符，单引号里的 '' 还原为 '",
          {"flag": conv.yaml_scalar(r'"\U0001F1ED\U0001F1F0香港02"')})

    surge_nodes, surge_fmt, surge_groups = nodes_of("surge.conf")
    surge_vmess = next((n for n in surge_nodes if n["type"] == "vmess"), {})
    s.add("text_profile_surge",
          surge_fmt == "text-profile" and len(surge_nodes) == 3
          and [g["name"] for g in surge_groups] == ["Proxy", "Auto"]
          and surge_vmess.get("security") == "auto"
          and (surge_vmess.get("transport") or {}).get("type") == "ws"
          and (surge_vmess.get("tls") or {}).get("server_name") == "jp3.example.com",
          "Surge [Proxy]/[Proxy Group] 解析成节点与分组，ws/tls 参数正确",
          {"nodes": len(surge_nodes), "groups": [g["name"] for g in surge_groups]})

    qx_nodes, qx_fmt, _ = nodes_of("quantumultx.conf")
    qx_vmess = next((n for n in qx_nodes if n["type"] == "vmess"), {})
    s.add("text_profile_quantumultx",
          qx_fmt == "text-profile" and len(qx_nodes) == 3
          and qx_vmess.get("uuid") == "44444444-5555-6666-7777-888888888888"
          and qx_vmess.get("security") == "chacha20-poly1305"
          and (qx_vmess.get("tls") or {}).get("insecure") is True,
          "Quantumult X [server_local] 解析：password 当 UUID、cipher 归一化、"
          "tls-verification=false 转 insecure",
          {"nodes": len(qx_nodes), "vmess": qx_vmess})

    loon_nodes, loon_fmt, _ = nodes_of("loon.conf")
    s.add("text_profile_loon",
          loon_fmt == "text-profile" and len(loon_nodes) == 3
          and any((n.get("transport") or {}).get("type") == "ws" for n in loon_nodes),
          "Loon 位置参数写法（协议,主机,端口,方法,\"密码\"）也能解析")

    sip_nodes, sip_fmt, _ = nodes_of("sip008.json")
    s.add("sip008_supported",
          sip_fmt == "sip008" and len(sip_nodes) == 2
          and sip_nodes[0]["type"] == "shadowsocks"
          and sip_nodes[1].get("plugin") == "obfs-local",
          "SIP008（shadowsocks 订阅标准）解析，plugin/plugin_opts 一并保留",
          {"nodes": len(sip_nodes)})

    arr_nodes, arr_fmt, _ = nodes_of("nodes_array.json")
    s.add("nodes_array_json",
          arr_fmt == "nodes-json" and len(arr_nodes) == 2
          and {n["type"] for n in arr_nodes} == {"shadowsocks", "trojan"},
          "裸 JSON 数组（Clash 对象混排 sing-box 对象）也能取到节点")

    hy_nodes, hy_fmt, _ = nodes_of("uri_hysteria.txt")
    hy_v1 = next((n for n in hy_nodes if n["type"] == "hysteria"), {})
    s.add("uri_hysteria_v1_and_trojan_go",
          hy_fmt == "uri-list" and len(hy_nodes) == 3
          and hy_v1.get("auth_str") == "pass11" and hy_v1.get("up_mbps") == 30
          and any(n["type"] == "trojan" and (n.get("transport") or {}).get("type") == "ws"
                  for n in hy_nodes),
          "hysteria v1 / hysteria2 / trojan-go 三种分享链接都能转换",
          {"types": [n["type"] for n in hy_nodes]})

    # Shadowrocket（UA=Shadowrocket 下发）的写法：STATUS 状态行 + 整段 base64 的
    # `auto:uuid@host:port` + remark= 节点名 + tls/xtls/pbk/sid/fp 参数。
    sr_nodes, sr_fmt, _ = nodes_of("uri_shadowrocket.txt")
    sr_vless = next((n for n in sr_nodes if n["type"] == "vless"), {})
    sr_tls = sr_vless.get("tls") or {}
    sr_reality = sr_tls.get("reality") or {}
    s.add("uri_shadowrocket_style",
          sr_fmt == "uri-list" and len(sr_nodes) == 3
          and sr_vless.get("uuid") == "11111111-2222-3333-4444-555555555555"
          and sr_vless.get("flow") == "xtls-rprx-vision"
          and sr_tls.get("server_name") == "cloudflare.com"
          and (sr_tls.get("utls") or {}).get("fingerprint") == "ios"
          and sr_reality.get("enabled") is True
          and sr_reality.get("short_id") == "8f153b"
          and sr_vless.get("tag") == "🇭🇰 香港1"
          and any(n["type"] == "shadowsocks" and n.get("method") == "chacha20-ietf-poly1305"
                  for n in sr_nodes),
          "Shadowrocket 订阅：STATUS 行忽略、base64 的 auto:uuid@host:port 还原、"
          "remark 当节点名、tls/xtls→vision/pbk+sid→reality/fp→utls 全部落地，"
          "旧式 ss://<base64> 也能解",
          {"vless": sr_vless})

    ssr_nodes, ssr_fmt, _ = nodes_of("uri_ssr_mixed.txt")
    ssr_pool, ssr_skipped = conv.normalize_nodes(ssr_nodes, "dns_resolver", {}, {})
    s.add("ssr_reported_not_silent",
          ssr_fmt == "uri-list" and len(ssr_pool) == 1
          and any("ShadowsocksR" in x for x in ssr_skipped),
          "SSR 链接（sing-box 已移除）给出明确跳过原因，不再静默丢节点",
          {"nodes": len(ssr_pool), "skipped": ssr_skipped})

    wg_raw = b"wireguard://aGVsbG8=@wg.example.com:51820?publickey=abc#WG\n"
    conv.extract_nodes(wg_raw, {}, allow_providers=False)
    s.add("unsupported_scheme_reason",
          any("WireGuard" in x for x in conv.EXTRACT_SKIPS),
          "内核无法承载的 scheme（wireguard/juicity/naive）写进格式级跳过原因",
          {"skips": conv.EXTRACT_SKIPS})

    b64_nodes, b64_fmt, _ = nodes_of("uri_base64_double.txt")
    s.add("base64_double_layer",
          b64_fmt == "uri-list+base64x2" and len(b64_nodes) == 2,
          "两层 base64 包裹的订阅也能逐层解开",
          {"format": b64_fmt, "nodes": len(b64_nodes)})

    plugin_raw = (b"ss://YWVzLTI1Ni1nY206cA==@ss.example.com:8388"
                  b"?plugin=obfs-local%3Bobfs%3Dhttp%3Bobfs-host%3Dcdn.example.com#SS-OBFS\n")
    plugin_nodes, _, _ = conv.extract_nodes(plugin_raw, {}, allow_providers=False)
    s.add("ss_plugin_mapped",
          plugin_nodes and plugin_nodes[0].get("plugin") == "obfs-local"
          and "obfs-host=cdn.example.com" in plugin_nodes[0].get("plugin_opts", ""),
          "SIP002 ss:// 的 plugin 参数映射为 sing-box plugin/plugin_opts",
          {"node": plugin_nodes[0] if plugin_nodes else None})

    s.add("vmess_security_normalized",
          conv.normalize_vmess_security("chacha20-ietf-poly1305") == "chacha20-poly1305"
          and conv.normalize_vmess_security("aes-256-gcm") == "auto"
          and conv.normalize_vmess_security("") == "auto",
          "Surge/QX 把 SS cipher 填在 vmess 加密列时归一化，避免内核 "
          "unsupported security type 直接 FATAL")

    clash_plugin = conv.clash_to_singbox({
        "name": "p", "type": "ss", "server": "s.example.com", "port": 8388,
        "cipher": "aes-256-gcm", "password": "x",
        "plugin": "obfs", "plugin-opts": {"mode": "http", "host": "cdn.example.com"},
    })
    s.add("clash_ss_plugin_translated",
          clash_plugin.get("plugin") == "obfs-local"
          and clash_plugin.get("plugin_opts") == "obfs=http;obfs-host=cdn.example.com",
          "Clash 的 plugin: obfs + {mode,host} 翻译成 sing-box obfs-local 的 "
          "obfs=/obfs-host=，键名不同不再直接透传",
          {"node": clash_plugin})

    # utls 指纹：未显式写 client-fingerprint 时不应强制启用（与 Mihomo 默认一致），
    # 避免给没写指纹的节点硬加 chrome 指纹导致握手变慢/被限速/拒绝（延迟偏大）。
    vm_no_fp = conv.clash_to_singbox({
        "name": "VM", "type": "vmess", "server": "a.example.com", "port": 443,
        "uuid": "x", "cipher": "auto", "alterId": 0, "tls": True,
        "servername": "a.example.com",
    })
    vm_fp = conv.clash_to_singbox({
        "name": "VM2", "type": "vmess", "server": "a.example.com", "port": 443,
        "uuid": "x", "cipher": "auto", "alterId": 0, "tls": True,
        "servername": "a.example.com", "client-fingerprint": "chrome",
    })
    s.add("clash_utls_only_when_explicit",
          "utls" not in (vm_no_fp.get("tls") or {})
          and (vm_fp.get("tls") or {}).get("utls") == {"enabled": True, "fingerprint": "chrome"},
          "未写 client-fingerprint 不加 utls；显式 chrome 才启用（与 Mihomo 默认一致）",
          {"no_fp_tls": vm_no_fp.get("tls"), "fp_tls": vm_fp.get("tls")})

    # client-fingerprint: none 显式关闭指纹，不落 utls
    vm_none = conv.clash_to_singbox({
        "name": "VM3", "type": "vmess", "server": "a.example.com", "port": 443,
        "uuid": "x", "cipher": "auto", "alterId": 0, "tls": True,
        "servername": "a.example.com", "client-fingerprint": "none",
    })
    s.add("clash_utls_none_disabled",
          "utls" not in (vm_none.get("tls") or {}),
          "client-fingerprint: none 表示关闭指纹，不落 utls")

    # sing-box 1.14 的 reality 客户端强制要求 uTLS（内核报错：uTLS is required by
    # reality client），reality 节点必须带 utls，否则整份配置被内核拒绝。
    vl_reality = conv.clash_to_singbox({
        "name": "VL", "type": "vless", "server": "c.example.com", "port": 443,
        "uuid": "x", "tls": True, "client-fingerprint": "chrome",
        "reality-opts": {"public-key": "abc", "short-id": "abcd"},
    })
    vl_tls = vl_reality.get("tls") or {}
    s.add("clash_reality_requires_utls",
          (vl_tls.get("utls") or {}).get("enabled") is True
          and (vl_tls.get("reality") or {}).get("enabled") is True
          and (vl_tls.get("reality") or {}).get("public_key") == "abc",
          "reality 节点必须带 utls（内核强制），reality 公钥/short-id 保留",
          {"tls": vl_tls})

    # vmess over reality：仅判断 tls 会丢 reality-opts，需按 reality-opts/servername 兜底
    vm_reality = conv.clash_to_singbox({
        "name": "VMR", "type": "vmess", "server": "c.example.com", "port": 443,
        "uuid": "x", "cipher": "auto", "alterId": 0, "servername": "real.example.com",
        "reality-opts": {"public-key": "abc"},
    })
    vm_rt = vm_reality.get("tls") or {}
    s.add("clash_vmess_reality_mapped",
          (vm_rt.get("reality") or {}).get("enabled") is True
          and vm_rt.get("server_name") == "real.example.com"
          and (vm_rt.get("utls") or {}).get("enabled") is True,
          "vmess 带 reality-opts 时正确生成 tls+reality+utls，不再因只判 tls 而丢失",
          {"tls": vm_rt})

    try:
        conv.extract_nodes(b"just some random text\n", {}, allow_providers=False)
        unknown_ok = False
    except conv.ConvertError as exc:
        unknown_ok = "SIP008" in str(exc) and "Surge" in str(exc)
    s.add("unknown_format_message", unknown_ok,
          "完全无法识别的输入给出列全支持格式的错误信息")

    rpcd_acl = SB / "usr/share/rpcd/acl.d/luci-app-momo.json"
    rpcd_ucode = SB / "usr/share/rpcd/ucode/luci.momo"
    rpcd_acl.parent.mkdir(parents=True, exist_ok=True)
    rpcd_ucode.parent.mkdir(parents=True, exist_ok=True)
    write(rpcd_acl, "{}", 0o000)
    write(rpcd_ucode, "#!/usr/bin/ucode\n", 0o000)
    for f in (SB / "etc/momo/scripts").glob("*.sh"):
        os.chmod(f, 0o644)
    env = dict(os.environ)
    env["IPKG_INSTROOT"] = SB_MSYS
    proc = subprocess.run(
        [SH, "-c", '. "%s/etc/momo/scripts/include.sh" && prepare_files' % SB_MSYS],
        capture_output=True, text=True, env=env, timeout=30)
    acl_mode = statmod.S_IMODE(rpcd_acl.stat().st_mode)
    ucode_mode = statmod.S_IMODE(rpcd_ucode.stat().st_mode)
    posix = os.name != "nt"  # Windows/NTFS 无法观测执行位，只校验可读位
    healed = (proc.returncode == 0
              and acl_mode & 0o444 == 0o444
              and ucode_mode & 0o444 == 0o444
              and (not posix or ucode_mode & 0o111 != 0))
    s.add("fix_permissions_self_heal", healed,
          "运行期自动修复 rpcd ACL/ucode 与脚本权限，无需编译期 chmod",
          {"rc": proc.returncode, "modes": [oct(acl_mode), oct(ucode_mode)],
           "stdout": proc.stdout[-200:], "stderr": proc.stderr[-200:]})

    reset_case(profile="nodes_uri.txt")
    for f in (SB / "etc/momo/scripts").glob("*.sh"):
        os.chmod(f, 0o644)
    os.chmod(SB / "etc/init.d/momo", 0o644)
    r = run("start")
    sh_modes = [statmod.S_IMODE(f.stat().st_mode)
                for f in (SB / "etc/momo/scripts").glob("*.sh")]
    s.add("no_exec_bit_start",
          r["rc"] == 0 and "OPEN" in r["procd_log"] and "已自动转换" in r["app_log"]
          and all(m & 0o444 == 0o444 for m in sh_modes)
          and (not posix or all(m & 0o111 != 0 for m in sh_modes)),
          "脚本无执行位时启动链路仍正常，并自动恢复执行位",
          {"rc": r["rc"], "modes": [oct(m) for m in sh_modes],
           "procd_log": r["procd_log"][-200:], "app_log": r["app_log"][-300:]})

    reset_case(subscription="nodes_uri.txt", curl_source="nodes_uri.txt")
    r = run("update", "sub1")
    sub_file = SB / "etc/momo/subscriptions/sub1.json"
    sub_mode = statmod.S_IMODE(sub_file.stat().st_mode)
    s.add("subscription_file_mode",
          r["rc"] == 0 and sub_mode & 0o044 == 0o044,
          "订阅下载落盘后为可读文件，LuCI 编辑器不会 RPCError",
          {"mode": oct(sub_mode)})

    # -------------------------------- proxy-providers / YAML 锚点 / 动态授权
    prov_url = "https://provider.test/airport"
    prov_cache = Path(tempfile.mkdtemp(prefix="momo-prov-cache-"))
    (prov_cache / (conv.provider_cache_key(prov_url) + ".txt")).write_text(
        (FIX / "provider_payload.yaml").read_text(encoding="utf-8"), encoding="utf-8")

    expanded = conv.expand_yaml_aliases(
        (FIX / "provider_main.yaml").read_text(encoding="utf-8"))
    s.add("yaml_anchor_expansion",
          "include-all: true" in expanded and "type: url-test" in expanded
          and "<<:" not in expanded,
          "Mihomo 模板的 &锚点 / << 合并键被展开，分组测速与 include-all 规则不丢失")

    reset_case(profile="provider_main.yaml")
    r = run("start", extra_env={
        "MOMO_CONVERTER_PROVIDERS": "1",
        "MOMO_CONVERTER_PROVIDER_CACHE": str(prov_cache).replace("\\", "/"),
        "MOMO_CONVERTER_PROVIDER_TTL": "999999",
        "MOMO_CONVERTER_RULESET": "0",
    })
    cfg = final_config()
    s.add("provider_template_e2e",
          r["rc"] == 0 and "已自动转换" in r["app_log"] and cfg is not None
          and len(cfg.get("outbounds", [])) > 5 and '"nodes": 2' in r["app_log"],
          "proxies 只有 direct 的模板配置也能从 proxy-providers 取到节点并启动",
          {"app_log": r["app_log"][-400:]})

    reset_case(profile="provider_main.yaml")
    r2 = run("start", extra_env={
        "MOMO_CONVERTER_PROVIDERS": "0",
        "MOMO_CONVERTER_PROVIDER_CACHE": str(prov_cache).replace("\\", "/"),
        "MOMO_CONVERTER_PROVIDER_TTL": "999999"})
    s.add("provider_switch_off",
          "未提取到可用节点" in r2["app_log"] and "已自动转换" not in r2["app_log"],
          "MOMO_CONVERTER_PROVIDERS=0 时完全不下载 provider，保持原行为",
          {"app_log": r2["app_log"][-300:]})

    empty_cache = Path(tempfile.mkdtemp(prefix="momo-prov-empty-"))
    reset_case(profile="provider_main.yaml")
    r3 = run("start", extra_env={
        "MOMO_CONVERTER_PROVIDERS": "1",
        "MOMO_CONVERTER_PROVIDER_CACHE": str(empty_cache).replace("\\", "/"),
        "MOMO_CONVERTER_PROVIDER_CURL": "momo-no-such-curl"})
    s.add("provider_offline_graceful",
          r3["rc"] == 0 and "未提取到可用节点" in r3["app_log"]
          and "Traceback" not in r3["app_log"],
          "provider 下载失败/无缓存时优雅降级，不崩溃、不阻断原有启动链路",
          {"app_log": r3["app_log"][-300:]})

    # -------------------------------- 混乱订阅：分组筛选 / 分流规则 / 占位节点
    messy = (FIX / "messy_clash.yaml").read_text(encoding="utf-8")
    messy_conf = {"MOMO_CONVERTER_RULESET_VERIFY": "0", "MOMO_CONVERTER_RULES": "512"}
    m_nodes, m_fmt, m_groups = conv.extract_nodes(
        messy.encode(), {"MOMO_CONVERTER_PROVIDERS": "0"})
    m_nodes, m_skipped = conv.normalize_nodes(m_nodes, "dns_resolver", {}, messy_conf)
    m_tags = [n["tag"] for n in m_nodes]
    m_groups, m_name_map = conv.assign_group_tags(m_groups, m_tags)
    m_groups = conv.resolve_group_members(m_groups, m_name_map, {}, m_tags)
    by_tag = dict((g["tag"], g) for g in m_groups)

    hk = by_tag.get("香港自动", {}).get("members") or []
    jp = by_tag.get("日本自动", {}).get("members") or []
    us = by_tag.get("美国自动", {}).get("members") or []
    s.add("clash_group_filter_applied",
          m_fmt.startswith("clash-yaml") and len(m_tags) == 4
          and hk and all("香港" in t for t in hk)
          and len(hk) == 2 and len(jp) == 1 and len(us) == 1
          and len(hk) < len(m_tags),
          "include-all + filter/exclude-filter 按 mihomo 语义筛选，分组不再合并成全部节点",
          {"hk": hk, "jp": jp, "us": us, "nodes": m_tags})

    s.add("clash_junk_nodes_dropped",
          not any("剩余流量" in t or "官网更新" in t for t in m_tags)
          and any("占位节点" in x for x in m_skipped),
          "机场「剩余流量/去官网」占位节点被剔除，不参与测速与自动分组",
          {"skipped": m_skipped, "tags": m_tags})

    admisc = by_tag.get("广告杂项自动组", {})
    s.add("clash_filter_miss_reported",
          admisc.get("filter_miss") == "*AdMisc"
          and len(admisc.get("members") or []) == len(m_tags),
          "filter 命不中任何节点（如 *AdMisc）时回退全部节点并在报告中标记 filter_miss，"
          "不再静默把组伪装成正常筛选结果",
          {"admisc": admisc})

    s.add("clash_global_group_kept",
          "GLOBAL" in by_tag and "GLOBAL" in m_name_map,
          "订阅自带的 GLOBAL 分组保留原名，不被内置别名改名")

    conf_rules = conv.compile_clash_rules(m_groups, m_name_map, messy_conf,
                                          conv.RULESET_MIRRORS[0])
    rules_out = conf_rules["rules"]
    final_tag = conf_rules["final"]
    rs_tags = [d["tag"] for d in conf_rules["rule_sets"]]
    logical = [r for r in rules_out if r.get("type") == "logical"]
    s.add("clash_rules_converted",
          len(rules_out) >= 5 and final_tag == "漏网之鱼"
          and any(r.get("rule_set") == ["geosite-youtube"] for r in rules_out)
          and any(r.get("domain_suffix") == ["github.com"]
                  and r.get("outbound") == "GitHub" for r in rules_out)
          and any(r.get("ip_cidr") == ["10.0.0.0/8"] for r in rules_out)
          and logical and logical[0].get("outbound") == "block"
          and any(s.get("rule_set") == ["geoip-cn"] for s in logical[0]["rules"])
          and any(s.get("network") == "udp" for s in logical[0]["rules"]),
          "订阅 rules 转成 sing-box 规则：RULE-SET/GEOSITE/DOMAIN/IP-CIDR/AND/MATCH 全部落地",
          {"rules": rules_out[:6], "final": final_tag, "rule_sets": rs_tags})

    s.add("clash_policy_alias_and_unmapped",
          any(r.get("domain_suffix") == ["taobao.com"] and r.get("outbound") == "direct"
              for r in rules_out)
          and any(r.get("outbound") == "广告拦截"
                  and r.get("domain_keyword") == ["ads"] for r in rules_out)
          and not any("fakeipfilter" in json.dumps(r) for r in rules_out)
          and "fakeipfilter_cn" in conf_rules["unmapped_providers"]
          and all(u.startswith("http") for u in
                  [d["url"] for d in conf_rules["rule_sets"]]),
          "「直连」等中文别名映射为 direct；无法映射的 provider 整条跳过，绝不给配置塞 404 URL",
          {"unmapped": conf_rules["unmapped_providers"],
           "dropped": conf_rules["dropped"]})

    s.add("clash_unsupported_condition_dropped",
          not any("curl" in json.dumps(r) for r in rules_out)
          and any("PROCESS-NAME" in x for x in conf_rules["dropped"]),
          "PROCESS-NAME 等 sing-box 无等价能力的条件整条丢弃，不让转换失败",
          {"dropped": conf_rules["dropped"]})

    m_cfg = conv.build_config(m_nodes, conv.load_template(
        str(ROOT / "momo/files/converter/momo-base.json")), m_groups, "127.0.0.1:9090")
    conv.inject_clash_rules(m_cfg, conf_rules)
    conv.apply_ruleset(m_cfg, conv.prepare_ruleset({"MOMO_CONVERTER_RULESET": "0"}))
    m_rules_out = conv.build_group_rules(m_groups, m_tags, "127.0.0.1:9090", "", m_cfg)
    ui_groups = [g["tag"] for g in m_rules_out["groups"]]
    defined = {rs.get("tag") for rs in m_cfg["route"].get("rule_set") or []}
    refs = set()
    for rule in m_cfg["route"]["rules"]:
        refs.update(rule.get("rule_set") or [])
        for sub in rule.get("rules") or []:
            refs.update(sub.get("rule_set") or [])
    s.add("clash_no_extra_builtin_groups",
          "proxy" not in ui_groups and "auto" not in ui_groups
          and ui_groups == [g["tag"] for g in m_groups]
          and m_cfg["route"]["final"] == "漏网之鱼",
          "订阅自带分组时不再注入 proxy/auto，面板分组与订阅完全一致",
          {"ui_groups": ui_groups})
    s.add("clash_rule_set_refs_resolved",
          refs <= defined and m_cfg["route"]["rules"][3].get("ip_is_private") is True
          and any(rule.get("rule_set") == ["geosite-youtube"]
                  for rule in m_cfg["route"]["rules"]),
          "分流规则插在私网直连之后、模板国内直连之前，且引用的规则集全部有定义")

    # 国内直连分流：模板引用 geosite-cn/geoip-cn，规则集未注入时引用自动清理
    tpl_text = (ROOT / "momo/files/converter/momo-base.json").read_text(encoding="utf-8")
    conv_text = (ROOT / "momo/files/scripts/momo_convert.py").read_text(encoding="utf-8")
    s.add("cn_direct_split_rules",
          '"geosite-cn"' in tpl_text and '"geoip-cn"' in tpl_text
          and tpl_text.count('"outbound": "direct"') >= 2
          and '"server": "dns_resolver"' in tpl_text,
          "模板含 geosite-cn/geoip-cn -> direct 与国内 DNS 解析规则，国内流量不再全量走代理")
    s.add("rule_set_dangling_ref_prune",
          "prune_missing_rule_sets" in conv_text
          and conv_text.count("prune_missing_rule_sets(cfg)") >= 3,
          "规则集定义缺失时自动移除悬空引用规则，离线降级不阻塞 momo 启动")

    # ------------------------------------- 脏模板：dns 段失步不拖累后续段 / 块锚点展开
    dirty = (FIX / "messy_sections.yaml").read_text(encoding="utf-8")
    dirty_doc = conv.parse_yaml_subset(conv.expand_yaml_aliases(dirty))
    d_groups = dirty_doc.get("proxy-groups") or []
    d_by_name = dict((g.get("name"), g) for g in d_groups)
    s.add("yaml_section_resync_after_broken",
          len(d_groups) == 2 and len(dirty_doc.get("rules") or []) == 3
          and "Airport-A" in (dirty_doc.get("proxy-providers") or {})
          and dirty_doc.get("proxies"),
          "dns 段缩进错位/键带冒号时不再截断整份文档，后面的 proxy-groups/rules/providers 全保留",
          {"groups": [g.get("name") for g in d_groups],
           "rules": len(dirty_doc.get("rules") or [])})
    s.add("yaml_block_anchor_expanded",
          (d_by_name.get("香港自动") or {}).get("type") == "url-test"
          and (d_by_name.get("香港自动") or {}).get("exclude-filter") == "过期|剩余"
          and (d_by_name.get("香港自动") or {}).get("use") == "*provs"
          and (d_by_name.get("香港自动") or {}).get("filter") == "(?i)港|HK",
          "块状锚点 `key: &anchor` + `<<: *anchor` 正确展开，url-test/use/exclude-filter 不再丢失",
          {"group": d_by_name.get("香港自动")})

    # -------------------------------- 全是占位节点：降级为全局直连而不是让内核退出
    junk_out = SB / "etc/momo/run/junk.json"
    if junk_out.exists():
        junk_out.unlink()
    jp = subprocess.run([PY, str(SB / "etc/momo/scripts/momo_convert.py"),
                         "-i", str((FIX / "all_junk.yaml").resolve()).replace("\\", "/"),
                         "-o", str(junk_out.resolve()).replace("\\", "/"),
                         "--template", str((SB / "etc/momo/converter/momo-base.json").resolve()).replace("\\", "/"),
                         "--conf", str((SB / "etc/momo/converter/converter.conf").resolve()).replace("\\", "/")],
                        capture_output=True, text=True, env=env, timeout=120)
    try:
        jrep = json.loads(jp.stdout)
    except ValueError:
        jrep = {}
    jcfg = json.loads(junk_out.read_text(encoding="utf-8")) if junk_out.exists() else {}
    jchk = real_check(str(junk_out.resolve()).replace("\\", "/")) if junk_out.exists() else {"rc": 1}
    j_dns = jcfg.get("dns") or {}
    j_servers = j_dns.get("servers") or []
    s.add("no_usable_nodes_safe_mode",
          jp.returncode == 0 and jrep.get("status") == "degraded"
          and jcfg.get("route", {}).get("final") == "direct"
          and jchk.get("rc") == 0
          and any(s_.get("tag") == "dns-in" for s_ in jcfg.get("inbounds") or [])
          and any(s_.get("type") == "fakeip" for s_ in j_servers)
          and not any(r.get("server") == "fake-ip-dns-server"
                      for r in (j_dns.get("rules") or []))
          and j_dns.get("final") != "fake-ip-dns-server",
          "全是占位节点时输出「全局直连」合法配置（保留 fakeip 服务端但不使用），"
          "momo 能正常启动而不是 DNS inbound not found 退出",
          {"rc": jp.returncode, "report": jrep, "check": jchk,
           "dns_final": j_dns.get("final")})

    conv_src = (ROOT / "momo/files/scripts/momo_convert.py").read_text(encoding="utf-8")
    fetch_body = conv_src.split("def fetch_provider_bodies", 1)[1].split(
        "def collect_provider_nodes", 1)[0]
    s.add("provider_cache_dir_bootstrap",
          0 <= fetch_body.find("os.makedirs(cache_dir")
          < fetch_body.find("subprocess.Popen"),
          "首轮下载前先建缓存目录，避免 curl -o 因目录不存在而全部失败")

    get_paths_body = inc_text.split("get_paths() {", 1)[-1].split("format_filesize()", 1)[0]
    # 去掉注释行再判断，避免说明文字里的 grant_rpcd_acl 误伤
    get_paths_code = "\n".join(line for line in get_paths_body.splitlines()
                               if not line.strip().startswith("#"))
    s.add("rpcd_live_grant_no_restart",
          "grant_rpcd_acl" in inc_text and "session grant" in inc_text
          and '\\"scope\\":\\"file\\"' in inc_text
          and '\\"scope\\":\\"ubus\\"' in inc_text and "session list" in inc_text
          and 'for f in read write list' in inc_text and '[\\"$p\\",\\"$f\\"]' in inc_text
          # 新约束：get_paths 是每次页面加载都会走的纯查询路径，绝不能再 fork
          # 子进程去 ubus 自调用（rpcd 单线程，会把自己堵死 → RPCError）。
          # 补权改在启动流程 fix_permissions / ensure_rpcd_plugin 与安装后 postinst。
          and "grant_rpcd_acl" not in get_paths_code
          and "&" not in get_paths_code
          and "grant_rpcd_acl" in inc_text.split("fix_permissions() {", 1)[-1]
          and "ensure_rpcd_plugin" in inc_text
          and "ensure_rpcd_plugin" in init_text
          and "grant_rpcd_acl" in mk
          and "chmod" not in mk,
          "ACL 在启动/安装时补齐，get_paths 保持纯查询（不再 fork 子进程拖死 rpcd）")

    pf = SB / "etc/momo/profiles/user.yaml"
    write(pf, "proxies: []\n", 0o600)
    proc = subprocess.run(
        [SH, "-c", '. "%s/etc/momo/scripts/include.sh" && prepare_files' % SB_MSYS],
        capture_output=True, text=True, env=env, timeout=30)
    pf_mode = statmod.S_IMODE(pf.stat().st_mode)
    s.add("user_profile_mode_healed",
          proc.returncode == 0 and pf_mode & 0o444 == 0o444,
          "上传的 0600 订阅/配置自动放成可读，LuCI 编辑器不再 RPCError",
          {"mode": oct(pf_mode), "stderr": proc.stderr[-200:]})

    # ------------------------------------------------------------- 汇总
    summary = s.summary()
    payload = {
        "generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "environment": {
            "python": sys.version.split()[0],
            "shell": SH,
            "sing_box_binary": SING_BOX_REAL or "(not found, JSON-only validation)",
            "sandbox": SB_WIN,
            "third_party_python_packages": [],
        },
        "summary": summary,
        "cases": s.results,
    }
    write(RESULTS, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print("\n==== SUMMARY: %d/%d PASS ====" % (summary["passed"], summary["total"]))
    print("results -> %s" % RESULTS)
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
