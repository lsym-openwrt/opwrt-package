# luci-app-argon-config · 翡翠绿定制版

<div align="center">

![Upstream](https://img.shields.io/badge/upstream-jerrykuku%2Fluci--app--argon--config--v1.0-green) ![License](https://img.shields.io/badge/license-Apache--2.0-orange)

</div>

> 基于 [jerrykuku/luci-app-argon-config](https://github.com/jerrykuku/luci-app-argon-config)（v1.0 独立版时代快照）修改：Argon 主题的设置插件，本版默认采用**翡翠绿**配色并新增 GHSer 壁纸源。

## ✨ 功能特性（继承上游）

- 登录背景图片上传 / 改名 / 删除管理
- 在线壁纸源：Bing / Unsplash / Wallhaven
- 主题模糊度、透明度实时调节
- 亮 / 暗模式切换与主色调自定义

## 📌 与上游的差异

| #   | 差异              | 说明                                                                |
| --- | ----------------- | ------------------------------------------------------------------- |
| 1   | 默认翡翠绿配色    | primary `#5e72e4` → `#10b981`，dark_primary `#483d8b` → `#047857`   |
| 2   | 默认观感调整      | blur `10` → `0`（不模糊），透明度 `0.5` → `0.3`                     |
| 3   | 新增 GHSer 壁纸源 | 设置页新增 GHSer 在线壁纸选项                                       |
| 4   | rpcd 后端调整     | 可用空间查询改走 `luci` system info 接口（原独立 `avail` 方法移除） |
| 5   | Makefile 精简     | 去除版本号 / 维护者 / po 构建块，适配本地构建                       |

## 📦 安装（SDK / buildroot 编译）

```bash
git clone https://github.com/lsym-openwrt/opwrt-package.git
cp -r opwrt-package/luci-theme-argon opwrt-package/luci-app-argon-config package/

make menuconfig   # LuCI → Applications → luci-app-argon-config
make package/luci-app-argon-config/compile V=s
```

> 需先安装 `luci-theme-argon`（见 `../luci-theme-argon`）。

## 📄 许可证

遵循上游的 **Apache License 2.0**。

## 🙏 致谢

- 上游项目：[jerrykuku/luci-app-argon-config](https://github.com/jerrykuku/luci-app-argon-config)（Jerrykuku）
