#
# Copyright (C) 2008-2014 The LuCI Team <luci@lists.subsignal.org>
#
# This is free software, licensed under the Apache License, Version 2.0 .

include $(TOPDIR)/rules.mk

PKG_NAME:=luci-theme-rog-red
LUCI_TITLE:=ROG-OS Theme (ROG Faith Red)
LUCI_DEPENDS:=+luci-base +luci-mod-status

PKG_LICENSE:=Apache-2.0

define Package/luci-theme-rog-red/postinst
#!/bin/sh
[ -n "$${IPKG_INSTROOT}" ] || {
	uci -q set luci.themes.ROGRed='/luci-static/rog-red'
	uci commit luci
}
endef

define Package/luci-theme-rog-red/postrm
#!/bin/sh
[ -n "$${IPKG_INSTROOT}" ] || {
	uci -q delete luci.themes.ROGRed
	uci commit luci
}
endef

include $(TOPDIR)/feeds/luci/luci.mk

# call BuildPackage - OpenWrt buildroot signature
