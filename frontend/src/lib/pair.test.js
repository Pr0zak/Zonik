import { describe, it, expect } from 'vitest';
import { normalizeCode, isCompleteCode, secondsLeft, formatCountdown, deviceTitle, pairNext } from './pair.js';
import { isPublicPath, loginUrl, safeNext } from './auth.js';

describe('pair helpers', () => {
	it('normalizeCode', () => {
		expect(normalizeCode('123 456')).toBe('123456');
		expect(normalizeCode('12-34-56789')).toBe('123456');
		expect(normalizeCode('https://x/pair?code=654321')).toBe('654321');
		expect(normalizeCode(null)).toBe('');
	});
	it('isCompleteCode', () => {
		expect(isCompleteCode('123456')).toBe(true);
		expect(isCompleteCode('12345')).toBe(false);
	});
	it('secondsLeft', () => {
		expect(secondsLeft(1100, 1000 * 1000)).toBe(100);
		expect(secondsLeft(900, 1000 * 1000)).toBe(0);
		expect(secondsLeft(new Date(1000500).toISOString(), 1000000)).toBe(1);
		expect(secondsLeft(null)).toBe(0);
		expect(secondsLeft('junk')).toBe(0);
	});
	it('formatCountdown', () => {
		expect(formatCountdown(125)).toBe('2:05');
		expect(formatCountdown(-3)).toBe('0:00');
	});
	it('deviceTitle', () => {
		expect(deviceTitle({ label: 'Living room TV' })).toBe('Living room TV');
		expect(deviceTitle({ platform: 'tv' })).toBe('A TV');
		expect(deviceTitle(null)).toBe('A device');
	});
	it('login redirect keeps the code', () => {
		expect(isPublicPath('/pair')).toBe(false);
		expect(safeNext(pairNext('123456'))).toBe('/pair?code=123456');
		expect(loginUrl('/pair?code=123456')).toBe('/login?next=' + encodeURIComponent('/pair?code=123456'));
	});
});
