# quickstart · 进程守护加固版

<div align="center">

![Version](https://img.shields.io/badge/version-0.13.0--r3-blue) ![Upstream](https://img.shields.io/badge/upstream-linkease%2Fistore--packages-green) ![License](https://img.shields.io/badge/license-GPL--3.0-orange)

</div>

> 基于 [linkease/istore-packages](https://github.com/linkease/istore-packages) **quickstart v0.13.0-r3**（预编译二进制包装包，主程序源码见 [istoreos/quickstart](https://github.com/istoreos/quickstart)）修改：iStoreOS 的仪表盘与使用向导守护进程，本版重点解决**开机高负载下进程"永不启动"**的问题。

## ✨ 功能特性（继承上游）

- iStoreOS 仪表盘与使用向导的后端守护进程
- 磁盘 / S.M.A.R.T. / RAID 支持（smartmontools、mdadm 等）
- 附带 `startdhns`（DHCP 通知辅助服务）与 `dhcpvalid.sh`

## 📌 与上游的主要差异

| #   | 改动               | 说明                                                                                                                                           |
| --- | ------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | init 脚本重写      | procd `respawn 3600 5 3`（默认重试 5 次后放弃，高负载开机可能永不启动）；`boot()` 后 5s / 10s / 20s 三段延迟自愈拉起；unix socket 目录自动创建 |
| 2   | startdhns 有界等待 | 3 次 × 2s 超时（≤13s），避免卡住 rcS 启动与 network reload                                                                                     |
| 3   | postinst 加固      | 安装 / 升级后始终 enable 并兜底启动，防止包脚本竞态导致服务未拉起                                                                              |

## 📦 安装（SDK / buildroot 编译）

```bash
git clone https://github.com/lsym-openwrt/opwrt-package.git
cp -r opwrt-package/quickstart package/

make menuconfig   # Network → Web Servers/Proxies → quickstart
make package/quickstart/compile V=s   # 编译时自动拉取上游预编译二进制
```

## 📄 许可证

遵循上游的 **GNU General Public License v3**。

## 🙏 致谢

- 上游项目：[linkease/istore-packages](https://github.com/linkease/istore-packages)、[istoreos/quickstart](https://github.com/istoreos/quickstart)（jjm2473 等）
