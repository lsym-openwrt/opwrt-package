# luci-app-quickstart · 加固版

<div align="center">

![Version](https://img.shields.io/badge/version-0.12.16-blue) ![Upstream](https://img.shields.io/badge/upstream-linkease%20(iStoreOS)-green) ![License](https://img.shields.io/badge/license-Apache--2.0-orange)

</div>

> 基于 linkease（iStoreOS 生态）**luci-app-quickstart v0.12.16** 修改：QuickStart 的 LuCI 前端，本版为后端守护进程增加了自愈拉起与导航兜底，解决后端偶发掉线后首页空白的问题。

## ✨ 功能特性（继承上游）

- iStoreOS 风格的首页仪表板与快速网络向导
- NAS 入口：RAID、S.M.A.R.T.、网口配置菜单
- 一键自动安装 / 配置软件包（`auto_setup` / `setup_result` 异步接口，见 [API.md](API.md)）
- 依赖 `quickstart` 后端与 `luci-app-ttyd` 终端

## 📌 与上游的主要差异

| #   | 改动            | 说明                                                                                                                                                  |
| --- | --------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | 后端自愈拉起    | 新增 `quickstart_running()` / `quickstart_revive()`：渲染菜单时检测到 quickstart 后端未运行则自动拉起（30 秒限频；刻意不写 enable，避免磨损 overlay） |
| 2   | 首页跳转兜底    | 后端不可达时重定向到 `admin/status`，不再白屏                                                                                                         |
| 3   | Docker 菜单兜底 | 新增 `redirect_dockerman`：dockerman 菜单缺失时重定向到 `admin/docker`                                                                                |
| 4   | 构建调整        | 禁用 CSS/JS 压缩（`LUCI_MINIFY_CSS/JS:=0`）                                                                                                           |

## 📦 安装（SDK / buildroot 编译）

```bash
git clone https://github.com/lsym-openwrt/opwrt-package.git
cp -r opwrt-package/quickstart opwrt-package/luci-app-quickstart package/

make menuconfig
make package/quickstart/compile V=s
make package/luci-app-quickstart/compile V=s
```

> 依赖 `quickstart` 后端（见 `../quickstart`，本仓库同样提供加固版）。

## 📄 许可证

遵循上游的 **Apache License 2.0**。

## 🙏 致谢

- 上游项目：linkease / iStoreOS（[istoreos/quickstart](https://github.com/istoreos/quickstart)、[linkease/istore-packages](https://github.com/linkease/istore-packages)）
