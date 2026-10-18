/**
 * Downloads page: how the rows of each tab are grouped (Release 2 instrument
 * panel) and how finished rows fold into runs.
 *
 * Pure module (no Svelte imports). Live groups follow the pipeline, closest to
 * done first; Failed groups follow the failure class; Done is one flat list,
 * newest first. See plans/downloads-feedback-ui/phase4-plan.md R2-A3, DC-20, DC-21.
 */
import { parseUTC } from '../utils.js';
import {
	resolveStage, failureClass, firstTrack, doneOutcome, sourceLabel,
	LIVE_GROUP_ORDER, GROUP_OF_STAGE, STAGE_COPY,
	FAILED_GROUP_ORDER, GROUP_OF_CLASS, CLASS_COPY, classSentence,
} from './stage.js';

/** Rows without a batch fold into one run while they arrive within this gap. */
export const RUN_GAP_MS = 20 * 60 * 1000;

const LIVE_STATUSES = new Set(['pending', 'running']);

function timeMs(iso) {
	if (!iso) return null;
	const d = typeof iso === 'number' ? new Date(iso) : parseUTC(iso);
	return d && !Number.isNaN(d.getTime()) ? d.getTime() : null;
}

/** finished_at, else started_at (ms), else 0. */
function whenMs(job) {
	return timeMs(job?.finished_at) ?? timeMs(job?.started_at) ?? 0;
}

function startMs(job) {
	return timeMs(job?.started_at) ?? whenMs(job);
}

/** The `transfer_progress` entry of a job: `ctx.transferFor(job)` or a job_id match in `ctx.transfers`. */
export function transferOf(job, ctx = {}) {
	if (typeof ctx.transferFor === 'function') return ctx.transferFor(job) || null;
	if (!Array.isArray(ctx.transfers) || !job?.id) return null;
	return ctx.transfers.find((t) => t && t.job_id === job.id) || null;
}

function stageSinceMs(job) {
	const t0 = firstTrack(job);
	return timeMs(job?.stage_since ?? t0.stage_since) ?? startMs(job);
}

/** The batch a row belongs to (`tracks[0].batch`, DC-21) or null. */
export function batchOf(job) {
	const b = firstTrack(job).batch;
	return b && typeof b === 'object' && b.id ? b : null;
}

function liveGroups(jobs, ctx) {
	const limits = ctx.limits || null;
	const nowMs = Number(ctx.nowMs) || Date.now();
	const buckets = Object.fromEntries(LIVE_GROUP_ORDER.map((k) => [k, []]));
	const stagesIn = Object.fromEntries(LIVE_GROUP_ORDER.map((k) => [k, new Set()]));

	for (const job of jobs) {
		if (!job || !LIVE_STATUSES.has(job.status)) continue;
		const st = resolveStage(job, transferOf(job, ctx), limits, nowMs, ctx);
		const key = GROUP_OF_STAGE[st.stage] || 'searching';
		buckets[key].push({ job, st });
		stagesIn[key].add(st.stage);
	}

	// Inside a group: importing before transferring (closest to done), then the
	// longest in its stage first ("#1 for a slot" is the one waiting longest).
	const order = { importing: 0, transferring: 1, connecting: 0, queued_at_peer: 1, waiting_slot: 0, peer_lock: 1 };
	for (const key of LIVE_GROUP_ORDER) {
		buckets[key].sort((a, b) => (order[a.st.stage] ?? 0) - (order[b.st.stage] ?? 0)
			|| stageSinceMs(a.job) - stageSinceMs(b.job));
	}

	// Transfer slots are held from slot acquisition to import: connecting, in a
	// peer's queue and transferring all count.
	const busy = buckets.transferring.filter((r) => r.st.stage === 'transferring').length + buckets.at_peer.length;

	// Hidden backlog: batches (GET /api/download/batches) with tracks not yet handed over.
	const backlog = [];
	for (const b of Array.isArray(ctx.batches) ? ctx.batches : []) {
		const pending = Number(b?.pending) || 0;
		if (!b || pending <= 0 || b.cancelled) continue;
		backlog.push({
			backlog: true,
			id: `backlog:${b.id}`,
			batch: b,
			card: b.source ? (String(b.source).startsWith('dl') ? b.source : `dl:${b.source}`) : null,
			title: b.label || 'Batch',
			pending,
			next_titles: Array.isArray(b.pending_titles) ? b.pending_titles : [],
		});
	}

	const out = [];
	for (const key of LIVE_GROUP_ORDER) {
		const copy = STAGE_COPY[key];
		if (key === 'backlog') {
			if (!backlog.length) continue;
			const count = backlog.reduce((n, r) => n + r.pending, 0);
			const kinds = new Set(backlog.map((r) => r.batch.kind));
			out.push({
				key, dot: copy.dot, name: copy.name, count,
				reason: copy.reason({ limits, handover: ctx.handover, batchKind: kinds.size === 1 ? [...kinds][0] : null }),
				rows: backlog,
			});
			continue;
		}
		const rows = buckets[key];
		if (!rows.length) continue;
		out.push({
			key, dot: copy.dot, name: copy.name, count: rows.length,
			reason: copy.reason({ limits, count: rows.length, busy, stages: stagesIn[key], queryTotal: ctx.queryTotal }),
			rows: rows.map((r) => r.job),
		});
	}
	return out;
}

function failedGroups(jobs, ctx) {
	const buckets = Object.fromEntries(FAILED_GROUP_ORDER.map((k) => [k, []]));
	const classesIn = Object.fromEntries(FAILED_GROUP_ORDER.map((k) => [k, new Set()]));
	for (const job of jobs) {
		if (!job || job.status !== 'failed') continue;
		const cls = failureClass(job) || 'orphan';
		const key = GROUP_OF_CLASS[cls] || 'infra';
		buckets[key].push(job);
		classesIn[key].add(cls);
	}
	const out = [];
	for (const key of FAILED_GROUP_ORDER) {
		const rows = buckets[key];
		if (!rows.length) continue;
		rows.sort((a, b) => (Number(b.times_failed_30d) || 0) - (Number(a.times_failed_30d) || 0) || whenMs(b) - whenMs(a));
		let copyKey = key;
		let sentenceKey = key;
		if (key === 'rejected') {
			const both = classesIn.rejected.has('rejected') && classesIn.rejected.has('no_better');
			copyKey = both ? 'rejected' : [...classesIn.rejected][0];
			sentenceKey = both ? 'rejected+no_better' : copyKey;
		}
		const copy = CLASS_COPY[copyKey] || CLASS_COPY[key];
		out.push({
			key,
			dot: copy.dot,
			name: key === 'rejected' && sentenceKey === 'rejected+no_better' ? 'Not imported or nothing better' : copy.name,
			count: rows.length,
			reason: classSentence(sentenceKey, ctx),
			rows,
		});
	}
	return out;
}

function doneGroups(jobs) {
	const rows = jobs.filter((j) => j && j.status === 'completed').sort((a, b) => whenMs(b) - whenMs(a));
	if (!rows.length) return [];
	// No name: GroupedList draws the Done feed without a group header (final-A/done.png).
	return [{ key: 'done', dot: 'emerald', name: '', count: rows.length, reason: '', rows }];
}

/**
 * Group a tab's rows: `[{key, dot, name, count, reason, rows}]`, empty groups left out.
 *
 * @param {object[]} jobs  list items / WS jobs
 * @param {'live'|'failed'|'done'} tab
 * @param {object} [ctx]   `{limits, nowMs, transfers | transferFor, pacer, medianSpeed,
 *                          batches, handover, queryTotal, incidentNote}`
 *
 * Live rows are job objects, except the backlog group whose rows are
 * `{backlog: true, id, batch, card, title, pending, next_titles}`.
 */
export function groups(jobs, tab, ctx = {}) {
	const list = Array.isArray(jobs) ? jobs : [];
	if (tab === 'live') return liveGroups(list, ctx);
	if (tab === 'failed') return failedGroups(list, ctx);
	if (tab === 'done') return doneGroups(list);
	return [];
}

// ---------------------------------------------------------------------------
// Runs
// ---------------------------------------------------------------------------

const BUCKET_OF_CLASS = {
	not_found: 'not_found', no_better: 'no_better', rejected: 'rejected', peer: 'peer',
	cancelled: 'infra', infra: 'infra', orphan: 'infra',
};

function emptyCounts() {
	return { total: 0, new: 0, replaced: 0, already_had: 0, not_found: 0, peer: 0, rejected: 0, no_better: 0, infra: 0, live: 0 };
}

/** DC-20 run counts over a run's rows (mirror of download_ledger._run). */
export function runCounts(rows) {
	const c = emptyCounts();
	for (const r of rows) {
		c.total += 1;
		if (LIVE_STATUSES.has(r.status)) c.live += 1;
		else if (r.status === 'completed') c[doneOutcome(r)?.kind || 'new'] += 1;
		else if (r.status === 'failed') c[BUCKET_OF_CLASS[failureClass(r)] || 'infra'] += 1;
	}
	return c;
}

function isoOf(ms) {
	return ms ? new Date(ms).toISOString().replace('Z', '') : null;
}

function makeRun(id, rows, batch) {
	const tally = new Map();
	for (const r of rows) tally.set(r.card ?? null, (tally.get(r.card ?? null) || 0) + 1);
	let card = null;
	let best = 0;
	for (const [c, n] of tally) if (n > best) { card = c; best = n; }
	const label = (batch && rows.map(batchOf).find((b) => b?.label)?.label) || sourceLabel(card);
	const starts = rows.map(startMs).filter(Boolean);
	const ends = rows.map(whenMs).filter(Boolean);
	return {
		id,
		label,
		kind: batch?.kind ?? null,
		card,
		start: starts.length ? isoOf(Math.min(...starts)) : null,
		end: ends.length ? isoOf(Math.max(...ends)) : null,
		counts: runCounts(rows),
		job_ids: rows.map((r) => r.id),
		rows: [...rows].sort((a, b) => whenMs(b) - whenMs(a)),
	};
}

/**
 * Fold rows into runs, newest first: `[{id, label, kind, card, start, end, counts,
 * job_ids, rows}]`. Runs from `GET /api/jobs/runs` (`apiRuns`) claim their rows
 * first and keep the server's label and counts; the rest group by
 * `tracks[0].batch.id`, else per card, a new run starting when a row was
 * submitted more than 20 min after the run's last activity.
 */
export function runs(jobs, apiRuns = null) {
	const list = (Array.isArray(jobs) ? jobs : []).filter(Boolean);
	const byId = new Map(list.map((j) => [j.id, j]));
	const claimed = new Set();
	const out = [];

	for (const ar of Array.isArray(apiRuns) ? apiRuns : []) {
		if (!ar) continue;
		const rows = (ar.job_ids || []).map((id) => byId.get(id)).filter((r) => r && !claimed.has(r.id));
		rows.forEach((r) => claimed.add(r.id));
		rows.sort((a, b) => whenMs(b) - whenMs(a));
		out.push({
			id: ar.id, label: ar.label || sourceLabel(ar.card), kind: ar.kind ?? null, card: ar.card ?? null,
			start: ar.start ?? null, end: ar.end ?? null,
			counts: ar.counts || runCounts(rows), job_ids: ar.job_ids || rows.map((r) => r.id), rows,
		});
	}

	const batched = new Map();
	const byCard = new Map();
	for (const j of list) {
		if (claimed.has(j.id)) continue;
		const b = batchOf(j);
		if (b) {
			const k = String(b.id);
			if (!batched.has(k)) batched.set(k, []);
			batched.get(k).push(j);
		} else {
			const k = j.card ?? null;
			if (!byCard.has(k)) byCard.set(k, []);
			byCard.get(k).push(j);
		}
	}
	for (const [id, rows] of batched) {
		rows.sort((a, b) => startMs(a) - startMs(b));
		out.push(makeRun(id, rows, batchOf(rows[0])));
	}
	for (const [card, rows] of byCard) {
		rows.sort((a, b) => startMs(a) - startMs(b));
		let current = [];
		let latest = 0;
		const close = () => out.push(makeRun(`${card || 'dl'}@${isoOf(startMs(current[0]))}`, current, null));
		for (const r of rows) {
			if (current.length && startMs(r) - latest > RUN_GAP_MS) {
				close();
				current = [];
				latest = 0;
			}
			current.push(r);
			latest = Math.max(latest, whenMs(r));
		}
		if (current.length) close();
	}
	out.sort((a, b) => (timeMs(b.start) ?? 0) - (timeMs(a.start) ?? 0));
	return out;
}
