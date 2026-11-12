'use strict';
'require form';
'require view';
'require uci';
'require tools.momo as momo';

return view.extend({
    load: function () {
        return Promise.all([
            uci.load('momo'),
            momo.getPaths(),
        ]);
    },
    render: function (data) {
        const paths = data[1];

        let m, s, o, so;

        m = new form.Map('momo', _('配置'),
            _('上传本地 YAML 文件，或维护远程订阅地址。更新后会自动重新转换。'));

        s = m.section(form.NamedSection, 'config', 'config', _('Profile'));

        o = s.option(form.FileUpload, '_upload_profile', _('Upload Profile'));
        o.browser = true;
        o.enable_download = true;
        o.root_directory = paths.profiles_dir;
        o.write = function (section_id, formvalue) {
            return true;
        };

        s = m.section(form.GridSection, 'subscription', _('Subscription'));
        s.addremove = true;
        s.anonymous = true;
        s.sortable = true;
        s.modaltitle = _('Edit Subscription');

        o = s.option(form.Value, 'name', _('Subscription Name'));
        o.rmempty = false;

        o = s.option(form.Value, 'used', _('Used'));
        o.modalonly = false;
        o.optional = true;
        o.readonly = true;

        o = s.option(form.Value, 'total', _('Total'));
        o.modalonly = false;
        o.optional = true;
        o.readonly = true;

        o = s.option(form.Value, 'expire', _('Expire At'));
        o.modalonly = false;
        o.optional = true;
        o.readonly = true;

        o = s.option(form.Value, 'update', _('Update At'));
        o.modalonly = false;
        o.optional = true;
        o.readonly = true;

        o = s.option(form.Button, 'update_subscription');
        o.editable = true;
        o.inputstyle = 'positive';
        o.inputtitle = _('Update');
        o.modalonly = false;
        o.onclick = function (_, section_id) {
            // 后台更新 + 轮询：请求立即返回，页面不会因为订阅域名超时而卡死
            const startTs = Math.floor(Date.now() / 1000);
            return momo.updateSubscription(section_id).then(function (res) {
                if (!res || !res.started) {
                    return;
                }
                let waited = 0;
                const poll = function () {
                    return momo.updateStatus().then(function (st) {
                        if (st && st.state == 'done' && st.section == section_id
                            && Number(st.since || 0) >= startTs) {
                            return st;
                        }
                        waited += 1500;
                        if (waited >= 90000) {
                            return null;
                        }
                        return new Promise(function (resolve) {
                            window.setTimeout(resolve, 1500);
                        }).then(poll);
                    });
                };
                return poll().then(function (st) {
                    if (st && st.success == 1) {
                        window.location.reload();
                    }
                });
            });
        };

        o = s.option(form.Value, 'info_url', _('Subscription Info Url'));
        o.modalonly = true;

        o = s.option(form.Value, 'url', _('Subscription Url'));
        o.modalonly = true;
        o.rmempty = false;

        // 机场按 UA 决定下发哪种格式，选错会拿到 HTML 报错页或格式对不上的订阅
        o = s.option(form.Value, 'user_agent', _('User Agent'));
        o.description = _('Airports serve different formats per User-Agent. Auto tries Clash.Meta, sing-box, v2rayN, Shadowrocket, PassWall in order; a pinned UA is tried first and falls back to that chain if it fails.');
        o.default = 'auto';
        o.modalonly = true;
        o.rmempty = false;
        o.value('auto', _('Auto (recommended)'));
        o.value('clash.meta', 'Clash.Meta (YAML)');
        o.value('mihomo', 'mihomo (YAML)');
        o.value('sing-box', 'sing-box (JSON)');
        o.value('v2rayN/6.31', 'v2rayN (base64)');
        o.value('Shadowrocket/2.2.16', 'Shadowrocket (URI)');
        o.value('PassWall', 'PassWall (URI)');

        o = s.option(form.ListValue, 'prefer', _('Prefer'));
        o.default = 'remote';
        o.modalonly = true;
        o.value('remote', _('Remote'));
        o.value('local', _('Local'));

        return m.render();
    }
});
