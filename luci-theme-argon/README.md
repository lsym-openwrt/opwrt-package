# luci-theme-argon · 圆角微调版

<div align="center">

![Version](https://img.shields.io/badge/version-2.3.2-blue) ![Upstream](https://img.shields.io/badge/upstream-jerrykuku%2Fluci--theme--argon--v2.3.2-green) ![License](https://img.shields.io/badge/license-Apache--2.0-orange)

</div>

> 基于 [jerrykuku/luci-theme-argon](https://github.com/jerrykuku/luci-theme-argon) **v2.3.2** 修改：Argon 是 OpenWrt 最流行的 LuCI 主题之一，本版仅对按钮与登录输入框做了圆角微调，其余与上游完全一致。

## ✨ 功能特性（继承上游）

- 干净整洁的侧边栏布局，可折叠导航
- 亮 / 暗色模式：自动跟随系统 + 手动切换
- 自定义登录页图片 / 视频 / Bing 每日壁纸背景
- 模糊度、透明度可调（配合 luci-app-argon-config）
- 内置多种配色方案

## 📌 与上游的差异

| #   | 差异           | 说明                                                                        |
| --- | -------------- | --------------------------------------------------------------------------- |
| 1   | 按钮圆角       | `.pure-button` 圆角 `2px` → `1rem`                                          |
| 2   | 登录输入框圆角 | `.input-group input` 圆角 `0` → `1rem`（less 源文件同步修改并重新生成 CSS） |

## 📦 安装（SDK / buildroot 编译）

```bash
git clone https://github.com/lsym-openwrt/opwrt-package.git
cp -r opwrt-package/luci-theme-argon package/

make menuconfig   # LuCI → Themes → luci-theme-argon
make package/luci-theme-argon/compile V=s
```

> 推荐搭配 `../luci-app-argon-config`（翡翠绿定制版）使用。

## 📄 许可证

遵循上游的 **Apache License 2.0**（见 [LICENSE](LICENSE)）。

## 🙏 致谢

- 上游项目：[jerrykuku/luci-theme-argon](https://github.com/jerrykuku/luci-theme-argon)（Jerrykuku）
- 原始设计灵感：[luci-theme-material](https://github.com/LuttyYang/luci-theme-material) 等 LuCI 社区主题
