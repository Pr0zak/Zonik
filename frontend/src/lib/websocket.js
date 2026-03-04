import { activeJobs } from './stores.js';

let ws = null;

export function connectWebSocket() {
	const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
	const url = `${protocol}//${location.host}/api/ws`;

	ws = new WebSocket(url);

	ws.onmessage = (event) => {
		try {
			const data = JSON.parse(event.data);
			if (data.type === 'job_update') {
				activeJobs.update(jobs => {
					const idx = jobs.findIndex(j => j.id === data.job.id);
					if (idx >= 0) {
						jobs[idx] = data.job;
					} else {
						jobs.push(data.job);
					}
					return jobs.filter(j => j.status === 'running' || j.status === 'pending');
				});
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
