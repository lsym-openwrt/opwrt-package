# luci-theme-prism · 中文界面版

<div align="center">

![Version](https://img.shields.io/badge/version-3.9.7__beta2--r10-blue) ![Based on](https://img.shields.io/badge/based%20on-derisamedia%20alpha%20template-green) ![License](https://img.shields.io/badge/license-Apache--2.0-orange)

</div>

> 基于 derisamedia 的 **luci-theme-alpha 模板**（3.9.7_beta2-r10，原 prism 分发仓库已不可访问）修改的深色 LuCI 主题：**Prism Dark**。

## ✨ 功能特性

- 🌑 深灰黑主色 `#27272a`，纯净无模糊的深色界面
- 🎨 内置 5 组 SVG 纹理登录背景：hex / network / polygon / triangle / voronoi
- 🧭 顶栏入口可配置（`/etc/config/prism`，可自定义图标）
- ✍️ Inter + Quicksand 字体
- 🇨🇳 中文登录页（用户名 / 密码 / 错误提示本地化）

## 📌 相对模板的差异

| #   | 差异         | 说明                                             |
| --- | ------------ | ------------------------------------------------ |
| 1   | 登录页中文化 | `sysauth` 模板中文本地化                         |
| 2   | 独立主题包   | 作为独立主题使用，不依赖 luci-theme-alpha-config |

## 📦 安装（SDK / buildroot 编译）

```bash
git clone https://github.com/lsym-openwrt/opwrt-package.git
cp -r opwrt-package/luci-theme-prism package/

make menuconfig   # LuCI → Themes → luci-theme-prism
make package/luci-theme-prism/compile V=s
```

## 📄 许可证

遵循上游的 **Apache License 2.0**（见 [LICENSE](LICENSE)）。

## 🙏 致谢

- 模板来源：[derisamedia/luci-theme-alpha](https://github.com/derisamedia/luci-theme-alpha)（derisamedia）
- 底层：基于 luci-theme-material 模板体系与 LuCI 社区
