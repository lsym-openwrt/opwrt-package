// luci-app-unidash 多语言资源 (简体中文 / English)
// 说明:
//   1) 模板中的 <%%:中文%%> 在缺少英文 .lmo 时会原样输出中文, 本文件以中文原文为 key 做前端翻译,
//      因此无需在路由器上编译 po 文件, 直接覆盖文件即可生效;
//   2) 语言跟随 OpenWrt/LuCI 系统语言: 模板注入 UNIDASH_LANG > <html lang> > navigator.language;
//      不提供独立切换按钮, 在 LuCI 系统设置中切换语言即同步切换本仪表板语言。
// 扩展方法: 在 EN 字典中按 "中文原文": "English" 追加一行即可。
window.UNIDASH_I18N = (function (w, d) {
    'use strict';

    var EN = {
        /* ---- 顶部统计 / 卡片标题 ---- */
        '联网状态': 'Internet',
        '活跃服务': 'Active Services',
        '在线用户': 'Online Users',
        '连接数': 'Connections',
        '今日流量': "Today's Traffic",
        '实时流量': 'Live Traffic',
        '实时连接分布': 'Live Connections',
        '用户流量Top8': 'Top 8 Users',
        '活跃终端Top8': 'Top 8 Active Devices',
        '活跃地址': 'Recent Sites',
        '正在访问': 'Browsing Now',

        /* ---- 通用字段 ---- */
        '名称': 'Name',
        'IP': 'IP',
        'DNS': 'DNS',
        'IP地址': 'IP Address',
        'MAC地址': 'MAC Address',
        '上行': 'Up',
        '下行': 'Down',
        '上行速率': 'Up Rate',
        '下行速率': 'Down Rate',
        '上行流量': 'Up Traffic',
        '下行流量': 'Down Traffic',
        '总流量': 'Total',
        '速率': 'Rate',
        '状态': 'Status',
        '双工': 'Duplex',
        '协议': 'Protocol',
        '源地址': 'Source',
        '目标地址': 'Dest',
        '源端口': 'Src Port',
        '目标端口': 'Dst Port',
        '匹配域名': 'Domain',
        '用户': 'User',
        '服务分类': 'Category',
        '应用ID': 'App ID',
        '访问时间': 'Access Time',
        '近一小时': 'Last Hour',
        '今日': 'Today',
        '天': 'd',
        '时': 'h',
        '分': 'm',

        /* ---- 表头 / 单位 ---- */
        '终端信息': 'Device',
        '条连接': 'connections',
        '条': 'conns',
        '暂无数据': 'No data',
        '当前APP': 'Current App',
        '当前URL': 'Current URL',

        /* ---- 系统信息 ---- */
        '系统信息': 'System Info',
        '设备型号': 'Model',
        '主机名': 'Hostname',
        '固件版本': 'Firmware',
        '内核版本': 'Kernel',
        '运行时间': 'Uptime',
        '运行状态': 'Status',
        '内存': 'Memory',
        '网络': 'Network',
        '网关': 'Gateway',
        '子网掩码': 'Netmask',
        '端口状态': 'Port Status',
        '温度': 'Temp',
        '临时空间': 'Temp',
        '磁盘空间': 'Disk',
        '启动空间': 'Boot',
        '已扩容': 'Expanded',

        /* ---- 网络状态 ---- */
        '检测中...': 'Checking...',
        '已联网': 'Online',
        '未连接': 'Offline',
        '未连接网线': 'No cable',
        '拨号失败': 'Dial failed',
        '未知': 'Unknown',
        '未采集': 'No capture',
        '未运行': 'Not running',

        /* ---- 引导气泡 ---- */
        '快速引导': 'Quick Guide',
        '知道了': 'Got it',
        '提示:点击此处切换模式。': 'Tip: click here to switch modes.',

        /* ---- 网口 / 抓包详情 ---- */
        '(全双工)': ' (Full duplex)',
        '(半双工)': ' (Half duplex)',
        '接收字节': 'RX Bytes',
        '发送字节': 'TX Bytes',
        '接收包数': 'RX Packets',
        '发送包数': 'TX Packets',
        '接收错包': 'RX Errors',
        '发送错包': 'TX Errors',

        /* ---- 服务分类 (后端返回的中文分类名) ---- */
        '服务使用分布': 'Service Usage',
        '网页浏览': 'Web Browsing',
        '视频与直播': 'Video & Live',
        '游戏娱乐': 'Gaming',
        '下载传输': 'Downloads',
        '远程访问': 'Remote Access',
        '语音视频': 'Voice & Video',
        'DNS解析': 'DNS',
        '系统服务': 'System',
        '邮件服务': 'Mail',
        '其他服务': 'Other',

        /* ---- 站点品牌名 (配合 site_names.js 使用) ---- */
        '爱奇艺': 'iQIYI',
        '哔哩哔哩': 'Bilibili',
        '优酷': 'Youku',
        '乐视': 'LeTV',
        '咪咕视频': 'Migu Video',
        '央视': 'CCTV',
        '斗鱼': 'Douyu',
        '虎牙': 'Huya',
        '网易云信': 'NetEase Yunxin',
        '腾讯': 'Tencent',
        '腾讯应用宝': 'Tencent MyApp',
        '微信': 'WeChat',
        '抖音': 'Douyin',
        '今日头条': 'Toutiao',
        '字节跳动': 'ByteDance',
        '西瓜视频': 'Xigua Video',
        '百度': 'Baidu',
        '淘宝': 'Taobao',
        '天猫': 'Tmall',
        '阿里云': 'Alibaba Cloud',
        '阿里云盘': 'Aliyun Drive',
        '京东': 'JD.com',
        '拼多多': 'Pinduoduo',
        '苏宁': 'Suning',
        '美团': 'Meituan',
        '大众点评': 'Dianping',
        '饿了么': 'Ele.me',
        '携程': 'Ctrip',
        '去哪儿': 'Qunar',
        '微博': 'Weibo',
        '新浪': 'Sina',
        '知乎': 'Zhihu',
        '豆瓣': 'Douban',
        '小红书': 'Xiaohongshu',
        '快手': 'Kuaishou',
        '搜狐': 'Sohu',
        '凤凰网': 'ifeng',
        '澎湃新闻': 'The Paper',
        '掘金': 'Juejin',
        '小米': 'Xiaomi',
        '华为': 'Huawei',
        '荣耀': 'HONOR',
        '苹果': 'Apple',
        '微软': 'Microsoft',
        '必应': 'Bing',
        '迅雷': 'Xunlei',
        '有道': 'Youdao',
        '搜狗': 'Sogou',
        '360搜索': '360 Search',
        '神马搜索': 'Shenma',
        '友盟': 'Umeng',
        '消息推送': 'Push Service',
        '维基百科': 'Wikipedia',
        'X(推特)': 'X (Twitter)',
        '亚马逊': 'Amazon',
        '阿里DNS': 'Alibaba DNS',
        '腾讯DNSPod': 'Tencent DNSPod'
    };

    // 动态文本规则: [正则, 替换] —— 只处理含数字/随机后缀的拼接串
    var PATTERNS = [
        [/^设备-([0-9A-Fa-f]{2,})([:：].*)$/i, 'Device-$1$2'],
        [/^设备-([0-9A-Fa-f]{2,})$/i, 'Device-$1'],
        [/^未知设备([:：].*)$/, 'Unknown device$1'],
        [/^未知设备$/, 'Unknown device'],
        [/^未识别$/, 'Unknown'],
        [/^(\d[\d,]*)\s*条连接$/, '$1 connections'],
        [/^(\d[\d,]*)\s*条$/, '$1 conns'],
        [/^([\w.\-]+)\s*·\s*(\d[\d,]*)\s*条$/, '$1 · $2 conns']
    ];

    function patternize(s) {
        for (var i = 0; i < PATTERNS.length; i++) {
            if (PATTERNS[i][0].test(s)) return s.replace(PATTERNS[i][0], PATTERNS[i][1]);
        }
        return s;
    }

    var CJK = /[\u4e00-\u9fff]/;
    var ATTRS = ['title', 'data-label', 'placeholder', 'aria-label', 'alt'];

    function normalize(v) {
        v = String(v || '').toLowerCase();
        return v.indexOf('zh') === 0 ? 'zh' : 'en';
    }

    // 语言完全跟随 OpenWrt/LuCI 系统语言 (模板注入的 window.UNIDASH_LANG),
    // 不提供独立切换按钮。
    var systemLang = w.UNIDASH_LANG || (d.documentElement && d.documentElement.getAttribute('lang')) ||
        (w.navigator && w.navigator.language) || 'zh';
    var lang = normalize(systemLang);

    function t(key, vars) {
        if (key === undefined || key === null) return '';
        var out = (lang === 'en' && EN[key]) ? EN[key] : String(key);
        if (vars) {
            out = out.replace(/\{(\w+)\}/g, function (m, k) {
                return vars[k] === undefined ? m : vars[k];
            });
        }
        return out;
    }

    // 先查字典, 再套动态规则
    function tr(text) {
        if (lang !== 'en' || !text) return text;
        var s = String(text);
        if (EN[s]) return EN[s];
        // "设备-AB12:" / "上行:" 这类带尾部标点的标签, 去掉标点再查一次
        var tail = s.match(/^([\s\S]*?)([:：])$/);
        if (tail && tail[1]) {
            var base = tail[1];
            if (EN[base]) return EN[base] + tail[2];
            var patched = patternize(base);
            if (patched !== base) return patched + tail[2];
        }
        return patternize(s);
    }

    function roots() {
        var list = [];
        var dash = d.querySelector('.dash');
        var mobile = d.getElementById('dashboard-mobile');
        if (dash) list.push(dash);
        if (mobile) list.push(mobile);
        if (!list.length && d.body) list.push(d.body);
        return list;
    }

    function translateTextNode(node) {
        var value = node.nodeValue;
        if (!value || !CJK.test(value)) return false;
        var core = value.trim();
        if (!core || !CJK.test(core)) return false;
        var out = tr(core);
        if (out === core) return false;
        var start = value.indexOf(core);
        node.nodeValue = value.slice(0, start) + out + value.slice(start + core.length);
        return true;
    }

    function translateAttrs(root) {
        if (!root.querySelectorAll) return;
        var nodes = root.querySelectorAll('[title],[data-label],[placeholder],[aria-label],[alt]');
        for (var i = 0; i < nodes.length; i++) {
            for (var j = 0; j < ATTRS.length; j++) {
                var raw = nodes[i].getAttribute(ATTRS[j]);
                if (!raw || !CJK.test(raw)) continue;
                var out = tr(raw.trim());
                if (out !== raw.trim()) nodes[i].setAttribute(ATTRS[j], out);
            }
        }
    }

    function apply() {
        if (lang !== 'en') return;
        var list = roots();
        for (var i = 0; i < list.length; i++) {
            var root = list[i];
            var walker = d.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
                acceptNode: function (n) {
                    var p = n.parentNode;
                    if (!p) return NodeFilter.FILTER_REJECT;
                    // 跳过 SVG (ECharts 图表) 内部文本: 图表标签在构建 option 时已用 ut() 翻译,
                    // 且 SVG 会随时间轴/动画高频重绘, 若在此翻译会与图表渲染互相触发导致浏览器卡死。
                    if (p.ownerSVGElement) return NodeFilter.FILTER_REJECT;
                    var tag = p.nodeName;
                    if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'TEXTAREA' || tag === 'CODE') {
                        return NodeFilter.FILTER_REJECT;
                    }
                    return CJK.test(n.nodeValue || '') ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
                }
            }, false);
            var batch = [];
            while (walker.nextNode()) batch.push(walker.currentNode);
            for (var k = 0; k < batch.length; k++) translateTextNode(batch[k]);
            translateAttrs(root);
        }
    }

    // 侧边栏菜单本地化: 后端在构建菜单树缓存时语言固定为默认(zh), 标题会被锁成中文;
    // 而 iStoreOS/WenWrt 主题又用 data-title (CSS content:attr(data-title)) 显示文字。
    // 注意: 给 nodeValue/textContent 赋相同值也会产生 mutation 记录, 若配合 MutationObserver
    // 会形成死循环卡死浏览器 —— 因此这里一律"先比较、确有变化才写", 并用有界轮询代替全页监听。
    function setMenuText(a, label) {
        if (!a) return;
        if (a.classList && a.classList.contains('mini')) return;
        // 1) 主题用 content:attr(data-title) 显示文字 / tooltip; 只改已知标签值, 避免误伤其它链接
        var dt = a.getAttribute('data-title');
        if (dt === '仪表板' || dt === 'Dashboard') {
            if (dt !== label) a.setAttribute('data-title', label);
        }
        var tt = a.getAttribute('title');
        if (tt && tt !== label) a.setAttribute('title', label);
        // 2) 直接文本节点 (本主题为 <a>仪表板</a> 这种裸文本), 先比较再写
        var nodes = a.childNodes, hit = false;
        for (var i = 0; i < nodes.length; i++) {
            if (nodes[i].nodeType === 3 && nodes[i].textContent.trim() !== '') {
                var v = nodes[i].nodeValue;
                var desired = (v.match(/^\s*/)[0] || '') + label + (v.match(/\s*$/)[0] || '');
                if (v !== desired) nodes[i].nodeValue = desired;
                hit = true;
            }
        }
        // 3) 兜底: 主题把标题包在 span 里 (排除含图标的 span)
        if (!hit) {
            var spans = a.querySelectorAll('span');
            for (var j = 0; j < spans.length; j++) {
                if (spans[j].querySelector && spans[j].querySelector('svg, img, i[class], .icon')) continue;
                if ((spans[j].textContent || '').trim()) {
                    if (spans[j].textContent !== label) spans[j].textContent = label;
                    hit = true;
                    break;
                }
            }
        }
        if (!hit && (a.textContent || '').trim() !== label) a.textContent = label;
    }

    function fixUnidashMenu() {
        var label = (lang === 'en') ? 'Dashboard' : '仪表板';
        function findLinks() {
            // 优先 #mainmenu, 找不到就在整页查找 (兼容不同主题把菜单放在别的容器)
            var scope = d.getElementById('mainmenu') || d.body || d.documentElement;
            return scope.querySelectorAll('a[href*="admin/unidash"]');
        }
        function needsFix(a) {
            var cur = (a.textContent || '').trim();
            if (cur !== label) return true;
            var dt = a.getAttribute('data-title');
            return !!(dt && dt !== label && (dt === '仪表板' || dt === 'Dashboard'));
        }
        function doApply() {
            var links = findLinks();
            if (!links.length) return false;
            for (var i = 0; i < links.length; i++) {
                if (needsFix(links[i])) setMenuText(links[i], label);
            }
            return true;
        }
        // 复核几次, 防主题在本页稍后重渲染菜单 (幂等, 有界, 不做全页监听)
        function recheck() {
            var re = 0;
            (function again() {
                if (++re > 3) return;
                w.setTimeout(function () { doApply(); again(); }, 800);
            })();
        }
        if (doApply()) { recheck(); return; }
        // 菜单由主题 JS 延迟渲染: 短暂轮询等待 (最多 ~5s), 出现后复核即停
        var tries = 0;
        (function poll() {
            if (doApply()) { recheck(); return; }
            if (++tries >= 12) return;
            w.setTimeout(poll, 400);
        })();
    }

    // 模板里 var _Xxx = '<%:中文%>' 形式定义在 window 上的全局文案
    function translateGlobals(scope) {
        if (lang !== 'en') return;
        scope = scope || w;
        for (var key in scope) {
            if (/^_[A-Z]/.test(key) && typeof scope[key] === 'string' && CJK.test(scope[key])) {
                scope[key] = tr(scope[key]);
            }
        }
    }

    var observer = null;
    var scheduled = false;

    function schedule() {
        if (scheduled) return;
        scheduled = true;
        (w.requestAnimationFrame || function (fn) { return w.setTimeout(fn, 16); })(function () {
            scheduled = false;
            apply();
        });
    }

    function start() {
        // 仅英文模式改写 <html lang>; 中文模式保留主题原值, 不影响字体/断行规则
        if (lang === 'en' && d.documentElement) d.documentElement.setAttribute('lang', 'en');
        translateGlobals(w);
        apply();
        fixUnidashMenu();
        if (lang !== 'en' || observer || !w.MutationObserver) return;
        observer = new MutationObserver(function (records) {
            for (var i = 0; i < records.length; i++) {
                var t = records[i].target;
                if (!t) continue;
                var el = (t.nodeType === 1) ? t : t.parentNode;
                // 跳过 SVG (ECharts) 内部的高频重绘变更, 避免与图表动画互相触发造成卡顿/卡死
                if (el && (el.ownerSVGElement || (el.closest && el.closest('svg')))) continue;
                var txt = (t.nodeType === 3) ? (t.nodeValue || '') : (t.textContent || '');
                if (!CJK.test(txt)) continue;
                schedule();
                return;
            }
        });
        var list = roots();
        for (var i = 0; i < list.length; i++) {
            observer.observe(list[i], { childList: true, subtree: true, characterData: true });
        }
    }

    return {
        lang: lang,
        systemLang: systemLang,
        t: t,
        tr: tr,
        apply: apply,
        start: start,
        translateGlobals: translateGlobals,
        dict: EN
    };
})(window, document);

// 模板内简写: 视图中可用 ut('中文原文')
window.ut = function (key, vars) {
    return window.UNIDASH_I18N ? window.UNIDASH_I18N.t(key, vars) : key;
};
