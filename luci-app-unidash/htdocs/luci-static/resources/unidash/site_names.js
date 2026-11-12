// luci-app-unidash 站点名称字典
// 作用: 把访问的域名翻译成易读的站点名 (如 www.iqiyi.com -> 爱奇艺), 显示在「正在访问」磁贴上。
// 扩展方法: 直接在本文件 window.UNIDASH_SITE_NAMES 中按 "域名后缀": "名称" 添加一行即可,
//           路由器上路径: /www/luci-static/resources/unidash/site_names.js, 改完无需重启。
// 匹配规则: 去掉 www. 后先精确匹配, 再按最长域名后缀匹配 (子域名自动命中, 如 v.qq.com -> 腾讯)。
window.UNIDASH_SITE_NAMES = {
	// 国内视频
	"iqiyi.com": "爱奇艺", "qiyipic.com": "爱奇艺", "iqiyipic.com": "爱奇艺",
	"bilibili.com": "哔哩哔哩", "hdslb.com": "哔哩哔哩", "biliapi.net": "哔哩哔哩", "bilivideo.com": "哔哩哔哩",
	"youku.com": "优酷", "youkucdn.com": "优酷",
	"le.com": "乐视", "letv.com": "乐视",
	"acfun.cn": "AcFun",
	"miguvideo.com": "咪咕视频",
	"cntv.cn": "央视", "cctv.com": "央视",
	"douyu.com": "斗鱼", "douyucdn.cn": "斗鱼",
	"huya.com": "虎牙", "huyacdn.com": "虎牙",
	"netease.im": "网易云信",
	// 腾讯系
	"qq.com": "腾讯", "gtimg.com": "腾讯", "qpic.cn": "腾讯", "qlogo.cn": "腾讯",
	"myapp.com": "腾讯应用宝", "wegame.com": "WeGame", "qq.com.cn": "腾讯",
	"wechat.com": "微信", "weixinbridge.com": "微信",
	// 字节系
	"douyin.com": "抖音", "douyinpic.com": "抖音", "douyinvod.com": "抖音",
	"tiktokv.com": "TikTok", "tiktokcdn.com": "TikTok",
	"toutiao.com": "今日头条", "pstatp.com": "字节跳动", "bytecdn.cn": "字节跳动",
	"zjcdn.com": "字节跳动", "zijieapi.com": "字节跳动", "bytedance.com": "字节跳动",
	"ixigua.com": "西瓜视频",
	// 百度系
	"baidu.com": "百度", "bdstatic.com": "百度", "bcebos.com": "百度",
	"baidubce.com": "百度", "baiducontent.com": "百度", "bce.baidu.com": "百度",
	// 阿里系
	"taobao.com": "淘宝", "tmall.com": "天猫", "tbcdn.cn": "淘宝",
	"aliyun.com": "阿里云", "aliyuncs.com": "阿里云", "alicdn.com": "阿里云",
	"aliyundrive.com": "阿里云盘",
	// 电商/生活
	"jd.com": "京东", "360buyimg.com": "京东", "jdcloud.com": "京东",
	"pinduoduo.com": "拼多多", "yangkeduo.com": "拼多多",
	"suning.com": "苏宁",
	"meituan.com": "美团", "meituan.net": "美团", "dianping.com": "大众点评",
	"ele.me": "饿了么", "elemecdn.com": "饿了么",
	"ctrip.com": "携程", "qunar.com": "去哪儿", "12306.cn": "12306",
	// 社区/资讯
	"weibo.com": "微博", "weibo.cn": "微博", "sina.com.cn": "新浪", "sinaimg.cn": "微博",
	"zhihu.com": "知乎", "zhimg.com": "知乎",
	"douban.com": "豆瓣", "doubanio.com": "豆瓣",
	"xiaohongshu.com": "小红书", "xhscdn.com": "小红书",
	"kuaishou.com": "快手", "gifshow.com": "快手", "ksapisrv.com": "快手",
	"sohu.com": "搜狐", "sohucs.com": "搜狐", "itc.cn": "搜狐",
	"ifeng.com": "凤凰网", "thepaper.cn": "澎湃新闻",
	"csdn.net": "CSDN", "juejin.cn": "掘金", "v2ex.com": "V2EX",
	// 厂商
	"mi.com": "小米", "xiaomi.com": "小米", "miui.com": "小米", "xiaomi.net": "小米",
	"huawei.com": "华为", "hicloud.com": "华为", "dbankcloud.com": "华为",
	"honor.com": "荣耀",
	"oppo.com": "OPPO", "heytapmobi.com": "OPPO",
	"vivo.com": "vivo",
	"apple.com": "苹果", "icloud.com": "苹果", "mzstatic.com": "苹果",
	"microsoft.com": "微软", "live.com": "微软", "msn.com": "微软",
	"microsoftonline.com": "微软", "windowsupdate.com": "微软", "office.com": "微软",
	"bing.com": "必应",
	// 工具/云
	"wps.cn": "WPS", "kdocs.cn": "WPS",
	"xunlei.com": "迅雷", "sandai.net": "迅雷",
	"youdao.com": "有道",
	"sogou.com": "搜狗", "sogoucdn.com": "搜狗",
	"so.com": "360搜索", "360.cn": "360",
	"sm.cn": "神马搜索",
	"umeng.com": "友盟", "umengcloud.com": "友盟",
	"getui.com": "消息推送", "jpush.cn": "消息推送",
	"cloudflare.com": "Cloudflare", "fastly.net": "Fastly CDN",
	"akamaihd.net": "Akamai CDN", "akamaized.net": "Akamai CDN",
	// 国际
	"google.com": "Google", "gstatic.com": "Google", "googleapis.com": "Google",
	"googleusercontent.com": "Google", "googlevideo.com": "Google",
	"youtube.com": "YouTube", "ytimg.com": "YouTube", "youtu.be": "YouTube",
	"github.com": "GitHub", "githubusercontent.com": "GitHub", "gitlab.com": "GitLab",
	"openai.com": "OpenAI", "oaistatic.com": "OpenAI", "chatgpt.com": "OpenAI",
	"wikipedia.org": "维基百科", "wikimedia.org": "维基百科",
	"facebook.com": "Facebook", "fbcdn.net": "Facebook",
	"instagram.com": "Instagram", "cdninstagram.com": "Instagram",
	"whatsapp.com": "WhatsApp",
	"twitter.com": "X(推特)", "x.com": "X(推特)", "twimg.com": "X(推特)",
	"telegram.org": "Telegram", "t.me": "Telegram", "cdn-telegram.org": "Telegram",
	"netflix.com": "Netflix", "nflximg.com": "Netflix", "nflxvideo.net": "Netflix", "nflxso.net": "Netflix",
	"amazon.com": "亚马逊", "amazonaws.com": "亚马逊", "media-amazon.com": "亚马逊",
	"steamcontent.com": "Steam", "steampowered.com": "Steam", "steamstatic.com": "Steam", "steamserver.net": "Steam",
	"twitch.tv": "Twitch", "twitchcdn.net": "Twitch",
	"reddit.com": "Reddit", "redd.it": "Reddit", "redditmedia.com": "Reddit",
	"spotify.com": "Spotify", "scdn.co": "Spotify"
};

// 知名 IP 前缀 (这些服务通过 IP 直连, 无域名可查, 按前缀显示名称)
window.UNIDASH_IP_NAMES = {
	"91.108.": "Telegram", "149.154.": "Telegram",
	"223.5.5.": "阿里DNS", "223.6.6.": "阿里DNS",
	"119.29.29.": "腾讯DNSPod",
	"114.114.114.": "114DNS", "114.114.115.": "114DNS",
	"1.1.1.": "CloudflareDNS", "1.0.0.": "CloudflareDNS",
	"8.8.8.": "GoogleDNS", "8.8.4.": "GoogleDNS",
	"9.9.9.": "Quad9DNS"
};

// 英文站点名: 仅收录上表中文名的对应英文/拉丁写法, 未收录的按原名显示
window.UNIDASH_SITE_NAMES_EN = {
	"爱奇艺": "iQIYI", "哔哩哔哩": "Bilibili", "优酷": "Youku", "乐视": "LeTV",
	"咪咕视频": "Migu Video", "央视": "CCTV", "斗鱼": "Douyu", "虎牙": "Huya",
	"网易云信": "NetEase Yunxin", "腾讯": "Tencent", "腾讯应用宝": "Tencent MyApp",
	"微信": "WeChat", "抖音": "Douyin", "今日头条": "Toutiao", "字节跳动": "ByteDance",
	"西瓜视频": "Xigua Video", "百度": "Baidu", "淘宝": "Taobao", "天猫": "Tmall",
	"阿里云": "Alibaba Cloud", "阿里云盘": "Aliyun Drive", "京东": "JD.com",
	"拼多多": "Pinduoduo", "苏宁": "Suning", "美团": "Meituan", "大众点评": "Dianping",
	"饿了么": "Ele.me", "携程": "Ctrip", "去哪儿": "Qunar", "微博": "Weibo",
	"新浪": "Sina", "知乎": "Zhihu", "豆瓣": "Douban", "小红书": "Xiaohongshu",
	"快手": "Kuaishou", "搜狐": "Sohu", "凤凰网": "ifeng", "澎湃新闻": "The Paper",
	"掘金": "Juejin", "小米": "Xiaomi", "华为": "Huawei", "荣耀": "HONOR",
	"苹果": "Apple", "微软": "Microsoft", "必应": "Bing", "迅雷": "Xunlei",
	"有道": "Youdao", "搜狗": "Sogou", "360搜索": "360 Search", "神马搜索": "Shenma",
	"友盟": "Umeng", "消息推送": "Push Service", "维基百科": "Wikipedia",
	"X(推特)": "X (Twitter)", "亚马逊": "Amazon", "阿里DNS": "Alibaba DNS",
	"腾讯DNSPod": "Tencent DNSPod", "114DNS": "114DNS",
	"CloudflareDNS": "Cloudflare DNS", "GoogleDNS": "Google DNS", "Quad9DNS": "Quad9 DNS"
};

// 当前是否英文界面 (由 i18n.js 决定)
window.unidashIsEnglish = function () {
	var i18n = window.UNIDASH_I18N;
	return !!(i18n && i18n.lang === 'en');
};

// 把中文站点名转成当前语言
window.unidashLocalizeSiteName = function (name) {
	if (!name) return name;
	if (window.unidashIsEnglish()) {
		return window.UNIDASH_SITE_NAMES_EN[name] || name;
	}
	return name;
};

// 匹配函数: 传入域名或 IP, 返回站点名; 未命中返回 null
window.unidashMatchSiteName = function (host) {
	if (!host) return null;
	var h = String(host).toLowerCase().replace(/^www\./, '');
	if (/^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(h)) {
		for (var p in window.UNIDASH_IP_NAMES) {
			if (h.indexOf(p) === 0) return window.unidashLocalizeSiteName(window.UNIDASH_IP_NAMES[p]);
		}
		return null;
	}
	var dict = window.UNIDASH_SITE_NAMES;
	if (dict[h]) return window.unidashLocalizeSiteName(dict[h]);
	var best = null, bestLen = 0;
	for (var k in dict) {
		if (h.length > k.length && h.slice(-(k.length + 1)) === '.' + k) {
			if (k.length > bestLen) { best = dict[k]; bestLen = k.length; }
		}
	}
	return window.unidashLocalizeSiteName(best);
};
