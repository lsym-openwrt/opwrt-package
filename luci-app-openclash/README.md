# luci-app-openclash · 卡片界面定制版

<div align="center">

![Version](https://img.shields.io/badge/version-0.47.156-blue) ![Upstream](https://img.shields.io/badge/upstream-vernesong%2FOpenClash--0.47.156-green) ![License](https://img.shields.io/badge/license-MIT-orange)

</div>

> 基于 [vernesong/OpenClash](https://github.com/vernesong/OpenClash) **v0.47.156** 修改：OpenClash 是 OpenWrt 上功能最完善的 Mihomo(Clash) 客户端，本版重做了主界面样式（卡片式布局）。

## ✨ 功能特性（继承上游）

- 多协议支持：Shadowsocks(R) / VMess / VLESS / Trojan / Snell / Hysteria2 等
- 灵活的规则分流，自定义规则 / DNS / 防火墙脚本
- 内置 metacubexd 仪表板、Watchdog 守护进程
- GeoSite / GeoIP 数据库自动更新，rule_provider 分流规则
- 兼容 firewall4（nftables）与 firewall3（iptables）
- 多内核切换（Dev / Smart / Meta / TUN 等）

## 📌 与上游的主要差异

| #   | 改动         | 说明                                                                                            |
| --- | ------------ | ----------------------------------------------------------------------------------------------- |
| 1   | 界面样式重制 | 将上游多个 `oc-*.css` 合并重写为单文件 `oc.css`（约 7,500 行），主界面改为**卡片式布局**        |
| 2   | 视图模板同步 | `config_merge_editor` / `config_upload` 等 4 个视图改用合并后的 `oc.css` 并带版本号引用刷新缓存 |

其余功能与上游 v0.47.156 保持一致。

## 📦 安装（SDK / buildroot 编译）

```bash
git clone https://github.com/lsym-openwrt/opwrt-package.git
cp -r opwrt-package/luci-app-openclash package/

make menuconfig   # LuCI → Applications → luci-app-openclash
make package/luci-app-openclash/compile V=s
```

> 需要先安装 Mihomo(Clash) 内核，可从 [OpenClash Core](https://github.com/vernesong/OpenClash/tree/master/core) 下载。

## 📄 许可证

遵循上游的 **MIT** 许可证（Copyright (c) 2019-2026 vernesong）。

## 🙏 致谢

- 上游项目：[vernesong/OpenClash](https://github.com/vernesong/OpenClash)
- 内核：[MetaCubeX/mihomo](https://github.com/MetaCubeX/mihomo)
