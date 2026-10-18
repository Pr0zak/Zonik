import { describe, it, expect } from 'vitest';
import {
	SOURCE_LABELS,
	compactSpeed,
	sourceLabel,
	ordinal,
	formatDurationWords,
	clockTime,
	shortDate,
	STAGE_LIMITS,
	resolveStageLimits,
	resolveStage,
	failureClass,
	failureSentence,
	peerErrorClause,
	doneOutcome,
	nextSentence,
	STAGE_COPY,
	stageGroupReason,
	classSentence,
	CLASS_COPY,
	GROUP_OF_STAGE,
	GROUP_OF_CLASS,
	LIVE_GROUP_ORDER,
	LIVE_STAGES,
} from './stage.js';

const NOW = Date.UTC(2026, 9, 18, 7, 12, 30); // 2026-10-18T07:12:30Z
const iso = (msAgo) => new Date(NOW - msAgo).toISOString().replace('Z', ''); // naive UTC like the API
const epoch = (msAgo) => (NOW - msAgo) / 1000; // Transfer.to_dict floats

const LIMITS = {
	transfer_slots: 2, search_slots: 3, peer_connect_s: 20, peer_busy_wait_s: 60,
	peer_queue_s: 120, stall_s: 60,
};

function job(stage, extra = {}, status = 'running') {
	const { tracks: tExtra = {}, ...rest } = extra;
	return {
		id: 'j1', type: 'download', status, card: 'dl:playlist',
		started_at: iso(600_000),
		tracks: JSON.stringify([{ artist: 'A', track: 'T', status: 'downloading', stage, ...tExtra }]),
		...rest,
	};
}

describe('sourceLabel', () => {
	it.each([
		['dl:upgrade', 'Upgrade'],
		['dl:recommendation', 'For You'],
		['dl:weekly-radar', 'Weekly Radar'],
		['dl:radar', 'Radar'],
		['dl:new-releases', 'New Releases'],
		['dl:search', 'Search'],
		['dl:worker', 'Worker'],
		['dl', 'Phone'],
		['dl:library', 'Library'],
		['dl:upgrade_scan', 'Upgrade scan'],
	])('%s -> %s', (card, label) => {
		expect(sourceLabel(card)).toBe(label);
		expect(sourceLabel({ card })).toBe(label);
	});

	it('keeps the original seven', () => {
		for (const k of ['dl:upgrade', 'dl:discovery', 'dl:similar', 'dl:remix', 'dl:recommendation', 'dl:playlist', 'dl:manual']) {
			expect(SOURCE_LABELS[k]).toBeTruthy();
		}
	});

	it('falls back without ever being empty', () => {
		expect(sourceLabel('dl:something-new')).toBe('something-new');
		expect(sourceLabel('custom')).toBe('custom');
		expect(sourceLabel(null)).toBe('Download');
		expect(sourceLabel({})).toBe('Download');
		expect(sourceLabel('dl:')).toBe('Download');
	});
});

describe('ordinal', () => {
	it.each([
		[1, '1st'], [2, '2nd'], [3, '3rd'], [4, '4th'], [11, '11th'], [12, '12th'],
		[13, '13th'], [21, '21st'], [22, '22nd'], [26, '26th'], [101, '101st'], [111, '111th'],
	])('%i -> %s', (n, s) => expect(ordinal(n)).toBe(s));
});

describe('formatDurationWords', () => {
	it.each([
		[0, '0 s'], [48, '48 s'], [185, '3 m 05 s'], [3599, '59 m 59 s'],
		[4380, '1 h 13 m'], [100000, '1 d 3 h'], [12.7, '12 s'],
	])('%s -> %s', (s, out) => expect(formatDurationWords(s)).toBe(out));
	it('is empty for nothing', () => expect(formatDurationWords(null)).toBe(''));
});

describe('stage limits', () => {
	it('defaults', () => expect(resolveStageLimits(null)).toEqual(STAGE_LIMITS));
	it('reads DC-12 limits', () => {
		expect(resolveStageLimits({ peer_connect_s: 30, peer_busy_wait_s: 90, peer_queue_s: 180, stall_s: 45 }))
			.toEqual({ connecting: 30, peer_lock: 90, queued_at_peer: 180, transferring: 45, importing: 10 });
	});
});

describe('resolveStage — live stages', () => {
	const cases = [
		{
			name: 'queue_search (pending, pacer)',
			job: { ...job(null, {}, 'pending'), started_at: iso(40_000) },
			ctx: { pacer: { next_slot_in_s: 6.2 } },
			expect: { stage: 'queue_search', word: 'Waiting to search', colour: 'muted', detail: 'next search opens in 7 s', big: '40 s', amber: false },
		},
		{
			name: 'searching with funnel',
			job: job('searching', { tracks: { stage_since: iso(19_000), search: { query_index: 2, query_total: 4, query: 'michael crawford all i ask of you', files_seen: 14, kept: 0 } } }),
			expect: {
				stage: 'searching', word: 'Searching', colour: 'indigo',
				detail: 'query 2 of 4 “michael crawford all i ask of you” · 14 files seen, 0 kept',
				big: 'query 2 of 4 · 19 s', small: 'then 2 more queries',
			},
		},
		{
			name: 'searching from a WS payload (no query text)',
			job: { ...job(null), stage: 'searching', stage_since: iso(5_000), search: { query_index: 4, query_total: 4, files_seen: 3, kept: 1 } },
			expect: { stage: 'searching', detail: 'query 4 of 4 · 3 files seen, 1 kept', small: 'last query' },
		},
		{
			name: 'peer_lock',
			job: job('peer_lock', { tracks: { stage_since: iso(42_000), username: 'piaga' } }),
			expect: { stage: 'peer_lock', word: 'Waiting for the peer', colour: 'amber', detail: 'another download of yours is using piaga', big: '42 s of 60 s', small: 'then next peer', amber: false, limitS: 60 },
		},
		{
			name: 'waiting_slot',
			job: job('waiting_slot', { tracks: { stage_since: iso(185_000), attempt: 1, of: 5 } }),
			expect: { stage: 'waiting_slot', word: 'Waiting for a slot', detail: 'file picked (1 of 5 peers), both slots busy', big: '3 m 05 s' },
		},
		{
			name: 'connecting',
			job: job('connecting', { tracks: { stage_since: iso(6_000), attempt: 1, of: 2, username: 'celticfiddler' } }),
			expect: { stage: 'connecting', word: 'Connecting', detail: 'direct and relayed', big: '6 s of 20 s', small: 'attempt 1 of 2', amber: false },
		},
		{
			name: 'queued_at_peer with place',
			job: job('queued_at_peer', { tracks: { stage_since: iso(48_000), attempt: 1, of: 4, username: 'DJ-Promo', queue_place: 3 } }),
			expect: { stage: 'queued_at_peer', word: "In DJ-Promo's queue", detail: 'place 3', big: '48 s of 120 s', small: 'attempt 1 of 4', amber: false },
		},
		{
			name: 'queued_at_peer before a place is known',
			job: job('queued_at_peer', { tracks: { stage_since: iso(12_000), username: 'DJ-Promo' } }),
			expect: { word: 'Asked the peer', detail: 'waiting for DJ-Promo to start the upload', big: '12 s of 120 s' },
		},
		{
			name: 'transferring, healthy',
			job: job('transferring', { tracks: { stage_since: iso(20_000), attempt: 1, of: 2, username: 'we@S3l' } }),
			transfer: {
				state: 'transferring', username: 'we@S3l', total_bytes: 41.5 * 1048576, received_bytes: 25.73 * 1048576,
				speed: 2.4 * 1048576, eta_seconds: 11, last_progress_at: epoch(500), state_since: epoch(20_000),
			},
			ctx: { medianSpeed: 2 * 1048576 },
			expect: { stage: 'transferring', word: 'Transferring', colour: 'sky', detail: '25.7 of 41.5 MB', big: '62 % · 2.4 MB/s · 11 s left', small: 'attempt 1 of 2', progress: 62, amber: false },
		},
		{
			name: 'importing',
			job: job('importing', { tracks: { stage_since: iso(2_000) } }),
			expect: { stage: 'importing', word: 'Importing', detail: 'checking tags, duplicates and quality', big: '2 s', small: 'usually under 10 s', amber: false },
		},
	];

	it.each(cases)('$name', (c) => {
		const s = resolveStage(c.job, c.transfer || null, LIMITS, NOW, c.ctx || {});
		expect(s).toMatchObject(c.expect);
	});

	it('turns amber at 75 % of the stage limit', () => {
		const below = resolveStage(job('queued_at_peer', { tracks: { stage_since: iso(89_000), queue_place: 3, username: 'p' } }), null, LIMITS, NOW);
		const at = resolveStage(job('queued_at_peer', { tracks: { stage_since: iso(90_000), queue_place: 3, username: 'p' } }), null, LIMITS, NOW);
		expect(below.amber).toBe(false);
		expect(at.amber).toBe(true);
		const conn = resolveStage(job('connecting', { tracks: { stage_since: iso(16_000) } }), null, LIMITS, NOW);
		expect(conn).toMatchObject({ big: '16 s of 20 s', amber: true });
		const imp = resolveStage(job('importing', { tracks: { stage_since: iso(8_000) } }), null, LIMITS, NOW);
		expect(imp.amber).toBe(true);
	});

	it('uses server limits over defaults', () => {
		const s = resolveStage(job('connecting', { tracks: { stage_since: iso(6_000) } }), null, { peer_connect_s: 30 }, NOW);
		expect(s.big).toBe('6 s of 30 s');
	});

	it('shows a stalled transfer as no data of the stall limit, in amber', () => {
		const s = resolveStage(job('transferring'), {
			state: 'transferring', total_bytes: 38.1 * 1048576, received_bytes: 3.0 * 1048576,
			speed: 0, eta_seconds: null, last_progress_at: epoch(24_000), state_since: epoch(60_000),
		}, LIMITS, NOW);
		expect(s).toMatchObject({ big: 'no data for 24 s of 60 s', amber: true, elapsedS: 24, limitS: 60, progress: 7 });
	});

	it('flags a slow transfer against the median speed', () => {
		const s = resolveStage(job('transferring'), {
			state: 'transferring', username: 'forgottenfrequencies', total_bytes: 38.1 * 1048576, received_bytes: 3.0 * 1048576,
			speed: 310 * 1024, eta_seconds: 113, last_progress_at: epoch(200), state_since: epoch(10_000),
		}, LIMITS, NOW, { medianSpeed: 4 * 1048576 });
		expect(s.detail).toBe('3.0 of 38.1 MB · slow');
		expect(s.big).toBe('7 % · 310 KB/s · 1 m 53 s left');
		expect(s.amber).toBe(false);
	});

	it('does not call a transfer slow without a median', () => {
		const s = resolveStage(job('transferring'), {
			state: 'transferring', total_bytes: 100, received_bytes: 50, speed: 10, last_progress_at: epoch(0),
		}, LIMITS, NOW);
		expect(s.detail).not.toContain('slow');
	});
});

describe('resolveStage — precedence', () => {
	it('job status wins over everything', () => {
		const done = resolveStage(job('transferring', { finished_at: iso(0) }, 'completed'), { state: 'transferring' }, LIMITS, NOW);
		expect(done).toMatchObject({ stage: 'completed', word: 'Done', colour: 'emerald', detail: 'New' });
		const failed = resolveStage(job('queued_at_peer', {
			finished_at: iso(0), failure_class: 'peer',
			result: JSON.stringify({ message: 'All 1 sources failed', source_errors: [{ user: 'x', error: 'Peer never answered in 120 s' }] }),
		}, 'failed'), null, LIMITS, NOW);
		expect(failed).toMatchObject({ stage: 'failed', word: 'Failed', colour: 'rose', detail: '1 peer: x never answered in 120 s' });
	});

	it('falls back to transfer.state when there is no stored stage', () => {
		const base = { ...job(null), started_at: iso(100_000) };
		expect(resolveStage(base, { state: 'requested', state_since: epoch(10_000) }, LIMITS, NOW))
			.toMatchObject({ stage: 'queued_at_peer', big: '10 s of 120 s' });
		expect(resolveStage(base, { state: 'queued', queue_place: 5, username: 'u', state_since: epoch(10_000) }, LIMITS, NOW))
			.toMatchObject({ stage: 'queued_at_peer', word: "In u's queue", detail: 'place 5' });
		expect(resolveStage(base, { state: 'connected', state_since: epoch(3_000) }, LIMITS, NOW).stage).toBe('connecting');
		expect(resolveStage(base, { state: 'transferring', total_bytes: 10, received_bytes: 5, last_progress_at: epoch(0) }, LIMITS, NOW).stage).toBe('transferring');
	});

	it('a live transfer refines a stale stored transfer-phase stage', () => {
		const j = job('connecting', { tracks: { stage_since: iso(30_000) } });
		const s = resolveStage(j, { state: 'transferring', total_bytes: 100, received_bytes: 10, last_progress_at: epoch(0), state_since: epoch(2_000) }, LIMITS, NOW);
		expect(s.stage).toBe('transferring');
		expect(s.elapsedS).toBe(2);
	});

	it('a stored pre-transfer stage beats a transfer entry', () => {
		const j = job('importing', { tracks: { stage_since: iso(1_000) } });
		expect(resolveStage(j, { state: 'transferring' }, LIMITS, NOW).stage).toBe('importing');
	});

	it('pending without a stage is queue_search; running without one is searching', () => {
		expect(resolveStage(job(null, {}, 'pending'), null, LIMITS, NOW).stage).toBe('queue_search');
		const s = resolveStage(job(null), null, LIMITS, NOW);
		expect(s).toMatchObject({ stage: 'searching', word: 'Searching', big: '10 m 00 s' });
	});

	it('elapsed falls back from stage_since to transfer.state_since to started_at', () => {
		const viaTransfer = resolveStage(job('queued_at_peer'), { state: 'queued', state_since: epoch(7_000) }, LIMITS, NOW);
		expect(viaTransfer.elapsedS).toBe(7);
		const viaStarted = resolveStage({ ...job('peer_lock'), started_at: iso(33_000) }, null, LIMITS, NOW);
		expect(viaStarted.elapsedS).toBe(33);
	});
});

describe('failureSentence', () => {
	const failed = (result, extra = {}) => ({
		id: 'f', type: 'download', status: 'failed', card: 'dl:weekly-radar',
		started_at: iso(900_000), finished_at: iso(60_000),
		result: result == null ? null : JSON.stringify(result),
		tracks: JSON.stringify([{ artist: 'A', track: 'T', status: 'failed', ...(extra.t0 || {}) }]),
		...extra,
	});

	it('not_found with a funnel', () => {
		const j = failed({
			message: 'No results for Eddie Valero - Motion After Family',
			search: { queries: [{}, {}, {}, {}, {}], album_query: null, files_seen: 11, kept: 0, rejected: { title: 9, duration: 2, size: 0 } },
		}, { failure_class: 'not_found' });
		expect(failureSentence(j)).toBe('5 queries, 0 files kept · 11 seen, 9 wrong title, 2 wrong length');
	});

	it('not_found with the album query and nothing seen', () => {
		const withAlbum = failed({ message: 'No results for X - Y', search: { queries: [{}, {}, {}, {}], album_query: 'x album', files_seen: 42, kept: 0, rejected: { title: 42 } } }, { failure_class: 'not_found' });
		expect(failureSentence(withAlbum)).toBe('4 queries + album query, 0 files kept · 42 seen, 42 wrong title');
		const none = failed({ message: 'No results for X - Y', search: { queries: [{}], files_seen: 0, kept: 0 } }, { failure_class: 'not_found' });
		expect(failureSentence(none)).toBe('1 query, no files found');
	});

	it('not_found legacy (no funnel)', () => {
		expect(failureSentence(failed({ message: 'No results for X - Y' }))).toBe('No peer shared a file that passed the title, length and quality checks');
	});

	it('peer: every peer, one clause each', () => {
		const j = failed({
			message: 'All 3 sources failed',
			source_errors: [
				{ user: 'DJ-Promo', error: 'Peer queued us (place 7) but did not start in 120 s' },
				{ user: "DJ's Private Club", error: 'Too many files' },
				{ user: 'musicmasterrdjpool', error: 'Peer never answered in 120 s' },
			],
		}, { failure_class: 'peer' });
		expect(failureSentence(j)).toBe(
			"3 peers: DJ-Promo queued us at place 7, then nothing for 120 s · DJ's Private Club refused “Too many files” · musicmasterrdjpool never answered in 120 s",
		);
	});

	it('peer: list items carry source_errors already parsed', () => {
		const j = failed({ message: 'All 1 sources failed' }, {
			failure_class: 'peer',
			source_errors: [{ user: 'lwl', error: 'Connection timeout: TimeoutError()' }],
		});
		expect(failureSentence(j)).toBe('1 peer: lwl could not be reached, direct or relayed');
	});

	it('peer: legacy row with only failed_sources', () => {
		const j = failed({ message: 'All 2 parallel sources failed', last_error: 'No data received', failed_sources: ['a', 'b'] });
		expect(failureClass(j)).toBe('peer');
		expect(failureSentence(j)).toBe('2 peers failed · last: b connected but sent no data');
	});

	it('rejected', () => {
		const withPeers = failed({
			message: 'All 2 sources failed',
			source_errors: [
				{ user: 'kfs86', error: 'Not imported: different song' },
				{ user: 'dblbbr', error: 'Import rejected: empty, truncated, or unreadable' },
			],
		}, { failure_class: 'rejected' });
		expect(failureSentence(withPeers)).toBe(
			"2 peers: kfs86's file was not imported (different song) · dblbbr's file was empty, truncated or unreadable",
		);
		const single = failed({ message: 'Not imported: not better than the library copy', username: 'x' });
		expect(failureClass(single)).toBe('rejected');
		expect(failureSentence(single)).toBe('The file arrived but was not imported (not better than the library copy)');
	});

	it('no_better', () => {
		const j = failed({ message: 'No source better than the current mp3 320kbps for A - T', search: { files_seen: 6 } }, { failure_class: 'no_better' });
		expect(failureSentence(j)).toBe('6 copies found, none better than your mp3 320kbps');
		const legacy = failed({ message: 'No source better than the current file for A - T' });
		expect(failureClass(legacy)).toBe('no_better');
		expect(failureSentence(legacy)).toBe('No source better than your file');
	});

	it('cancelled, with where it was', () => {
		const j = failed({ error: 'Cancelled by user', message: 'Cancelled by user' }, {
			t0: { stage: 'queued_at_peer', username: 'NuagistTurtleize' },
		});
		expect(failureClass(j)).toBe('cancelled');
		expect(failureSentence(j)).toBe(`You cancelled it at ${clockTime(j.finished_at)} while it sat in NuagistTurtleize's queue`);
		const plain = failed({ error: 'Cancelled by user' }, { failure_class: 'cancelled' });
		expect(failureSentence(plain)).toBe(`You cancelled it at ${clockTime(plain.finished_at)}`);
	});

	it('infra', () => {
		const restart = failed({ message: 'Interrupted by restart' });
		expect(failureClass(restart)).toBe('infra');
		expect(failureSentence(restart)).toBe(`Zonik restarted at ${clockTime(restart.finished_at)} and ended it mid-flight · not the track's fault`);
		const outage = failed({ message: 'Soulseek server not connected — try again later' }, { failure_class: 'infra' });
		expect(failureSentence(outage)).toBe(`Soulseek was not connected at ${clockTime(outage.finished_at)} · not the track's fault`);
		const internal = failed({ message: 'Internal error: database is locked' });
		expect(failureSentence(internal)).toContain('internal error');
		expect(failureSentence(internal)).toContain('database is locked');
	});

	it('orphan', () => {
		const j = failed(null, { t0: { stage: 'transferring', username: 'SKYLiGHT_D' } });
		expect(failureClass(j)).toBe('orphan');
		expect(failureSentence(j)).toBe(`Stopped mid-transfer on ${shortDate(j.finished_at)} with no reason recorded (from SKYLiGHT_D)`);
		const bare = failed(null, { finished_at: null, started_at: null });
		expect(failureSentence(bare)).toBe('Stopped with no reason recorded');
	});

	it('server failure_class beats the legacy regexes', () => {
		const j = failed({ message: 'No results for X - Y' }, { failure_class: 'infra' });
		expect(failureClass(j)).toBe('infra');
	});

	it('a WS final payload (error, no result) still classifies', () => {
		const j = { id: 'w', status: 'failed', error: 'No results for A - T' };
		expect(failureClass(j)).toBe('not_found');
		expect(failureClass({ id: 'w', status: 'failed' })).toBe('orphan');
	});

	it('is empty for jobs that did not fail', () => {
		expect(failureSentence({ status: 'completed' })).toBe('');
		expect(failureClass({ status: 'running' })).toBeNull();
	});
});

describe('peerErrorClause', () => {
	it.each([
		['u', 'Peer queued us but did not start in 180 s', 'u queued us, then nothing for 180 s'],
		['u', 'Peer did not respond in time', 'u never answered'],
		['u', 'Queue timeout', 'u queued us, then never started'],
		['u', 'Peer busy with another download', 'u was busy with another of your downloads'],
		['u', 'Incomplete: 43/100', 'u stopped sending at 43 %'],
		['u', 'File not shared.', 'u refused “File not shared”'],
		['unknown', 'boom', 'a peer: boom'],
		['u', '', 'u failed'],
	])('%s / %s', (user, err, out) => expect(peerErrorClause(user, err)).toBe(out));
});

describe('doneOutcome', () => {
	const done = (extra = {}) => ({ status: 'completed', card: 'dl:similar', result: JSON.stringify({ track_id: 't' }), ...extra });
	it('new', () => expect(doneOutcome(done())).toEqual({ kind: 'new', label: 'New', badgeVariant: 'success' }));
	it('already had', () => {
		expect(doneOutcome(done({ already_in_library: true }))).toEqual({ kind: 'already_had', label: 'Already had · file discarded', badgeVariant: 'default' });
		expect(doneOutcome(done({ result: JSON.stringify({ already_in_library: true }) })).kind).toBe('already_had');
		expect(doneOutcome(done({ outcome: 'already_had' })).kind).toBe('already_had');
	});
	it('replaced with the upgrade join', () => {
		const j = done({
			card: 'dl:upgrade', outcome: 'replaced',
			upgrade: { original_format: 'mp3', original_bitrate: 320, upgraded_format: 'flac', upgraded_bitrate: 1002, status: 'completed' },
		});
		expect(doneOutcome(j)).toEqual({ kind: 'replaced', label: 'Replaced · MP3 320 → FLAC', badgeVariant: 'info' });
	});
	it('replaced from the card alone', () => {
		expect(doneOutcome(done({ card: 'dl:upgrade' }))).toEqual({ kind: 'replaced', label: 'Replaced', badgeVariant: 'info' });
	});
	it('server outcome wins', () => expect(doneOutcome(done({ card: 'dl:upgrade', outcome: 'new' })).kind).toBe('new'));
	it('null unless completed', () => expect(doneOutcome({ status: 'failed' })).toBeNull());
});

describe('nextSentence', () => {
	const f = (next) => ({ status: 'failed', next });
	const at = (ms) => new Date(NOW + ms).toISOString().replace('Z', '');
	it.each([
		['retired', { kind: 'retired' }, { text: 'retired for a year', tone: 'rose' }],
		['none', { kind: 'none' }, { text: 'nothing scheduled', tone: 'muted' }],
		['missing', undefined, { text: 'nothing scheduled', tone: 'muted' }],
		['1 day', { kind: 'retry', at: at(86400_000) }, { text: 'retries in 1 day', tone: 'default' }],
		['7 days', { kind: 'retry', at: at(7 * 86400_000 - 3600_000) }, { text: 'retries in 7 days', tone: 'default' }],
		['30 days', { kind: 'retry', at: at(30 * 86400_000) }, { text: 'retries in 30 days', tone: 'default' }],
		['hours', { kind: 'retry', at: at(5 * 3600_000) }, { text: 'retries in 5 hours', tone: 'default' }],
		['overdue', { kind: 'retry', at: at(-60_000) }, { text: 'retries with the next run', tone: 'default' }],
		['retry without time', { kind: 'retry', at: null }, { text: 'retries on its own', tone: 'default' }],
		['scans', { kind: 'scans', attempts: 2, max_attempts: 3 }, { text: '2 of 3 scans', tone: 'default' }],
		['scans exhausted', { kind: 'scans', attempts: 3, max_attempts: 3 }, { text: '3 of 3 scans · upgrade retired', tone: 'rose' }],
	])('%s', (_name, next, out) => expect(nextSentence(f(next), NOW)).toEqual(out));

	it('is empty for non-failed jobs', () => expect(nextSentence({ status: 'completed' }, NOW).text).toBe(''));
});

describe('clockTime', () => {
	it('formats local HH:MM from naive UTC', () => {
		const d = new Date(Date.UTC(2026, 9, 18, 6, 51));
		const expected = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
		expect(clockTime('2026-10-18T06:51:00')).toBe(expected);
		expect(clockTime(null)).toBe('');
	});
});

describe('group copy (R2)', () => {
	const L = { transfer_slots: 2, search_slots: 3, searches_per_minute: 6, search_min_interval_s: 8.0 };

	it('every live stage maps to a group with copy', () => {
		for (const s of LIVE_STAGES) expect(STAGE_COPY[GROUP_OF_STAGE[s]]).toBeTruthy();
		for (const k of LIVE_GROUP_ORDER) expect(STAGE_COPY[k].name).toBeTruthy();
	});

	it('reason clauses read the limits', () => {
		expect(stageGroupReason('transferring', { limits: L, busy: 2 })).toBe('2 of 2 slots busy');
		expect(stageGroupReason('transferring', { limits: { transfer_slots: 3 }, busy: 1 })).toBe('1 of 3 slots busy');
		expect(stageGroupReason('transferring', { count: 1 })).toBe('1 slot busy');
		expect(stageGroupReason('at_peer', {})).toBe('asked, waiting for the upload to start');
		expect(stageGroupReason('searching', {})).toBe('up to 4 queries, then an album query');
		expect(stageGroupReason('waiting_slot', { limits: L })).toBe('file picked, both slots busy');
		expect(stageGroupReason('waiting_slot', { limits: { transfer_slots: 3 } })).toBe('file picked, all 3 slots busy');
		expect(stageGroupReason('queue_search', { limits: L })).toBe('pacer allows 6 searches a minute, 8 s apart');
		expect(stageGroupReason('queue_search', { limits: { searches_per_minute: 10, search_min_interval_s: 4.5 } }))
			.toBe('pacer allows 10 searches a minute, 4.5 s apart');
		expect(stageGroupReason('backlog', { batchKind: 'playlist' })).toBe('the import hands tracks over 4 at a time');
		expect(stageGroupReason('backlog', { batchKind: 'scheduled', handover: 2 })).toBe('the run hands tracks over 2 at a time');
		expect(stageGroupReason('nope')).toBe('');
	});

	it('class sentences and names', () => {
		expect(classSentence('not_found')).toMatch(/^a normal outcome/);
		expect(classSentence('peer')).toBe('a file was found, every peer that had it failed');
		expect(classSentence('cancelled')).toBe(classSentence('infra'));
		expect(classSentence('orphan', { incidentNote: 'x' })).toBe('cancelled, restart or outage · not counted against the track · x');
		expect(classSentence('weird')).toBe('');
		for (const c of ['not_found', 'no_better', 'rejected', 'peer', 'cancelled', 'infra', 'orphan']) {
			expect(CLASS_COPY[c].name).toBeTruthy();
			expect(GROUP_OF_CLASS[c]).toBeTruthy();
		}
	});
});

describe('compactSpeed', () => {
	it('drops the decimal below 1 MB/s and keeps it above', () => {
		expect(compactSpeed(310 * 1024)).toBe('310 KB/s');
		expect(compactSpeed(200)).toBe('1 KB/s');
		expect(compactSpeed(2.4 * 1024 * 1024)).toBe('2.4 MB/s');
		expect(compactSpeed(0)).toBe('');
		expect(compactSpeed(null)).toBe('');
	});
});
