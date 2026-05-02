import { activeJobs, activeTransfers } from './stores.js';

let ws = null;
let reconnectDelay = 1000;
const MAX_RECONNECT_DELAY = 30000;
const _jobListeners = new Set();

export function onJobUpdate(callback) {
	_jobListeners.add(callback);
	return () => _jobListeners.delete(callback);
}

// Mirror transfer bytes onto the matching job row so any UI reading job.progress / job.total
// (TopBar bell, sidebar pulse, dashboard activity) reflects real download progress.
// The backend updates Job.progress=received_bytes / Job.total=total_bytes on each throttled
// transfer tick — this just keeps client state in sync between job_update broadcasts.
function syncJobsFromTransfers(transfers) {
	if (!transfers?.length) return;
	const byId = new Map();
	for (const t of transfers) {
		if (t.job_id && t.total_bytes > 0) byId.set(t.job_id, t);
	}
	if (!byId.size) return;
	activeJobs.update(jobs => {
		let dirty = false;
		for (const j of jobs) {
			const t = byId.get(j.id);
			if (!t) continue;
			if (j.progress !== t.received_bytes || j.total !== t.total_bytes) {
				j.progress = t.received_bytes;
				j.total = t.total_bytes;
				dirty = true;
			}
		}
		return dirty ? [...jobs] : jobs;
	});
}

export function connectWebSocket() {
	const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
	const url = `${protocol}//${location.host}/api/ws`;

	ws = new WebSocket(url);

	ws.onopen = () => {
		reconnectDelay = 1000;
	};

	ws.onmessage = (event) => {
		try {
			const data = JSON.parse(event.data);
			if (data.type === 'transfer_progress') {
				const transfers = data.transfers || [];
				activeTransfers.set(transfers);
				syncJobsFromTransfers(transfers);
			} else if (data.type === 'job_update') {
				const job = data.job;
				activeJobs.update(jobs => {
					const idx = jobs.findIndex(j => j.id === job.id);
					if (idx >= 0) {
						jobs[idx] = job;
					} else {
						jobs.push(job);
					}
					return jobs.filter(j => j.status === 'running' || j.status === 'pending');
				});
				for (const cb of _jobListeners) {
					try { cb(job); } catch {}
				}
			}
		} catch (e) {
			console.error('WebSocket message parse error:', e);
		}
	};

	ws.onclose = () => {
		setTimeout(connectWebSocket, reconnectDelay);
		reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY);
	};
}

export function disconnectWebSocket() {
	if (ws) ws.close();
}
