#!/usr/bin/env python3
"""ucode 桩：等价模拟 mixin.uc 的 UCI -> 运行配置 merge（trim_all 语义）。"""
import json
import os
import sys

# 与 momo/files/ucode/mixin.uc 一一对应
MAP = {
    "log.disabled": ("mixin", "log_disabled", "bool"),
    "log.level": ("mixin", "log_level", "str"),
    "log.timestamp": ("mixin", "log_timestamp", "bool"),
    "log.output": ("mixin", "log_output", "str"),
    "dns.strategy": ("mixin", "dns_strategy", "str"),
    "dns.disable_cache": ("mixin", "dns_disable_cache", "bool"),
    "dns.disable_expire": ("mixin", "dns_disable_expire", "bool"),
    "dns.cache_capacity": ("mixin", "dns_cache_capacity", "int"),
    "dns.reverse_mapping": ("mixin", "dns_reverse_mapping", "bool"),
    "ntp.enabled": ("mixin", "ntp_enabled", "bool"),
    "ntp.server": ("mixin", "ntp_server", "str"),
    "ntp.server_port": ("mixin", "ntp_server_port", "int"),
    "ntp.interval": ("mixin", "ntp_interval", "str"),
    "experimental.cache_file.enabled": ("mixin", "cache_enabled", "bool"),
    "experimental.cache_file.path": ("mixin", "cache_path", "str"),
    "experimental.cache_file.store_fakeip": ("mixin", "cache_store_fakeip", "bool"),
    "experimental.cache_file.store_dns": ("mixin", "cache_store_rdrc", "bool"),
    "experimental.clash_api.external_ui": ("mixin", "external_control_ui_path", "str"),
    "experimental.clash_api.external_ui_download_url": ("mixin", "external_control_ui_download_url", "str"),
    "experimental.clash_api.external_controller": ("mixin", "external_control_api_listen", "str"),
    "experimental.clash_api.secret": ("mixin", "external_control_api_secret", "str"),
}


def main():
    root = os.environ.get("MOMO_TEST_ROOT", "")
    profile = os.path.join(root, "etc/momo/run/config.json")
    uci_map_path = os.path.join(root, "uci_map.json")
    try:
        with open(profile, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        return 0  # 非 JSON 配置：保持原样，交由后续 format/check 按原有逻辑处理
    with open(uci_map_path, "r", encoding="utf-8") as f:
        uci_map = json.load(f)
    for path, (section, option, kind) in MAP.items():
        value = uci_map.get("%s.%s" % (section, option))
        if value is None or value == "":
            continue  # trim_all 会删掉空值
        if kind == "bool":
            value = str(value) == "1"
        elif kind == "int":
            try:
                value = int(value)
            except ValueError:
                continue
        node = cfg
        keys = path.split(".")
        for key in keys[:-1]:
            node = node.setdefault(key, {})
        node[keys[-1]] = value
    with open(profile, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
