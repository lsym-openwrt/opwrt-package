#
# This is free software, licensed under the Apache License, Version 2.0 .
#

include $(TOPDIR)/rules.mk

LUCI_TITLE:=LuCI support for universal OpenWrt dashboard
LUCI_DESCRIPTION:=Universal OpenWrt dashboard (ported from luci-app-fwx-dashboard). \
 Same layout, data blocks and charts, but data comes from standard OpenWrt sources \
 (/proc, ubus, conntrack, dhcp.leases) - no fwxd / kmod-fwx required. \
 Works with any LuCI theme, light and dark.
LUCI_PKGARCH:=all
LUCI_DEPENDS:=+luci-compat
PKG_NAME:=luci-app-unidash
PKG_VERSION:=1.2.2
PKG_RELEASE:=1

include $(TOPDIR)/feeds/luci/luci.mk

# call BuildPackage - OpenWrt buildroot signature
