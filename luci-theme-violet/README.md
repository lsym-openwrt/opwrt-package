# luci-theme-violet · 中文界面版

<div align="center">

![Version](https://img.shields.io/badge/version-3.9.7__beta2--r10-blue) ![Based on](https://img.shields.io/badge/based%20on-derisamedia%20alpha%20template-green) ![License](https://img.shields.io/badge/license-Apache--2.0-orange)

</div>

> 基于 derisamedia 的 **luci-theme-alpha 模板**（3.9.7_beta2-r10，原 violet 分发仓库已不可访问）修改的毛玻璃深色主题，Violet OS 配套风格。

## ✨ 功能特性

- 💜 深蓝灰毛玻璃界面 `rgba(30,41,59,0.6)` + blur 12
- 🖼️ 内置矢量背景：dashboard-bg.svg / login-bg.svg
- ✍️ Inter + Quicksand 多字重字体（Medium / Regular / SemiBold）
- 🧭 顶栏入口可配置（`/etc/config/violet`）
- 🇨🇳 中文登录页（用户名 / 密码 / 错误提示本地化）

## 📌 相对模板的差异

| #   | 差异         | 说明                                             |
| --- | ------------ | ------------------------------------------------ |
| 1   | 登录页中文化 | `sysauth` 模板中文本地化                         |
| 2   | 独立主题包   | 作为独立主题使用，不依赖 luci-theme-alpha-config |

## 📦 安装（SDK / buildroot 编译）

```bash
git clone https://github.com/lsym-openwrt/opwrt-package.git
cp -r opwrt-package/luci-theme-violet package/

make menuconfig   # LuCI → Themes → luci-theme-violet
make package/luci-theme-violet/compile V=s
```

## 📄 许可证

遵循上游的 **Apache License 2.0**（见 [LICENSE](LICENSE)）。

## 🙏 致谢

- 模板来源：[derisamedia/luci-theme-alpha](https://github.com/derisamedia/luci-theme-alpha)（derisamedia）
