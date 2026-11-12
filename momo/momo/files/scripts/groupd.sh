#!/bin/sh
# momo 分组驱动加载器（POSIX sh，供 /etc/init.d/momo 调用，也可单独使用）
#
#   groupd.sh start    按 groups.json 启动分组驱动（原生配置/转换失败时不会启动）
#   groupd.sh stop     停止分组驱动
#   groupd.sh check    自检插件与 Clash API 可达性
#
# 设计约束：任何失败都不得阻断 momo 原有启动/停止链路；start/stop 恒返回 0。
set -u

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" 2>/dev/null && pwd)
PY_SCRIPT="${MOMO_GROUPD_PY:-$SCRIPT_DIR/momo_groupd.py}"
CONF="${MOMO_CONVERTER_CONF:-$SCRIPT_DIR/../converter/converter.conf}"
LOG_FILE="${MOMO_CONVERTER_LOG:-/var/log/momo/app.log}"

if [ ! -f "$PY_SCRIPT" ]; then
	PY_SCRIPT="/etc/momo/scripts/momo_groupd.py"
fi
if [ ! -f "$CONF" ]; then
	CONF="/etc/momo/converter/converter.conf"
fi

conf_get() {
	if [ ! -f "$CONF" ]; then
		printf '%s' "$2"
		return 0
	fi
	value=$(sed -n "s/^[[:space:]]*$1=//p" "$CONF" 2>/dev/null | head -n 1)
	printf '%s' "${value:-$2}"
}

log_msg() {
	[ -d "$(dirname "$LOG_FILE")" ] || return 0
	printf '[%s] [Group] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" >> "$LOG_FILE" 2>/dev/null
}

find_python() {
	if [ -n "${MOMO_PYTHON:-}" ] && [ -x "$MOMO_PYTHON" ]; then
		printf '%s' "$MOMO_PYTHON"
		return 0
	fi
	if command -v python3 >/dev/null 2>&1; then
		command -v python3
		return 0
	fi
	if command -v python >/dev/null 2>&1; then
		command -v python
		return 0
	fi
	return 1
}

ENABLED="${MOMO_GROUPD_ENABLED:-$(conf_get MOMO_GROUPD_ENABLED 1)}"
RULES="${MOMO_GROUPD_RULES:-$(conf_get MOMO_GROUPD_RULES /var/run/momo/groups.json)}"
STATE="${MOMO_GROUPD_STATE:-$(conf_get MOMO_GROUPD_STATE /var/run/momo/group_state.json)}"
PID_FILE="${MOMO_GROUPD_PID:-$(conf_get MOMO_GROUPD_PID /var/run/momo/groupd.pid)}"
PROFILE="${MOMO_GROUPD_PROFILE:-${MOMO_RUN_PROFILE:-/etc/momo/run/config.json}}"
EXTRA_ARGS="${MOMO_GROUPD_ARGS:-}"

PY=$(find_python) || {
	log_msg "Python3 不可用，分组驱动跳过（原有流程不受影响）"
	[ "${1:-}" = "check" ] && exit 1
	exit 0
}

case "${1:-}" in
	check)
		exec "$PY" "$PY_SCRIPT" --check --rules "$RULES" --profile "$PROFILE" \
			--conf "$CONF" --state "$STATE" --log "$LOG_FILE"
	;;
	start)
		case "$ENABLED" in 0|off|false|no) exit 0;; esac
		if [ ! -f "$PY_SCRIPT" ] || [ ! -f "$RULES" ]; then
			exit 0
		fi
		if [ -f "$PID_FILE" ]; then
			old_pid=$(cat "$PID_FILE" 2>/dev/null)
			if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
				# 避免陈旧 PID 被无关进程复用：Linux 上核对 /proc/<pid>/cmdline
				if [ ! -r "/proc/$old_pid/cmdline" ] || \
					grep -q "momo_groupd.py" "/proc/$old_pid/cmdline" 2>/dev/null; then
					exit 0
				fi
			fi
		fi
		mkdir -p "$(dirname "$PID_FILE")" "$(dirname "$STATE")" 2>/dev/null
		if command -v nohup >/dev/null 2>&1; then
			NOHUP=nohup
		else
			NOHUP=""
		fi
		# shellcheck disable=SC2086
		(
			set -f   # $EXTRA_ARGS 需要按空格分词，但禁止通配符展开
			# 1000>&-：关闭继承的 procd flock 描述符；否则 init 脚本的
			# /var/lock/procd_momo.lock 会被本进程永久持有，后续所有
			# rc.common 调用（含 LuCI 状态轮询）全部阻塞，主界面显示未运行。
			$NOHUP "$PY" "$PY_SCRIPT" --rules "$RULES" --profile "$PROFILE" \
				--state "$STATE" --conf "$CONF" --log "$LOG_FILE" \
				$EXTRA_ARGS </dev/null >> "$LOG_FILE" 2>&1 1000>&- &
			echo $! > "$PID_FILE"
		)
	;;
	stop)
		if [ -f "$PID_FILE" ]; then
			pid=$(cat "$PID_FILE" 2>/dev/null)
			if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
				kill "$pid" 2>/dev/null
			fi
			rm -f "$PID_FILE" > /dev/null 2>&1
		fi
	;;
	*)
		log_msg "用法: groupd.sh start|stop|check"
	;;
esac
exit 0
