include $(TOPDIR)/rules.mk

PKG_NAME:=momo
PKG_VERSION:=2026.10.14
PKG_RELEASE:=8

PKG_LICENSE:=GPL-3.0+
PKG_MAINTAINER:=Joseph Mory <morytyann@gmail.com>

include $(INCLUDE_DIR)/package.mk

define Package/momo
  SECTION:=net
  CATEGORY:=Network
  TITLE:=Transparent Proxy with sing-box on OpenWrt.
  URL:=https://github.com/nikkinikki-org
  DEPENDS:=+ca-bundle +curl firewall4 +ip-full +kmod-inet-diag +kmod-nft-socket +kmod-nft-tproxy +kmod-tun +kmod-dummy +sing-box +python3-light
endef

define Package/momo/conffiles
/etc/config/momo
/etc/momo/converter/converter.conf
/etc/momo/converter/momo-base.json
endef

define Package/momo/install
	$(INSTALL_DIR) $(1)/etc/momo
	$(INSTALL_DIR) $(1)/etc/momo/ucode
	$(INSTALL_DIR) $(1)/etc/momo/scripts
	$(INSTALL_DIR) $(1)/etc/momo/firewall
	$(INSTALL_DIR) $(1)/etc/momo/profiles
	$(INSTALL_DIR) $(1)/etc/momo/subscriptions
	$(INSTALL_DIR) $(1)/etc/momo/run
	$(INSTALL_DIR) $(1)/etc/momo/converter

	$(INSTALL_BIN) $(CURDIR)/files/ucode/include.uc $(1)/etc/momo/ucode/include.uc
	$(INSTALL_BIN) $(CURDIR)/files/ucode/mixin.uc $(1)/etc/momo/ucode/mixin.uc
	$(INSTALL_BIN) $(CURDIR)/files/ucode/hijack.ut $(1)/etc/momo/ucode/hijack.ut

	$(INSTALL_BIN) $(CURDIR)/files/scripts/include.sh $(1)/etc/momo/scripts/include.sh
	$(INSTALL_BIN) $(CURDIR)/files/scripts/firewall_include.sh $(1)/etc/momo/scripts/firewall_include.sh
	$(INSTALL_BIN) $(CURDIR)/files/scripts/debug.sh $(1)/etc/momo/scripts/debug.sh
	$(INSTALL_BIN) $(CURDIR)/files/scripts/convert.sh $(1)/etc/momo/scripts/convert.sh
	$(INSTALL_BIN) $(CURDIR)/files/scripts/groupd.sh $(1)/etc/momo/scripts/groupd.sh
	$(INSTALL_DATA) $(CURDIR)/files/scripts/momo_convert.py $(1)/etc/momo/scripts/momo_convert.py
	$(INSTALL_DATA) $(CURDIR)/files/scripts/momo_groupd.py $(1)/etc/momo/scripts/momo_groupd.py

	$(INSTALL_CONF) $(CURDIR)/files/converter/converter.conf $(1)/etc/momo/converter/converter.conf
	$(INSTALL_DATA) $(CURDIR)/files/converter/momo-base.json $(1)/etc/momo/converter/momo-base.json

	$(INSTALL_BIN) $(CURDIR)/files/firewall/geoip_cn.nft $(1)/etc/momo/firewall/geoip_cn.nft
	$(INSTALL_BIN) $(CURDIR)/files/firewall/geoip6_cn.nft $(1)/etc/momo/firewall/geoip6_cn.nft

	$(INSTALL_DIR) $(1)/etc/config
	$(INSTALL_CONF) $(CURDIR)/files/momo.conf $(1)/etc/config/momo

	$(INSTALL_DIR) $(1)/etc/init.d
	$(INSTALL_BIN) $(CURDIR)/files/momo.init $(1)/etc/init.d/momo

	$(INSTALL_DIR) $(1)/etc/uci-defaults
	$(INSTALL_BIN) $(CURDIR)/files/uci-defaults/firewall.sh $(1)/etc/uci-defaults/99_firewall_momo
	$(INSTALL_BIN) $(CURDIR)/files/uci-defaults/init.sh $(1)/etc/uci-defaults/99_init_momo
	$(INSTALL_BIN) $(CURDIR)/files/uci-defaults/migrate.sh $(1)/etc/uci-defaults/99_migrate_momo

	$(INSTALL_DIR) $(1)/lib/upgrade/keep.d
	$(INSTALL_DATA) $(CURDIR)/files/momo.upgrade $(1)/lib/upgrade/keep.d/momo
endef

define Package/momo/postinst
#!/bin/sh
[ -n "$${IPKG_INSTROOT}" ] && exit 0
# 升级安装时 uci-defaults 不会被自动执行，这里显式跑一次配置迁移（脚本内部幂等）
if [ -f /etc/uci-defaults/99_migrate_momo ]; then
	IPKG_INSTROOT= /bin/sh /etc/uci-defaults/99_migrate_momo >/dev/null 2>&1
	rm -f /etc/uci-defaults/99_migrate_momo
fi
# rpcd 只在登录时把 acl.d 读进会话，升级 ACL 后已登录的会话仍持旧快照，
# 前端就会一直报 RPCError，直到手动重启 rpcd。这里给现存会话即时补权；
# 若 ubus 上压根没有 luci.momo 对象（插件加载失败），ensure_rpcd_plugin 会重启 rpcd。
if [ -f /etc/momo/scripts/include.sh ]; then
	. /etc/momo/scripts/include.sh 2>/dev/null
	if command -v ensure_rpcd_plugin >/dev/null 2>&1; then
		ensure_rpcd_plugin >/dev/null 2>&1
	fi
	command -v grant_rpcd_acl >/dev/null 2>&1 && grant_rpcd_acl >/dev/null 2>&1
fi
exit 0
endef

define Package/momo/postrm
#!/bin/sh
if [ -z $${IPKG_INSTROOT} ]; then
	uci -q batch <<-EOF > /dev/null
		del firewall.momo
		commit firewall
	EOF
fi
endef

define Build/Compile

endef

$(eval $(call BuildPackage,momo))