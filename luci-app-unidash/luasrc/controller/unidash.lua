-- luci-app-unidash : 通用 OpenWrt 仪表板 (移植自 luci-app-fwx-dashboard)
-- 数据层完全基于标准 OpenWrt 组件:
--   /proc (net/dev, nf_conntrack, meminfo, stat, arp), /sys (class/net, thermal),
--   ubus (network.interface.*, system board), /tmp/dhcp.leases, df, ping
-- 不依赖 fwxd / kmod-fwx, 可运行于任何 OpenWrt 固件与任意主题。

module("luci.controller.unidash", package.seeall)

local util  = require("luci.util")
local http  = require("luci.http")

-- 延迟加载: LuCI 每个请求 (包括登录页) 都会加载所有控制器模块,
-- 这里把 jsonc / nixio.fs 改为首次真正用到时才 require, 避免拖慢页面首字节
local jsonc, jsonc_ready = nil, false

local function getjsonc()
	if not jsonc_ready then
		jsonc_ready = true
		local ok, j = pcall(require, "luci.jsonc")
		if ok and j and type(j.parse) == "function" then
			jsonc = j
		end
	end
	return jsonc
end

-- ---------------------------------------------------------------- JSON 输出

local function json_str(s)
	s = tostring(s or "")
	s = s:gsub("\\", "\\\\")
	s = s:gsub('"', '\\"')
	s = s:gsub("\n", "\\n")
	s = s:gsub("\r", "\\r")
	s = s:gsub("\t", "\\t")
	s = s:gsub("%c", function(c)
		return string.format("\\u%04x", string.byte(c))
	end)
	return '"' .. s .. '"'
end

local function json_num(v)
	if v ~= v or v == math.huge or v == -math.huge then
		return "0"
	end
	if v == math.floor(v) and math.abs(v) < 9007199254740992 then
		-- 用 %.0f 输出 double 整数: %d 在 lua_Integer 为 32 位的平台会溢出
		-- (rx_bytes / conntrack 字节计数实际可超过 2^31)
		return string.format("%.0f", v)
	end
	return tostring(v)
end

local function json_enc(v)
	local t = type(v)
	if t == "nil" then
		return "null"
	elseif t == "boolean" then
		return v and "true" or "false"
	elseif t == "number" then
		return json_num(v)
	elseif t == "string" then
		return json_str(v)
	elseif t == "table" then
		local mt = getmetatable(v)
		if mt and mt.__jsontype == "array" then
			local parts = {}
			for i = 1, #v do
				parts[i] = json_enc(v[i])
			end
			return "[" .. table.concat(parts, ",") .. "]"
		end
		-- 启发式兜底: 无标记但为 1..n 连续数字键的表按数组编码,
		-- 否则纯 Lua 数组会被编码为 {} (数字键被跳过)
		local n = #v
		if n > 0 then
			local isarr = true
			local count = 0
			for k in pairs(v) do
				count = count + 1
				if type(k) ~= "number" or k < 1 or k > n or math.floor(k) ~= k then
					isarr = false
				end
			end
			if isarr and count == n then
				local parts = {}
				for i = 1, n do
					parts[i] = json_enc(v[i])
				end
				return "[" .. table.concat(parts, ",") .. "]"
			end
		end
		local parts = {}
		for k, val in pairs(v) do
			if type(k) == "string" then
				parts[#parts + 1] = json_str(k) .. ":" .. json_enc(val)
			end
		end
		return "{" .. table.concat(parts, ",") .. "}"
	end
	return "null"
end

local function arr(t)
	return setmetatable(t, { __jsontype = "array" })
end

local function obj(t)
	return setmetatable(t, { __jsontype = "object" })
end

local function json_out(data)
	http.prepare_content("application/json; charset=utf-8")
	http.write(json_enc(data))
end

-- ---------------------------------------------------------------- 性能基础设施
-- LuCI 每个 CGI 请求都是独立的 Lua 进程, 模块级表天然只在单次请求内有效,
-- 因此这里不需要任何过期策略。原先一次 api_common 里 wan_device() / iface_status()
-- 会被反复调用 (共 4 次), 加上 df / cat / ls / ubus 等, 单次请求要 fork 十几次
-- 外部命令 (每次 10~40ms)。仪表板 3 秒轮询 5 个接口时, uhttpd 的 CGI 槽被占满,
-- 同一时间打开的登录页请求只能排队, 表现就是"登录等很久"。
local MEMO = {}

local function memo(key, fn)
	local v = MEMO[key]
	if v == nil then
		v = fn()
		if v == nil then
			v = false
		end
		MEMO[key] = v
	end
	if v == false then
		return nil
	end
	return v
end

-- nixio.fs 可用时直接读 /sys, 省掉 cat / ls 的 fork (同样延迟加载)
local nfs, nfs_ready = nil, false

local function getfs()
	if not nfs_ready then
		nfs_ready = true
		local ok, m = pcall(require, "nixio.fs")
		if ok and m then
			nfs = m
		end
	end
	return nfs
end

-- nixio.fs.glob() 返回的是迭代器函数 (不是表), 这里统一收敛成数组返回;
-- 无 nixio 或无匹配时返回 nil, 由调用方退回 shell
local function globlist(pattern)
	local fs = getfs()
	if not fs or not fs.glob then
		return nil
	end
	local list = {}
	local ok, r = pcall(fs.glob, pattern)
	if not ok or not r then
		return nil
	end
	if type(r) == "function" then
		for p in r do
			list[#list + 1] = p
		end
	elseif type(r) == "table" then
		for _, p in ipairs(r) do
			list[#list + 1] = p
		end
	end
	if #list == 0 then
		return nil
	end
	return list
end

-- ---------------------------------------------------------------- 基础工具

local function readfile(path)
	local f = io.open(path, "r")
	if not f then
		return nil
	end
	local c = f:read("*a")
	f:close()
	if c == "" then
		return nil
	end
	return c
end

local function readnum(path)
	local c = readfile(path)
	if not c then
		return nil
	end
	return tonumber(c:match("^%s*([%-%d%.]+)"))
end

local function readstr(path)
	local c = readfile(path)
	if not c then
		return nil
	end
	return (c:gsub("%z", ""):gsub("^%s+", ""):gsub("%s+$", ""))
end

local function shellout(cmd)
	local ok, out = pcall(function()
		return util.exec(cmd .. " 2>/dev/null")
	end)
	if ok and type(out) == "string" then
		return out
	end
	return ""
end

local function clamp(v, lo, hi)
	if v < lo then return lo end
	if v > hi then return hi end
	return v
end

-- ---------------------------------------------------------------- 响应级缓存
-- 同一个接口 2 秒内的重复请求直接回放上次的 JSON 文本 (数据本身变化周期 >= 3 秒),
-- 多开页面 / 多台设备同时看仪表板时只算一次, 避免把 uhttpd 的 CGI 槽占满。
local API_TTL = 2

-- 本进程 pid: 并发请求写 /tmp 时用独立临时文件, 避免多个 CGI 同时写同一 tmp 造成内容交错
local PID = nil
local function pid()
	if not PID then
		PID = (readfile("/proc/self/stat") or ""):match("^(%d+)") or "0"
	end
	return PID
end

local function cache_play(tag)
	local c = readfile("/tmp/unidash_api_" .. tag)
	if not c then
		return false
	end
	local ts, body = c:match("^(%d+)\n(.*)$")
	if not ts or not body or #body < 2 then
		return false
	end
	if os.time() - (tonumber(ts) or 0) > API_TTL then
		return false
	end
	http.prepare_content("application/json; charset=utf-8")
	http.write(body)
	return true
end

local function cache_save(tag, body)
	local path = "/tmp/unidash_api_" .. tag
	local tmp = path .. "." .. pid() .. ".tmp"
	local f = io.open(tmp, "w")
	if not f then
		return
	end
	f:write(os.time(), "\n", body)
	f:close()
	os.rename(tmp, path)
end

-- 统一出口: 命中缓存直接回放, 未命中才真正计算并落缓存
local function json_cached(tag, builder, fallback)
	if cache_play(tag) then
		return
	end
	local ok, data = pcall(builder)
	local body = json_enc((ok and data) and data or fallback)
	http.prepare_content("application/json; charset=utf-8")
	http.write(body)
	cache_save(tag, body)
end

local function state_read(name)
	local c = readfile("/tmp/unidash_" .. name .. ".json")
	if not c or #c < 2 then
		return nil
	end
	local jc = getjsonc()
	if jc then
		local ok, t = pcall(jc.parse, c)
		if ok and type(t) == "table" then
			return t
		end
	end
	return nil
end

local function state_write(name, tbl)
	local path = "/tmp/unidash_" .. name .. ".json"
	local tmp = path .. "." .. pid() .. ".tmp"
	local f = io.open(tmp, "w")
	if not f then
		return
	end
	f:write(json_enc(tbl))
	f:close()
	os.rename(tmp, path)
end

-- ---------------------------------------------------------------- 网络工具

local function is_private_ip(ip)
	-- 直接比较八位组, 不做大数乘法 (避免 32 位 lua_Integer 构建下的整型回绕)
	local a, b = ip:match("^(%d+)%.(%d+)%.")
	a, b = tonumber(a), tonumber(b)
	if not a or not b or a > 255 or b > 255 then
		return false
	end
	if a == 10 then return true end
	if a == 192 and b == 168 then return true end
	if a == 172 and b >= 16 and b <= 31 then return true end
	if a == 100 and b >= 64 and b <= 127 then return true end
	return false
end

local function prefix_to_mask(p)
	p = tonumber(p) or 24
	if p < 0 or p > 32 then p = 24 end
	local m = 0
	local i = 0
	while i < p do
		m = m + 2 ^ (31 - i)
		i = i + 1
	end
	return string.format("%d.%d.%d.%d",
		math.floor(m / 16777216) % 256,
		math.floor(m / 65536) % 256,
		math.floor(m / 256) % 256,
		math.floor(m) % 256)
end

local function ubus_json(objname, method)
	local out = shellout("ubus call " .. objname .. " " .. method)
	local jc = getjsonc()
	if out and #out > 2 and jc then
		local ok, t = pcall(jc.parse, out)
		if ok and type(t) == "table" then
			return t
		end
	end
	return nil
end

local function iface_status(name)
	if not name or name == "" then
		return nil
	end
	return memo("ifstatus:" .. name, function()
		local st = ubus_json("network.interface." .. name, "status")
		if st then
			return st
		end
		local out = shellout("ifstatus " .. name)
		local jc = getjsonc()
		if out and #out > 2 and jc then
			local ok, t = pcall(jc.parse, out)
			if ok and type(t) == "table" then
				return t
			end
		end
		return nil
	end)
end

local function iface_v4info(st)
	local info = { ip = "", mask = "", gw = "", dns = {}, ipv6 = "" }
	if not st then
		return info
	end
	local v4 = st["ipv4-address"]
	if type(v4) == "table" and v4[1] then
		info.ip = tostring(v4[1].address or "")
		info.mask = prefix_to_mask(v4[1].mask)
	end
	local routes = st.route
	if type(routes) == "table" then
		for _, r in ipairs(routes) do
			if r.target == "0.0.0.0" and r.nexthop then
				info.gw = tostring(r.nexthop)
			end
		end
	end
	local dns = st["dns-server"]
	if type(dns) == "table" then
		for _, d in ipairs(dns) do
			info.dns[#info.dns + 1] = tostring(d)
		end
	end
	local v6 = st["ipv6-address"]
	if type(v6) == "table" and v6[1] and v6[1].address then
		info.ipv6 = tostring(v6[1].address)
	else
		local v6a = st["ipv6-prefix-assignment"]
		if type(v6a) == "table" and v6a[1] and v6a[1]["local-address"] then
			info.ipv6 = tostring(v6a[1]["local-address"].address or "")
		end
	end
	return info
end

local function default_route_dev()
	return memo("defdev", function()
		local out = shellout("ip route show table main")
		local dev = out:match("^default via %S+ dev (%S+)")
		if not dev then
			dev = out:match("default via %S+ dev (%S+)")
		end
		return dev
	end)
end

local function wan_device()
	return memo("wandev", function()
		local st = iface_status("wan")
		if st then
			if st.l3_device then
				return tostring(st.l3_device)
			end
			if st.device then
				return tostring(st.device)
			end
		end
		return default_route_dev() or "wan"
	end)
end

local function dns_from_resolv()
	local list = {}
	local c = readfile("/tmp/resolv.conf.d/resolv.conf.auto")
		or readfile("/tmp/resolv.conf.auto")
		or readfile("/tmp/resolv.conf")
		or ""
	for ns in c:gmatch("nameserver%s+([%w%.:]+)") do
		list[#list + 1] = ns
	end
	return list
end

local function ipaddr_fallback(dev)
	local info = { ip = "", mask = "", gw = "" }
	if not dev or dev == "" then
		return info
	end
	local out = shellout("ip -4 addr show " .. dev)
	local ip, pfx = out:match("inet (%d+%.%d+%.%d+%.%d+)/(%d+)")
	if ip then
		info.ip = ip
		info.mask = prefix_to_mask(pfx)
	end
	info.gw = shellout("ip route show default"):match("default via (%d+%.%d+%.%d+%.%d+)") or ""
	return info
end

-- ---------------------------------------------------------------- 系统信息

local function sys_hostname()
	return readstr("/proc/sys/kernel/hostname") or "OpenWrt"
end

local function device_model()
	return memo("model", function()
		local m = readstr("/tmp/sysinfo/model")
		if not m or m == "" then
			m = readstr("/proc/device-tree/model")
		end
		if not m or m == "" then
			local b = ubus_json("system", "board")
			if b and b.model then
				m = tostring(b.model)
			end
		end
		return (m and m ~= "") and m or "Unknown"
	end)
end

local function board_arch()
	return memo("arch", function()
		local b = ubus_json("system", "board")
		if b and b.system and b.system ~= "" then
			return tostring(b.system)
		end
		return (shellout("uname -m"):gsub("%s+", "")) or ""
	end)
end

local function cpu_model_name(arch)
	local c = readfile("/proc/cpuinfo") or ""
	local m = c:match("model name%s*:%s*([^\r\n]+)")
	if not m or m == "" then
		m = c:match("Hardware%s*:%s*([^\r\n]+)")
	end
	if not m or m == "" then
		m = c:match("system type%s*:%s*([^\r\n]+)")
	end
	if m and m ~= "" then
		return (m:gsub("%s+$", ""))
	end
	local model = device_model()
	if model ~= "Unknown" then
		return model
	end
	return arch ~= "" and arch or "CPU"
end

-- 解析 key='value' / key="value" / key=value 三种写法
-- OpenWrt 官方文件用单引号, 早期代码只匹配双引号, 导致版本号恒为空
local function release_field(txt, key)
	if not txt or txt == "" then
		return nil
	end
	local v = txt:match(key .. "%s*=%s*'([^']*)'")
		or txt:match(key .. '%s*=%s*"([^"]*)"')
		or txt:match(key .. "%s*=%s*([^%s'\"\r\n]+)")
	if v and v ~= "" then
		return v
	end
	return nil
end

local function openwrt_version()
	return memo("owrtver", function()
		local c = readfile("/etc/openwrt_release") or ""
		-- 1) 首选发行版本号 (25.12.6 / SNAPSHOT)
		local v = release_field(c, "DISTRIB_RELEASE")
		if v then
			return v
		end
		-- 2) 回退 /etc/os-release (新版 OpenWrt 必定存在)
		local o = readfile("/etc/os-release") or ""
		v = release_field(o, "VERSION_ID") or release_field(o, "VERSION")
		if v then
			return v
		end
		-- 3) 从描述行里提取版本号
		local d = release_field(c, "DISTRIB_DESCRIPTION")
			or release_field(o, "PRETTY_NAME")
			or ""
		local num = d:match("(%d+%.%d+%.%d+)") or d:match("(%d+%.%d+)")
		if num then
			return num
		end
		if d ~= "" then
			return d
		end
		return ""
	end)
end

local function sys_uptime()
	local c = readfile("/proc/uptime")
	if not c then
		return 0
	end
	return math.floor(tonumber(c:match("^([%d%.]+)")) or 0)
end

local function meminfo_kb()
	local c = readfile("/proc/meminfo") or ""
	local total = tonumber(c:match("MemTotal:%s+(%d+)"))
	local avail = tonumber(c:match("MemAvailable:%s+(%d+)"))
	local free = tonumber(c:match("MemFree:%s+(%d+)"))
	local buffers = tonumber(c:match("Buffers:%s+(%d+)"))
	local cached = tonumber(c:match("^Cached:%s+(%d+)"))
	local used = nil
	if total then
		if avail then
			used = total - avail
		elseif free then
			used = total - free - (buffers or 0) - (cached or 0)
			if used < 0 then
				used = total - free
			end
		end
	end
	return total, used
end

local function cpu_percent()
	local c = readfile("/proc/stat")
	if not c then
		return 0
	end
	local line = c:match("^cpu%s+([%d%s]+)")
	if not line then
		return 0
	end
	local fields = {}
	for n in line:gmatch("%d+") do
		fields[#fields + 1] = tonumber(n)
	end
	local idle = (fields[4] or 0) + (fields[5] or 0)
	local total = 0
	for _, v in ipairs(fields) do
		total = total + v
	end
	local now = os.time()
	local s = state_read("cpu") or {}
	local pct = s.last or 0
	if s.total and s.idle and s.ts and total > s.total then
		local dt = now - s.ts
		if dt >= 1 and dt <= 120 then
			pct = (1 - (idle - s.idle) / (total - s.total)) * 100
			pct = clamp(pct, 0, 100)
		end
	end
	state_write("cpu", { ts = now, total = total, idle = idle, last = math.floor(pct * 10 + 0.5) / 10 })
	return math.floor(pct * 10 + 0.5) / 10
end

local function conntrack_count()
	local n = readnum("/proc/sys/net/netfilter/nf_conntrack_count")
	if n then
		return math.floor(n)
	end
	local c = readfile("/proc/net/nf_conntrack") or readfile("/proc/net/ip_conntrack") or ""
	local count = 0
	for _ in c:gmatch("src=") do
		count = count + 1
	end
	return math.floor(count / 2)
end

-- 一次性执行 df -k (无参数), 三个分区共用一次结果, 原来每个分区各 fork 一次
local function df_table()
	return memo("df", function()
		local t = {}
		local out = shellout("df -k")
		for line in out:gmatch("[^\r\n]+") do
			local dev, total, used, avail, pct, mount =
				line:match("^(%S+)%s+(%d+)%s+(%d+)%s+(%d+)%s+(%d+)%%%s+(.+)$")
			if total and mount then
				mount = mount:gsub("%s+$", "")
				if t[mount] == nil then
					t[mount] = { total = tonumber(total), used = tonumber(used) }
				end
			end
		end
		return t
	end) or {}
end

local function df_usage_kb(path)
	local e = df_table()[path]
	if not e and path == "/overlay" then
		-- overlayfs 未单独挂载时退化为根分区
		e = df_table()["/"]
	end
	if not e then
		return nil, nil
	end
	return e.total, e.used
end

local function storage_info()
	local ot, ou = df_usage_kb("/overlay")
	if not ot then
		ot, ou = df_usage_kb("/")
	end
	local tt, tu = df_usage_kb("/tmp")
	local storage = obj({})
	if ot then
		storage.overlay = obj({ total_kb = ot, used_kb = ou })
	end
	if tt then
		storage.tmp = obj({ total_kb = tt, used_kb = tu })
	end
	return storage
end

local function cpu_temperature()
	return memo("cputemp", function()
		local mx = 0
		local function take(v)
			v = tonumber(v) or 0
			if v < 0 then v = 0 end
			if v > 1000 then v = v / 1000 end
			if v > 0 and v < 150 and v > mx then mx = v end
		end
		-- 直接读 /sys (nixio.fs 可用时), 不再 fork cat
		local thermal = globlist("/sys/class/thermal/thermal_zone*/temp")
		local hwmon = globlist("/sys/class/hwmon/hwmon*/temp*_input")
		if thermal or hwmon then
			for _, p in ipairs(thermal or {}) do
				take(readnum(p))
			end
			for _, p in ipairs(hwmon or {}) do
				take(readnum(p))
			end
		else
			local out = shellout("cat /sys/class/thermal/thermal_zone*/temp /sys/class/hwmon/hwmon*/temp*_input")
			for n in out:gmatch("%-?%d+") do
				take(n)
			end
		end
		if mx > 0 then
			return math.floor(mx * 10 + 0.5) / 10
		end
		return nil
	end)
end

-- ---------------------------------------------------------------- 今日流量

local function today_flow_kb()
	local wan_dev = wan_device()
	local rx, tx = 0, 0
	if wan_dev and wan_dev ~= "" then
		rx = readnum("/sys/class/net/" .. wan_dev .. "/statistics/rx_bytes") or 0
		tx = readnum("/sys/class/net/" .. wan_dev .. "/statistics/tx_bytes") or 0
	end
	local now = os.time()
	local t = os.date("*t", now)
	local day = string.format("%04d%02d%02d", t.year, t.month, t.day)
	local s = state_read("flow") or {}
	if s.date ~= day or not s.rx_base or not s.tx_base
		or rx < (s.rx_base or 0) or tx < (s.tx_base or 0) then
		s = { date = day, rx_base = rx, tx_base = tx }
		state_write("flow", s)
	end
	local up_kb = math.max(0, math.floor((tx - (s.tx_base or 0)) / 1024))
	local down_kb = math.max(0, math.floor((rx - (s.rx_base or 0)) / 1024))
	return up_kb, down_kb
end

-- ---------------------------------------------------------------- 外网探测

local function internet_status(wan_ip)
	local wan_dev = wan_device()
	if wan_dev and wan_dev ~= "wan" then
		local oper = readstr("/sys/class/net/" .. wan_dev .. "/operstate")
		if oper and oper == "down" then
			return 2, 1
		end
	end
	if not wan_ip or wan_ip == "" or wan_ip == "0.0.0.0" then
		return 3, 1
	end

	-- 探测结果缓存 45 秒, 由后台 ping 写入, 不阻塞轮询
	local now = os.time()
	local c = readfile("/tmp/unidash_ping")
	local ts, rc
	if c then
		ts, rc = c:match("^(%d+)%s+(%d+)")
	end
	if ts and (now - tonumber(ts)) <= 45 then
		return (tonumber(rc) == 0) and 0 or 1, 1
	end

	os.execute(
		"{ ( ping -c1 -W2 223.5.5.5 >/dev/null 2>&1" ..
		" || ping -c1 -W2 119.29.29.29 >/dev/null 2>&1" ..
		" || ping -c1 -W2 1.1.1.1 >/dev/null 2>&1 ); " ..
		"rc=$?; echo " .. now .. " $rc > /tmp/unidash_ping; } >/dev/null 2>&1 &"
	)
	return 1, 0
end

-- ---------------------------------------------------------------- 物理端口

-- /sys/class/net 下的网卡与软链目标 (优先 nixio, 退化为 ls -l)
local function net_devices()
	return memo("netdev", function()
		local list = {}
		local paths = globlist("/sys/class/net/*")
		local fs = getfs()
		if paths and fs and fs.readlink then
			for _, p in ipairs(paths) do
				local dev = p:match("([^/]+)$")
				if dev then
					list[#list + 1] = { dev = dev, target = fs.readlink(p) or "" }
				end
			end
		else
			for line in shellout("ls -l /sys/class/net"):gmatch("[^\r\n]+") do
				local dev, target = line:match("(%S+)%s*->%s*(.+)$")
				if dev then
					list[#list + 1] = { dev = dev, target = target or "" }
				end
			end
		end
		return list
	end) or {}
end

local function list_ports(wan_l3dev)
	local ports = {}
	local physical = {}
	local others = {}
	for _, d in ipairs(net_devices()) do
		local dev, target = d.dev, d.target
		if dev ~= "lo" then
			local isvirt = target ~= "" and target:find("devices/virtual", 1, true) ~= nil
			local iswlan = target ~= "" and target:find("ieee80211", 1, true) ~= nil
			if isvirt or iswlan then
				others[#others + 1] = dev
			else
				physical[#physical + 1] = dev
			end
		end
	end

	local function port_info(dev, role)
		local base = "/sys/class/net/" .. dev
		local up = false
		local oper = readstr(base .. "/operstate")
		local carrier = readnum(base .. "/carrier")
		if oper == "up" or carrier == 1 then
			up = true
		end
		local speed = readnum(base .. "/speed") or 0
		if not up or speed < 0 or speed > 1000000 then
			speed = 0
		end
		local duplex = readstr(base .. "/duplex") or "unknown"
		return obj({
			name = dev,
			role = role,
			up = up and 1 or 0,
			speed = math.floor(speed),
			duplex = duplex ~= "" and duplex or "unknown",
			mac = (readstr(base .. "/address") or ""):upper(),
			rx_bytes = readnum(base .. "/statistics/rx_bytes") or 0,
			tx_bytes = readnum(base .. "/statistics/tx_bytes") or 0,
			rx_packets = readnum(base .. "/statistics/rx_packets") or 0,
			tx_packets = readnum(base .. "/statistics/tx_packets") or 0,
			rx_error_packets = readnum(base .. "/statistics/rx_errors") or 0,
			tx_error_packets = readnum(base .. "/statistics/tx_errors") or 0
		})
	end

	if #physical == 0 then
		-- 虚拟交换机环境降级: 展示 br-lan / wan 逻辑口
		if wan_l3dev and wan_l3dev ~= "" then
			ports[#ports + 1] = port_info(wan_l3dev, "wan")
		end
		for _, d in ipairs(others) do
			if d:match("^br%-") then
				ports[#ports + 1] = port_info(d, "lan")
			end
		end
	else
		for _, d in ipairs(physical) do
			local role = "lan"
			if d == wan_l3dev or d == "wan" then
				role = "wan"
			end
			ports[#ports + 1] = port_info(d, role)
		end
	end

	table.sort(ports, function(a, b)
		local ra = (a.role == "wan") and 0 or 1
		local rb = (b.role == "wan") and 0 or 1
		if ra ~= rb then
			return ra < rb
		end
		return a.name < b.name
	end)

	while #ports > 8 do
		table.remove(ports)
	end
	return arr(ports)
end

-- ---------------------------------------------------------------- 连接跟踪

-- 知名加密 DNS (DoH/DoT) 服务器, 目标为这些 IP 的 443/853 连接按 DNS 解析归类
local DNS_SERVERS = {
	["223.5.5.5"] = true, ["223.6.6.6"] = true, ["119.29.29.29"] = true,
	["114.114.114.114"] = true, ["114.114.115.115"] = true,
	["1.1.1.1"] = true, ["1.0.0.1"] = true, ["8.8.8.8"] = true,
	["8.8.4.4"] = true, ["9.9.9.9"] = true
}

local function classify_service(proto, port, dst)
	proto = tostring(proto or "")
	port = tonumber(port) or 0
	dst = tostring(dst or "")
	if DNS_SERVERS[dst] and (port == 443 or port == 853) then return "DNS解析" end
	if port == 853 then return "DNS解析" end
	if proto == "udp" and port == 443 then return "视频与直播" end
	if port == 53 then return "DNS解析" end
	if proto == "udp" and (port == 67 or port == 68) then return "系统服务" end
	if proto == "udp" and port == 123 then return "系统服务" end
	if proto == "tcp" and (port == 80 or port == 443 or port == 8080) then return "网页浏览" end
	if proto == "tcp" and (port == 22 or port == 23) then return "远程访问" end
	if proto == "tcp" and (port == 1723 or port == 1194) then return "远程访问" end
	if proto == "udp" and (port == 500 or port == 4500 or port == 51820) then return "远程访问" end
	if proto == "udp" and (port >= 3478 and port <= 3481 or port == 5349) then return "语音视频" end
	if proto == "tcp" and (port == 5060 or port == 5061) then return "语音视频" end
	if proto == "tcp" and (port == 1935 or port == 554 or port == 8554) then return "视频与直播" end
	if proto == "tcp" and (port >= 6881 and port <= 6999 or port == 16881 or port == 51413) then return "下载传输" end
	if proto == "udp" and (port >= 6881 and port <= 6999) then return "下载传输" end
	if proto == "tcp" and (port == 3074 or (port >= 27015 and port <= 27050)) then return "游戏娱乐" end
	if proto == "udp" and (port == 3074 or (port >= 27000 and port <= 27050) or (port >= 7777 and port <= 7788)) then return "游戏娱乐" end
	if proto == "tcp" and (port == 993 or port == 995 or port == 465 or port == 587 or port == 25 or port == 110 or port == 143) then return "邮件服务" end
	return "其他服务"
end

local function is_public_unicast(ip)
	-- 排除组播/保留/环回地址 (224.0.0.0/3、0.x、127.x), 避免广播噪声混入会话
	local a = tonumber(ip:match("^(%d+)%."))
	if not a or a >= 224 or a == 0 or a == 127 then
		return false
	end
	return true
end

local function parse_conntrack()
	return memo("ctrack", function()
		local raw = readfile("/proc/net/nf_conntrack")
			or readfile("/proc/net/ip_conntrack")
			or ""
		local sessions = {}
		for line in raw:gmatch("[^\r\n]+") do
			local proto = line:match("^%S+%s+%S+%s+(%a+)")
			if proto then
				-- 只取需要的 5 个字段: 拿到原始/应答两个方向的 bytes 后立即跳出,
				-- 不再把整行的 mark/use/status 等全部扫一遍 (大连接表下省一半时间)
				local src, dst, sport, dport
				local up, down, nb = 0, 0, 0
				for k, v in line:gmatch("(%w+)=(%S+)") do
					if k == "src" then
						if not src then src = v end
					elseif k == "dst" then
						if not dst then dst = v end
					elseif k == "sport" then
						if not sport then sport = v end
					elseif k == "dport" then
						if not dport then dport = v end
					elseif k == "bytes" then
						nb = nb + 1
						if nb == 1 then
							up = tonumber(v) or 0
						else
							down = tonumber(v) or 0
							break
						end
					end
				end
				if src and dst and is_private_ip(src) and not is_private_ip(dst) and is_public_unicast(dst) then
					sessions[#sessions + 1] = {
						ip = src,
						dst = dst,
						proto = proto,
						sport = tonumber(sport) or 0,
						dport = tonumber(dport) or 0,
						up = up,
						down = down
					}
				end
			end
		end
		return sessions
	end) or {}
end

local function hostnames()
	local h = memo("hosts", function()
		local mac_by_ip = {}
		local name_by_mac = {}

		local leases = readfile("/tmp/dhcp.leases") or ""
		for line in leases:gmatch("[^\r\n]+") do
			local mac, ip, hn = line:match("^%d+%s+(%S+)%s+(%S+)%s+(%S*)")
			if mac and ip then
				mac_by_ip[ip] = mac:lower()
				if hn and hn ~= "" and hn ~= "*" then
					name_by_mac[mac:lower()] = hn
				end
			end
		end

		for line in (readfile("/etc/ethers") or ""):gmatch("[^\r\n]+") do
			local mac, ip = line:match("^(%S+)%s+(%S+)")
			if mac and ip then
				mac_by_ip[ip] = mac:lower()
			end
		end

		local arp = readfile("/proc/net/arp") or ""
		for line in arp:gmatch("[^\r\n]+") do
			local ip, mac = line:match("^(%d+%.%d+%.%d+%.%d+)%s+%S+%s+%S+%s+([%x:]+)")
			if ip and mac and mac ~= "00:00:00:00:00:00" then
				mac_by_ip[ip] = mac:lower()
			end
		end

		return { mac = mac_by_ip, name = name_by_mac }
	end)
	return h.mac, h.name
end

local function mac_tail(mac)
	if mac and #mac >= 5 then
		return "设备-" .. mac:upper():gsub(":", ""):sub(-4)
	end
	return "未知设备"
end

local function user_aggregate(sessions, mac_by_ip, name_by_mac)
	local users = {}
	for _, s in ipairs(sessions) do
		local u = users[s.ip]
		if not u then
			u = { ip = s.ip, up = 0, down = 0, cats = {}, tops = {} }
			users[s.ip] = u
		end
		u.up = u.up + s.up
		u.down = u.down + s.down
		local cat = classify_service(s.proto, s.dport, s.dst)
		u.cats[cat] = (u.cats[cat] or 0) + 1
		local rk = s.dst .. ":" .. s.dport
		u.tops[rk] = (u.tops[rk] or 0) + s.up + s.down
	end

	local list = {}
	for ip, u in pairs(users) do
		local mac = mac_by_ip[ip] or ""
		local name = name_by_mac[mac] or mac_tail(mac)
		local topcat, topn = "其他服务", 0
		for c, n in pairs(u.cats) do
			if n > topn then
				topcat, topn = c, n
			end
		end
		local topurl, topv = "", 0
		for k, v in pairs(u.tops) do
			if v > topv then
				topurl, topv = k, v
			end
		end
		list[#list + 1] = {
			ip = ip,
			mac = mac,
			hostname = name,
			up = u.up,
			down = u.down,
			app = topcat,
			url = topurl
		}
	end
	table.sort(list, function(a, b)
		return (a.up + a.down) > (b.up + b.down)
	end)
	return list
end

-- ---------------------------------------------------------------- 实时流量序列

local function traffic_series()
	local wan_dev = wan_device()
	local samples = {}
	if wan_dev and wan_dev ~= "" then
		local rx = readnum("/sys/class/net/" .. wan_dev .. "/statistics/rx_bytes")
		local tx = readnum("/sys/class/net/" .. wan_dev .. "/statistics/tx_bytes")
		if rx and tx then
			local now = os.time()
			local s = state_read("traffic") or {}
			s.samples = s.samples or {}
			local last = s.samples[#s.samples]
			if not (last and now - (last.t or 0) < 2) then
				local up, down = 0, 0
				if last and (now - last.t) <= 30 and tx >= (last.tx or 0) and rx >= (last.rx or 0) then
					local dt = math.max(1, now - last.t)
					up = math.floor((tx - last.tx) / dt)
					down = math.floor((rx - last.rx) / dt)
				end
				s.samples[#s.samples + 1] = { t = now, up = up, down = down, rx = rx, tx = tx }
				while #s.samples > 70 do
					table.remove(s.samples, 1)
				end
				state_write("traffic", s)
			end
			samples = s.samples
		end
	end

	local list = {}
	for _, x in ipairs(samples) do
		list[#list + 1] = { up = x.up or 0, down = x.down or 0 }
	end
	while #list < 60 do
		table.insert(list, 1, { up = 0, down = 0 })
	end
	while #list > 60 do
		table.remove(list, 1)
	end
	return arr(list), wan_dev or "wan"
end

-- ---------------------------------------------------------------- DNS 采集状态 (unidash-dnsd)

local function dns_state()
	local jc = getjsonc()
	if not jc then
		return nil
	end
	return memo("dnsstate", function()
		local c = readfile("/tmp/unidash_dns.json")
		if not c or #c < 2 then
			return nil
		end
		local ok, t = pcall(jc.parse, c)
		if ok and type(t) == "table" then
			return t
		end
		return nil
	end)
end

-- ---------------------------------------------------------------- API 实现

local function build_common()
	local mac_by_ip, name_by_mac = hostnames()

	local arch = board_arch()
	local total_mem, used_mem = meminfo_kb()
	local up_kb, down_kb = today_flow_kb()

	local lan_st = iface_status("lan")
	local wan_st = iface_status("wan")
	local lan = iface_v4info(lan_st)
	local wan = iface_v4info(wan_st)

	if lan.ip == "" and lan_st == nil then
		local fb = ipaddr_fallback("br-lan")
		lan.ip = fb.ip
		lan.mask = fb.mask
	end
	if wan.ip == "" and wan_st == nil then
		local fb = ipaddr_fallback(default_route_dev())
		wan.ip = fb.ip
		wan.mask = fb.mask
		wan.gw = fb.gw
	end
	if #lan.dns == 0 then
		lan.dns = dns_from_resolv()
	end
	if #wan.dns == 0 then
		wan.dns = dns_from_resolv()
	end

	local internet, check_status = internet_status(wan.ip)

	local wan_l3dev = wan_device()
	local client_num = 0
	local seen = {}
	for ip, mac in pairs(mac_by_ip) do
		if not seen[mac] and is_private_ip(ip) then
			seen[mac] = true
			client_num = client_num + 1
		end
	end

	local sessions = parse_conntrack()

	-- DNS 采集数据 (unidash-dnsd 写入): 把连接目标 IP 反查成访问网址
	local dns = dns_state() or {}
	local dns_ipmap = dns.ipmap or {}
	local dns_clients = dns.clients or {}

	local function dns_domain(ip)
		local e = dns_ipmap[ip]
		if type(e) == "table" and type(e.d) == "string" and e.d ~= "" then
			return e.d
		end
		return nil
	end

	-- 各终端最近一次解析成功的域名: 当某些连接的目标 IP 没进映射表
	-- (dnsmasq 缓存应答 / fake-ip / 采集刚启动) 时, 用它给网页类连接兜底域名
	local client_dom = {}
	local cnow = os.time()
	for client, qs in pairs(dns_clients) do
		if type(qs) == "table" then
			local best
			for _, q in ipairs(qs) do
				if type(q) == "table" and type(q.d) == "string" and q.d ~= ""
					and (cnow - (q.t or 0)) <= 300 then
					if not best or (q.t or 0) > (best.t or 0) then
						best = q
					end
				end
			end
			if best then client_dom[client] = best.d end
		end
	end

	-- 网页类端口才套用终端最近域名, 避免把 CDN/游戏等连接错标成浏览过的站点
	local WEB_PORTS = { [80] = true, [443] = true, [8080] = true, [8443] = true }
	local function session_domain(s)
		local d = dns_domain(s.dst)
		if d then return d end
		if WEB_PORTS[tonumber(s.dport) or 0] and client_dom[s.ip] then
			return client_dom[s.ip]
		end
		return nil
	end

	-- 活跃服务 (替代原"正在访问"的 DPI 应用识别)
	local top = {}
	for _, s in ipairs(sessions) do
		top[#top + 1] = s
	end
	table.sort(top, function(a, b)
		return (a.up + a.down) > (b.up + b.down)
	end)
	-- 有网址映射的会话优先展示 (磁贴显示网址), 其余按流量补位
	local with_dom, without_dom = {}, {}
	local cats = {}
	for _, s in ipairs(top) do
		local cat = classify_service(s.proto, s.dport, s.dst)
		cats[cat] = (cats[cat] or 0) + 1
		if session_domain(s) then
			with_dom[#with_dom + 1] = s
		else
			without_dom[#without_dom + 1] = s
		end
	end
	local ordered = {}
	for _, s in ipairs(with_dom) do ordered[#ordered + 1] = s end
	for _, s in ipairs(without_dom) do ordered[#ordered + 1] = s end
	-- 每类服务只保留一条代表会话 (top 已按字节降序),
	-- 否则同类会话(如 PCDN 随机端口)会把磁贴区刷成重复项
	local cat_seen = {}
	local app_list = {}
	for i = 1, #ordered do
		local s = ordered[i]
		local cat = classify_service(s.proto, s.dport, s.dst)
		if not cat_seen[cat] then
			cat_seen[cat] = true
			app_list[#app_list + 1] = obj({
				id = "",
				name = session_domain(s) or s.dst,
				cat_name = cat,
				icon = 0,
				timestamp = os.time(),
				mac = mac_by_ip[s.ip] or "",
				src_ip = s.ip,
				dst_ip = s.dst,
				protocol = s.proto,
				src_port = s.sport,
				dst_port = s.dport
			})
			if #app_list >= 10 then
				break
			end
		end
	end
	local cat_total = 0
	for _ in pairs(cats) do
		cat_total = cat_total + 1
	end

	-- 活跃地址: 维护"最近访问目标"持久列表 (/tmp/unidash_recent_hosts.json)
	-- 原来靠 60 秒节流增量下发, 页面一刷新列表就是空的; 改为持久化后刷新仍能看到最近网址
	local now = os.time()
	local recent_hosts = state_read("recent_hosts") or {}

	local function touch_host(name, mac, url)
		if not url or url == "" then return end
		local key = tostring(mac or "") .. "|" .. url
		local e = recent_hosts[key]
		if not e then
			recent_hosts[key] = { name = name or "", mac = mac or "", url = url, t = now, seen = now }
		else
			e.seen = now
			if name and name ~= "" then e.name = name end
		end
	end

	-- 终端名: 已登记主机名 > MAC 末四位 > 短标签 (IPv6 终端不能把整串地址塞进面板)
	local function host_label(ip)
		local mac = mac_by_ip[ip]
		if mac and mac ~= "" then
			return name_by_mac[mac] or mac_tail(mac)
		end
		if ip:find(":", 1, true) then
			return "设备-" .. ip:gsub(":", ""):sub(-4):upper()
		end
		return ip
	end

	-- 1) 当前连接的目标 (优先域名, 没命中映射时才退化为 IP:端口)
	for i = 1, math.min(#ordered, 12) do
		local s = ordered[i]
		local mac = mac_by_ip[s.ip] or s.ip
		touch_host(host_label(s.ip), mac,
			session_domain(s) or (s.dst .. ":" .. s.dport))
	end
	-- 2) 各终端最近的 DNS 查询域名 (采集刚启动、连接映射还没建立时也能显示网址)
	for client, qs in pairs(dns_clients) do
		if type(qs) == "table" then
			local latest
			for _, q in ipairs(qs) do
				if type(q) == "table" and type(q.d) == "string" and q.d ~= ""
					and (now - (q.t or 0)) <= 300 then
					if not latest or (q.t or 0) > (latest.t or 0) then
						latest = q
					end
				end
			end
			if latest then
				local mac = mac_by_ip[client] or ""
				touch_host(host_label(client), (mac ~= "" and mac) or client, latest.d)
			end
		end
	end

	local host_list = {}
	local hl = {}
	for k, e in pairs(recent_hosts) do
		-- 域名条目保留 30 分钟, 只有 IP 的条目 5 分钟即清 (尽快换成域名)
		local ttl = 1800
		if e.url and (e.url:match("^%d+%.%d+%.%d+%.%d+") or e.url:find(":", 1, true)) then
			ttl = 300
		end
		if now - (e.seen or e.t or 0) > ttl then
			recent_hosts[k] = nil
		else
			hl[#hl + 1] = e
		end
	end
	table.sort(hl, function(a, b) return (a.t or 0) > (b.t or 0) end)
	for i = 1, math.min(#hl, 10) do
		local e = hl[i]
		host_list[#host_list + 1] = obj({
			name = e.name or "",
			mac = e.mac or "",
			url = e.url or "",
			timestamp = e.t or now
		})
	end
	state_write("recent_hosts", recent_hosts)

	local series, iface_label = traffic_series()

	local ports = list_ports(wan_l3dev)

	local dns_count = 0
	for _ in pairs(dns_ipmap) do
		dns_count = dns_count + 1
	end

	return obj({
		system_status = obj({
			hostname = sys_hostname(),
			model = device_model(),
			arch = arch,
			cpu_model_name = cpu_model_name(arch),
			openwrt_version = openwrt_version(),
			kernel_version = readstr("/proc/sys/kernel/osrelease") or "",
			uptime = sys_uptime(),
			cpu = cpu_percent(),
			cpu_temp = cpu_temperature(),
			total_mem = total_mem,
			used_mem = used_mem,
			connections = conntrack_count(),
			client_num = client_num,
			storage = storage_info(),
			flow = obj({
				today_up = up_kb,
				today_down = down_kb
			})
		}),
		network_status = obj({
			work_mode = 1,
			internet = internet,
			internet_check_status = check_status,
			lan = obj({
				ip = lan.ip ~= "" and lan.ip or "0.0.0.0",
				mask = lan.mask ~= "" and lan.mask or "255.255.255.0",
				ipv6 = lan.ipv6,
				gateway = lan.gw,
				dns = arr(lan.dns)
			}),
			wan = obj({
				ip = wan.ip ~= "" and wan.ip or "0.0.0.0",
				mask = wan.mask ~= "" and wan.mask or "255.255.255.0",
				ipv6 = wan.ipv6,
				gateway = wan.gw,
				dns = arr(wan.dns)
			}),
			port_status = ports
		}),
		active_app = obj({
			total = cat_total,
			list = arr(app_list)
		}),
		active_host = obj({
			capture = obj({
				mode = tostring(dns.mode or "未运行"),
				count = dns_count
			}),
			list = arr(host_list)
		}),
		interface_traffic = obj({
			interface = iface_label,
			traffic = series
		})
	})
end

function api_common()
	json_cached("common", build_common, obj({
		system_status = obj({}),
		network_status = obj({}),
		active_app = obj({ total = 0, list = arr({}) }),
		active_host = obj({ list = arr({}) }),
		interface_traffic = obj({ interface = "wan", traffic = arr({}) })
	}))
end

function api_init_status()
	json_out(obj({ init_status = 1 }))
end

function api_set_init_status()
	json_out(obj({ ok = 1 }))
end

function api_daily_top_users()
	json_cached("top", function()
		local mac_by_ip, name_by_mac = hostnames()
		local sessions = parse_conntrack()
		local users = user_aggregate(sessions, mac_by_ip, name_by_mac)
		local out = {}
		for i = 1, math.min(#users, 20) do
			local u = users[i]
			out[#out + 1] = obj({
				nickname = "",
				hostname = u.hostname,
				mac = u.mac,
				ip = u.ip,
				up_bytes = u.up,
				down_bytes = u.down,
				total_bytes = u.up + u.down
			})
		end
		return obj({ users = arr(out) })
	end, obj({ users = arr({}) }))
end

function api_active_users()
	local count = tonumber(http.formvalue("count")) or 8
	json_cached("users" .. count, function()
		local mac_by_ip, name_by_mac = hostnames()
		local sessions = parse_conntrack()
		local users = user_aggregate(sessions, mac_by_ip, name_by_mac)

		-- 速率: 与上次快照做差分
		local now = os.time()
		local prev = state_read("rates") or {}
		local prev_users = prev.users or {}
		local cur_users = {}
		local out = {}
		for i = 1, math.min(#users, count) do
			local u = users[i]
			cur_users[u.ip] = { up = u.up, down = u.down }
			local up_rate, down_rate = 0, 0
			local p = prev_users[u.ip]
			local dt = now - (prev.ts or 0)
			if p and dt >= 2 and dt <= 120 and u.up >= p.up and u.down >= p.down then
				up_rate = math.floor((u.up - p.up) / dt)
				down_rate = math.floor((u.down - p.down) / dt)
			end
			out[#out + 1] = obj({
				nickname = "",
				hostname = u.hostname,
				mac = u.mac,
				ip = u.ip,
				up_rate = up_rate,
				down_rate = down_rate,
				today_up_bytes = u.up,
				today_down_bytes = u.down,
				app = u.app,
				url = u.url ~= "" and u.url or ""
			})
		end
		state_write("rates", { ts = now, users = cur_users })
		return obj({ users = arr(out) })
	end, obj({ users = arr({}) }))
end

function api_app_type_stats()
	-- 注意: 该接口的 type 参数 (hourly/daily) 不参与统计, 两个请求结果完全一致,
	-- 所以共用同一个缓存 tag, 前端并行发的两次请求只做一次统计
	json_cached("apptype", function()
		local sessions = parse_conntrack()
		local counts = {}
		local order = {}
		for _, s in ipairs(sessions) do
			local cat = classify_service(s.proto, s.dport, s.dst)
			if counts[cat] == nil then
				counts[cat] = 0
				order[#order + 1] = cat
			end
			counts[cat] = counts[cat] + 1
		end
		table.sort(order, function(a, b)
			return counts[a] > counts[b]
		end)
		local types = {}
		for i, cat in ipairs(order) do
			types[#types + 1] = obj({
				app_type = i,
				name = cat,
				total_time = counts[cat]
			})
		end
		return obj({ types = arr(types) })
	end, obj({ types = arr({}) }))
end

-- ---------------------------------------------------------------- 路由注册

function index()
	-- 页面注册为 admin 下单段叶子节点 (与原版 fwx_dashboard 一致),
	-- 在所有主题的侧边栏渲染为顶级菜单项「仪表板」。
	-- 注意: 不能用 admin/xxx/dashboard 两段结构 —— 中间节点无标题时,
	-- 标准主题 (bootstrap/argon 等) 的菜单渲染会跳过整个子树。
	-- 菜单标题跟随 LuCI 语言: 中文环境显示「仪表板」, 其他语言显示 Dashboard
	local menu_title = "Dashboard"
	local ok_i18n, i18n = pcall(require, "luci.i18n")
	if ok_i18n and i18n and i18n.context then
		local lang = tostring(i18n.context.lang or ""):lower()
		if lang:match("^zh") then
			menu_title = "仪表板"
		end
	end
	local page = entry({ "admin", "unidash" }, template("unidash/dashboard"), menu_title, 1)
	page.leaf = true

	entry({ "admin", "unidash_api", "get_dashboard_common" }, call("api_common")).leaf = true
	entry({ "admin", "unidash_api", "get_init_status" }, call("api_init_status")).leaf = true
	entry({ "admin", "unidash_api", "set_init_status" }, call("api_set_init_status")).leaf = true
	entry({ "admin", "unidash_api", "get_daily_top_users" }, call("api_daily_top_users")).leaf = true
	entry({ "admin", "unidash_api", "get_active_users" }, call("api_active_users")).leaf = true
	entry({ "admin", "unidash_api", "get_app_type_stats" }, call("api_app_type_stats")).leaf = true
end
