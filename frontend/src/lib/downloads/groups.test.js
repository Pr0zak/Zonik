import { describe, it, expect } from 'vitest';
import { groups, runs, runCounts, transferOf, batchOf, RUN_GAP_MS } from './groups.js';

const NOW = Date.UTC(2026, 9, 18, 7, 12, 30);
const iso = (msAgo) => new Date(NOW - msAgo).toISOString().replace('Z', '');
const epoch = (msAgo) => (NOW - msAgo) / 1000;
const MIN = 60_000;

const LIMITS = {
	transfer_slots: 2, search_slots: 3, searches_per_minute: 6, search_min_interval_s: 8,
	peer_connect_s: 20, peer_busy_wait_s: 60, peer_queue_s: 120, stall_s: 60,
};

let seq = 0;
function live(stage, { since = MIN, status = 'running', extra = {}, ...rest } = {}) {
	seq += 1;
	return {
		id: `j${seq}`, type: 'download', status, card: 'dl:playlist', started_at: iso(10 * MIN),
		tracks: JSON.stringify([{ artist: `A${seq}`, track: `T${seq}`, status: 'downloading', stage, stage_since: iso(since), ...extra }]),
		...rest,
	};
}

describe('groups — Live, the busy mockup', () => {
	const bowie = live('transferring', { since: 30_000 });
	const webber = live('transferring', { since: 20_000 });
	const sarah = live('queued_at_peer', { since: 48_000, extra: { username: 'DJ-Promo', queue_place: 3 } });
	const crawford = live('searching', { since: 19_000, extra: { search: { query_index: 2, query_total: 4, files_seen: 14, kept: 0 } } });
	const cake = live('waiting_slot', { since: 185_000 });
	const lunasa = live('waiting_slot', { since: 130_000 });
	const agnes = live('waiting_slot', { since: 62_000 });
	const tinashe = live('queue_search', { status: 'pending', since: 40_000 });
	const finished = { id: 'done1', status: 'completed', card: 'dl:playlist' };
	const transfers = [
		{ job_id: bowie.id, state: 'transferring', username: 'we@S3l', total_bytes: 100, received_bytes: 62, speed: 2516582, last_progress_at: epoch(0), state_since: epoch(30_000) },
		{ job_id: webber.id, state: 'transferring', username: 'forgottenfrequencies', total_bytes: 100, received_bytes: 8, speed: 317440, last_progress_at: epoch(0), state_since: epoch(20_000) },
	];
	const batches = [{
		id: 'b1', label: 'Phantom of the Opera (2026 Mix)', kind: 'playlist', source: 'playlist', total: 60,
		submitted: 9, done: 1, failed: 0, skipped: 0, live: 8, pending: 51,
		pending_titles: ['Il Divo — Phantom of the Opera', 'Nightwish — The Phantom of the Opera'], started_at: iso(10 * MIN),
	}];
	const jobs = [tinashe, agnes, crawford, finished, sarah, lunasa, webber, cake, bowie];
	const g = groups(jobs, 'live', { limits: LIMITS, nowMs: NOW, transfers, batches });

	it('pipeline order with counts and reason clauses from the limits', () => {
		expect(g.map((x) => [x.key, x.name, x.count, x.reason])).toEqual([
			['transferring', 'Transferring', 2, '2 of 2 slots busy'],
			['at_peer', 'At the peer', 1, 'asked, waiting for the upload to start'],
			['searching', 'Searching', 1, 'up to 4 queries, then an album query'],
			['waiting_slot', 'Waiting for a transfer slot', 3, 'file picked, both slots busy'],
			['queue_search', 'Waiting to search', 1, 'pacer allows 6 searches a minute, 8 s apart'],
			['backlog', 'Not yet submitted', 51, 'the import hands tracks over 4 at a time'],
		]);
	});

	it('dots per group', () => {
		expect(g.map((x) => x.dot)).toEqual(['sky', 'amber', 'indigo', 'amber', 'muted', 'muted']);
	});

	it('rows inside a group: longest in the stage first, finished jobs left out', () => {
		expect(g[3].rows.map((r) => r.id)).toEqual([cake.id, lunasa.id, agnes.id]);
		expect(g[0].rows.map((r) => r.id)).toEqual([bowie.id, webber.id]);
		expect(g.flatMap((x) => x.rows).some((r) => r.id === finished.id)).toBe(false);
	});

	it('the backlog row carries the batch and its next titles', () => {
		expect(g[5].rows).toEqual([expect.objectContaining({
			backlog: true, id: 'backlog:b1', title: 'Phantom of the Opera (2026 Mix)', pending: 51, card: 'dl:playlist',
			next_titles: ['Il Divo — Phantom of the Opera', 'Nightwish — The Phantom of the Opera'],
		})]);
	});

	it('a transfer moves a row out of a stale stored stage', () => {
		const j = live('connecting', { since: 5000 });
		const out = groups([j], 'live', { limits: LIMITS, nowMs: NOW, transfers: [{ job_id: j.id, state: 'transferring', state_since: epoch(1000), last_progress_at: epoch(0) }] });
		expect(out.map((x) => x.key)).toEqual(['transferring']);
	});

	it('connecting only / peer lock only change the clause; no limits fall back', () => {
		const out = groups([live('connecting'), live('peer_lock')], 'live', { nowMs: NOW });
		expect(out.map((x) => [x.key, x.reason])).toEqual([
			['at_peer', 'connecting, direct and relayed'],
			['waiting_slot', 'file picked, the peer is busy with another of your downloads'],
		]);
		expect(groups([live('queue_search', { status: 'pending' })], 'live', { nowMs: NOW, limits: { search_slots: 3 } })[0].reason)
			.toBe('waiting for one of the 3 search slots');
	});

	it('cancelled or finished batches add no backlog; empty input is empty', () => {
		expect(groups([], 'live', { batches: [{ id: 'x', pending: 3, cancelled: true }] })).toEqual([]);
		expect(groups(null, 'live')).toEqual([]);
		expect(groups([bowie], 'nope')).toEqual([]);
	});
});

describe('groups — Failed', () => {
	const failed = (cls, times, finishedAgo, extra = {}) => ({
		id: `${cls}-${times}-${finishedAgo}`, status: 'failed', failure_class: cls, times_failed_30d: times,
		finished_at: iso(finishedAgo), card: 'dl:weekly-radar', ...extra,
	});
	const jobs = [
		failed('peer', 1, 3 * MIN), failed('not_found', 9, 5 * MIN), failed('cancelled', 0, MIN),
		failed('not_found', 26, 50 * MIN), failed('peer', 2, 4 * MIN), failed('orphan', 0, 2 * MIN),
		failed('not_found', 9, 2 * MIN), { id: 'ok', status: 'completed' },
	];
	const g = groups(jobs, 'failed', { incidentNote: "yesterday's 142 are in the banner" });

	it('class order not_found, peer, infra; cancelled and orphan fold into infra', () => {
		expect(g.map((x) => [x.key, x.name, x.count])).toEqual([
			['not_found', 'Not found', 3],
			['peer', 'Peer problems', 2],
			['infra', "Not the track's fault", 2],
		]);
	});

	it('dots: muted not found, rose peer, amber for not the track\'s fault (final-A/failed.png)', () => {
		expect(g.map((x) => x.dot)).toEqual(['muted', 'rose', 'amber']);
	});

	it('times_failed_30d desc inside a group, then newest first', () => {
		expect(g[0].rows.map((r) => r.id)).toEqual(['not_found-26-3000000', 'not_found-9-120000', 'not_found-9-300000']);
		expect(g[1].rows.map((r) => r.times_failed_30d)).toEqual([2, 1]);
	});

	it('class sentences', () => {
		expect(g[0].reason).toBe('a normal outcome: no peer shared a file that passed the title, length and quality checks');
		expect(g[1].reason).toBe('a file was found, every peer that had it failed');
		expect(g[2].reason).toBe("cancelled, restart or outage · not counted against the track · yesterday's 142 are in the banner");
	});

	it('rejected and no_better share a group named for what is in it', () => {
		expect(groups([failed('no_better', 1, MIN)], 'failed')[0]).toMatchObject({ key: 'rejected', name: 'Nothing better', reason: 'copies were found, none better than the file you have' });
		expect(groups([failed('rejected', 1, MIN)], 'failed')[0].name).toBe('Not imported');
		expect(groups([failed('rejected', 1, MIN), failed('no_better', 1, 2 * MIN)], 'failed')[0])
			.toMatchObject({ name: 'Not imported or nothing better', count: 2, reason: 'not imported, or no copy better than yours' });
	});

	it('legacy rows without failure_class classify from the raw strings', () => {
		const legacy = { id: 'L', status: 'failed', result: JSON.stringify({ message: 'No results for A - T' }) };
		expect(groups([legacy], 'failed')[0].key).toBe('not_found');
	});
});

describe('groups — Done', () => {
	it('one flat group, newest first', () => {
		const a = { id: 'a', status: 'completed', finished_at: iso(5 * MIN) };
		const b = { id: 'b', status: 'completed', finished_at: iso(MIN) };
		const g = groups([a, { id: 'f', status: 'failed' }, b], 'done');
		expect(g).toHaveLength(1);
		expect(g[0]).toMatchObject({ key: 'done', name: '', count: 2 });
		expect(g[0].rows.map((r) => r.id)).toEqual(['b', 'a']);
		expect(groups([], 'done')).toEqual([]);
	});
});

describe('runs', () => {
	const row = (id, card, startedAgo, finishedAgo, status = 'completed', t0 = {}, extra = {}) => ({
		id, card, status, started_at: iso(startedAgo), finished_at: finishedAgo == null ? null : iso(finishedAgo),
		tracks: JSON.stringify([{ artist: 'A', track: id, ...t0 }]), ...extra,
	});

	it('groups by batch id first, then per card with a 20-minute gap', () => {
		const batch = { id: 'b1', label: 'Phantom of the Opera (2026 Mix)', kind: 'playlist' };
		const jobs = [
			row('p1', 'dl:playlist', 10 * MIN, 8 * MIN, 'completed', { batch }),
			row('p2', 'dl:playlist', 9 * MIN, null, 'running', { batch }),
			row('s1', 'dl:similar', 200 * MIN, 195 * MIN),
			row('s2', 'dl:similar', 190 * MIN, 185 * MIN, 'failed', {}, { failure_class: 'not_found' }),
			// 60 min after s2 finished -> a new run
			row('s3', 'dl:similar', 125 * MIN, 120 * MIN, 'completed', {}, { already_in_library: true }),
		];
		const out = runs(jobs);
		expect(out.map((r) => [r.id, r.label, r.kind, r.job_ids.length])).toEqual([
			['b1', 'Phantom of the Opera (2026 Mix)', 'playlist', 2],
			[`dl:similar@${iso(125 * MIN)}`, 'Similar', null, 1],
			[`dl:similar@${iso(200 * MIN)}`, 'Similar', null, 2],
		]);
		expect(out[0].counts).toMatchObject({ total: 2, new: 1, live: 1 });
		expect(out[2].counts).toMatchObject({ total: 2, new: 1, not_found: 1 });
		expect(out[1].counts).toMatchObject({ already_had: 1 });
		expect(out[2].rows.map((r) => r.id)).toEqual(['s2', 's1']);
	});

	it('the gap is measured from the run\'s last activity', () => {
		const jobs = [
			row('a', 'dl:discovery', 100 * MIN, 70 * MIN), // long job: busy until 70 min ago
			row('b', 'dl:discovery', 75 * MIN, 74 * MIN), // starts within 20 min of 'a' finishing
			row('c', 'dl:discovery', 74 * MIN + RUN_GAP_MS / 2, 50 * MIN),
		];
		expect(runs(jobs)).toHaveLength(1);
	});

	it('server runs claim their rows and keep their label and counts', () => {
		const jobs = [row('x1', 'dl:weekly-radar', 30 * MIN, 25 * MIN), row('x2', 'dl:weekly-radar', 29 * MIN, 24 * MIN), row('y', 'dl:manual', 5 * MIN, 4 * MIN)];
		const api = [{
			id: 'sched-1', label: 'Weekly Radar', kind: 'scheduled', card: 'dl:weekly-radar', start: iso(30 * MIN), end: iso(24 * MIN),
			counts: { total: 64, new: 48, replaced: 0, already_had: 9, not_found: 6, peer: 1, rejected: 0, no_better: 0, infra: 0, live: 0 },
			job_ids: ['x1', 'x2', 'gone'],
		}];
		const out = runs(jobs, api);
		expect(out.map((r) => r.id)).toEqual([`dl:manual@${iso(5 * MIN)}`, 'sched-1']);
		expect(out[1].counts.total).toBe(64);
		expect(out[1].rows.map((r) => r.id)).toEqual(['x2', 'x1']);
		expect(out[0].label).toBe('Manual');
	});

	it('runCounts buckets failures and outcomes', () => {
		expect(runCounts([
			{ status: 'failed', failure_class: 'cancelled' },
			{ status: 'failed', failure_class: 'peer' },
			{ status: 'completed', outcome: 'replaced' },
			{ status: 'pending' },
		])).toEqual({ total: 4, new: 0, replaced: 1, already_had: 0, not_found: 0, peer: 1, rejected: 0, no_better: 0, infra: 1, live: 1 });
	});

	it('empty', () => expect(runs(null)).toEqual([]));
});

describe('helpers', () => {
	it('transferOf matches by job_id or uses the page resolver', () => {
		const t = { job_id: 'j', state: 'queued' };
		expect(transferOf({ id: 'j' }, { transfers: [t] })).toBe(t);
		expect(transferOf({ id: 'k' }, { transfers: [t] })).toBeNull();
		expect(transferOf({ id: 'k' }, { transferFor: () => t })).toBe(t);
	});
	it('batchOf', () => {
		expect(batchOf({ tracks: JSON.stringify([{ batch: { id: 'b', label: 'L' } }]) })).toEqual({ id: 'b', label: 'L' });
		expect(batchOf({ tracks: JSON.stringify([{ batch: null }]) })).toBeNull();
	});
});
