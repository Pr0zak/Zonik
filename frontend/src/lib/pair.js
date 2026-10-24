// Pure helpers for the /pair page (pairing v2).

/** Keep digits only, max 6. Accepts pasted "123 456", "123-456" or a full /pair?code= URL. */
export function normalizeCode(input) {
	let s = String(input ?? '');
	const m = s.match(/[?&]code=(\d+)/);
	if (m) s = m[1];
	return s.replace(/\D/g, '').slice(0, 6);
}

export function isCompleteCode(code) {
	return /^\d{6}$/.test(code || '');
}

/** Seconds left until `expires` (unix seconds, or ISO string), never negative. */
export function secondsLeft(expires, nowMs = Date.now()) {
	if (expires == null || expires === '') return 0;
	const ms = typeof expires === 'number'
		? (expires < 1e12 ? expires * 1000 : expires)
		: Date.parse(expires);
	if (!Number.isFinite(ms)) return 0;
	return Math.max(0, Math.ceil((ms - nowMs) / 1000));
}

/** 125 -> "2:05". */
export function formatCountdown(secs) {
	const s = Math.max(0, Math.floor(secs || 0));
	return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

/** "Living room TV" label with sane fallbacks by platform. */
export function deviceTitle(info) {
	if (info?.label) return info.label;
	return info?.platform === 'tv' ? 'A TV' : 'A device';
}

/** Where the pair page sends an anonymous visitor. */
export function pairNext(code) {
	return isCompleteCode(code) ? `/pair?code=${code}` : '/pair';
}
