#!/bin/sh

. "$IPKG_INSTROOT/usr/share/libubox/jshn.sh"

# paths

## home
HOME_DIR="/etc/momo"
PROFILES_DIR="$HOME_DIR/profiles"
SUBSCRIPTIONS_DIR="$HOME_DIR/subscriptions"

## run
RUN_DIR="$HOME_DIR/run"
RUN_PROFILE_PATH="$RUN_DIR/config.json"

## ucode
UCODE_DIR="$HOME_DIR/ucode"
INCLUDE_UC="$UCODE_DIR/include.uc"
MIXIN_UC="$UCODE_DIR/mixin.uc"
HIJACK_UT="$UCODE_DIR/hijack.ut"

## scripts
SH_DIR="$HOME_DIR/scripts"
INCLUDE_SH="$SH_DIR/include.sh"
FIREWALL_INCLUDE_SH="$SH_DIR/firewall_include.sh"
DEBUG_SH="$SH_DIR/debug.sh"
CONVERT_SH="$SH_DIR/convert.sh"
GROUPD_SH="$SH_DIR/groupd.sh"
# 分组规则文件路径：环境变量 > converter.conf > 默认值；与 convert.sh / groupd.sh 读法一致
GROUPD_RULES_PATH="${MOMO_GROUPD_RULES:-$(sed -n 's/^[[:space:]]*MOMO_GROUPD_RULES=//p' "$HOME_DIR/converter/converter.conf" 2>/dev/null | head -n 1)}"
GROUPD_RULES_PATH="${GROUPD_RULES_PATH:-/var/run/momo/groups.json}"

## firewall
FIREWALL_DIR="$HOME_DIR/firewall"
GEOIP_CN_NFT="$FIREWALL_DIR/geoip_cn.nft"
GEOIP6_CN_NFT="$FIREWALL_DIR/geoip6_cn.nft"

## log
LOG_DIR="/var/log/momo"
APP_LOG_PATH="$LOG_DIR/app.log"
CORE_LOG_PATH="$LOG_DIR/core.log"
DEBUG_LOG_PATH="$LOG_DIR/debug.log"

## temp
TEMP_DIR="/var/run/momo"
PID_FILE_PATH="$TEMP_DIR/momo.pid"
STARTED_FLAG_PATH="$TEMP_DIR/started.flag"
# 订阅只更新元数据（流量/到期/失败标记）时，避免 procd reload 把代理整条链路重启
META_ONLY_FLAG_PATH="$TEMP_DIR/meta_only.flag"
# 订阅更新进度：running <section> <ts> / done <section> <success> <ts>
SUB_UPDATE_STATUS_PATH="$TEMP_DIR/sub_update.status"
BRIDGE_NF_CALL_IPTABLES_FLAG_PATH="$TEMP_DIR/bridge_nf_call_iptables.flag"
BRIDGE_NF_CALL_IP6TABLES_FLAG_PATH="$TEMP_DIR/bridge_nf_call_ip6tables.flag"

# functions
get_paths() {
	# 这里只做纯查询。补权（grant_rpcd_acl）放在 momo 启动的 fix_permissions 与
	# 安装后的 postinst 里：rpcd 是单线程事件循环，在本 RPC 内同步调用 ubus 会自调用超时，
	# 而后台 fork 又会在每次取路径时堆一批短命进程，把面板轮询拖慢。
	json_init

	json_add_string home_dir "$HOME_DIR"
	json_add_string profiles_dir "$PROFILES_DIR"
	json_add_string subscriptions_dir "$SUBSCRIPTIONS_DIR"

	json_add_string run_dir "$RUN_DIR"
	json_add_string run_profile_path "$RUN_PROFILE_PATH"

	json_add_string ucode_dir "$UCODE_DIR"
	json_add_string include_uc "$INCLUDE_UC"
	json_add_string hijack_ut "$HIJACK_UT"

	json_add_string sh_dir "$SH_DIR"
	json_add_string include_sh "$INCLUDE_SH"
	json_add_string firewall_include_sh "$FIREWALL_INCLUDE_SH"
	json_add_string debug_sh "$DEBUG_SH"

	json_add_string firewall_dir "$FIREWALL_DIR"
	json_add_string geoip_cn_nft "$GEOIP_CN_NFT"
	json_add_string geoip6_cn_nft "$GEOIP6_CN_NFT"

	json_add_string log_dir "$LOG_DIR"
	json_add_string app_log_path "$APP_LOG_PATH"
	json_add_string core_log_path "$CORE_LOG_PATH"
	json_add_string debug_log_path "$DEBUG_LOG_PATH"

	json_add_string temp_dir "$TEMP_DIR"
	json_add_string pid_file_path "$PID_FILE_PATH"
	json_add_string started_flag_path "$STARTED_FLAG_PATH"
	json_add_string bridge_nf_call_iptables_flag_path "$BRIDGE_NF_CALL_IPTABLES_FLAG_PATH"
	json_add_string bridge_nf_call_ip6tables_flag_path "$BRIDGE_NF_CALL_IP6TABLES_FLAG_PATH"

	json_dump

	json_cleanup
}

format_filesize() {
	local b; b=1
	local kb; kb=$((b * 1024))
	local mb; mb=$((kb * 1024))
	local gb; gb=$((mb * 1024))
	local tb; tb=$((gb * 1024))
	local pb; pb=$((tb * 1024))
	local size; size=$1
	if [ -n "$size" ]; then
		if [ "$size" -lt "$kb" ]; then
			echo "$(awk "BEGIN {print $size / $b}") B"
		elif [ "$size" -lt "$mb" ]; then
			echo "$(awk "BEGIN {print $size / $kb}") KB"
		elif [ "$size" -lt "$gb" ]; then
			echo "$(awk "BEGIN {print $size / $mb}") MB"
		elif [ "$size" -lt "$tb" ]; then
			echo "$(awk "BEGIN {print $size / $gb}") GB"
		elif [ "$size" -lt "$pb" ]; then
			echo "$(awk "BEGIN {print $size / $tb}") TB"
		else
			echo "$(awk "BEGIN {print $size / $pb}") PB"
		fi
	fi
}

# 文件权限声明与自愈：写在运行期代码里，不依赖打包/编译阶段执行 chmod 命令。
# LuCI 经 rpcd 的 file.list / file.stat / file.read / file.write 访问 momo 文件：
# 目录必须可列、配置必须对 rpcd 可读可写，否则前端会抛 RPCError 权限错误。
# 所有脚本均由 sh 显式调用，即使丢失执行位也不影响启动。chmod 一律 best-effort，
# 任何失败都不阻断 momo 原有启动链路。
fix_permissions() {
	local root; root="${IPKG_INSTROOT:-}"
	local d f
	for d in "$HOME_DIR" "$PROFILES_DIR" "$SUBSCRIPTIONS_DIR" "$RUN_DIR" \
		"$UCODE_DIR" "$SH_DIR" "$FIREWALL_DIR" "$HOME_DIR/converter" \
		"$LOG_DIR" "$TEMP_DIR"; do
		[ -d "$d" ] && chmod 755 "$d" 2>/dev/null
	done
	for f in "$INCLUDE_SH" "$FIREWALL_INCLUDE_SH" "$DEBUG_SH" "$CONVERT_SH" "$GROUPD_SH" \
		"$root/etc/init.d/momo" "$root/usr/share/rpcd/ucode/luci.momo"; do
		[ -f "$f" ] && chmod 755 "$f" 2>/dev/null
	done
	for f in "$SH_DIR"/*.py "$UCODE_DIR"/*.uc "$UCODE_DIR"/*.ut \
		"$HOME_DIR/converter"/*.json "$HOME_DIR/converter"/*.conf \
		"$FIREWALL_DIR"/*.nft "$RUN_PROFILE_PATH" "$GROUPD_RULES_PATH" \
		"$APP_LOG_PATH" "$CORE_LOG_PATH" "$DEBUG_LOG_PATH" \
		"$root/usr/share/rpcd/acl.d/luci-app-momo.json" \
		"$PROFILES_DIR"/* "$SUBSCRIPTIONS_DIR"/*; do
		[ -f "$f" ] && chmod 644 "$f" 2>/dev/null
	done
	grant_rpcd_acl
	# 恒成功：不能因为个别文件缺失/只读就让 prepare_files 返回非 0
	return 0
}

# rpcd 只在登录时把 acl.d 读进会话；升级 ACL 后旧会话仍持旧快照，
# 于是 LuCI 会一直报 RPCError，直到重启 rpcd 或重新登录。
# 这里用 session.grant 给所有现有会话即时补权限，不需要重启 rpcd。
grant_rpcd_acl() {
	local ubus_bin sid objects p f
	ubus_bin=$(command -v ubus 2>/dev/null || echo /sbin/ubus)
	[ -x "$ubus_bin" ] || return 0
	# rpcd 的 session.grant 要求 objects 每项为 [object, function] 两个字符串，
	# 写成 [path, [funcs...]] 会被静默忽略；这里为每个路径×权限生成一条。
	objects=''
	for p in "/etc/momo" "/etc/momo/*" "/etc/momo/profiles" "/etc/momo/profiles/*" \
		"/etc/momo/subscriptions" "/etc/momo/subscriptions/*" "/etc/momo/run" \
		"/etc/momo/run/*" "/etc/momo/converter" "/etc/momo/converter/*" \
		"/var/run/momo" "/var/run/momo/*" "/var/log/momo" "/var/log/momo/*" \
		"/tmp/log/momo" "/tmp/log/momo/*"; do
		for f in read write list; do
			[ -n "$objects" ] && objects="$objects,"
			objects="$objects[\"$p\",\"$f\"]"
		done
	done
	objects="[$objects]"
	"$ubus_bin" -t 3 call session list 2>/dev/null | \
		sed -n 's/.*"ubus_rpc_session": *"\([0-9a-f]\{32\}\)".*/\1/p' | \
		while read -r sid; do
			[ "$sid" = "00000000000000000000000000000000" ] && continue
			"$ubus_bin" -t 3 call session grant \
				"{\"ubus_rpc_session\":\"$sid\",\"scope\":\"file\",\"objects\":$objects}" > /dev/null 2>&1
			"$ubus_bin" -t 3 call session grant \
				"{\"ubus_rpc_session\":\"$sid\",\"scope\":\"ubus\",\"objects\":[[\"file\",\"*\"],[\"rc\",\"*\"],[\"luci.momo\",\"*\"]]}" > /dev/null 2>&1
		done
	return 0
}

# rpcd 在 START=12 就扫描 /usr/share/rpcd/ucode/ 加载插件；只要那一刻插件加载失败
# （升级时文件被替换、依赖文件暂缺、ucode 崩溃），rpcd 会静默丢弃整个模块，
# ubus 上就没有 luci.momo，前端所有 momo 页面直接 RPCError: Object not found。
# 这里在 momo 启动时体检一次，缺失就重启 rpcd 重新挂载插件。
# 只在「确实没有对象」时动手，正常启动零开销。
ensure_rpcd_plugin() {
	local attempt
	for attempt in 1 2 3; do
		ubus -t 2 list luci.momo > /dev/null 2>&1 && return 0
		[ "$attempt" = 3 ] || sleep 1
	done
	[ -x /etc/init.d/rpcd ] || return 0
	logger -t momo "ubus object luci.momo missing, restarting rpcd" 2>/dev/null
	/etc/init.d/rpcd restart > /dev/null 2>&1
	# rpcd 重启后会话全部失效，重启完再补一次 file/ubus 权限
	for attempt in 1 2 3; do
		ubus -t 2 list luci.momo > /dev/null 2>&1 && break
		sleep 1
	done
	grant_rpcd_acl
	return 0
}

prepare_files() {
	if [ ! -d "$LOG_DIR" ]; then
		mkdir -p "$LOG_DIR"
	fi
	if [ ! -f "$APP_LOG_PATH" ]; then
		touch "$APP_LOG_PATH"
	fi
	if [ ! -f "$CORE_LOG_PATH" ]; then
		touch "$CORE_LOG_PATH"
	fi
	if [ ! -d "$TEMP_DIR" ]; then
		mkdir -p "$TEMP_DIR"
	fi
	fix_permissions
}

log() {
	echo "[$(date "+%Y-%m-%d %H:%M:%S")] [$1] $2" >> "$APP_LOG_PATH"
}
