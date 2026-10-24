import { describe, it, expect } from 'vitest';
import { inviteStatusLabel, inviteStatusTone, usernameProblem, codeFromInput, inviteLink, copyText } from './invites.js';
import { isPublicPath, safeNext } from './auth.js';

describe('invites helpers', () => {
	it('status label/tone', () => {
		expect(inviteStatusLabel('active')).toBe('Active');
		expect(inviteStatusLabel('zzz')).toBe('Unknown');
		expect(inviteStatusTone('revoked')).toBe('error');
	});
	it('usernameProblem', () => {
		expect(usernameProblem('ab')).toBeTruthy();
		expect(usernameProblem('a'.repeat(33))).toBeTruthy();
		expect(usernameProblem('bad name')).toBeTruthy();
		expect(usernameProblem('good.name_1-x')).toBe('');
	});
	it('codeFromInput', () => {
		expect(codeFromInput('https://z.lan/join/abc_DEF-1?x=1')).toBe('abc_DEF-1');
		expect(codeFromInput(' abc ')).toBe('abc');
	});
	it('inviteLink', () => {
		expect(inviteLink({ url: 'http://h/join/x', code: 'x' })).toBe('http://h/join/x');
		expect(inviteLink({ code: 'x' }, 'http://h/')).toBe('http://h/join/x');
	});
	it('copyText without clipboard or element is false', async () => {
		expect(await copyText('x')).toBe(false);
	});
	it('/join is public', () => {
		expect(isPublicPath('/join/abc')).toBe(true);
		expect(safeNext('/join/abc')).toBe('/');
	});
});
