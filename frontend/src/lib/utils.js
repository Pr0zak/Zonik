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

/**
 * Parse an ISO timestamp from the API as UTC.
 * Backend stores UTC but .isoformat() omits the Z suffix.
 */
export function parseUTC(iso) {
	if (!iso) return null;
	// If it already ends with Z or has timezone offset, leave it
	if (iso.endsWith('Z') || /[+-]\d{2}:\d{2}$/.test(iso)) return new Date(iso);
	return new Date(iso + 'Z');
}

export function formatDate(iso) {
	if (!iso) return '';
	return parseUTC(iso).toLocaleDateString();
}

export function formatDateTime(iso) {
	if (!iso) return '';
	return parseUTC(iso).toLocaleString();
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

export function formatRelativeTime(iso) {
	if (!iso) return '';
	const diff = Date.now() - parseUTC(iso).getTime();
	if (diff < 0) return 'just now';
	const mins = Math.floor(diff / 60000);
	if (mins < 1) return 'just now';
	if (mins < 60) return `${mins}m ago`;
	const hrs = Math.floor(mins / 60);
	if (hrs < 24) return `${hrs}h ago`;
	const days = Math.floor(hrs / 24);
	if (days < 30) return `${days}d ago`;
	const months = Math.floor(days / 30);
	if (months < 12) return `${months}mo ago`;
	return `${Math.floor(months / 12)}y ago`;
}

export function debounce(fn, ms = 300) {
	let timer;
	return (...args) => {
		clearTimeout(timer);
		timer = setTimeout(() => fn(...args), ms);
	};
}
