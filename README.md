# OpenWrt Themes & Apps Collection · Modified Editions

<p align="center">
  <img src="https://img.shields.io/badge/OpenWrt-LuCI%20Themes%20%26%20Apps-blue" alt="OpenWrt">
  <img src="https://img.shields.io/badge/packages-13-green" alt="packages">
  <img src="https://img.shields.io/badge/license-mixed-orange" alt="license">
</p>

> A collection of 13 OpenWrt LuCI themes and apps, all modified from upstream open-source projects and published in compliance with their licenses. Thanks to all the original authors.
>
> [简体中文](README.zh.md) ｜ English

---

## 📦 Package Overview

### Apps / Suites (7)

| Package                   | What it does                     | Based on                                                                                                                                         | Upstream version    | What was changed                                                                                                                                                                                                         | What it achieves                                                                                                                                                                                                  | License    |
| ------------------------- | -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| **nikki**                 | mihomo transparent proxy suite   | [nikkinikki-org/OpenWrt-nikki](https://github.com/nikkinikki-org/OpenWrt-nikki)                                                                  | v1.26.2             | ① Replaced the mihomo kernel with MeowC ② Fixed the rpcd `-32000` error caused by world-writable ucode scripts ③ Hardened ucode JSON parsing ④ Changed default API port to `25262`, bypass mainland China IPs by default | Adds **Miu, AnyTLS + REALITY, Snell v6** protocol support; fixes LuCI "Object not found"; bad configs no longer crash the RPC; mainland-direct out of the box                                                     | GPL-3.0    |
| **momo**                  | sing-box transparent proxy suite | [nikkinikki-org/OpenWrt-momo](https://github.com/nikkinikki-org/OpenWrt-momo)                                                                    | main @`f177d79`     | ① Added a subscription auto-conversion subsystem (absent upstream) ② Added group speed-test driver `groupd` ③ Custom LuCI styling ④ Hardened init / rpcd                                                                 | Converts **13 subscription formats** (Clash YAML/JSON, URI, Surge, Loon, QX, SIP008…) to sing-box in one step; automatic node speed-testing and switching; configs validated with `sing-box check` before writing | GPL-3.0    |
| **luci-app-openclash**    | Mihomo(Clash) client             | [vernesong/OpenClash](https://github.com/vernesong/OpenClash)                                                                                    | 0.47.156            | Merged upstream's multiple `oc-*.css` files into a single rewritten `oc.css` (~7,500 lines); adapted 4 view templates                                                                                                    | **Card-style main UI**, everything else identical to upstream                                                                                                                                                     | MIT        |
| **luci-app-quickstart**   | LuCI front-end for QuickStart    | linkease (iStoreOS ecosystem)                                                                                                                    | 0.12.16             | ① Added backend self-revival (30s rate-limited, no enable write to protect overlay) ② Fallback to admin/status when the home redirect fails ③ Redirect to admin/docker when dockerman menu is missing                    | **No more blank home page** when the backend is down; auto-recovery                                                                                                                                               | Apache-2.0 |
| **quickstart**            | Dashboard / setup-wizard backend | [linkease/istore-packages](https://github.com/linkease/istore-packages) (sources: [istoreos/quickstart](https://github.com/istoreos/quickstart)) | 0.13.0-r3           | ① Rewrote init: `respawn 3600 5 3` + 5s/10s/20s delayed self-healing after boot ② Bounded wait for startdhns (≤13s) ③ postinst starts the daemon after install/upgrade                                                   | Fixes the daemon **never starting under heavy boot load**                                                                                                                                                         | GPL-3.0    |
| **luci-app-unidash**      | Universal OpenWrt dashboard      | Ported from luci-app-fwx-dashboard in [fanchmwrt/fanchmwrt-packages](https://github.com/fanchmwrt/fanchmwrt-packages)                            | 1.2.2               | ① All data sources switched to /proc, ubus, conntrack, dhcp.leases ② Added EN/ZH i18n (150+ strings) ③ Request memoization + 2s cache + anti-pile-up ④ Enhanced dual-mode DNS collector                                  | Runs on any OpenWrt **without the proprietary fwxd / kmod-fwx**; one polling round 0.85s → 0.53s (**-37%**); visited sites shown as readable names                                                                | Apache-2.0 |
| **luci-app-argon-config** | Settings app for the Argon theme | [jerrykuku/luci-app-argon-config](https://github.com/jerrykuku/luci-app-argon-config)                                                            | v1.0 standalone era | ① Default palette switched to emerald green (`#10b981`/`#047857`) ② blur 10→0, transparency 0.5→0.3 ③ Added GHSer wallpaper source ④ rpcd free-space query via system info                                               | Argon ships with an **emerald-green** look out of the box                                                                                                                                                         | Apache-2.0 |

### Themes (6)

| Package                 | Style                       | Based on                                                                                                                 | Version         | What was changed                                                                                                                                               | What it achieves                                                                                         | License    |
| ----------------------- | --------------------------- | ------------------------------------------------------------------------------------------------------------------------ | --------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- | ---------- |
| **luci-theme-argon**    | Classic sidebar             | [jerrykuku/luci-theme-argon](https://github.com/jerrykuku/luci-theme-argon)                                              | v2.3.2          | Button corner radius `2px`→`1rem`, login input radius `0`→`1rem` (less sources updated)                                                                        | A rounder look; otherwise identical to upstream                                                          | Apache-2.0 |
| **luci-theme-carbon**   | Apple-style frosted glass   | [mrjoechen/luci-theme-carbon](https://github.com/mrjoechen/luci-theme-carbon)                                            | v1.1.4          | ① Wider content `--cb-content-wide: 1240px` ② New rtp2httpd/udpxy/iptv→fiber-modem device icons ③ Grouped listbox ④ Dark-mode checkbox fix (~300 lines total)  | Device recognition for **IPTV / multicast** setups; widescreen layout                                    | Apache-2.0 |
| **luci-theme-prism**    | Dark "Prism Dark"           | derisamedia's [luci-theme-alpha](https://github.com/derisamedia/luci-theme-alpha) template                               | 3.9.7_beta2-r10 | ① Chinese-localized login page ② Made standalone (no alpha-config dependency)                                                                                  | A standalone installable Prism dark theme                                                                | Apache-2.0 |
| **luci-theme-violet**   | Frosted-glass dark Violet   | derisamedia's [luci-theme-alpha](https://github.com/derisamedia/luci-theme-alpha) template                               | 3.9.7_beta2-r10 | ① Chinese-localized login page ② Made standalone                                                                                                               | Violet-OS-style frosted glass theme                                                                      | Apache-2.0 |
| **luci-theme-rog-red**  | ROG faith red × matte black | [KawaiiHachimi/luci-theme-techblue](https://github.com/KawaiiHachimi/luci-theme-techblue) (upstream no longer available) | CSS v1.0.9      | Full visual rebuild: faith red `#FF0018`, global right angles + clip-path bevels, breathing-light animation, header CPU/RAM status bars, `initDashboardTables` | A **ROG gaming**-style theme; keeps `--asus-*`/`--techblue-*` variable compat layer for easy re-skinning | Apache-2.0 |
| **luci-theme-techblue** | ASUS techno blue            | [KawaiiHachimi/luci-theme-techblue](https://github.com/KawaiiHachimi/luci-theme-techblue) (upstream no longer available) | —               | Redesigned with the "ASUS Techno Blue" visual identity: deep navy + cyan glow, gradient buttons, glassmorphism login, ASUS breathing light                     | A cyberpunk techno-blue theme (parent of rog-red)                                                        | Apache-2.0 |

---

## 📂 Repository Layout

```text
.
├── nikki/                    # mihomo transparent proxy suite (MeowC kernel edition)
│   ├── nikki/                #   core package
│   ├── luci-app-nikki/       #   LuCI interface
│   └── meowc/                #   MeowC kernel packaging (meowx-core 0.4.9)
├── momo/                     # sing-box transparent proxy suite (subscription-converter edition)
│   ├── momo/                 #   core package (converter / groupd included)
│   └── luci-app-momo/        #   LuCI interface
├── luci-app-openclash/       # OpenClash card-UI edition
├── luci-app-quickstart/      # QuickStart front-end, hardened
├── quickstart/               # QuickStart backend, hardened
├── luci-app-unidash/         # Universal dashboard (fwx-dashboard port)
├── luci-theme-argon/         # Argon, rounded-corner tweak
├── luci-app-argon-config/    # Argon config app, emerald edition
├── luci-theme-carbon/        # Carbon Apple-style, IPTV edition
├── luci-theme-prism/         # Prism dark, Chinese UI edition
├── luci-theme-violet/        # Violet frosted glass, Chinese UI edition
├── luci-theme-rog-red/       # ROG faith red
└── luci-theme-techblue/      # ASUS techno blue
```

Each package directory contains its own detailed README and the upstream LICENSE file.

---

## 🔨 Build & Use

All packages follow the standard OpenWrt package layout. Copy the ones you need into your buildroot's `package/` directory:

```bash
git clone https://github.com/lsym-openwrt/openwrt-packages.git
cp -r openwrt-packages/luci-theme-argon openwrt-packages/luci-app-argon-config package/

make menuconfig          # select under LuCI → Themes / Applications
make package/luci-theme-argon/compile V=s
make package/luci-app-argon-config/compile V=s
```

> - Themes are independent and can be built separately
> - `luci-app-argon-config` depends on `luci-theme-argon`
> - `luci-app-quickstart` depends on `quickstart`
> - `nikki` and `momo` can also be used as feeds: add their directories to `feeds.conf.default`

---

## 📄 Licenses

This repository is a **collection of modified editions** of upstream open-source projects. Each package remains under its upstream license (see tables above):

| License    | Packages                                                                                                                                                                        |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GPL-3.0    | nikki, momo, quickstart (full text included per package, see [nikki/LICENSE](nikki/LICENSE))                                                                                    |
| Apache-2.0 | luci-app-quickstart, luci-app-unidash, luci-theme-argon, luci-app-argon-config, luci-theme-carbon, luci-theme-prism, luci-theme-violet, luci-theme-rog-red, luci-theme-techblue |
| MIT        | luci-app-openclash (following upstream vernesong/OpenClash)                                                                                                                     |

- Every modified edition credits its upstream project and is published under the same license, as required
- Upstream LICENSE files are kept (or added) in each package directory
- This collection neither changes any package's license nor introduces new licensing terms

---

## 🙏 Acknowledgements

Every package here stands on the shoulders of others. Thanks to the following upstream projects and authors:

| Upstream project                                                                                                                                          | Author / Organization           | Used in                                 |
| --------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------- | --------------------------------------- |
| [OpenWrt-nikki](https://github.com/nikkinikki-org/OpenWrt-nikki)                                                                                          | Joseph Mory / nikkinikki-org    | nikki                                   |
| [OpenWrt-momo](https://github.com/nikkinikki-org/OpenWrt-momo)                                                                                            | Joseph Mory / nikkinikki-org    | momo                                    |
| [OpenClash](https://github.com/vernesong/OpenClash)                                                                                                       | vernesong                       | luci-app-openclash                      |
| [istore-packages](https://github.com/linkease/istore-packages) / [quickstart](https://github.com/istoreos/quickstart)                                     | linkease, jjm2473               | quickstart, luci-app-quickstart         |
| [fanchmwrt-packages](https://github.com/fanchmwrt/fanchmwrt-packages) (luci-app-fwx-dashboard)                                                            | fanchmwrt                       | luci-app-unidash (port)                 |
| [luci-theme-argon](https://github.com/jerrykuku/luci-theme-argon) / [luci-app-argon-config](https://github.com/jerrykuku/luci-app-argon-config)           | jerrykuku                       | luci-theme-argon, luci-app-argon-config |
| [luci-theme-carbon](https://github.com/mrjoechen/luci-theme-carbon)                                                                                       | mrjoechen                       | luci-theme-carbon                       |
| [luci-theme-alpha](https://github.com/derisamedia/luci-theme-alpha) (template)                                                                            | derisamedia                     | luci-theme-prism, luci-theme-violet     |
| [luci-theme-techblue](https://github.com/KawaiiHachimi/luci-theme-techblue)                                                                               | KawaiiHachimi                   | luci-theme-rog-red, luci-theme-techblue |
| [mihomo](https://github.com/MetaCubeX/mihomo) / [meowx-core](https://github.com/mmwx-group/meowx-core) / [sing-box](https://github.com/SagerNet/sing-box) | MetaCubeX, mmwx-group, SagerNet | proxy kernels of nikki / momo           |

And the whole [OpenWrt](https://openwrt.org/) / [LuCI](https://github.com/openwrt/luci) community. **Thanks to all original authors for their great work!**

---

<div align="center">

If these modified editions help you, a ⭐ is appreciated

</div>
