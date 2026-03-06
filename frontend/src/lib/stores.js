import { writable, get } from 'svelte/store';

export const sidebarOpen = writable(true);
export const currentTrack = writable(null);
export const isPlaying = writable(false);
export const activeJobs = writable([]);
export const toasts = writable([]);
export const updateAvailable = writable(false);
export const showShortcuts = writable(false);
export const activeTransfers = writable([]);
export const trackQueue = writable([]);
export const queueIndex = writable(-1);
export const discoverTrackStatus = writable({});

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
export function addToast(message, type = 'info', duration = 5000) {
	const id = toastId++;
	toasts.update(t => [...t, { id, message, type }]);
	if (duration > 0) {
		setTimeout(() => {
			toasts.update(t => t.filter(toast => toast.id !== id));
		}, duration);
	}
}
