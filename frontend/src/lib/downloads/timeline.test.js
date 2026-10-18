import { describe, it, expect } from 'vitest';
import {
	clockSeconds,
	durationPhrase,
	timelineSentences,
	funnelSegments,
	candidateLines,
	peerSentences,
	scheduleSentence,
	stateSentence,
	pickedCandidates,
	liveQueries,
} from './timeline.js';

// Local wall-clock times -> naive UTC ISO like the API, so clockSeconds() reads them back.
const at = (h, m, s = 0) => new Date(2026, 9, 18, h, m, s).toISOString().replace('Z', '');
const ms = (h, m, s = 0) => new Date(2026, 9, 18, h, m, s).getTime();

const LIMITS = {
	transfer_slots: 2, search_slots: 3, searches_per_minute: 6, search_min_interval_s: 8,
	peer_connect_s: 20, peer_busy_wait_s: 60, peer_queue_s: 120, stall_s: 60,
	backoff_days: [1, 7, 30], retired_days: 365,
};

// The busy mockup's drawer story (final-B/busy.png): Sarah Brightman — Think of Me.
const SARAH_CANDIDATES = [
	{ username: 'DJ-Promo', filename: '03 - Think of Me.flac', extension: 'flac', size: 30828134, bitRate: null, slots_free: true, queue_length: 0, avg_speed: 1153434, duration: 221, score: 58 },
	{ username: 'dblbbr', filename: 'Think of Me.flac', extension: 'flac', size: 30303437, bitRate: null, slots_free: true, queue_length: 0, avg_speed: 900000, duration: 221, score: 54 },
	{ username: 'kfs86', filename: 'Think of Me.flac', extension: 'flac', size: 30513152, bitRate: null, slots_free: false, queue_length: 4, avg_speed: 700000, duration: 221, score: 50 },
	{ username: 'lwl', filename: 'Think of Me.mp3', extension: 'mp3', size: 9646899, bitRate: 320, slots_free: false, queue_length: 0, avg_speed: 0, duration: 221, score: 30 },
];

const SARAH_LOG = [
	{ t: at(7, 3, 10), k: 'submitted', card: 'dl:playlist', source: 'playlist', batch: { id: 'b1', label: 'Phantom of the Opera (2026 Mix)', kind: 'playlist' } },
	{ t: at(7, 4, 30), k: 'search_slot', waited_s: 80 },
	{ t: at(7, 4, 30), k: 'query_start', i: 1, n: 4, q: 'Sarah Brightman Think of Me', kind: 'variant' },
	{ t: at(7, 4, 58), k: 'query_end', i: 1, n: 4, q: 'Sarah Brightman Think of Me', kind: 'variant', peers: 11, files: 23 },
	{
		t: at(7, 5, 2), k: 'searched',
		funnel: {
			queries: [{ q: 'Sarah Brightman Think of Me', kind: 'variant', peers: 11, files: 23 }], album_query: null,
			peers_seen: 11, files_seen: 23, rejected: { size: 2, ext: 0, quality: 0, title: 12, duration: 5, score: 0, artist_path: 0 },
			kept: 4, wanted_duration: 221, strict: false,
		},
	},
	{ t: at(7, 5, 2), k: 'picked', candidates: SARAH_CANDIDATES },
	{ t: at(7, 5, 2), k: 'attempt', i: 1, of: 4, user: 'DJ-Promo', filename: '03 - Think of Me.flac', size: 30828134, ext: 'flac' },
	{ t: at(7, 5, 2), k: 'peer_lock', user: 'DJ-Promo' },
	{ t: at(7, 11, 8), k: 'transfer_slot', waited_s: 366 },
	{ t: at(7, 11, 8), k: 'connecting', user: 'DJ-Promo' },
	{ t: at(7, 11, 8), k: 'requested', user: 'DJ-Promo' },
	{ t: at(7, 11, 10), k: 'queued', user: 'DJ-Promo', place: 5 },
];

const SARAH_JOB = {
	id: 'j-sarah', type: 'download', status: 'running', card: 'dl:playlist', started_at: at(7, 3, 10),
	tracks: JSON.stringify([{
		artist: 'Sarah Brightman', track: 'Think of Me', status: 'downloading', stage: 'queued_at_peer',
		stage_since: at(7, 11, 10), attempt: 1, of: 4, username: 'DJ-Promo', queue_place: 3,
	}]),
	candidates: SARAH_CANDIDATES,
};

describe('small formatters', () => {
	it('durationPhrase', () => {
		expect(durationPhrase(40)).toBe('40 s');
		expect(durationPhrase(80)).toBe('1 min 20 s');
		expect(durationPhrase(366)).toBe('6 min 6 s');
		expect(durationPhrase(120)).toBe('2 min');
		expect(durationPhrase(3900)).toBe('1 h 5 min');
	});
	it('clockSeconds reads naive UTC as local time', () => {
		expect(clockSeconds(at(7, 3, 10))).toBe('07:03:10');
		expect(clockSeconds(null)).toBe('');
	});
});

describe('timelineSentences — the busy mockup story', () => {
	const rows = timelineSentences(SARAH_LOG, SARAH_JOB, ms(7, 11, 58), { limits: LIMITS });

	it('tells it in order, one sentence per beat', () => {
		expect(rows.map((r) => r.text)).toEqual([
			'Submitted by the playlist import.',
			'Waited 1 min 20 s for a search slot.',
			'Searched “Sarah Brightman Think of Me”: 23 files from 11 peers. Kept 4; rejected 12 by title, 5 by length, 2 too small.',
			"Picked DJ-Promo's FLAC, 29.4 MB (free slot, 1.1 MB/s on average). Waited 6 min 6 s for a transfer slot.",
			'Asked DJ-Promo for the file. They queued us at place 5.',
			'Place 3. 48 s in their queue so far.',
		]);
	});

	it('stamps local clock times and marks only the live row as now', () => {
		expect(rows[0].time).toBe('07:03:10');
		expect(rows[4].time).toBe('07:11:08');
		expect(rows.filter((r) => r.isNow)).toHaveLength(1);
		expect(rows[rows.length - 1]).toMatchObject({ isNow: true, time: '07:11:58', colour: 'amber' });
	});

	it('the live row follows the transfer when one is attached', () => {
		const t = { state: 'transferring', username: 'DJ-Promo', total_bytes: 1000, received_bytes: 620, speed: 2516582, eta_seconds: 11, last_progress_at: ms(7, 11, 58) / 1000, state_since: ms(7, 11, 40) / 1000 };
		const job = { ...SARAH_JOB, tracks: SARAH_JOB.tracks.replace('queued_at_peer', 'transferring') };
		const last = timelineSentences(SARAH_LOG, job, ms(7, 11, 58), { transfer: t }).at(-1);
		expect(last.text).toBe('62 % received, 2.4 MB/s, about 11 s left.');
		expect(last.colour).toBe('sky');
	});
});

describe('timelineSentences — edge cases', () => {
	it('null, legacy and string logs', () => {
		expect(timelineSentences(null, SARAH_JOB)).toEqual([]);
		expect(timelineSentences('not json', SARAH_JOB)).toEqual([]);
		// another job type's log: a list of strings
		expect(timelineSentences(JSON.stringify(['Scanning…', 'Done']), SARAH_JOB)).toEqual([]);
		expect(timelineSentences(JSON.stringify(SARAH_LOG.slice(0, 2)), { status: 'failed' }).map((r) => r.text)).toEqual([
			'Submitted by the playlist import.',
			'Waited 1 min 20 s for a search slot.',
		]);
	});

	it('a not-found run over several queries ends on the ledger', () => {
		const log = [
			{ t: at(4, 13, 8), k: 'submitted', card: 'dl:similar', source: 'similar' },
			{ t: at(4, 13, 9), k: 'search_slot', waited_s: 40 },
			{ t: at(4, 13, 49), k: 'query_start', i: 1, n: 4, q: 'aespa Lemonade', kind: 'variant' },
			{
				t: at(4, 15, 17), k: 'searched',
				funnel: {
					queries: [
						{ q: 'aespa Lemonade', kind: 'variant', peers: 9, files: 14 },
						{ q: 'aespa lemonade', kind: 'variant', peers: 5, files: 9 },
						{ q: 'aespa Lemon', kind: 'variant', peers: 3, files: 4 },
						{ q: 'Lemonade', kind: 'variant', peers: 0, files: 0 },
						{ q: 'aespa Armageddon', kind: 'album', peers: 0, files: 0 },
					],
					album_query: 'aespa Armageddon', peers_seen: 14, files_seen: 27,
					rejected: { size: 2, ext: 0, quality: 0, title: 21, duration: 4, score: 0, artist_path: 0 }, kept: 0,
					wanted_duration: 191, strict: true,
				},
			},
			{ t: at(4, 15, 17), k: 'picked', candidates: [] },
			{ t: at(4, 15, 18), k: 'failed', error: 'No results for aespa - Lemonade', class: 'not_found' },
		];
		const job = {
			status: 'failed', card: 'dl:similar', failure_class: 'not_found',
			ledger: { attempts: 9, next_retry_at: '2026-11-17T04:15:18' },
			next: { kind: 'retry', at: '2026-11-17T04:15:18', attempts: 9, max_attempts: null },
		};
		const rows = timelineSentences(log, job, Date.UTC(2026, 9, 18, 4, 15, 18));
		expect(rows.map((r) => r.text)).toEqual([
			'Submitted by the Similar run.',
			'Waited 40 s for a search slot.',
			'Searched 5 ways over 1 min 28 s: 27 files from 14 peers. Nothing kept; rejected 21 by title, 4 by length, 2 too small.',
			'Gave up: not found. Written to the retry ledger, 9th failure, next try in 30 days.',
		]);
		expect(rows.at(-1).isNow).toBe(true);
		expect(rows.at(-1).colour).toBe('muted');
	});

	it('peers that failed one after the other', () => {
		const log = [
			{ t: at(3, 41, 10), k: 'submitted', card: 'dl:weekly-radar', batch: { id: 's1', label: 'Weekly Radar', kind: 'scheduled' } },
			{ t: at(3, 43, 40), k: 'attempt', i: 1, of: 3, user: 'DJ-Promo', filename: 'x.flac', size: 42991616, ext: 'flac' },
			{ t: at(3, 44, 12), k: 'requested', user: 'DJ-Promo' },
			{ t: at(3, 44, 14), k: 'queued', user: 'DJ-Promo', place: 7 },
			{ t: at(3, 46, 14), k: 'peer_failed', user: 'DJ-Promo', error: 'Peer queued us (place 7) but did not start in 120 s' },
			{ t: at(3, 46, 24), k: 'attempt', i: 2, of: 3, user: "DJ's Private Club", filename: 'x.flac', size: 41943040, ext: 'flac' },
			{ t: at(3, 46, 26), k: 'peer_failed', user: "DJ's Private Club", error: 'Too many files' },
			{ t: at(3, 48, 36), k: 'failed', error: 'All 2 sources failed', class: 'peer' },
		];
		const texts = timelineSentences(log, { status: 'failed', failure_class: 'peer', next: { kind: 'retry', at: null } }, ms(3, 50)).map((r) => r.text);
		expect(texts).toEqual([
			'Submitted by the Weekly Radar run.',
			"Picked DJ-Promo's FLAC, 41.0 MB.",
			'Asked DJ-Promo for the file. They queued us at place 7.',
			'DJ-Promo queued us at place 7, then nothing for 120 s.',
			"Moved on to the 2nd of 3 peers: DJ's Private Club's FLAC, 40.0 MB.",
			"DJ's Private Club refused “Too many files”.",
			'Gave up: all 2 peers failed. Written to the retry ledger.',
		]);
	});

	it('a completed download: start, speed, import, done', () => {
		const log = [
			{ t: at(4, 33, 7), k: 'submitted', card: 'dl:similar' },
			{ t: at(4, 34, 30), k: 'attempt', i: 1, of: 5, user: 'piaga', filename: 'Crash Out.flac', size: 32715571, ext: 'flac' },
			{ t: at(4, 36, 29), k: 'requested', user: 'piaga' },
			{ t: at(4, 36, 35), k: 'connected', user: 'piaga', total_bytes: 32715571 },
			{ t: at(4, 36, 35), k: 'transferring', user: 'piaga' },
			{ t: at(4, 37, 16), k: 'importing', user: 'piaga', bytes: 32715571 },
			{ t: at(4, 37, 47), k: 'done', track_id: 't1', file_size: 32715571, already_in_library: false, attempt: 1 },
		];
		const rows = timelineSentences(log, { status: 'completed', outcome: 'new' }, ms(5, 0));
		expect(rows.map((r) => r.text)).toEqual([
			'Submitted by the Similar run.',
			"Picked piaga's FLAC, 31.2 MB.",
			'Asked piaga for the file.',
			'piaga started sending after 6 s. 41 s at 779.2 KB/s.',
			'Received 31.2 MB; importing.',
			'Done. Added to your library, 31.2 MB.',
		]);
		expect(rows.at(-1)).toMatchObject({ isNow: true, colour: 'emerald' });
	});

	it('already had and cancelled endings', () => {
		const done = [{ t: at(4, 35), k: 'done', already_in_library: true }];
		expect(timelineSentences(done, { status: 'completed', outcome: 'already_had' })[0].text)
			.toBe('Done. You already had it, so the file was discarded.');
		const cancelled = [{ t: at(6, 51), k: 'cancelled' }];
		expect(timelineSentences(cancelled, { status: 'failed' })[0].text).toBe('You cancelled it.');
	});

	it('a live search shows the query it is on', () => {
		const log = [
			{ t: at(7, 8, 0), k: 'submitted', card: 'dl:playlist' },
			{ t: at(7, 8, 1), k: 'query_start', i: 1, n: 4, q: 'michael crawford all i ask of you', kind: 'variant' },
			{ t: at(7, 8, 10), k: 'query_end', i: 1, n: 4, q: 'michael crawford all i ask of you', kind: 'variant', peers: 5, files: 14 },
			{ t: at(7, 8, 11), k: 'query_start', i: 2, n: 4, q: 'michael crawford all i ask', kind: 'variant' },
		];
		const job = {
			status: 'running', started_at: at(7, 8, 0),
			tracks: JSON.stringify([{ stage: 'searching', stage_since: at(7, 8, 1), search: { query_index: 2, query_total: 4, files_seen: 14, kept: 0 } }]),
		};
		const texts = timelineSentences(log, job, ms(7, 8, 20)).map((r) => r.text);
		expect(texts).toEqual([
			'Submitted by the playlist import.',
			'Searched “michael crawford all i ask of you”: 14 files from 5 peers (query 1 of 4).',
			'Searching “michael crawford all i ask” (query 2 of 4).',
			'Query 2 of 4: 14 files seen, 0 kept so far.',
		]);
	});
});

describe('funnelSegments', () => {
	it('album funnel: queries with the album fallback and four segments', () => {
		const f = funnelSegments({
			queries: [
				{ q: 'aespa Lemonade', kind: 'variant', peers: 9, files: 14 },
				{ q: 'aespa Lemon', kind: 'variant', peers: 3, files: 4 },
				{ q: 'aespa Armageddon', kind: 'album', peers: 0, files: 0 },
			],
			album_query: 'aespa Armageddon', peers_seen: 12, files_seen: 27,
			rejected: { size: 2, ext: 0, quality: 0, title: 21, duration: 4, score: 0, artist_path: 0 }, kept: 0, wanted_duration: 191,
		});
		expect(f.queries.map((q) => [q.q, q.prefix, q.files])).toEqual([
			['aespa Lemonade', '', 14], ['aespa Lemon', '', 4], ['aespa Armageddon', 'album fallback', 0],
		]);
		expect(f.segments.map((s) => [s.key, s.count, s.colour])).toEqual([
			['title', 21, 'rose'], ['duration', 4, 'amber'], ['size', 2, 'muted'], ['kept', 0, 'emerald'],
		]);
		expect(f.segments[1].label).toBe('length off (wanted 3:11)');
		expect(f.total).toBe(27);
		expect(f.wanted).toBe('3:11');
	});

	it('adds an "other checks" segment only when needed; null without a funnel', () => {
		const f = funnelSegments(JSON.stringify({ queries: [], rejected: { ext: 1, quality: 2 }, kept: 3 }));
		expect(f.segments.map((s) => s.key)).toEqual(['title', 'duration', 'size', 'other', 'kept']);
		expect(f.segments[3].count).toBe(3);
		expect(f.segments[1].label).toBe('length off');
		expect(funnelSegments(null)).toBeNull();
		expect(funnelSegments('garbage')).toBeNull();
	});
});

describe('candidateLines', () => {
	it('lists who comes next after the current attempt', () => {
		expect(candidateLines(SARAH_CANDIDATES, 1)).toEqual([
			{ n: '2nd', user: 'dblbbr', text: 'dblbbr · FLAC 28.9 MB · free slot' },
			{ n: '3rd', user: 'kfs86', text: 'kfs86 · FLAC 29.1 MB · 4 in their queue' },
			{ n: '4th', user: 'lwl', text: 'lwl · MP3 320, 9.2 MB' },
		]);
	});
	it('after attempt 2 only the 3rd and 4th remain', () => {
		expect(candidateLines(SARAH_CANDIDATES, 2).map((c) => c.n)).toEqual(['3rd', '4th']);
		expect(candidateLines(SARAH_CANDIDATES, 4)).toEqual([]);
	});
	it('empty for nothing', () => {
		expect(candidateLines(null, 1)).toEqual([]);
		expect(candidateLines([], 1)).toEqual([]);
	});
});

describe('peerSentences', () => {
	it('one clause per peer', () => {
		expect(peerSentences({
			'DJ-Promo': { successes: 0, failures: 4, score: -8, recent_failure: false },
			dblbbr: { successes: 2, failures: 0, score: 4, recent_failure: false },
			musicmaster: { successes: 1, failures: 3, score: -4, recent_failure: true },
			newbie: { successes: 0, failures: 0 },
		})).toEqual([
			{ user: 'DJ-Promo', text: 'has failed you 4 times and never delivered' },
			{ user: 'dblbbr', text: 'has delivered 2 of 2' },
			{ user: 'musicmaster', text: 'has delivered 1, failed 3 (failed in the last 30 min)' },
			{ user: 'newbie', text: 'first contact' },
		]);
	});
	it('empty map (reputation reset) -> nothing', () => {
		expect(peerSentences({})).toEqual([]);
		expect(peerSentences(null)).toEqual([]);
	});
});

describe('scheduleSentence', () => {
	const NOW = Date.UTC(2026, 9, 18, 12, 0, 0);
	const failed = (extra) => ({ status: 'failed', failure_class: 'peer', ...extra });

	it('first failure lists every remaining step', () => {
		expect(scheduleSentence(failed({
			ledger: { attempts: 1 }, next: { kind: 'retry', at: '2026-10-19T12:00:00' },
		}), LIMITS, NOW)).toBe(`First failure for this track. Zonik tries again in 1 day (Oct 19), then after 7 and 30 days, then stops for a year.`);
	});
	it('a later failure', () => {
		expect(scheduleSentence(failed({
			failure_class: 'not_found', ledger: { attempts: 9 }, next: { kind: 'retry', at: '2026-11-17T12:00:00' },
		}), LIMITS, NOW)).toBe('9th failure for this track. Zonik tries again in 30 days (Nov 17), then stops for a year.');
		expect(scheduleSentence(failed({
			ledger: { attempts: 2 }, next: { kind: 'retry', at: '2026-10-25T12:00:00' },
		}), LIMITS, NOW)).toBe('2nd failure for this track. Zonik tries again in 7 days (Oct 25), then after 30 days, then stops for a year.');
	});
	it('retired, scans, nothing scheduled', () => {
		expect(scheduleSentence(failed({ ledger: { attempts: 26, next_retry_at: '2027-10-18T12:00:00' }, next: { kind: 'retired' } }), LIMITS, NOW))
			.toBe('26th failure for this track. Zonik has stopped trying for a year (until Oct 18).');
		expect(scheduleSentence(failed({ next: { kind: 'scans', attempts: 3, max_attempts: 3 } }), LIMITS, NOW))
			.toBe('Upgrade scan 3 of 3; this upgrade is retired.');
		expect(scheduleSentence(failed({ failure_class: 'cancelled', next: { kind: 'none' } }), LIMITS, NOW))
			.toBe('Not counted against the track; nothing retries it on its own.');
		expect(scheduleSentence({ status: 'completed' }, LIMITS, NOW)).toBe('');
	});
});

describe('drawer helpers', () => {

	it('live state sentence: the busy mockup', () => {
		expect(stateSentence(SARAH_JOB, null, LIMITS, ms(7, 11, 58))).toEqual({
			em: "In DJ-Promo's upload queue",
			text: " at place 3, for 48 s of the 2 min allowed. If they haven't started sending by then, Zonik moves on to the next peer.",
			colour: 'amber',
		});
	});

	it('the last peer gives up instead of moving on', () => {
		const job = { ...SARAH_JOB, tracks: SARAH_JOB.tracks.replace('"attempt":1', '"attempt":4') };
		expect(stateSentence(job, null, LIMITS, ms(7, 11, 58)).text).toMatch(/Zonik gives up on this peer\.$/);
	});

	it('failed: class lead, what happened, schedule', () => {
		const s = stateSentence({
			status: 'failed', failure_class: 'not_found',
			result: JSON.stringify({ message: 'No results for aespa - Lemonade', search: { queries: [{ q: 'a' }, { q: 'b' }], album_query: 'x', files_seen: 27, kept: 0, rejected: { title: 27 } } }),
			ledger: { attempts: 9 }, next: { kind: 'retry', at: '2026-11-17T12:00:00' },
		}, null, LIMITS, Date.UTC(2026, 9, 18, 12));
		expect(s.em).toBe('Not found.');
		expect(s.text).toBe(' 2 queries + album query, 0 files kept · 27 seen, 27 wrong title. 9th failure for this track. Zonik tries again in 30 days (Nov 17), then stops for a year.');
		expect(s.colour).toBe('muted');
	});

	it('done: added, replaced, already had', () => {
		expect(stateSentence({ status: 'completed', outcome: 'new', track: { format: 'flac', file_size: 32715571, bitrate: 1002, duration_seconds: 189, play_count: 0 } }))
			.toEqual({ em: 'Added to your library', text: ' as FLAC, 31.2 MB, 1,002 kbps, 3:09. Not played yet.', colour: 'emerald' });
		expect(stateSentence({ status: 'completed', outcome: 'replaced', upgrade: { original_format: 'MP3', original_bitrate: 320 }, track: { format: 'flac', file_size: 25270000, play_count: 1 } }).text)
			.toBe(' your MP3 320 with FLAC, 24.1 MB. Played once.');
		expect(stateSentence({ status: 'completed', outcome: 'already_had' }).em).toBe('You already had this.');
	});

	it('picked candidates and live queries come from the log', () => {
		expect(pickedCandidates(SARAH_LOG).map((c) => c.username)).toEqual(['DJ-Promo', 'dblbbr', 'kfs86', 'lwl']);
		expect(pickedCandidates(null)).toEqual([]);
		expect(liveQueries(SARAH_LOG)).toEqual([{ q: 'Sarah Brightman Think of Me', kind: 'variant', files: 23, peers: 11 }]);
	});
});
