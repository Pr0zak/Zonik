import { writable, get } from 'svelte/store';

export const sidebarOpen = writable(true);
export const currentTrack = writable(null);
export const isPlaying = writable(false);
export const activeJobs = writable([]);
export const toasts = writable([]);
export const updateAvailable = writable(false);
export const showShortcuts = writable(false);
export const activeTransfers = writable([]);
// Uploads we are serving to Soulseek peers (WebSocket `upload_progress`, kept apart from downloads).
export const activeUploads = writable([]);
// Live state of the /api/ws socket, written by lib/websocket.js. `lastMessageAt` is the
// Date.now() of the last frame of any type (pings included); `reconnects` counts re-opens
// after the first successful connect.
export const wsState = writable({ connected: false, reconnecting: false, lastMessageAt: 0, reconnects: 0 });
export const trackQueue = writable([]);
export const queueIndex = writable(-1);
export const discoverTrackStatus = writable({});
export const isMobile = writable(false);

export function playTrack(track, queue = null) {
	currentTrack.set(track);
	if (queue && queue.length > 0) {
		trackQueue.set(queue);
		const idx = queue.findIndex(t => t.id === track.id);
		queueIndex.set(idx >= 0 ? idx : 0);
	} else {
		trackQueue.set([track]);
		queueIndex.set(0);
	}
}

export function playNext() {
	const q = get(trackQueue);
	const idx = get(queueIndex);
	if (q.length > 0 && idx < q.length - 1) {
		const next = idx + 1;
		queueIndex.set(next);
		currentTrack.set(q[next]);
	}
}

export function playPrev() {
	const q = get(trackQueue);
	const idx = get(queueIndex);
	if (q.length > 0 && idx > 0) {
		const prev = idx - 1;
		queueIndex.set(prev);
		currentTrack.set(q[prev]);
	}
}

let toastId = 0;
/**
 * Show a toast. `extra` (optional) adds a link: `{ href, label }`, e.g.
 * `{ href: '/library?track=…', label: 'Open track' }`. Positional args are unchanged.
 */
export function addToast(message, type = 'info', duration = 5000, extra = null) {
	const id = toastId++;
	toasts.update(t => [...t, { id, message, type, extra: extra && extra.href ? extra : null }]);
	if (duration > 0) {
		setTimeout(() => {
			toasts.update(t => t.filter(toast => toast.id !== id));
		}, duration);
	}
}

export function dismissToast(id) {
	toasts.update(t => t.filter(toast => toast.id !== id));
}
