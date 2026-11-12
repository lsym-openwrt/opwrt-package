'use strict';
'require baseclass';
'require uci';
'require fs';
'require rpc';
'require request';

const MX_CSS_ID = 'momo-theme-css';
const MX_CSS_HREF = '/luci-static/resources/view/momo/app.css';

function mxDetectTheme() {
    try {
        const bg = window.getComputedStyle(document.body).backgroundColor || '';
        const parts = bg.match(/[\d.]+/g);
        if (!parts || parts.length < 3)
            return 'light';
        if (parts.length > 3 && parseFloat(parts[3]) === 0)
            return 'light';
        const luma = 0.299 * +parts[0] + 0.587 * +parts[1] + 0.114 * +parts[2];
        return luma < 128 ? 'dark' : 'light';
    } catch (e) {
        return 'light';
    }
}

function mxApplyTheme() {
    try {
        const theme = mxDetectTheme();
        const root = document.documentElement;
        if (root.getAttribute('data-mx') !== theme)
            root.setAttribute('data-mx', theme);
    } catch (e) { }
}

function mxInjectCss() {
    if (document.getElementById(MX_CSS_ID))
        return;
    const link = document.createElement('link');
    link.id = MX_CSS_ID;
    link.rel = 'stylesheet';
    link.href = MX_CSS_HREF + '?t=' + Date.now();
    (document.head || document.documentElement).appendChild(link);
}

let mxObserved = false;

function mxInit() {
    mxInjectCss();
    mxApplyTheme();

    if (!mxObserved && typeof MutationObserver !== 'undefined' && document.body) {
        mxObserved = true;
        new MutationObserver(mxApplyTheme).observe(document.body, {
            attributes: true,
            attributeFilter: ['class', 'style', 'data-darkmode']
        });
    }

    if (typeof window !== 'undefined' && window.matchMedia) {
        const mq = window.matchMedia('(prefers-color-scheme: dark)');
        if (mq.addEventListener)
            mq.addEventListener('change', mxApplyTheme);
        else if (mq.addListener)
            mq.addListener(mxApplyTheme);
    }
}

// 模块可能在 body 就绪前加载，等 DOM 可用再落地主题
if (document.readyState === 'loading')
    document.addEventListener('DOMContentLoaded', mxInit);
else
    mxInit();

const callRCList = rpc.declare({
    object: 'rc',
    method: 'list',
    params: ['name'],
    expect: { '': {} }
});

const callRCInit = rpc.declare({
    object: 'rc',
    method: 'init',
    params: ['name', 'action'],
    expect: { '': {} }
});

const callFileWrite = rpc.declare({
    object: 'file',
    method: 'write',
    params: ['path', 'data', 'append', 'mode']
});

const callMomoGetPaths = rpc.declare({
    object: 'luci.momo',
    method: 'get_paths',
    expect: { '': {} }
});

const callMomoVersion = rpc.declare({
    object: 'luci.momo',
    method: 'version',
    expect: { '': {} }
});

const callMomoProfile = rpc.declare({
    object: 'luci.momo',
    method: 'profile',
    params: ['defaults'],
    expect: { '': {} }
});

const callMomoUpdateSubscription = rpc.declare({
    object: 'luci.momo',
    method: 'update_subscription',
    params: ['section_id'],
    expect: { '': {} }
});

const callMomoUpdateSubscriptionAsync = rpc.declare({
    object: 'luci.momo',
    method: 'update_subscription_async',
    params: ['section_id'],
    expect: { '': {} }
});

const callMomoUpdateStatus = rpc.declare({
    object: 'luci.momo',
    method: 'update_status',
    expect: { '': {} }
});

function callFailsafe(fn, ...args) {
    return fn(...args).catch(function () { return null; });
}

const callMomoAPI = rpc.declare({
    object: 'luci.momo',
    method: 'api',
    params: ['method', 'path', 'query', 'body'],
    expect: { '': {} }
});

const callMomoGetIdentifiers = rpc.declare({
    object: 'luci.momo',
    method: 'get_identifiers',
    expect: { '': {} }
});

const callMomoDebug = rpc.declare({
    object: 'luci.momo',
    method: 'debug',
    expect: { '': {} }
});

return baseclass.extend({
    getPaths: async function () {
        return callMomoGetPaths();
    },

    status: async function () {
        return (await callRCList('momo'))?.momo?.running;
    },

    reload: function () {
        return callRCInit('momo', 'reload');
    },

    restart: function () {
        return callRCInit('momo', 'restart');
    },

    writefile: function (path, data, mode) {
        data = (data != null) ? String(data) : '';
        mode = (mode != null) ? mode : 0o644;

        const encoder = new TextEncoder();
        const decoder = new TextDecoder();
        const chunkSize = 8 * 1024;

        const bytes = encoder.encode(data);

        if (bytes.length <= chunkSize) {
            return callFileWrite(path, data, false, mode);
        }

        let promise = Promise.resolve();
        for(let offset = 0; offset < bytes.length; offset += chunkSize) {
            const chunkStart = offset;
            const chunkEnd = Math.min(offset + chunkSize, bytes.length);
            const isLastChunk = chunkEnd === bytes.length;
            const chunkBytes = bytes.slice(chunkStart, chunkEnd);
            const chunk = decoder.decode(chunkBytes, { stream: !isLastChunk });
            const append = offset > 0;
            promise = promise.then(() => callFileWrite(path, chunk, append, mode));
        }

        return promise;
    },

    version: function () {
        return callMomoVersion();
    },

    profile: function (defaults) {
        return callMomoProfile(defaults);
    },

    // 后台更新：避免 rpcd 单线程被 curl 堵住，导致整个 LuCI 无响应。
    // 老后端没有 async 方法时回退到同步调用。
    updateSubscription: function (section_id) {
        return callMomoUpdateSubscriptionAsync(section_id).then(function (res) {
            if (res && res.started) {
                return res;
            }
            return callFailsafe(callMomoUpdateSubscription, section_id);
        }).catch(function () {
            return callFailsafe(callMomoUpdateSubscription, section_id);
        });
    },

    updateStatus: function () {
        return callFailsafe(callMomoUpdateStatus);
    },

    updateDashboard: function () {
        return callMomoAPI('POST', '/upgrade/ui');
    },

    openDashboard: async function () {
        const profile = await callMomoProfile({ 'experimental': { 'clash_api': { 'external_controller': null, 'secret': null } } });
        const apiListen = profile?.['experimental']?.['clash_api']?.['external_controller'];
        const apiSecret = profile?.['experimental']?.['clash_api']?.['secret'] ?? '';
        if (!apiListen) {
            return Promise.reject('Clash API has not been configured');
        }
        const apiPort = apiListen.substring(apiListen.lastIndexOf(':') + 1);
        const params = {
            host: window.location.hostname,
            hostname: window.location.hostname,
            port: apiPort,
            secret: apiSecret
        };
        const query = new URLSearchParams(params).toString();
        const url = `http://${window.location.hostname}:${apiPort}/ui/?${query}`;
        setTimeout(function () { window.open(url, '_blank') }, 0);
        return Promise.resolve();
    },

    getIdentifiers: function () {
        return callMomoGetIdentifiers();
    },

    listProfiles: async function () {
        const paths = await this.getPaths();
        return L.resolveDefault(fs.list(paths.profiles_dir), []);
    },

    getAppLog: async function () {
        const paths = await this.getPaths();
        return L.resolveDefault(fs.read_direct(paths.app_log_path));
    },

    getCoreLog: async function () {
        const paths = await this.getPaths();
        return L.resolveDefault(fs.read_direct(paths.core_log_path));
    },

    clearAppLog: async function () {
        const paths = await this.getPaths();
        return this.writefile(paths.app_log_path);
    },

    clearCoreLog: async function () {
        const paths = await this.getPaths();
        return this.writefile(paths.core_log_path);
    },

    debug: function () {
        return callMomoDebug();
    },
})
