/**
 * Shared download/poll helpers used by discover page and PlaylistDiscoveryTab.
 */

/**
 * Build a unique key for a track (artist::name or artist::title).
 * @param {object} t - Track object with artist and name/title
 * @param {string} [nameField='name'] - Field name for track title
 * @returns {string}
 */
export function trackKey(t, nameField = 'name') {
	return `${t.artist}::${t[nameField] || ''}`.toLowerCase();
}

/**
 * Trigger a download and poll for completion.
 * @param {object} params
 * @param {string} params.artist
 * @param {string} params.track - Track title
 * @param {string} [params.source='discovery']
 * @param {function} params.onStatus - Called with (key, status) to update status
 * @param {string} params.key - Track status key
 * @param {function} [params.isDestroyed] - Returns true if component unmounted
 * @returns {Promise<void>}
 */
export async function downloadAndPoll({ artist, track, source = 'discovery', onStatus, key, isDestroyed }) {
	onStatus(key, 'downloading');
	try {
		const res = await fetch('/api/download/trigger', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ artist, track, source }),
		});
		const data = await res.json();
		if (data.error) {
			onStatus(key, 'failed');
			return;
		}
		onStatus(key, 'queued');
		await pollJob(data.job_id, key, onStatus, isDestroyed);
	} catch {
		onStatus(key, 'failed');
	}
}

/**
 * Poll a job until terminal state.
 * @param {string} jobId
 * @param {string} key - Track status key
 * @param {function} onStatus - Called with (key, status)
 * @param {function} [isDestroyed] - Returns true if component unmounted
 * @returns {Promise<void>}
 */
export async function pollJob(jobId, key, onStatus, isDestroyed) {
	for (let i = 0; i < 180; i++) {
		if (isDestroyed?.()) return;
		await new Promise(r => setTimeout(r, 2000));
		if (isDestroyed?.()) return;
		try {
			const job = await fetch(`/api/jobs/${jobId}`).then(r => r.json());
			if (job.status === 'completed') { onStatus(key, 'completed'); return; }
			if (job.status === 'failed') { onStatus(key, 'failed'); return; }
		} catch {}
	}
	onStatus(key, 'failed');
}
