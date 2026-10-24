// Auth state and pure helpers. No $app imports so it stays unit-testable; the layout registers
// the navigation side of a 401 through setUnauthorizedHandler().
import { writable, get } from 'svelte/store';

/** The signed-in user (GET /api/auth/me), or null. */
export const currentUser = writable(null);
/** GET /api/auth/status: { needs_setup, enforce, version }, or null until loaded. */
export const authStatus = writable(null);
/** True once the first status + me round trip has finished (the layout waits on this). */
export const authReady = writable(false);

/** Pages that render without the app shell and without a session. */
export const PUBLIC_PATHS = ['/login', '/pair', '/join'];

/** Pages only admins may open. */
export const ADMIN_PATHS = ['/duplicates', '/upgrades', '/tidy', '/schedule', '/visualizer', '/logs', '/settings'];

/** Sidebar entries a plain `user` sees; admins see every entry. */
export const USER_NAV = ['/', '/library', '/favorites', '/stats', '/discover', '/map', '/analysis', '/live', '/downloads', '/playlists'];

const ADMIN_ONLY_PERMS = ['downloads.admin', 'library.manage', 'settings.manage', 'users.manage', 'logs.read'];

function pathMatches(path, base) {
	return path === base || path.startsWith(base + '/');
}

export function isAdmin(user) {
	return !!user && (user.role === 'admin' || user.is_admin === true);
}

/** Permission check against the server-provided list, with a role fallback if it is missing. */
export function can(user, perm) {
	if (!user) return false;
	if (isAdmin(user)) return true;
	if (Array.isArray(user.permissions)) return user.permissions.includes(perm);
	return !ADMIN_ONLY_PERMS.includes(perm);
}

export function isPublicPath(path) {
	return PUBLIC_PATHS.some((p) => pathMatches(path || '', p));
}

export function isAdminPath(path) {
	return ADMIN_PATHS.some((p) => pathMatches(path || '', p));
}

/** Should this sidebar href be shown to the user? */
export function navVisible(user, href) {
	if (isAdmin(user)) return true;
	return USER_NAV.includes(href);
}

/** Only same-site relative paths are valid post-login targets (no open redirects). */
export function safeNext(next) {
	if (typeof next !== 'string' || !next.startsWith('/') || next.startsWith('//') || next.startsWith('/\\')) return '/';
	if (isPublicPath(next.split('?')[0])) return '/';
	return next;
}

export function loginUrl(path = '/') {
	const next = safeNext(path);
	return next === '/' ? '/login' : `/login?next=${encodeURIComponent(next)}`;
}

export function initials(user) {
	const name = (user?.display_name || user?.username || '?').trim();
	return (name[0] || '?').toUpperCase();
}

export function displayName(user) {
	return user?.display_name || user?.username || '';
}

/** Client-side password rule mirroring the server (min 8, not "admin"). Returns an error or ''. */
export function passwordProblem(pw, confirm = null) {
	if (!pw || pw.length < 8) return 'Use at least 8 characters';
	if (pw === 'admin') return 'Choose something other than "admin"';
	if (confirm !== null && pw !== confirm) return 'Passwords do not match';
	return '';
}

// --- network -----------------------------------------------------------------------------

async function call(path, options = {}) {
	const res = await fetch(`/api/auth${path}`, {
		headers: { 'Content-Type': 'application/json' },
		credentials: 'same-origin',
		...options,
	});
	let body = null;
	try { body = await res.json(); } catch {}
	if (!res.ok) {
		const err = new Error(body?.detail || `Request failed (${res.status})`);
		err.status = res.status;
		throw err;
	}
	return body;
}

export async function loadStatus() {
	try {
		const s = await call('/status');
		authStatus.set(s);
		return s;
	} catch {
		return null;
	}
}

/** Fetch /me. Sets and returns the user, or null when not signed in. */
export async function loadMe() {
	try {
		const me = await call('/me');
		currentUser.set(me);
		return me;
	} catch {
		currentUser.set(null);
		return null;
	}
}

export async function login(username, password) {
	const me = await call('/login', { method: 'POST', body: JSON.stringify({ username, password }) });
	currentUser.set(me);
	return me;
}

export async function setupAdmin(username, password, display_name) {
	const body = { username, password };
	if (display_name) body.display_name = display_name;
	const me = await call('/setup', { method: 'POST', body: JSON.stringify(body) });
	currentUser.set(me);
	authStatus.update((s) => (s ? { ...s, needs_setup: false } : s));
	return me;
}

/** Public: check an invite code. Throws (status 404) when invalid/expired/used. */
export function getInvite(code) {
	return call(`/invite/${encodeURIComponent(code)}`);
}

/** Redeem an invite: creates the account and starts a session. */
export async function joinWithInvite({ code, username, display_name, password }) {
	const body = { code, username, password };
	if (display_name) body.display_name = display_name;
	const me = await call('/join', { method: 'POST', body: JSON.stringify(body) });
	currentUser.set(me);
	return me;
}

export async function logout() {
	try { await call('/logout', { method: 'POST' }); } catch {}
	currentUser.set(null);
}

export const authApi = {
	updateMe: (display_name) => call('/me', { method: 'PUT', body: JSON.stringify({ display_name }) }),
	changePassword: (current_password, new_password) =>
		call('/password', { method: 'POST', body: JSON.stringify({ current_password, new_password }) }),
	getDevices: () => call('/devices'),
	revokeDevice: (id) => call(`/devices/${encodeURIComponent(id)}`, { method: 'DELETE' }),
};

// --- 401 handling --------------------------------------------------------------------------

let unauthorizedHandler = null;
export function setUnauthorizedHandler(fn) { unauthorizedHandler = fn; }

/** Called by api.js and the fetch wrapper when an API call came back 401. */
export function notifyUnauthorized() {
	if (get(currentUser) === null && !get(authReady)) return;
	unauthorizedHandler?.();
}

/** Paths a 401 must NOT bounce to the login page (auth endpoints, pairing, log upload). */
export function isAuthExempt(url) {
	let p = String(url || '');
	try { p = new URL(p, 'http://x').pathname; } catch {}
	return p.startsWith('/api/auth/') || p.startsWith('/api/pair') || p === '/api/logs';
}
