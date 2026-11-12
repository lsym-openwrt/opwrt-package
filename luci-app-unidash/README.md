# luci-app-unidash · 通用 OpenWrt 仪表盘

<div align="center">

![Version](https://img.shields.io/badge/version-1.2.2-blue) ![Ported from](https://img.shields.io/badge/ported%20from-luci--app--fwx--dashboard-green) ![License](https://img.shields.io/badge/license-Apache--2.0-orange)

</div>

> 从 [fanchmwrt/fanchmwrt-packages](https://github.com/fanchmwrt/fanchmwrt-packages) 的 **luci-app-fwx-dashboard** 完整移植并二次开发：保留原版布局、数据块与图表，数据源全部改为标准 OpenWrt 接口，**无需 fwxd / kmod-fwx 私有组件**，任意 LuCI 主题均可使用。

## ✨ 功能特性

- 📊 顶部 5 数据块：联网状态 / 活跃服务 / 在线用户 / 连接数 / 今日流量
- 📈 ECharts 实时流量双折线图、连接分布环形图
- 👥 用户流量 Top8、活跃终端 Top8
- 🖥️ 右侧系统信息 / 温度 / 端口状态栏
- 🔍 `unidash-dnsd` 被动 DNS 采集（tcpdump / logread 双模式）：连接目标反查为网址，经站点字典显示中文名（爱奇艺 / 百度 / Google…）
- 🌐 中英双语，跟随系统语言（150+ 词条，动态翻译）
- 🎨 亮暗自适应，兼容任意 LuCI 主题，仅依赖 `luci-compat`

## 📌 与 fwx-dashboard 的差异

| #   | 差异       | 说明                                                                                                  |
| --- | ---------- | ----------------------------------------------------------------------------------------------------- |
| 1   | 标准数据源 | 全部改用 /proc、ubus、conntrack、dhcp.leases，去掉 fwxd / kmod-fwx 依赖                               |
| 2   | 双语体系   | 新增 `i18n.js`（EN 字典 + TreeWalker / MutationObserver 动态翻译），站点字典扩充 58 个英文品牌        |
| 3   | 性能治理   | 请求级记忆化 + 响应级 2 秒缓存 + 前端防请求堆积 + 后台页停轮询，一轮轮询 0.85s → 0.53s（约 **-37%**） |
| 4   | dnsd 增强  | tcpdump IPv6 行解析修复、活跃地址持久化（`/tmp/unidash_recent_hosts.json`）                           |

## 📦 安装

**方式一：一键脚本**

```bash
curl -sL https://raw.githubusercontent.com/lsym-openwrt/opwrt-package/main/luci-app-unidash/install.sh | ash
```

**方式二：SDK 编译**

```bash
git clone https://github.com/lsym-openwrt/opwrt-package.git
cp -r opwrt-package/luci-app-unidash package/

make menuconfig   # LuCI → Applications → luci-app-unidash
make package/luci-app-unidash/compile V=s
```

## 📄 许可证

**Apache License 2.0**（与原项目一致）。

## 🙏 致谢

- 原版仪表盘：[fanchmwrt/fanchmwrt-packages](https://github.com/fanchmwrt/fanchmwrt-packages) 的 luci-app-fwx-dashboard
