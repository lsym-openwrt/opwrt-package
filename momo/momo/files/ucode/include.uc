import { readfile, writefile, popen, stat } from 'fs';

// 路径在进程生命周期内不会变（安装目录固定），首次 fork include.sh 取一次后常驻。
// 这一点很关键：luci.momo 的每个 RPC 都会调 get_paths()，而 rpcd 是单线程事件循环，
// 每次 fork 一个 shell 会让面板轮询把 rpcd 排队堵死，前端表现为 RPCError。
let _paths_cache = null;

export function get_paths() {
	if (_paths_cache) {
		return _paths_cache;
	}

	let result = {};
	const process = popen('. /etc/momo/scripts/include.sh && get_paths 2>/dev/null');
	if (process) {
		try {
			result = json(process);
		} catch (e) {
			result = {};
		}
		process.close();
	}

	// 只在拿到有效结果时缓存：include.sh 缺失这类瞬时故障下次仍可重试
	if (type(result) == 'object' && length(keys(result)) > 0) {
		_paths_cache = result;
	}

	return result;
};

export function uci_bool(obj) {
	return obj == null ? null : obj == '1';
};

export function uci_int(obj) {
	return obj == null ? null : int(obj);
};

export function uci_array(obj) {
	if (obj == null) {
		return [];
	}
	if (type(obj) == 'array') {
		return uniq(obj);
	}
	return [obj];
};

export function merge(target, ...sources) {
	for (let source in sources) {
		for (let key in keys(source)) {
			const target_value = target[key];
			const target_value_type = type(target_value);
			const source_value = source[key];
			const source_value_type = type(source_value);
			if (target_value_type === 'object' && source_value_type === 'object') {
				target[key] = merge(target_value, source_value);
			} else {
				target[key] = source[key];
			}
		}
	}
	return target;
};

export function merge_exists(target, ...sources) {
	for (let source in sources) {
		for (let key in keys(source)) {
			if (exists(target, key)) {
				const target_value = target[key];
				const target_value_type = type(target_value);
				const source_value = source[key];
				const source_value_type = type(source_value);
				if (target_value_type === 'object' && source_value_type === 'object') {
					target[key] = merge_exists(target_value, source_value);
				} else {
					target[key] = source[key];
				}
			}
		}
	}
	return target;
};

export function trim_all(obj) {
	if (obj == null) {
		return null;
	}
	if (type(obj) == 'string') {
		if (length(obj) == 0) {
			return null;
		}
		return obj;
	}
	if (type(obj) == 'array') {
		if (length(obj) == 0) {
			return null;
		}
		return obj;
	}
	if (type(obj) == 'object') {
		const obj_keys = keys(obj);
		for (let key in obj_keys) {
			obj[key] = trim_all(obj[key]);
			if (obj[key] == null) {
				delete obj[key];
			}
		}
		if (length(keys(obj)) == 0) {
			return null;
		}
		return obj;
	}
	return obj;
};

export function get_cgroups_version() {
	return system('mount | grep -q -w "^cgroup"') == 0 ? 1 : 2;
};

export function get_users() {
	return map(split(readfile('/etc/passwd'), '\n'), (x) => split(x, ':')[0]);
};

export function get_groups() {
	return map(split(readfile('/etc/group'), '\n'), (x) => split(x, ':')[0]);
};

export function get_cgroups() {
	const result = [];
	if (get_cgroups_version() == 2) {
		const cgroup_path = '/sys/fs/cgroup/';
		const process = popen(`find ${cgroup_path} -type d -mindepth 1`);
		if (process) {
			for (let line = process.read('line'); length(line); line = process.read('line')) {
				push(result, substr(trim(line), length(cgroup_path)));
			}
		}
	}
	return result;
};

// api() 每次调用都要读一次 config.json 并做 JSON 解析，config.json 动辄几百 KB，
// 面板轮询时这条路径会被反复走。按 mtime 缓存，转换脚本重写文件后自动失效。
let _profile_cache = null;
let _profile_mtime = 0;

export function load_profile() {
	const paths = get_paths();
	if (!paths.run_profile_path) {
		return {};
	}

	let mtime = 0;
	try {
		const st = stat(paths.run_profile_path);
		mtime = st ? st.mtime : 0;
	} catch (e) {
		mtime = 0;
	}

	if (_profile_cache && mtime != 0 && mtime == _profile_mtime) {
		return _profile_cache;
	}

	let result = {};
	try {
		result = json(readfile(paths.run_profile_path));
	} catch (e) {
		// 转换过程中可能读到写了一半的文件，回退到上一份可用配置
		return _profile_cache ?? {};
	}

	if (type(result) == 'object') {
		_profile_cache = result;
		_profile_mtime = mtime;
	}

	return result ?? {};
};

export function save_profile(obj) {
	const paths = get_paths();
	_profile_cache = null;
	return writefile(paths.run_profile_path, obj);
};