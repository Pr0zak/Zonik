/**
 * Schedule helper functions — shared across Library, Discover, Analysis, Playlists, Settings pages.
 */

export function createScheduleHelpers(getSchedTasks, setSchedTask, addToast) {
	async function toggleSched(name) {
		const t = getSchedTasks()[name];
		if (!t) return;
		const newEnabled = !t.enabled;
		await fetch(`/api/schedule/${name}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled: newEnabled }) });
		setSchedTask(name, { ...t, enabled: newEnabled });
	}

	async function updateSched(name, updates) {
		await fetch(`/api/schedule/${name}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(updates) });
		setSchedTask(name, { ...getSchedTasks()[name], ...updates });
	}

	async function runSched(name) {
		try {
			await fetch(`/api/schedule/${name}/run`, { method: 'POST' });
			addToast('Task started', 'success');
		} catch { addToast('Failed to run task', 'error'); }
	}

	async function toggleAutoDownload(name) {
		const t = getSchedTasks()[name];
		if (!t) return;
		const current = t.config?.auto_download || false;
		const newConfig = { auto_download: !current };
		await fetch(`/api/schedule/${name}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ config: newConfig }) });
		setSchedTask(name, { ...t, config: { ...t.config, ...newConfig } });
	}

	async function updateSchedConfig(name, configUpdates) {
		const t = getSchedTasks()[name];
		if (!t) return;
		const newConfig = { ...t.config, ...configUpdates };
		await fetch(`/api/schedule/${name}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ config: newConfig }) });
		setSchedTask(name, { ...t, config: newConfig });
	}

	return { toggleSched, updateSched, runSched, toggleAutoDownload, updateSchedConfig };
}
