# luci-theme-carbon · IPTV 增强版

<div align="center">

![Version](https://img.shields.io/badge/version-1.1.4-blue) ![Upstream](https://img.shields.io/badge/upstream-mrjoechen%2Fluci--theme--carbon--v1.1.4-green) ![License](https://img.shields.io/badge/license-Apache--2.0-orange)

</div>

> 基于 [mrjoechen/luci-theme-carbon](https://github.com/mrjoechen/luci-theme-carbon) **v1.1.4** 修改：Carbon 是一款**苹果风格（毛玻璃）**的 LuCI 主题，本版增加了 IPTV 场景设备识别与布局增强。

## ✨ 功能特性（继承上游）

- 🍎 苹果式毛玻璃（backdrop-filter / color-mix），浅色 / 深色 / 跟随系统
- 📊 内置仪表盘：实时流量图、CPU / 内存 / 存储圆环、温度、外网 IP
- 🖥️ 在线设备品牌识别（35 品牌、约 9,200 条 IEEE OUI 前缀）
- 📂 简洁 / 专业双菜单模式、可收起毛玻璃侧栏（Ctrl+\）、手机抽屉适配
- 🌍 内置 13 种语言、自定义 Logo 上传（系统 → Carbon 主题）
- ⬆️ 网页在线升级（带 APK 签名校验）

## 📌 与上游的差异（v1.1.4 基础上约 300 行增强）

| #   | 差异          | 说明                                                                |
| --- | ------------- | ------------------------------------------------------------------- |
| 1   | 内容区加宽    | 新增 `--cb-content-wide: 1240px` 宽屏布局变量                       |
| 2   | IPTV 设备识别 | 新增 rtp2httpd / rtp2httpx / udpxy / iptv → 光纤猫（fiber）图标匹配 |
| 3   | 列表分组      | listbox 支持 optgroup 式分组显示                                    |
| 4   | 细节修复      | 暗色 checkbox 选中态、列表圆角 14px 与内边距微调                    |

## 📦 安装（SDK / buildroot 编译）

```bash
git clone https://github.com/lsym-openwrt/opwrt-package.git
cp -r opwrt-package/luci-theme-carbon package/

make menuconfig   # LuCI → Themes → luci-theme-carbon
make package/luci-theme-carbon/compile V=s
```

## 📄 许可证

遵循上游的 **Apache License 2.0**（见 [LICENSE](LICENSE)）。

## 🙏 致谢

- 上游项目：[mrjoechen/luci-theme-carbon](https://github.com/mrjoechen/luci-theme-carbon)
