import { activeJobs, activeTransfers } from './stores.js';

let ws = null;
const _jobListeners = new Set();

export function onJobUpdate(callback) {
	_jobListeners.add(callback);
	return () => _jobListeners.delete(callback);
}

export function connectWebSocket() {
	const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
	const url = `${protocol}//${location.host}/api/ws`;

	ws = new WebSocket(url);

	ws.onmessage = (event) => {
		try {
			const data = JSON.parse(event.data);
			if (data.type === 'transfer_progress') {
				activeTransfers.set(data.transfers || []);
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
		setTimeout(connectWebSocket, 3000);
	};
}

export function disconnectWebSocket() {
	if (ws) ws.close();
}
