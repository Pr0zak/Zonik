import { writable } from 'svelte/store';

export const sidebarOpen = writable(true);
export const currentTrack = writable(null);
export const isPlaying = writable(false);
export const activeJobs = writable([]);
export const toasts = writable([]);

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
