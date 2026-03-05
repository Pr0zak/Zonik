export function formatDuration(seconds) {
	if (!seconds) return '0:00';
	const m = Math.floor(seconds / 60);
	const s = Math.floor(seconds % 60);
	return `${m}:${s.toString().padStart(2, '0')}`;
}

export function formatSize(bytes) {
	if (!bytes) return '0 B';
	const units = ['B', 'KB', 'MB', 'GB'];
	let i = 0;
	let size = bytes;
	while (size >= 1024 && i < units.length - 1) {
		size /= 1024;
		i++;
	}
	return `${size.toFixed(1)} ${units[i]}`;
}

export function formatDate(iso) {
	if (!iso) return '';
	return new Date(iso).toLocaleDateString();
}

export function formatSpeed(bytesPerSec) {
	if (!bytesPerSec || bytesPerSec <= 0) return '';
	const units = ['B/s', 'KB/s', 'MB/s', 'GB/s'];
	let i = 0;
	let speed = bytesPerSec;
	while (speed >= 1024 && i < units.length - 1) {
		speed /= 1024;
		i++;
	}
	return `${speed.toFixed(1)} ${units[i]}`;
}

export function formatETA(seconds) {
	if (seconds == null || seconds <= 0) return '';
	if (seconds < 60) return `${Math.round(seconds)}s`;
	if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
	return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

export const inputClass = 'w-full bg-[var(--bg-primary)] border border-[var(--border-interactive)] rounded-md px-3 py-1.5 text-sm text-[var(--text-body)] placeholder-[var(--text-disabled)] focus:outline-none focus:ring-1 focus:border-[var(--color-accent)]/50 focus:ring-[var(--color-accent)]/20';

export function debounce(fn, ms = 300) {
	let timer;
	return (...args) => {
		clearTimeout(timer);
		timer = setTimeout(() => fn(...args), ms);
	};
}
