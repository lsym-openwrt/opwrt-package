'use strict';
'require form';
'require view';
'require uci';
'require poll';
'require tools.momo as momo';

function renderStatus(running) {
    return updateStatus(E('input', {
        id: 'core_status',
        class: 'mx-status',
        readonly: '',
        'data-state': running ? 'on' : 'off'
    }), running);
}

function updateStatus(element, running) {
    if (element) {
        element.value = running ? _('Running') : _('Not Running');
        element.setAttribute('data-state', running ? 'on' : 'off');
    }
    return element;
}

return view.extend({
    load: function () {
        return Promise.all([
            uci.load('momo'),
            momo.version(),
            momo.status(),
            momo.listProfiles()
        ]);
    },
    render: function (data) {
        const subscriptions = uci.sections('momo', 'subscription');
        const appVersion = data[1].app ?? '';
        const coreVersion = data[1].core ?? '';
        const running = data[2];
        const profiles = data[3];

        let m, s, o;

        m = new form.Map('momo', 'MomoX', '');

        s = m.section(form.NamedSection, 'placeholder', 'placeholder', '');
        s.anonymous = true;

        o = s.option(form.DummyValue, '_head', null);
        o.load = function () {
            return null;
        };
        o.cfgvalue = function () {
            return E('div', { class: 'mx-hero' }, [
                E('div', { class: 'mx-hero-head' }, [
                    E('div', { class: 'mx-hero-title' }, 'MomoX'),
                    renderStatus(running)
                ]),
                E('div', { class: 'mx-hero-sub' },
                    _('OpenWrt-momo 修改版：YAML 配置与订阅，上传即用，开箱即跑。')),
                E('div', { class: 'mx-meta' }, [
                    E('span', {}, ['App ', E('b', {}, [appVersion || '—'])]),
                    E('span', { class: 'mx-sep' }, '·'),
                    E('span', {}, ['Core ', E('b', {}, [coreVersion || '—'])]),
                    E('span', { class: 'mx-sep' }, '·'),
                    E('a', {
                        class: 'mx-link',
                        href: 'https://github.com/nikkinikki-org/OpenWrt-momo/wiki',
                        target: '_blank'
                    }, _('How To Use'))
                ])
            ]);
        };
        poll.add(function () {
            return L.resolveDefault(momo.status()).then(function (running) {
                updateStatus(document.getElementById('core_status'), running);
            });
        });

        o = s.option(form.Button, 'reload');
        o.inputstyle = 'action';
        o.inputtitle = _('Reload Service');
        o.onclick = function () {
            return momo.reload();
        };

        o = s.option(form.Button, 'restart');
        o.inputstyle = 'negative';
        o.inputtitle = _('Restart Service');
        o.onclick = function () {
            return momo.restart();
        };

        o = s.option(form.Button, 'update_dashboard');
        o.inputstyle = 'positive';
        o.inputtitle = _('Update Dashboard');
        o.onclick = function () {
            return momo.updateDashboard();
        };

        o = s.option(form.Button, 'open_dashboard');
        o.inputtitle = _('Open Dashboard');
        o.onclick = function () {
            return momo.openDashboard();
        };

        s = m.section(form.NamedSection, 'config', 'config', _('App Config'));

        o = s.option(form.Flag, 'enabled', _('Enable'));
        o.rmempty = false;

        o = s.option(form.ListValue, 'profile', _('Choose Profile'));
        o.optional = true;

        for (const profile of profiles) {
            o.value('file:' + profile.name, _('File:') + profile.name);
        };

        for (const subscription of subscriptions) {
            o.value('subscription:' + subscription['.name'], _('Subscription:') + subscription.name);
        };

        o = s.option(form.Value, 'start_delay', _('Start Delay'));
        o.datatype = 'uinteger';
        o.placeholder = _('Start Immidiately');

        o = s.option(form.Flag, 'scheduled_restart', _('Scheduled Restart'));
        o.default = '0';
        o.rmempty = false;

        o = s.option(form.Value, 'scheduled_restart_cron', _('Scheduled Restart Cron'));
        o.retain = true;
        o.rmempty = false;
        o.depends('scheduled_restart', '1');

        o = s.option(form.Flag, 'test_profile', _('Test Profile'));
        o.rmempty = false;

        o = s.option(form.Flag, 'core_only', _('Core Only'));
        o.rmempty = false;

        s = m.section(form.NamedSection, 'procd', 'procd', _('procd Config'));

        s.tab('general', _('General Config'));

        o = s.taboption('general', form.Flag, 'fast_reload', _('Fast Reload'));
        o.rmempty = false;

        s.tab('rlimit', _('RLIMIT Config'));

        o = s.taboption('rlimit', form.Value, 'rlimit_nproc_soft', _('Number of Processes Soft Limit'));
        o.datatype = 'uinteger';

        o = s.taboption('rlimit', form.Value, 'rlimit_nproc_hard', _('Number of Processes Hard Limit'));
        o.datatype = 'uinteger';

        o = s.taboption('rlimit', form.Value, 'rlimit_address_space_soft', _('Address Space Size Soft Limit'));
        o.datatype = 'uinteger';
        o.placeholder = _('Unlimited');

        o = s.taboption('rlimit', form.Value, 'rlimit_address_space_hard', _('Address Space Size Hard Limit'));
        o.datatype = 'uinteger';
        o.placeholder = _('Unlimited');

        o = s.taboption('rlimit', form.Value, 'rlimit_data_soft', _('Heap Size Soft Limit'));
        o.datatype = 'uinteger';
        o.placeholder = _('Unlimited');

        o = s.taboption('rlimit', form.Value, 'rlimit_data_hard', _('Heap Size Hard Limit'));
        o.datatype = 'uinteger';
        o.placeholder = _('Unlimited');

        o = s.taboption('rlimit', form.Value, 'rlimit_stack_soft', _('Stack Size Soft Limit'));
        o.datatype = 'uinteger';
        o.placeholder = _('Unlimited');

        o = s.taboption('rlimit', form.Value, 'rlimit_stack_hard', _('Stack Size Hard Limit'));
        o.datatype = 'uinteger';
        o.placeholder = _('Unlimited');

        o = s.taboption('rlimit', form.Value, 'rlimit_nofile_soft', _('Number of Open Files Soft Limit'));
        o.datatype = 'uinteger';

        o = s.taboption('rlimit', form.Value, 'rlimit_nofile_hard', _('Number of Open Files Hard Limit'));
        o.datatype = 'uinteger';

        s.tab('environment_variable', _('Environment Variable Config'));

        o = s.taboption('environment_variable', form.Value, 'env_go_max_procs', 'GOMAXPROCS');
        o.datatype = 'uinteger';
        o.placeholder = _('Unlimited');

        o = s.taboption('environment_variable', form.Value, 'env_go_mem_limit', 'GOMEMLIMIT');
        o.datatype = 'uinteger';
        o.placeholder = _('Unlimited');

        return m.render();
    }
});
