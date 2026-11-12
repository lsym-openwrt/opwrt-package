# OpenWrt Nikki · MeowC 版

<div align="center">

![Version](https://img.shields.io/badge/version-1.26.2-blue) ![Upstream](https://img.shields.io/badge/upstream-nikkinikki%2FOpenWrt--nikki--v1.26.2-green) ![License](https://img.shields.io/badge/license-GPL--3.0-orange)

</div>

> 基于 [nikkinikki-org/OpenWrt-nikki](https://github.com/nikkinikki-org/OpenWrt-nikki) **v1.26.2** 修改的 OpenWrt 透明代理套件：mihomo 内核替换为 **MeowC**（meowx-core），并针对 rpcd 兼容性与默认策略做了增强。

Nikki 是在 OpenWrt 上运行 mihomo 内核的透明代理解决方案，包含核心包 `nikki` 与 LuCI 管理界面 `luci-app-nikki`。

## ✨ 功能特性

- 透明代理：支持 Redirect / TPROXY / TUN 三种模式，IPv4 与 IPv6 可独立开关
- 访问控制：按接口 / IP / MAC 精细分流
- 配置文件混入（mixin）与在线配置编辑器
- 定时重启内核、配置文件订阅
- 完整的 LuCI 管理界面

## 📌 与上游的主要差异

本项目基于上游 v1.26.2（含上游提交 `78e1a75`）修改，主要改动：

| #   | 改动                                     | 说明                                                                                                                                                                                                                                                       |
| --- | ---------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | 内核替换为 MeowC                         | 移除上游 `mihomo-alpha` / `mihomo-meta`，改为 [mmwx-group/meowx-core](https://github.com/mmwx-group/meowx-core) **0.4.9**（mihomo 分支），额外支持 Miu 协议、AnyTLS + REALITY、Snell v6，二进制安装为 `/usr/bin/meowc`，全链路（服务、界面、文档）同步更名 |
| 2   | 修复 LuCI 报 `Object not found (-32000)` | rpcd 会跳过"所有人可写"的 ucode 脚本导致 `luci.nikki` 无法注册；构建时统一权限，`postinst` 兜底 `chmod 0644 /usr/share/rpcd/ucode/luci.nikki`                                                                                                              |
| 3   | ucode 健壮性增强                         | `include.uc` 的 JSON 解析加 try/catch 与类型兜底，坏配置不再打崩 RPC；rpcd 插件对 apk/opkg 多行输出做首行兜底                                                                                                                                              |
| 4   | 默认配置调整                             | API 监听端口 `9090` → `25262`；默认绕过中国大陆 IP（`bypass_china_mainland_ip` / `bypass_china_mainland_ip6` 默认开启）                                                                                                                                    |

## ⚙️ 系统要求

- OpenWrt ≥ 24.10，内核 ≥ 5.13，firewall4
- 依赖 `yq`、`ip-full`、`kmod-nft-tproxy`、`kmod-tun` 等（由包管理器自动解析）

## 📦 安装（SDK / buildroot 编译）

```bash
git clone https://github.com/lsym-openwrt/opwrt-package.git
cp -r opwrt-package/nikki package/nikki

make menuconfig   # LuCI → Applications → luci-app-nikki
make package/nikki/compile V=s    # 同时编译 nikki、luci-app-nikki、meowc
```

> 也可将 `nikki/` 目录加入 `feeds.conf.default` 作为自定义 feed 使用。

## 📄 许可证

本项目遵循上游的 **GPL-3.0** 许可证（见 [LICENSE](LICENSE)）。mihomo 与 meowx-core 内核同样以 GPL-3.0-or-later 发布。

## 🙏 致谢

- 上游项目：[nikkinikki-org/OpenWrt-nikki](https://github.com/nikkinikki-org/OpenWrt-nikki)（作者 Joseph Mory / nikkinikki-org）
- 内核：[MetaCubeX/mihomo](https://github.com/MetaCubeX/mihomo)、[mmwx-group/meowx-core](https://github.com/mmwx-group/meowx-core)
