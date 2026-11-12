#!/bin/sh

. "$IPKG_INSTROOT/etc/momo/scripts/include.sh"

# since v1.0.2

section_placeholder=$(uci -q get momo.placeholder); [ -z "$section_placeholder" ] && uci set momo.placeholder="placeholder"

# since v1.1.0

proxy_bypass_china_mainland_ip=$(uci -q get momo.proxy.bypass_china_mainland_ip)
proxy_bypass_china_mainland_ip6=$(uci -q get momo.proxy.bypass_china_mainland_ip6)
[ -z "$proxy_bypass_china_mainland_ip6" ] && uci set momo.proxy.bypass_china_mainland_ip6=$proxy_bypass_china_mainland_ip

routing_tproxy_fw_mask=$(uci -q get momo.routing.tproxy_fw_mask); [ -z "$routing_tproxy_fw_mask" ] && uci set momo.routing.tproxy_fw_mask=0xFF
routing_tun_fw_mask=$(uci -q get momo.routing.tun_fw_mask); [ -z "$routing_tun_fw_mask" ] && uci set momo.routing.tun_fw_mask=0xFF

procd=$(uci -q get momo.procd); [ -z "$procd" ] && {
	uci set momo.procd=procd
	uci set momo.procd.fast_reload=$(uci -q get momo.config.fast_reload)
	uci del momo.config.fast_reload
}

# since v1.1.1

dummy_device=$(uci -q get momo.routing.dummy_device); [ -z "$dummy_device" ] && uci set momo.routing.dummy_device=momo-dummy

# since v1.1.2

config_scheduled_restart_cron=$(uci -q get momo.config.scheduled_restart_cron); [ -z "$config_scheduled_restart_cron" ] && uci rename momo.config.cron_expression="scheduled_restart_cron"

section_log=$(uci -q get momo.log); [ -z "$section_log" ] && {
	uci set momo.log=log
	uci set momo.log.scheduled_clear=1
	uci set momo.log.scheduled_clear_cron="*/5 * * * *"
	uci set momo.log.scheduled_clear_size_limit=1
	uci set momo.log.scheduled_clear_size_limit_unit=MB
}

section_mixin=$(uci -q get momo.mixin); [ -z "$section_mixin" ] && {
	uci set momo.mixin=mixin
	uci set momo.mixin.log_disabled='0'
	uci set momo.mixin.log_level='error'
	uci set momo.mixin.log_timestamp='1'
	uci set momo.mixin.dns_independent_cache='1'
	uci set momo.mixin.dns_reverse_mapping='1'
	uci set momo.mixin.cache_enabled='1'
	uci set momo.mixin.cache_store_fakeip='1'
	uci set momo.mixin.cache_store_rdrc='1'
	uci set momo.mixin.external_control_ui_path='ui'
	uci set momo.mixin.external_control_ui_download_url='https://github.com/Zephyruso/zashboard/releases/latest/download/dist-cdn-fonts.zip'
}

# since v1.2.1
config_clear_at_stop=$(uci -q get momo.log.clear_at_stop); [ -z "$config_clear_at_stop" ] && uci set momo.log.clear_at_stop=1

# 日志级别默认 error（仅首次迁移；已经手动设了其它级别的不动）
mixin_log_level_migrated=$(uci -q get momo.mixin.log_level_migrated)
[ "$mixin_log_level_migrated" != 1 ] && {
	cur_log_level=$(uci -q get momo.mixin.log_level)
	case "$cur_log_level" in
		""|info) uci set momo.mixin.log_level='error' ;;
	esac
	uci set momo.mixin.log_level_migrated=1
}

# since 订阅转换插件集成
# API 监听默认 0.0.0.0:15425：面板与分组驱动都要能连上（旧配置未设置时补齐）
mixin_api_listen=$(uci -q get momo.mixin.external_control_api_listen)
[ -z "$mixin_api_listen" ] && uci set momo.mixin.external_control_api_listen='0.0.0.0:15425'

# 定时重启默认取消勾选（仅迁移一次，之后尊重用户手动设置）
config_scheduled_restart_migrated=$(uci -q get momo.config.scheduled_restart_migrated)
[ "$config_scheduled_restart_migrated" != 1 ] && {
	uci set momo.config.scheduled_restart=0
	uci set momo.config.scheduled_restart_migrated=1
	if [ -z "$IPKG_INSTROOT" ] && [ -f /etc/crontabs/root ]; then
		sed -i "/#momo scheduled restart/d" /etc/crontabs/root > /dev/null 2>&1
		/etc/init.d/cron reload > /dev/null 2>&1
	fi
}

# 日志定时清理默认勾选（仅迁移一次；用新的标记名，老配置里的 0 也会切过来）
section_scheduled_clear_migrated=$(uci -q get momo.log.scheduled_clear_defaulted)
[ "$section_scheduled_clear_migrated" != 1 ] && {
	uci set momo.log.scheduled_clear=1
	uci set momo.log.scheduled_clear_defaulted=1
	uci -q del momo.log.scheduled_clear_migrated
	# 立即挂上清理任务，不用等服务重启：momo 启动时也是同一行格式
	log_clear_cron=$(uci -q get momo.log.scheduled_clear_cron)
	if [ -z "$IPKG_INSTROOT" ] && [ -f /etc/crontabs/root ] && [ -n "$log_clear_cron" ]; then
		grep -q "#momo log scheduled clear" /etc/crontabs/root || \
			echo "$log_clear_cron /etc/init.d/momo clear_logs #momo log scheduled clear" >> /etc/crontabs/root
		/etc/init.d/cron reload > /dev/null 2>&1
	fi
}

# 订阅 UA 默认改 auto（仅迁移一次）：旧版把 user_agent 预填成 sing-box，
# 机场据此只下发 sing-box JSON；auto 会依次试探 Clash.Meta → sing-box →
# v2rayN → Shadowrocket → PassWall，各机场都能拿到能解析的格式。
# 用户手动填过其它 UA 的一律不动。
config_sub_ua_migrated=$(uci -q get momo.config.sub_ua_migrated)
[ "$config_sub_ua_migrated" != 1 ] && {
	for _sub in $(uci -q show momo 2>/dev/null | sed -n 's/^\(momo\.[^.]*\)=subscription$/\1/p'); do
		[ "$(uci -q get "$_sub.user_agent")" = "sing-box" ] && uci set "$_sub.user_agent=auto"
	done
	unset _sub
	uci set momo.config.sub_ua_migrated=1
}

# commit
uci commit momo

# exit with 0
exit 0
