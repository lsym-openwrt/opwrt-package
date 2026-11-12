#!/bin/sh
# momo 自动订阅转换插件加载器（POSIX sh，供 /etc/init.d/momo 调用，也可单独使用）
#
#   convert.sh <file>         就地转换；原生 sing-box 配置直接跳过（零改动）
#   convert.sh <in> <out>     转换到新文件，输入文件不变
#   convert.sh --check        自检插件是否可正常加载
#
# 设计约束：任何失败都不得阻断 momo 原有启动链路。就地模式恒返回 0，
# 转换失败时保留原文件，让后续 mixin/format/check 按原有方式处理。
set -u

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" 2>/dev/null && pwd)
PY_SCRIPT="${MOMO_CONVERTER_PY:-$SCRIPT_DIR/momo_convert.py}"
TEMPLATE="${MOMO_CONVERTER_TEMPLATE:-$SCRIPT_DIR/../converter/momo-base.json}"
CONF="${MOMO_CONVERTER_CONF:-$SCRIPT_DIR/../converter/converter.conf}"
LOG_FILE="${MOMO_CONVERTER_LOG:-/var/log/momo/app.log}"

if [ ! -f "$PY_SCRIPT" ]; then
	PY_SCRIPT="${MOMO_CONVERTER_PY:-/etc/momo/scripts/momo_convert.py}"
fi
if [ ! -f "$TEMPLATE" ]; then
	TEMPLATE="/etc/momo/converter/momo-base.json"
fi
if [ ! -f "$CONF" ]; then
	CONF="/etc/momo/converter/converter.conf"
fi

conf_get() {
	# 环境变量优先（便于临时禁用某项能力 / 调试）
	eval "env_value=\${$1:-}"
	if [ -n "${env_value:-}" ]; then
		printf '%s' "$env_value"
		return 0
	fi
	if [ ! -f "$CONF" ]; then
		printf '%s' "$2"
		return 0
	fi
	value=$(sed -n "s/^[[:space:]]*$1=//p" "$CONF" 2>/dev/null | head -n 1)
	printf '%s' "${value:-$2}"
}
# 与 groupd.sh / include.sh 保持同一套解析（环境变量 > converter.conf > 默认值）
GROUPS_PATH="${MOMO_GROUPD_RULES:-$(conf_get MOMO_GROUPD_RULES /var/run/momo/groups.json)}"

log_msg() {
	[ -n "$LOG_FILE" ] || return 0
	[ -d "$(dirname "$LOG_FILE")" ] || return 0
	printf '[%s] [Converter] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" >> "$LOG_FILE" 2>/dev/null
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

# 转换是纯 CPU + 多路 curl 的活儿，跑在 start_service 的同步路径里：
# 1) nice 降优先级，避免弱 CPU 路由器上转发掉速甚至像死机；
# 2) timeout 兜底，绝不让一次畸形 YAML 把 start 卡住（卡住=服务起不来=断网）。
CONVERT_TIMEOUT="${MOMO_CONVERTER_TIMEOUT:-120}"
run_converter() {
	if command -v nice > /dev/null 2>&1; then
		set -- nice -n 19 "$@"
	fi
	if command -v timeout > /dev/null 2>&1; then
		timeout "$CONVERT_TIMEOUT" "$@"
	else
		"$@"
	fi
}

PY=$(find_python) || {
	log_msg "Python3 不可用，自动转换跳过（原有流程不受影响）"
	[ "${1:-}" = "--check" ] && exit 1
	exit 0
}

if [ "${1:-}" = "--check" ]; then
	exec "$PY" "$PY_SCRIPT" --check --template "$TEMPLATE" --conf "$CONF"
fi

if [ $# -lt 1 ] || [ -z "$1" ]; then
	log_msg "用法: convert.sh <file> | <in> <out> | --check"
	exit 0
fi
INPUT="$1"
if [ $# -ge 2 ] && [ -n "$2" ]; then
	OUTPUT="$2"
	MODE="separate"
else
	OUTPUT=""
	MODE="inplace"
fi

if [ ! -f "$INPUT" ]; then
	log_msg "输入文件不存在: $INPUT"
	[ "$MODE" = "separate" ] && exit 1
	exit 0
fi

# 快路径：已是原生 sing-box 配置时完全不启动 Python，保证原有配置逐字节不变。
# 例外：开启骨架补齐（MOMO_CONVERTER_REPAIR=1，默认）时必须让 Python 过一眼，
# 否则机场给的原生订阅缺少 dns-in 等 momo 必需 inbound 会直接 Check failed 退出。
REPAIR=$(conf_get MOMO_CONVERTER_REPAIR 1)
case "$REPAIR" in
	0|off|false|no|OFF|False|No) REPAIR_DISABLED=1 ;;
	*) REPAIR_DISABLED=0 ;;
esac
if [ "$MODE" = "inplace" ] && [ "$REPAIR_DISABLED" = "1" ]; then
	# 去掉 BOM(EF BB BF) 与首部空白后再判断，避免带 BOM 的原生配置误入 Python 路径
	FIRST=$(head -c 16 "$INPUT" 2>/dev/null | tr -d '\000-\040\357\273\277' | head -c 1)
	if [ "$FIRST" = "{" ] && grep -q '"outbounds"[[:space:]]*:' "$INPUT" 2>/dev/null; then
		rm -f "$GROUPS_PATH" > /dev/null 2>&1
		exit 0
	fi
fi

if [ "$MODE" = "inplace" ]; then
	RESULT=$(run_converter "$PY" "$PY_SCRIPT" --input "$INPUT" --in-place \
		--template "$TEMPLATE" --conf "$CONF" --groups-out "$GROUPS_PATH" 2>&1)
	RC=$?
else
	RESULT=$(run_converter "$PY" "$PY_SCRIPT" --input "$INPUT" --output "$OUTPUT" \
		--template "$TEMPLATE" --conf "$CONF" 2>&1)
	RC=$?
fi

if [ $RC -eq 0 ]; then
	case "$RESULT" in
		*'"status": "converted"'*|*'"status":"converted"'*)
			log_msg "已自动转换订阅/节点配置: $INPUT ($RESULT)" ;;
		*'"status": "repaired"'*|*'"status":"repaired"'*)
			log_msg "原生配置缺少 momo 必需 inbound，已自动补齐: $INPUT ($RESULT)" ;;
		*'"status": "degraded"'*|*'"status":"degraded"'*)
			# 没有任何可用节点（订阅过期 / 全是占位节点 / provider 全挂）：
			# 已写成合法配置并全局直连，保证 momo 能起来、上网不断
			log_msg "订阅无可用节点，已降级为全局直连（代理不可用，上网不受影响）: $INPUT ($RESULT)" ;;
	esac
else
	# 转换失败时清理分组规则，避免守护进程拿着上一份订阅的规则误启动
	[ "$MODE" = "inplace" ] && rm -f "$GROUPS_PATH" > /dev/null 2>&1
	log_msg "自动转换跳过（保留原文件，momo 按原方式继续）: $RESULT"
fi

if [ "$MODE" = "separate" ]; then
	[ -n "$RESULT" ] && printf '%s\n' "$RESULT"
	exit "$RC"
fi
exit 0
