include $(TOPDIR)/rules.mk

# meowc 内核：升级到 meowx-core 0.4.9（同 meowx-openwrt 的内核版本）。
# 0.4.9 起源码在独立的 meowx-core 仓库，以前的 001（独立程序自起监听端口与 TUN）、
# 002（panel 子命令：主控账户、账户订阅、白名单上报）补丁都已合进内核，不再需要 patches/。
# 比官方 mihomo 多 Miu、AnyTLS + REALITY、Snell v6 等，按 meowx-core 的 tag 固定（PKG_VERSION = tag 去掉 v）。
# 包名与二进制名保持 meowc，nikki 的 init / LuCI / 安装脚本均按此工作。
PKG_NAME:=meowc
PKG_VERSION:=0.4.9
PKG_RELEASE:=1

PKG_SOURCE_PROTO:=git
PKG_SOURCE_URL:=https://github.com/mmwx-group/meowx-core.git
PKG_SOURCE_VERSION:=bca53bd296298fd13b79aa2c18bbe2740deb410a
PKG_MIRROR_HASH:=93480cd913eaeafa2ea023517859c1a5e6a42c92b416a2b8b176c350bfbbb5ac

PKG_LICENSE:=GPL-3.0-or-later
PKG_LICENSE_FILES:=LICENSE
PKG_MAINTAINER:=MeowX

PKG_BUILD_DEPENDS:=golang/host
PKG_BUILD_PARALLEL:=1
PKG_BUILD_FLAGS:=no-mips16

PKG_BUILD_DIR:=$(BUILD_DIR)/$(PKG_NAME)-$(PKG_VERSION)
PKG_BUILD_TIME:=$(shell date -u -Iseconds)

GO_PKG:=github.com/metacubex/mihomo
GO_PKG_BUILD_PKG:=github.com/metacubex/mihomo
GO_PKG_LDFLAGS_X:=$(GO_PKG)/constant.Version=meowc-$(PKG_VERSION) $(GO_PKG)/constant.BuildTime=$(PKG_BUILD_TIME)
# 路由器上用不到 Bettbox 带的三种组网出站（EasyTier 光内嵌的 WASM 就有 6.5MB）：去掉后 mipsle 59M → 41M
GO_PKG_TAGS:=with_gvisor,no_easytier,no_tailscale,no_zerotier

include $(INCLUDE_DIR)/package.mk
include $(TOPDIR)/feeds/packages/lang/golang/golang-package.mk

define Package/meowc
  SECTION:=net
  CATEGORY:=Network
  TITLE:=MeowC core (mihomo fork, meowx-core 0.4.9)
  URL:=https://github.com/mmwx-group/meowx-core
  DEPENDS:=$(GO_ARCH_DEPENDS) +ca-bundle +ip-full +kmod-inet-diag +kmod-tun
endef

define Package/meowc/description
  MeowC proxy core, a fork of mihomo with Miu, AnyTLS + REALITY and Snell v6.
endef

define Build/Prepare
	$(Build/Prepare/Default)
	$(RM) -r $(PKG_BUILD_DIR)/rules/logic_test
endef

define Package/meowc/install
	$(INSTALL_DIR) $(1)/usr/bin
	$(INSTALL_BIN) $(GO_PKG_BUILD_BIN_DIR)/mihomo $(1)/usr/bin/meowc
endef

$(eval $(call GoBinPackage,meowc))
$(eval $(call BuildPackage,meowc))
