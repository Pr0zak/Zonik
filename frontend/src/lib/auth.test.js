import { describe, it, expect } from 'vitest';
import { can, isAdmin, isAdminPath, isPublicPath, navVisible, safeNext, loginUrl, initials, passwordProblem, isAuthExempt } from './auth.js';

const admin = { role: 'admin', is_admin: true, permissions: ['downloads.admin'] };
const user = { role: 'user', is_admin: false, permissions: ['library.read', 'play', 'downloads.use'] };

describe('can', () => {
	it('admin can everything', () => expect(can(admin, 'users.manage')).toBe(true));
	it('user only listed perms', () => {
		expect(can(user, 'play')).toBe(true);
		expect(can(user, 'downloads.admin')).toBe(false);
	});
	it('no user, no perms', () => expect(can(null, 'play')).toBe(false));
	it('falls back to role when permissions missing', () => {
		expect(can({ role: 'user' }, 'downloads.admin')).toBe(false);
		expect(can({ role: 'user' }, 'play')).toBe(true);
	});
	it('isAdmin', () => { expect(isAdmin(admin)).toBe(true); expect(isAdmin(user)).toBe(false); });
});

describe('paths', () => {
	it('admin paths', () => {
		expect(isAdminPath('/settings')).toBe(true);
		expect(isAdminPath('/logs/x')).toBe(true);
		expect(isAdminPath('/library')).toBe(false);
		expect(isAdminPath('/settingsfoo')).toBe(false);
	});
	it('public paths', () => {
		expect(isPublicPath('/login')).toBe(true);
		expect(isPublicPath('/pair')).toBe(true);
		expect(isPublicPath('/')).toBe(false);
	});
	it('nav visibility', () => {
		expect(navVisible(user, '/downloads')).toBe(true);
		expect(navVisible(user, '/logs')).toBe(false);
		expect(navVisible(admin, '/logs')).toBe(true);
	});
});

describe('next / login url', () => {
	it('rejects open redirects', () => {
		expect(safeNext('//evil.com')).toBe('/');
		expect(safeNext('https://evil.com')).toBe('/');
		expect(safeNext('/\\evil')).toBe('/');
		expect(safeNext(null)).toBe('/');
		expect(safeNext('/login')).toBe('/');
	});
	it('keeps local paths', () => expect(safeNext('/library?q=a')).toBe('/library?q=a'));
	it('loginUrl', () => {
		expect(loginUrl('/')).toBe('/login');
		expect(loginUrl('/library?q=a')).toBe('/login?next=' + encodeURIComponent('/library?q=a'));
	});
});

describe('misc', () => {
	it('initials', () => {
		expect(initials({ username: 'zak' })).toBe('Z');
		expect(initials({ username: 'zak', display_name: 'amy' })).toBe('A');
		expect(initials(null)).toBe('?');
	});
	it('passwordProblem', () => {
		expect(passwordProblem('short')).toBeTruthy();
		expect(passwordProblem('admin')).toBeTruthy();
		expect(passwordProblem('longenough', 'different')).toBeTruthy();
		expect(passwordProblem('longenough', 'longenough')).toBe('');
	});
	it('auth exempt', () => {
		expect(isAuthExempt('/api/auth/login')).toBe(true);
		expect(isAuthExempt('/api/pair/123456/submit')).toBe(true);
		expect(isAuthExempt('/api/tracks')).toBe(false);
	});
});
