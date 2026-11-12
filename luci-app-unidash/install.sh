#!/bin/sh
# luci-app-unidash 一键安装脚本
# 在路由器 (OpenWrt) 上运行。
#
# 用法 (路由器上):
#   1. 把整个 luci-app-unidash 目录上传到路由器, 例如 /tmp/luci-app-unidash
#      (Windows 可用 WinSCP 拖拽, 或: scp -r -O luci-app-unidash root@192.168.1.1:/tmp/)
#   2. ssh 进路由器执行:  sh /tmp/luci-app-unidash/install.sh
#   3. 强制刷新浏览器 (Ctrl+F5), 打开侧边栏顶级「仪表板」
set -e
cd "$(dirname "$0")" || exit 1

LUA_ROOT=/usr/lib/lua/luci
WWW_ROOT=/www/luci-static

echo ">>> luci-app-unidash v1.2.2 安装开始"

if [ ! -d "$LUA_ROOT" ]; then
    echo "错误: 未找到 LuCI 目录 ($LUA_ROOT), 请确认系统为 OpenWrt 且已安装 LuCI"
    exit 1
fi

# 1. LuCI 控制器与视图
mkdir -p "$LUA_ROOT/controller" "$LUA_ROOT/view/unidash"
cp -f luasrc/controller/unidash.lua      "$LUA_ROOT/controller/"
cp -f luasrc/view/unidash/dashboard.htm  "$LUA_ROOT/view/unidash/"

# 2. 前端静态资源 (jquery / echarts / 站点名称字典 / 语言包 / 分类图标)
mkdir -p "$WWW_ROOT/resources/unidash/icons"
cp -f htdocs/luci-static/resources/unidash/jquery.min.js  "$WWW_ROOT/resources/unidash/"
cp -f htdocs/luci-static/resources/unidash/echarts.min.js "$WWW_ROOT/resources/unidash/"
cp -f htdocs/luci-static/resources/unidash/i18n.js        "$WWW_ROOT/resources/unidash/"
cp -f htdocs/luci-static/resources/unidash/site_names.js  "$WWW_ROOT/resources/unidash/"
cp -f htdocs/luci-static/resources/unidash/icons/*.svg    "$WWW_ROOT/resources/unidash/icons/"

# 3. luci-compat (XHR 兼容层, Lua 应用的标准依赖; 兼容 opkg 与 apk 两种包管理器)
if ! (command -v opkg >/dev/null 2>&1 && opkg list-installed luci-compat >/dev/null 2>&1); then
    echo ">>> 安装依赖 luci-compat ..."
    if command -v opkg >/dev/null 2>&1; then
        opkg update >/dev/null 2>&1 || true
        opkg install luci-compat || echo "警告: 自动安装失败, 请手动执行: opkg install luci-compat"
    elif command -v apk >/dev/null 2>&1; then
        apk update >/dev/null 2>&1 || true
        apk add luci-compat || echo "警告: 自动安装失败, 请手动执行: apk add luci-compat"
    else
        echo "警告: 未找到 opkg/apk, 请手动安装 luci-compat"
    fi
fi

# 4. DNS 采集守护进程 (实时显示访问网址) 与诊断工具
mkdir -p /usr/bin /etc/init.d
cp -f root/usr/bin/unidash-dnsd     /usr/bin/unidash-dnsd
cp -f root/usr/bin/unidash-diag     /usr/bin/unidash-diag
cp -f root/etc/init.d/unidash-dnsd  /etc/init.d/unidash-dnsd
chmod +x /usr/bin/unidash-dnsd /usr/bin/unidash-diag /etc/init.d/unidash-dnsd

command -v lua >/dev/null 2>&1 || {
    echo ">>> 安装依赖 lua ..."
    if command -v apk >/dev/null 2>&1; then
        apk add lua 2>/dev/null || apk add lua5.4 2>/dev/null || apk add lua5.3 2>/dev/null || apk add lua5.1 2>/dev/null || true
    elif command -v opkg >/dev/null 2>&1; then
        opkg install lua 2>/dev/null || opkg install lua5.3 2>/dev/null || opkg install lua5.1 2>/dev/null || true
    fi
}
if command -v tcpdump >/dev/null 2>&1; then
    echo ">>> [OK] tcpdump 可用, DNS 采集为精确模式 (域名 -> IP -> 客户端)"
else
    echo ">>> 尝试安装 tcpdump-mini (精确匹配域名; 失败会自动降级)..."
    if command -v apk >/dev/null 2>&1; then
        apk update >/dev/null 2>&1 || true
        apk add tcpdump-mini >/dev/null 2>&1 || true
    elif command -v opkg >/dev/null 2>&1; then
        opkg update >/dev/null 2>&1 || true
        opkg install tcpdump-mini >/dev/null 2>&1 || true
    fi
fi
if ! command -v tcpdump >/dev/null 2>&1; then
    echo ">>> tcpdump 不可用, 启用 dnsmasq 查询日志作为域名来源 (可 uci 关闭)"
    uci set dhcp.@dnsmasq[0].logqueries='1' 2>/dev/null || true
    uci commit dhcp 2>/dev/null || true
    /etc/init.d/dnsmasq restart 2>/dev/null || true
fi
/etc/init.d/unidash-dnsd enable 2>/dev/null || true
/etc/init.d/unidash-dnsd restart 2>/dev/null || true

# 5. 让 LuCI 重新扫描控制器 (清理索引缓存) 并重启 Web 服务
rm -rf /tmp/luci-indexcache* 2>/dev/null || true
/etc/init.d/uhttpd restart 2>/dev/null || true

# 6. 安装结果自检
echo ">>> 校验安装结果:"
[ -f "$LUA_ROOT/controller/unidash.lua" ] \
    && echo "    [OK] 控制器已安装" || echo "    [失败] 控制器缺失!"
[ -f "$LUA_ROOT/view/unidash/dashboard.htm" ] \
    && echo "    [OK] 页面模板已安装" || echo "    [失败] 页面模板缺失!"
[ -f "$WWW_ROOT/resources/unidash/echarts.min.js" ] \
    && echo "    [OK] 前端资源已安装" || echo "    [失败] 前端资源缺失!"
[ -f /usr/bin/unidash-dnsd ] \
    && echo "    [OK] DNS 采集守护进程已安装" || echo "    [失败] DNS 守护进程缺失!"
[ -f /usr/bin/unidash-diag ] \
    && echo "    [OK] 诊断工具已安装 (路由器上运行 unidash-diag)" || echo "    [失败] 诊断工具缺失!"
if /etc/init.d/unidash-dnsd enabled 2>/dev/null; then
    echo "    [OK] DNS 采集服务已启用"
else
    echo "    [警告] DNS 采集服务未启用, 网址显示将退化为 IP"
fi

COMPAT_OK=0
if command -v opkg >/dev/null 2>&1 && opkg list-installed luci-compat >/dev/null 2>&1; then
    COMPAT_OK=1
elif command -v apk >/dev/null 2>&1 && apk info -e luci-compat >/dev/null 2>&1; then
    COMPAT_OK=1
fi
if [ "$COMPAT_OK" = "1" ]; then
    echo "    [OK] luci-compat 已安装"
else
    echo "    [重要] luci-compat 未安装! 缺少它时 Lua 应用整体不生效,"
    echo "         菜单不会出现、页面会 404。请手动执行:"
    echo "           opkg update && opkg install luci-compat   (或 apk add luci-compat)"
fi

echo ">>> DNS 采集链路诊断 (磁贴显示网址的前提):"
LUA_BIN=""
for c in lua lua5.4 lua5.3 lua5.1; do
    command -v "$c" >/dev/null 2>&1 && { LUA_BIN="$c"; break; }
done
if [ -n "$LUA_BIN" ]; then
    echo "    [OK] lua 解释器存在 ($LUA_BIN)"
else
    echo "    [失败] 缺少 lua! 采集进程无法运行。执行: apk add lua (或 opkg install lua) 后:"
    echo "           /etc/init.d/unidash-dnsd restart"
fi
if command -v tcpdump >/dev/null 2>&1; then
    echo "    [OK] tcpdump 存在 (精确模式: 域名->IP->客户端)"
else
    echo "    [提示] 无 tcpdump, 使用日志模式 (需客户端走路由器 DNS)"
fi
sleep 1
if ps w 2>/dev/null | grep "[u]nidash-dnsd" >/dev/null; then
    echo "    [OK] 采集进程运行中"
else
    echo "    [失败] 采集进程未运行! 查看: logread | grep unidash-dnsd"
fi
if [ -s /tmp/unidash_dns.json ]; then
    echo "    [OK] 已产生采集数据: $(head -c 100 /tmp/unidash_dns.json 2>/dev/null)..."
else
    echo "    [等待] 暂无采集数据 (上网产生 DNS 查询后 2-5 秒内生成)"
fi
echo "    采集日志: $(logread 2>/dev/null | grep unidash-dnsd | tail -2 | tr '\n' ' | ')"

echo ">>> 安装完成!"
echo ">>> 菜单位置: 侧边栏顶级「仪表板」(找不到时请退出重新登录 + 浏览器 Ctrl+F5)"
echo ">>> 直接访问: http://<路由器IP>/cgi-bin/luci/admin/unidash"
echo ">>> 访问网址显示: 上网几秒后自动出现域名; 若只显示 IP, 运行 logread | grep unidash-dnsd 查看采集状态"
echo ">>> 若仍不显示, 运行诊断:"
echo "    opkg list-installed | grep compat; ls -l /usr/lib/lua/luci/controller/unidash.lua; ls /tmp | grep luci-indexcache"
