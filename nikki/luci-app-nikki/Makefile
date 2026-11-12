include $(TOPDIR)/rules.mk

PKG_VERSION:=1.26.2
PKG_RELEASE:=4

LUCI_TITLE:=LuCI Support for nikki
LUCI_DEPENDS:=+luci-base +nikki

# 本包目录。注意不能用 $(lastword $(MAKEFILE_LIST))：第 1 行已经 include 了 rules.mk，
# 那时 lastword 指向的是 rules.mk，$(dir) 出来是 $(TOPDIR)，chmod 会打到不存在的
# $(TOPDIR)/root 上、静默空转。OpenWrt 编译时会 make -C 到包目录，所以 $(CURDIR) 才是包目录
# —— luci.mk 自己判断装什么也是用 ${CURDIR}/root。
NikkiLUCI_DIR := $(CURDIR)

# 必须写在 include luci.mk 之前：luci.mk 里是 ifndef 判断，先定义才能覆盖它的默认实现
# （它原本只清 LuCI 缓存 + reload rpcd）。构建期已经保证权限正确，这里兜住
# 从旧版本升级、或手工 scp/解包留下的 0777。
# reload 发 SIGHUP，rpcd/main.c 里 respawn = (sig == SIGHUP)，等于重启并重新扫描脚本目录，
# 所以装完包不需要再手动 /etc/init.d/rpcd restart。
define Package/luci-app-nikki/postinst
[ -n "$${IPKG_INSTROOT}" ] || { \
	chmod 0644 /usr/share/rpcd/ucode/luci.nikki 2>/dev/null; \
	rm -f /tmp/luci-indexcache*; \
	rm -rf /tmp/luci-modulecache/; \
	/etc/init.d/rpcd reload 2>/dev/null; \
	exit 0; \
}
endef

include $(TOPDIR)/feeds/luci/luci.mk

# luci.mk 的 Build/Prepare 和 install 都是 cp -pR，源码树权限会原样进包、原样装到设备上。
# 从 Windows 拷进构建环境的文件常带 0777（world-writable），而 rpcd 扫描
# /usr/share/rpcd/ucode/ 时会直接跳过 world-writable 的脚本 —— rpcd/ucode.c：
#     if (stat(path, &s) || !S_ISREG(s.st_mode)) continue;
#     if (s.st_mode & S_IWOTH) {
#             fprintf(stderr, "Ignoring ucode script %s because it is world writable\n", path);
#             continue;
#     }
# 它只往 stderr 打一行、不进 syslog，所以现象是“文件在、内容也对，但 ubus 里没这个对象”，
# LuCI 报：RPC call to luci.nikki/version failed with error -32000: Object not found
#
# build_dir 里的副本也要一起归一：增量编译时 Build/Prepare 有 .prepared 标记会跳过，
# 上一轮留下的坏权限会继续被打进包。
#
# 这里只能用 $(shell)：luci.mk 末尾的 $(eval $(call BuildPackage,...)) 在解析期就把
# $(Build/Compile) 展开成文本了，include 之后再定义 Build/Compile 钩子根本不生效。
NikkiLUCI_FIX_DIRS := "$(NikkiLUCI_DIR)/root" "$(NikkiLUCI_DIR)/htdocs" \
	$(if $(PKG_BUILD_DIR),"$(PKG_BUILD_DIR)/root" "$(PKG_BUILD_DIR)/htdocs")

NikkiLUCI_FIXED := $(shell find $(NikkiLUCI_FIX_DIRS) -type d -exec chmod 0755 {} + 2>/dev/null; find $(NikkiLUCI_FIX_DIRS) -type f -exec chmod 0644 {} + 2>/dev/null; true)

# chmod 没生效（只读挂载、跨用户等）时在这里就喊，别等装到路由器上才发现。
NikkiLUCI_DIRTY := $(shell find "$(NikkiLUCI_DIR)/root" "$(NikkiLUCI_DIR)/htdocs" -type f -perm -0002 2>/dev/null | head -n 1)
ifneq ($(NikkiLUCI_DIRTY),)
$(warning luci-app-nikki: world-writable 文件残留（$(NikkiLUCI_DIRTY)），rpcd 会跳过 luci.nikki，装上必报 Object not found)
endif
