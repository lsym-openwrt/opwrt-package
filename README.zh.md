# OpenWrt 主题与插件合集 · 修改版

<p align="center">
  <img src="https://img.shields.io/badge/OpenWrt-LuCI%20Themes%20%26%20Apps-blue" alt="OpenWrt">
  <img src="https://img.shields.io/badge/packages-13-green" alt="packages">
  <img src="https://img.shields.io/badge/license-mixed-orange" alt="license">
</p>

> 收录 13 个 OpenWrt LuCI 主题与插件，全部基于各上游开源项目修改而来，遵循上游开源协议发布，在此感谢所有原作者。
>
> 简体中文 ｜ [English](README.md)

---

## 📦 包总览

### 应用 / 套件（7 个）

| 包名                      | 功能                    | 基于谁修改                                                                                                                                    | 上游版本        | 修改了什么                                                                                                                                         | 实现了什么                                                                                                                           | 许可证     |
| ------------------------- | ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- | --------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ | ---------- |
| **nikki**                 | mihomo 透明代理套件     | [nikkinikki-org/OpenWrt-nikki](https://github.com/nikkinikki-org/OpenWrt-nikki)                                                               | v1.26.2         | ① mihomo 内核整体替换为 MeowC ② 修复 rpcd 跳过 ucode 脚本导致的 `-32000` 报错 ③ ucode JSON 解析加固 ④ 默认 API 端口改 `25262`、默认绕过中国大陆 IP | 支持 **Miu、AnyTLS + REALITY、Snell v6** 等新协议；修复 LuCI "Object not found"；坏配置不再打崩 RPC；开箱即国内直连                  | GPL-3.0    |
| **momo**                  | sing-box 透明代理套件   | [nikkinikki-org/OpenWrt-momo](https://github.com/nikkinikki-org/OpenWrt-momo)                                                                 | main @`f177d79` | ① 新增订阅自动转换子系统（上游无此功能）② 新增分组测速驱动 groupd ③ 定制 LuCI 界面样式 ④ init / rpcd 加固                                          | **13 种订阅格式**（Clash YAML/JSON、URI、Surge、Loon、QX、SIP008…）一键转 sing-box；节点自动测速切换；配置写前 `sing-box check` 校验 | GPL-3.0    |
| **luci-app-openclash**    | Mihomo(Clash) 客户端    | [vernesong/OpenClash](https://github.com/vernesong/OpenClash)                                                                                 | 0.47.156        | 上游多个 `oc-*.css` 合并重写为单文件 `oc.css`（约 7,500 行），4 个视图模板同步适配                                                                 | **卡片式主界面**，其余功能与上游一致                                                                                                 | MIT        |
| **luci-app-quickstart**   | QuickStart 的 LuCI 前端 | linkease（iStoreOS 生态）                                                                                                                     | 0.12.16         | ① 新增后端进程自愈拉起（30 秒限频，不写 enable 保护 overlay）② 首页跳转失败回退 admin/status ③ dockerman 菜单缺失时重定向 admin/docker             | 后端掉线时**首页不再白屏**，可自动恢复                                                                                               | Apache-2.0 |
| **quickstart**            | 仪表盘 / 使用向导后端   | [linkease/istore-packages](https://github.com/linkease/istore-packages)（源码 [istoreos/quickstart](https://github.com/istoreos/quickstart)） | 0.13.0-r3       | ① init 重写：`respawn 3600 5 3` + boot 后 5s/10s/20s 三段延迟自愈 ② startdhns 有界等待（≤13s）③ postinst 安装/升级后兜底启动                       | 修复**开机高负载下守护进程"永不启动"**的问题                                                                                         | GPL-3.0    |
| **luci-app-unidash**      | 通用 OpenWrt 仪表盘     | 移植自 [fanchmwrt/fanchmwrt-packages](https://github.com/fanchmwrt/fanchmwrt-packages) 的 luci-app-fwx-dashboard                              | 1.2.2           | ① 数据源全部改为 /proc、ubus、conntrack、dhcp.leases ② 新增中英双语 i18n（150+ 词条）③ 请求记忆化 + 2s 缓存 + 防堆积 ④ dnsd 双模式 DNS 采集增强    | **无需 fwxd / kmod-fwx 私有组件**即可在任意 OpenWrt 运行；一轮轮询 0.85s → 0.53s（**-37%**）；站点连接显示中文名                     | Apache-2.0 |
| **luci-app-argon-config** | Argon 主题设置插件      | [jerrykuku/luci-app-argon-config](https://github.com/jerrykuku/luci-app-argon-config)                                                         | v1.0 独立版时代 | ① 默认配色改翡翠绿（`#10b981`/`#047857`）② blur 10→0、透明度 0.5→0.3 ③ 新增 GHSer 壁纸源 ④ rpcd 可用空间查询改走 system info                       | Argon 开箱即**翡翠绿**观感                                                                                                           | Apache-2.0 |

### 主题（5 个）

| 包名                    | 风格                | 基于谁修改                                                                                                  | 版本            | 修改了什么                                                                                                                                     | 实现了什么                                                                      | 许可证     |
| ----------------------- | ------------------- | ----------------------------------------------------------------------------------------------------------- | --------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- | ---------- |
| **luci-theme-argon**    | 经典侧边栏          | [jerrykuku/luci-theme-argon](https://github.com/jerrykuku/luci-theme-argon)                                 | v2.3.2          | 按钮圆角 `2px`→`1rem`、登录输入框圆角 `0`→`1rem`（less 同步改）                                                                                | 视觉更圆润，其余与上游完全一致                                                  | Apache-2.0 |
| **luci-theme-prism**    | 深色 Prism Dark     | derisamedia 的 [luci-theme-alpha](https://github.com/derisamedia/luci-theme-alpha) 模板                     | 3.9.7_beta2-r10 | ① 登录页中文化 ② 独立化（不依赖 alpha-config）                                                                                                 | 可独立安装使用的 Prism 深色主题                                                 | Apache-2.0 |
| **luci-theme-violet**   | 毛玻璃深色 Violet   | derisamedia 的 [luci-theme-alpha](https://github.com/derisamedia/luci-theme-alpha) 模板                     | 3.9.7_beta2-r10 | ① 登录页中文化 ② 独立化                                                                                                                        | Violet OS 风格毛玻璃主题                                                        | Apache-2.0 |
| **luci-theme-rog-red**  | ROG 信仰红 × 哑光黑 | [KawaiiHachimi/luci-theme-techblue](https://github.com/KawaiiHachimi/luci-theme-techblue)（上游已不可访问） | CSS v1.0.9      | 整包视觉重制：信仰红 `#FF0018`、全局直角 + clip-path 斜切、呼吸灯动画、Header CPU/内存状态条、`initDashboardTables`                            | **ROG 败家之眼**风格主题；保留 `--asus-*`/`--techblue-*` 变量兼容层便于二次换肤 | Apache-2.0 |
| **luci-theme-techblue** | ASUS 科技蓝         | [KawaiiHachimi/luci-theme-techblue](https://github.com/KawaiiHachimi/luci-theme-techblue)（上游已不可访问） | —               | 以 "ASUS Techno Blue" 视觉体系重新设计：深蓝黑 + 科技蓝辉光、渐变按钮、玻璃拟态登录框、ASUS 呼吸灯                                             | cyberpunk 风科技蓝主题（rog-red 的父本）                                        | Apache-2.0 |

---

## 📂 目录结构

```text
.
├── nikki/                    # mihomo 透明代理套件（MeowC 内核版）
│   ├── nikki/                #   核心包
│   ├── luci-app-nikki/       #   LuCI 管理界面
│   └── meowc/                #   MeowC 内核打包（meowx-core 0.4.9）
├── momo/                     # sing-box 透明代理套件（订阅转换增强版）
│   ├── momo/                 #   核心包（含 converter / groupd）
│   └── luci-app-momo/        #   LuCI 管理界面
├── luci-app-openclash/       # OpenClash 卡片界面定制版
├── luci-app-quickstart/      # QuickStart 前端加固版
├── quickstart/               # QuickStart 后端加固版
├── luci-app-unidash/         # 通用仪表盘（fwx-dashboard 移植）
├── luci-theme-argon/         # Argon 圆角微调版
├── luci-app-argon-config/    # Argon 设置插件（翡翠绿定制版）
├── luci-theme-prism/         # Prism 深色（中文界面版）
├── luci-theme-violet/        # Violet 毛玻璃（中文界面版）
├── luci-theme-rog-red/       # ROG 信仰红
└── luci-theme-techblue/      # ASUS 科技蓝
```

每个包目录内附该包的详细说明 README 与上游 LICENSE 文件。

---

## 🔨 编译使用

所有包均为标准 OpenWrt 包格式。将需要的包目录放入 buildroot 的 `package/` 下编译即可：

```bash
git clone https://github.com/lsym-openwrt/openwrt-packages.git
cp -r openwrt-packages/luci-theme-argon openwrt-packages/luci-app-argon-config package/

make menuconfig          # LuCI → Themes / Applications 中选中
make package/luci-theme-argon/compile V=s
make package/luci-app-argon-config/compile V=s
```

> - 主题类包相互独立，可单独编译安装
> - `luci-app-argon-config` 依赖 `luci-theme-argon`
> - `luci-app-quickstart` 依赖 `quickstart`
> - `nikki`、`momo` 也可作为 feed 使用：将仓库内对应目录加入 `feeds.conf.default`

---

## 🤖 在线编译（GitHub Actions）

仓库内置 [build-packages](.github/workflows/build.yml) 工作流，推送或手动触发（workflow_dispatch）后自动用官方 `openwrt/gh-action-sdk` 编译 **x86_64** 的全部 16 个包：

| SDK 分支 | 产物格式 | 对应系统 |
|----------|---------|---------|
| `openwrt-24.10` | `.ipk`（opkg） | OpenWrt 24.10.x |
| `openwrt-25.12` | `.apk`（APK 包管理器） | OpenWrt 25.12.x |

产物在 Actions 运行页面的 Artifacts 区下载（`opwrt-package_x86_64-openwrt-24.10` / `opwrt-package_x86_64-openwrt-25.12`），内含全部 ipk/apk 与软件源索引（`Packages` / `APKINDEX.tar.gz`），可直接当作自定义软件源使用。推送 `v*` 标签会自动创建 Release 并上传全部安装包。

---

## 📄 开源协议

本仓库为上游开源项目的**修改版合集**，各包继续遵循其上游许可证（见总览表）：

| 许可证     | 涉及的包                                                                                                                                                                        |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GPL-3.0    | nikki、momo、quickstart（各包目录内附 [GPL-3.0](nikki/LICENSE) 全文）                                                                                                           |
| Apache-2.0 | luci-app-quickstart、luci-app-unidash、luci-theme-argon、luci-app-argon-config、luci-theme-prism、luci-theme-violet、luci-theme-rog-red、luci-theme-techblue |
| MIT        | luci-app-openclash（遵循上游 vernesong/OpenClash 的 MIT 许可）                                                                                                                  |

- 所有修改版均在包内注明上游来源，并按协议要求以相同许可证开源发布
- 各包目录内保留 / 补充了上游的 LICENSE 文件
- 修改版按协议要求注明上游来源并保持相同许可证开源
- 本合集不改变任何包的许可证，也不引入新的许可约束

---

## 🙏 致谢

本仓库的每一个包都站在前人的肩膀上，向以下上游项目与作者致谢：

| 上游项目                                                                                                                                                  | 作者 / 组织                     | 本仓库中的包                            |
| --------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------- | --------------------------------------- |
| [OpenWrt-nikki](https://github.com/nikkinikki-org/OpenWrt-nikki)                                                                                          | Joseph Mory / nikkinikki-org    | nikki                                   |
| [OpenWrt-momo](https://github.com/nikkinikki-org/OpenWrt-momo)                                                                                            | Joseph Mory / nikkinikki-org    | momo                                    |
| [OpenClash](https://github.com/vernesong/OpenClash)                                                                                                       | vernesong                       | luci-app-openclash                      |
| [istore-packages](https://github.com/linkease/istore-packages) / [quickstart](https://github.com/istoreos/quickstart)                                     | linkease、jjm2473               | quickstart、luci-app-quickstart         |
| [fanchmwrt-packages](https://github.com/fanchmwrt/fanchmwrt-packages)（luci-app-fwx-dashboard）                                                           | fanchmwrt                       | luci-app-unidash（移植）                |
| [luci-theme-argon](https://github.com/jerrykuku/luci-theme-argon) / [luci-app-argon-config](https://github.com/jerrykuku/luci-app-argon-config)           | jerrykuku                       | luci-theme-argon、luci-app-argon-config |
| [luci-theme-alpha](https://github.com/derisamedia/luci-theme-alpha)（模板）                                                                               | derisamedia                     | luci-theme-prism、luci-theme-violet     |
| [luci-theme-techblue](https://github.com/KawaiiHachimi/luci-theme-techblue)                                                                               | KawaiiHachimi                   | luci-theme-rog-red、luci-theme-techblue |
| [mihomo](https://github.com/MetaCubeX/mihomo) / [meowx-core](https://github.com/mmwx-group/meowx-core) / [sing-box](https://github.com/SagerNet/sing-box) | MetaCubeX、mmwx-group、SagerNet | nikki / momo 的代理内核                 |

以及 [OpenWrt](https://openwrt.org/) / [LuCI](https://github.com/openwrt/luci) 社区的所有贡献者。**感谢所有原作者的优秀工作！**

---

<div align="center">

如果这些修改版对你有帮助，欢迎点个 ⭐

</div>
