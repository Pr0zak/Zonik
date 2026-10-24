// Pure helpers for invite links (P3). No imports so they stay unit-testable.

export const EXPIRY_OPTIONS = [1, 7, 14, 30];

const STATUS_LABELS = { active: 'Active', used: 'Used', expired: 'Expired', revoked: 'Revoked' };

export function inviteStatusLabel(status) {
	return STATUS_LABELS[status] || 'Unknown';
}

/** Badge variant for an invite status. */
export function inviteStatusTone(status) {
	return { active: 'success', used: 'default', expired: 'warning', revoked: 'error' }[status] || 'default';
}

/** Mirror of the server username rule: 3-32 chars of [A-Za-z0-9_.-]. Returns an error or ''. */
export function usernameProblem(name) {
	const n = (name || '').trim();
	if (n.length < 3) return 'Username must be at least 3 characters';
	if (n.length > 32) return 'Username must be 32 characters or fewer';
	if (!/^[A-Za-z0-9_.-]+$/.test(n)) return 'Use only letters, numbers, dots, dashes and underscores';
	return '';
}

/** Pull the invite code out of a pasted link or bare code. */
export function codeFromInput(text) {
	const t = (text || '').trim();
	const m = t.match(/\/join\/([^/?#\s]+)/);
	return m ? decodeURIComponent(m[1]) : t;
}

/** Absolute invite link; prefers the server-provided url. */
export function inviteLink(invite, origin = '') {
	if (invite?.url) return invite.url;
	return `${origin.replace(/\/+$/, '')}/join/${invite?.code ?? ''}`;
}

/** Copy text; falls back to selecting `fallbackEl` (input) and execCommand. Returns true if copied. */
export async function copyText(text, fallbackEl = null) {
	try {
		if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
			await navigator.clipboard.writeText(text);
			return true;
		}
	} catch {}
	if (fallbackEl && typeof fallbackEl.select === 'function') {
		try {
			fallbackEl.focus();
			fallbackEl.select();
			fallbackEl.setSelectionRange?.(0, text.length);
			if (typeof document !== 'undefined' && document.execCommand?.('copy')) return true;
		} catch {}
	}
	return false;
}
