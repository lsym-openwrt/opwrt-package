# OpenWrt Momo · 订阅转换增强版

<div align="center">

![Version](https://img.shields.io/badge/version-1.2.2-blue) ![Upstream](https://img.shields.io/badge/upstream-nikkinikki%2FOpenWrt--momo--main-green) ![License](https://img.shields.io/badge/license-GPL--3.0-orange)

</div>

> 基于 [nikkinikki-org/OpenWrt-momo](https://github.com/nikkinikki-org/OpenWrt-momo)（main 分支，基线提交 `f177d79`）修改：在原 sing-box 透明代理之上，新增**订阅自动转换**与**分组驱动**子系统，并附带定制 LuCI 界面样式。

Momo 是在 OpenWrt 上运行 sing-box 内核的透明代理解决方案，包含核心包 `momo` 与 LuCI 管理界面 `luci-app-momo`。

## ✨ 功能特性

**继承上游全部功能：**

- 透明代理：Redirect / TPROXY / TUN，IPv4 与 IPv6
- 访问控制、配置编辑器、定时重启
- 基于 sing-box ≥ 1.12，firewall4

**本版新增：**

- 🔁 **订阅自动转换**：支持 Clash YAML / JSON（含 base64）、节点 URI 列表、sing-box 原生、Surge / Loon / QuantumultX / SIP008 等 **13 种格式**一键转换为 sing-box 配置，UA 智能试探（clash.meta → sing-box → v2rayN → Shadowrocket → PassWall）
- 🧩 **配置骨架补齐**：生成的配置缺少 `dns-in` / `redirect-in` / `tproxy-in` / `tun-in` inbound 时自动补齐，避免 "DNS inbound not found" 断流
- ✅ **写前校验**：生成配置先过 `sing-box check`，校验失败不落盘
- 🚦 **分组驱动 groupd**：经 Clash API 定时测速并自动切换节点
- 🎨 **定制 LuCI 样式**：全新 `app.css` 界面
- 🛡️ **加固**：rpcd ACL 扩展、init / migrate 脚本健壮性增强

## 📌 与上游的主要差异

| #   | 改动               | 说明                                                                                                                               |
| --- | ------------------ | ---------------------------------------------------------------------------------------------------------------------------------- |
| 1   | 新增订阅转换子系统 | `momo/files/converter/`（converter.conf + momo-base.json 模板）与 `momo/files/scripts/momo_convert.py`，上游本身无任何订阅转换功能 |
| 2   | 新增分组驱动       | `momo_groupd.py` 守护进程 + Clash API 测速选节点                                                                                   |
| 3   | 后端脚本扩展       | `momo.init`、`include.sh`、`include.uc`、`migrate.sh`、`luci.momo` 等大幅增强                                                      |
| 4   | 前端重做           | `app.js`、`profile.js`、`proxy.js` 等适配转换功能，新增 `app.css` 定制样式                                                         |
| 5   | 依赖变化           | `momo` 包增加 `+python3-light`                                                                                                     |

## 📦 安装（SDK / buildroot 编译）

```bash
git clone https://github.com/lsym-openwrt/opwrt-package.git
cp -r opwrt-package/momo package/momo

make menuconfig   # LuCI → Applications → luci-app-momo
make package/momo/compile V=s    # 同时编译 momo、luci-app-momo
```

> 也可将 `momo/` 目录加入 `feeds.conf.default` 作为自定义 feed 使用。

## 🧪 测试

`tests/` 内置端到端自测套件（订阅格式样本因可能含真实节点信息，未随仓库分发，可自行放置于 `tests/fixtures/`）：

```bash
python3 tests/run_tests.py
```

## 📄 许可证

本项目遵循上游的 **GPL-3.0** 许可证（见 [LICENSE](LICENSE)）。

## 🙏 致谢

- 上游项目：[nikkinikki-org/OpenWrt-momo](https://github.com/nikkinikki-org/OpenWrt-momo)（作者 Joseph Mory / nikkinikki-org）
- 内核：[SagerNet/sing-box](https://github.com/SagerNet/sing-box)
