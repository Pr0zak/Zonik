/**
 * Downloads drawer: one job's story in plain sentences.
 *
 * Pure module (no Svelte imports). Reads the DC-2 timeline (`Job.log` for a
 * download, or `timeline` from GET /api/jobs/{id}?detail=1), the DC-5 funnel and
 * candidates, the DC-19 `peers`, `ledger` and `next`, and DC-12 `limits`.
 * See plans/downloads-feedback-ui/phase4-plan.md R2-A3, R2-B4.
 */
import { formatSpeed, parseUTC } from '../utils.js';
import {
	firstTrack, jobResult, parseMaybe, plural, mb, ordinal, relativeIn, shortDate,
	peerErrorClause, resolveStage, sourceLabel, failureClass, failureSentence as failureSentenceFor,
} from './stage.js';

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

function timeMs(v) {
	if (v == null || v === '') return null;
	if (typeof v === 'number') return v;
	const d = parseUTC(v);
	return d && !Number.isNaN(d.getTime()) ? d.getTime() : null;
}

/** Local "HH:MM:SS" of a naive-UTC ISO string or epoch ms. */
export function clockSeconds(v) {
	const ms = timeMs(v);
	if (ms == null) return '';
	const d = new Date(ms);
	return [d.getHours(), d.getMinutes(), d.getSeconds()].map((n) => String(n).padStart(2, '0')).join(':');
}

/** Seconds -> "40 s", "1 min 20 s", "2 min", "1 h 5 min" (sentence form). */
export function durationPhrase(s) {
	const sec = Math.max(0, Math.round(Number(s) || 0));
	if (sec < 60) return `${sec} s`;
	if (sec < 3600) {
		const m = Math.floor(sec / 60);
		const r = sec % 60;
		return r ? `${m} min ${r} s` : `${m} min`;
	}
	const h = Math.floor(sec / 3600);
	const m = Math.floor((sec % 3600) / 60);
	return m ? `${h} h ${m} min` : `${h} h`;
}

/** Seconds -> "3:11". */
function mss(s) {
	const n = Math.max(0, Math.round(Number(s) || 0));
	return `${Math.floor(n / 60)}:${String(n % 60).padStart(2, '0')}`;
}

function cap(s) {
	return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}

function quote(q) {
	return `“${q}”`;
}

const LOSSLESS = new Set(['FLAC', 'ALAC', 'WAV', 'AIFF', 'APE', 'WV']);

function extOf(ext, filename) {
	const e = (ext || (filename && filename.includes('.') ? filename.split('.').pop() : '') || '').toUpperCase();
	return e;
}

/**
 * "FLAC 29.4 MB" / "MP3 320, 9.2 MB" / "29.4 MB"; `comma` ("FLAC, 29.4 MB") for
 * the inside of a sentence.
 */
function fileWords(ext, size, bitRate, comma = false) {
	const e = (ext || '').toUpperCase();
	const sz = Number(size) > 0 ? `${mb(size)} MB` : '';
	const kind = e && bitRate && !LOSSLESS.has(e) ? `${e} ${bitRate}` : e;
	if (!kind) return sz;
	if (!sz) return kind;
	return `${kind}${comma || kind !== e ? ',' : ''} ${sz}`;
}

/** Who submitted a job, as the end of "Submitted by …". */
function submitter(ev, job) {
	const batch = ev?.batch || firstTrack(job).batch || null;
	const card = ev?.card || job?.card || null;
	if (batch && typeof batch === 'object') {
		const label = batch.label || '';
		switch (batch.kind) {
			case 'playlist': return 'the playlist import'; // the drawer's meta line names the playlist
			case 'scheduled': return `the ${label || sourceLabel(card)} run`;
			case 'recommendation': return 'the recommendations';
			case 'bulk': return label ? `“${label}”` : 'Download all';
			default: break;
		}
	}
	switch (card) {
		case 'dl:manual': return 'you, by hand';
		case 'dl:search': return 'you, from search';
		case 'dl': return 'the phone';
		case 'dl:playlist': return 'the playlist import';
		case 'dl:recommendation': return 'the recommendations';
		case null: case undefined: case '': return 'Zonik';
		default: return `the ${sourceLabel(card)} run`;
	}
}

const REJECT_PHRASES = [
	['title', (n) => `${n} by title`],
	['duration', (n) => `${n} by length`],
	['size', (n) => `${n} too small`],
	['ext', (n) => `${n} by format`],
	['quality', (n) => `${n} no better than yours`],
	['artist_path', (n) => `${n} by artist folder`],
	['score', (n) => `${n} as poor matches`],
];

function rejectedPhrase(rejected) {
	const parts = [];
	for (const [key, fn] of REJECT_PHRASES) {
		const n = Number(rejected?.[key]) || 0;
		if (n) parts.push(fn(n));
	}
	return parts.join(', ');
}

function searchedSentence(funnel, spanS) {
	const queries = Array.isArray(funnel?.queries) ? funnel.queries : [];
	const files = Number(funnel?.files_seen) || 0;
	const peers = Number(funnel?.peers_seen) || 0;
	const kept = Number(funnel?.kept) || 0;
	const trackQueries = queries.filter((q) => q?.kind !== 'album');
	let head;
	if (queries.length <= 1) head = `Searched ${quote(queries[0]?.q || trackQueries[0]?.q || 'the track')}`;
	else head = `Searched ${queries.length} ways${spanS >= 1 ? ` over ${durationPhrase(spanS)}` : ''}`;
	if (!files) return `${head}: no files found.`;
	const rej = rejectedPhrase(funnel?.rejected);
	const found = `${plural(files, 'file')} from ${plural(peers, 'peer')}`;
	if (!kept) return `${head}: ${found}. Nothing kept${rej ? `; rejected ${rej}` : ''}.`;
	return `${head}: ${found}. Kept ${kept}${rej ? `; rejected ${rej}` : ''}.`;
}

function candidateFor(candidates, i, user) {
	if (!Array.isArray(candidates)) return null;
	return candidates.find((c) => c?.username === user) || candidates[i - 1] || null;
}

function slotWords(c) {
	if (!c) return '';
	const bits = [];
	if (c.slots_free === true) bits.push('free slot');
	else if (Number(c.queue_length) > 0) bits.push(`${c.queue_length} in their queue`);
	if (Number(c.avg_speed) > 0) bits.push(`${formatSpeed(c.avg_speed)} on average`);
	return bits.join(', ');
}

// ---------------------------------------------------------------------------
// Timeline
// ---------------------------------------------------------------------------

function normaliseLog(log) {
	const v = parseMaybe(log);
	if (!Array.isArray(v)) return [];
	return v.filter((e) => e && typeof e === 'object' && typeof e.k === 'string');
}

function failedSentence(ev, job, peerFailures) {
	const cls = ev.class || failureClass(job);
	const err = ev.error || '';
	switch (cls) {
		case 'not_found': return 'Gave up: not found.';
		case 'no_better': return 'Gave up: no copy better than yours.';
		case 'rejected': return 'Gave up: the file was not imported.';
		case 'peer':
			if (peerFailures === 1) return 'Gave up: the only peer failed.';
			if (peerFailures > 1) return `Gave up: all ${peerFailures} peers failed.`;
			return 'Gave up: every peer failed.';
		case 'cancelled': return 'You cancelled it.';
		case 'infra':
			if (/Interrupted by restart/.test(err)) return 'Zonik restarted and ended it mid-flight.';
			if (/Soulseek server not connected/.test(err)) return 'Stopped: Soulseek was not connected.';
			return err ? `Stopped: ${err.replace(/\.$/, '')}.` : 'Stopped.';
		default:
			return err ? `Gave up: ${err.replace(/\.$/, '')}.` : 'Gave up.';
	}
}

function ledgerTail(job, nowMs) {
	const next = job?.next;
	const attempts = Number(job?.ledger?.attempts) || 0;
	if (!next || !next.kind || next.kind === 'none') return '';
	const nth = attempts ? `, ${ordinal(attempts)} failure` : '';
	if (next.kind === 'retry') {
		const when = next.at ? relativeIn(next.at, nowMs) : '';
		return ` Written to the retry ledger${nth}${when ? `, next try ${when}` : ''}.`;
	}
	if (next.kind === 'retired') return ` Written to the retry ledger${nth}; retired for a year.`;
	return '';
}

function doneSentence(ev, job) {
	const outcome = job?.outcome || (ev.already_in_library || job?.already_in_library ? 'already_had' : null);
	if (outcome === 'already_had') return 'Done. You already had it, so the file was discarded.';
	if (outcome === 'replaced') return 'Done. It replaced your old file.';
	const size = Number(ev.file_size) > 0 ? `, ${mb(ev.file_size)} MB` : '';
	return `Done. Added to your library${size}.`;
}

/** The live last row of a running job: what is happening now and for how long. */
function nowSentence(job, transfer, nowMs, limits) {
	const st = resolveStage(job, transfer || null, limits || null, nowMs);
	const t0 = firstTrack(job);
	const user = transfer?.username || job?.username || t0.username || 'the peer';
	const dur = durationPhrase(st.elapsedS || 0);
	switch (st.stage) {
		case 'queue_search': return { text: `Waiting for a search slot, ${dur} so far.`, colour: st.colour };
		case 'searching': {
			const s = parseMaybe(job?.search) || t0.search || null;
			if (s?.query_index) {
				return {
					text: `Query ${s.query_index} of ${s.query_total || '?'}: ${plural(Number(s.files_seen) || 0, 'file')} seen, ${Number(s.kept) || 0} kept so far.`,
					colour: st.colour,
				};
			}
			return { text: `Searching, ${dur} so far.`, colour: st.colour };
		}
		case 'peer_lock': return { text: `Waiting for ${user}, busy with another of your downloads, ${dur} so far.`, colour: st.colour };
		case 'waiting_slot': return { text: `Waiting for a transfer slot, ${dur} so far.`, colour: st.colour };
		case 'connecting': return { text: `Connecting to ${user}, ${dur} so far.`, colour: st.colour };
		case 'queued_at_peer': {
			const place = transfer?.queue_place ?? job?.queue_place ?? t0.queue_place;
			if (place != null) return { text: `Place ${place}. ${dur} in their queue so far.`, colour: st.colour };
			return { text: `Waiting for ${user} to start sending, ${dur} so far.`, colour: st.colour };
		}
		case 'transferring': {
			const bits = [];
			if (st.progress != null) bits.push(`${st.progress} % received`);
			else bits.push('Receiving');
			if (Number(transfer?.speed) > 0) bits.push(formatSpeed(transfer.speed));
			if (Number(transfer?.eta_seconds) > 0) bits.push(`about ${durationPhrase(transfer.eta_seconds)} left`);
			return { text: `${bits.join(', ')}.`, colour: st.colour };
		}
		case 'importing': return { text: `Importing: checking tags, duplicates and quality, ${dur} so far.`, colour: st.colour };
		default: return null;
	}
}

/**
 * The drawer's WHAT HAS HAPPENED SO FAR rows: `[{time, text, isNow, colour}]`.
 *
 * @param {Array|string|null} log  DC-2 events (parsed `timeline` or the raw `log` string)
 * @param {object} job             the job (detail payload or list item)
 * @param {number} [nowMs]
 * @param {object} [opts]          `{transfer, limits}` for the live last row
 *
 * A null/legacy log returns `[]`. While the job is live a final "now" row
 * says where it is (place in the peer's queue, query k of n, …); otherwise the
 * last event is the now row.
 */
export function timelineSentences(log, job, nowMs = Date.now(), opts = {}) {
	const events = normaliseLog(log);
	if (!events.length) return [];
	const out = [];
	const push = (ev, text, colour = null) => {
		const row = { time: clockSeconds(ev.t), text, isNow: false, colour, t: timeMs(ev.t) };
		out.push(row);
		return row;
	};
	const hasSearched = events.some((e) => e.k === 'searched');
	let candidates = parseMaybe(job?.candidates) || jobResult(job)?.candidates || null;
	let firstQueryMs = null;
	let attemptRow = null; // the row a transfer_slot / queued clause attaches to
	let requested = {}; // user -> {row, ms}
	let started = {}; // user -> {row, ms}
	let peerFailures = 0;

	events.forEach((ev, idx) => {
		const ms = timeMs(ev.t);
		switch (ev.k) {
			case 'submitted':
				push(ev, `Submitted by ${submitter(ev, job)}.`);
				break;
			case 'search_slot': {
				const w = Number(ev.waited_s) || 0;
				if (w >= 1) push(ev, `Waited ${durationPhrase(w)} for a search slot.`);
				break;
			}
			case 'reconnect_wait':
				push(ev, 'Waited for Soulseek to reconnect before searching.');
				break;
			case 'query_start':
				if (firstQueryMs == null) firstQueryMs = ms;
				if (!hasSearched && idx === events.length - 1) {
					push(ev, `Searching ${quote(ev.q)} (query ${ev.i} of ${ev.n}).`);
				}
				break;
			case 'query_end':
				if (firstQueryMs == null) firstQueryMs = ms;
				if (!hasSearched) {
					push(ev, `Searched ${quote(ev.q)}: ${plural(Number(ev.files) || 0, 'file')} from ${plural(Number(ev.peers) || 0, 'peer')} (query ${ev.i} of ${ev.n}).`);
				}
				break;
			case 'searched': {
				const span = firstQueryMs != null && ms != null ? (ms - firstQueryMs) / 1000 : 0;
				const funnel = ev.funnel || {};
				const kept = Number(funnel.kept) || 0;
				push(ev, searchedSentence(funnel, span), kept ? null : 'muted');
				break;
			}
			case 'picked':
				if (Array.isArray(ev.candidates) && ev.candidates.length) candidates = ev.candidates;
				break;
			case 'attempt': {
				const i = Number(ev.i) || 1;
				const c = candidateFor(candidates, i, ev.user);
				const file = fileWords(extOf(ev.ext || c?.extension, ev.filename), ev.size || c?.size, c?.bitRate, true);
				const slot = slotWords(c);
				const text = i === 1
					? `Picked ${ev.user}'s ${file || 'file'}${slot ? ` (${slot})` : ''}.`
					: `Moved on to the ${ordinal(i)} of ${ev.of || '?'} peers: ${ev.user}'s ${file || 'file'}${slot ? ` (${slot})` : ''}.`;
				attemptRow = push(ev, text);
				break;
			}
			case 'transfer_slot': {
				const w = Number(ev.waited_s) || 0;
				if (w < 1) break;
				const clause = `Waited ${durationPhrase(w)} for a transfer slot.`;
				if (attemptRow) attemptRow.text += ` ${clause}`;
				else push(ev, clause);
				break;
			}
			case 'peer_lock':
				break; // a stage move, not a story beat
			case 'peer_busy':
				if (ev.deferred) push(ev, `${ev.user} was busy with another of your downloads; trying other peers first.`, 'amber');
				else {
					peerFailures += 1;
					push(ev, `${ev.user} stayed busy with another of your downloads; gave up on them.`, 'rose');
				}
				break;
			case 'connecting':
				if (idx === events.length - 1) push(ev, `Connecting to ${ev.user}, direct and relayed.`);
				break;
			case 'requested':
				requested[ev.user] = { row: push(ev, `Asked ${ev.user} for the file.`), ms };
				attemptRow = null;
				break;
			case 'queued': {
				const clause = ev.place != null ? `They queued us at place ${ev.place}.` : 'They queued us.';
				const r = requested[ev.user];
				if (r) r.row.text += ` ${clause}`;
				else push(ev, `${ev.user} queued us${ev.place != null ? ` at place ${ev.place}` : ''}.`);
				break;
			}
			case 'connected':
			case 'transferring': {
				if (started[ev.user]) break;
				const r = requested[ev.user];
				const after = r?.ms != null && ms != null ? ` after ${durationPhrase((ms - r.ms) / 1000)}` : '';
				started[ev.user] = { row: push(ev, `${ev.user} started sending${after}.`), ms };
				break;
			}
			case 'peer_failed':
				peerFailures += 1;
				push(ev, `${cap(peerErrorClause(ev.user, ev.error))}.`, 'rose');
				break;
			case 'importing': {
				const s = started[ev.user];
				const bytes = Number(ev.bytes) || 0;
				if (s && s.ms != null && ms != null && bytes > 0) {
					const secs = Math.max(1, (ms - s.ms) / 1000);
					s.row.text += ` ${durationPhrase(secs)} at ${formatSpeed(bytes / secs)}.`;
				}
				push(ev, bytes > 0 ? `Received ${mb(bytes)} MB; importing.` : 'Importing.');
				break;
			}
			case 'done':
				push(ev, doneSentence(ev, job), 'emerald');
				break;
			case 'failed': {
				const cls = ev.class || failureClass(job);
				const muted = cls === 'infra' || cls === 'orphan' || cls === 'cancelled' || cls === 'not_found';
				push(ev, failedSentence(ev, job, peerFailures) + ledgerTail(job, nowMs), muted ? 'muted' : 'rose');
				break;
			}
			case 'cancelled':
				push(ev, 'You cancelled it.', 'muted');
				break;
			default:
				break;
		}
	});

	const live = job && (job.status === 'running' || job.status === 'pending');
	if (live) {
		const now = nowSentence(job, opts.transfer, nowMs, opts.limits);
		if (now) out.push({ time: clockSeconds(nowMs), text: now.text, isNow: true, colour: now.colour, t: nowMs });
	} else if (out.length) {
		out[out.length - 1].isNow = true;
	}
	return out.map(({ t, ...row }) => row);
}

// ---------------------------------------------------------------------------
// Search funnel, candidates, peers, schedule
// ---------------------------------------------------------------------------

/**
 * The SEARCHES block from a DC-5 `search` funnel: `{queries, segments, kept,
 * total, wanted}` or null without a funnel. Segments (bar + legend, in order):
 * wrong title (rose), length off (amber), under 3 MB (muted), other checks
 * (muted, only when non-zero) and kept (emerald); `count` 0 segments stay in the
 * legend but the bar drops them.
 */
export function funnelSegments(search) {
	const s = parseMaybe(search);
	if (!s || typeof s !== 'object') return null;
	const rej = s.rejected || {};
	const n = (k) => Number(rej[k]) || 0;
	const wanted = Number(s.wanted_duration) > 0 ? mss(s.wanted_duration) : null;
	const queries = (Array.isArray(s.queries) ? s.queries : []).map((q, i, all) => {
		const prev = all.slice(0, i).find((p) => p?.kind !== 'album' && p.q && q?.q && p.q.toLowerCase().startsWith(q.q.toLowerCase()) && p.q !== q.q);
		return {
			q: q?.q || '',
			kind: q?.kind || 'variant',
			prefix: q?.kind === 'album' ? 'album fallback' : '',
			suffix: q?.kind !== 'album' && prev ? 'shorter form' : '',
			files: Number(q?.files) || 0,
			peers: Number(q?.peers) || 0,
			error: q?.error || null,
		};
	});
	const other = n('ext') + n('quality') + n('score') + n('artist_path');
	const segments = [
		{ key: 'title', label: 'wrong title', detail: 'wrong title (other songs, live sets, mixes)', count: n('title'), colour: 'rose' },
		{
			key: 'duration',
			label: wanted ? `length off (wanted ${wanted})` : 'length off',
			detail: wanted ? `length off by more than 3 s (wanted ${wanted})` : 'length off by more than 3 s',
			count: n('duration'), colour: 'amber',
		},
		{ key: 'size', label: 'under 3 MB', detail: 'under 3 MB', count: n('size'), colour: 'muted' },
	];
	if (other) {
		segments.push({ key: 'other', label: 'other checks', detail: 'wrong format, artist or no better than yours', count: other, colour: 'muted' });
	}
	const kept = Number(s.kept) || 0;
	segments.push({ key: 'kept', label: 'kept', detail: 'kept', count: kept, colour: 'emerald' });
	const total = segments.reduce((a, g) => a + g.count, 0);
	return { queries, segments, kept, total, wanted, filesSeen: Number(s.files_seen) || 0, peersSeen: Number(s.peers_seen) || 0 };
}

/**
 * IF X DOESN'T DELIVER: the candidates after the current attempt (1-based),
 * `[{n, user, text}]` ("2nd", "dblbbr", "dblbbr · FLAC 28.9 MB · free slot").
 * With no attempt yet, every candidate after the first.
 */
export function candidateLines(candidates, attempt) {
	const list = parseMaybe(candidates);
	if (!Array.isArray(list)) return [];
	const from = Math.max(1, Number(attempt) || 1);
	return list.slice(from).filter((c) => c && c.username).map((c, k) => {
		const file = fileWords(extOf(c.extension, c.filename), c.size, c.bitRate);
		const slot = c.slots_free === true ? 'free slot' : Number(c.queue_length) > 0 ? `${c.queue_length} in their queue` : '';
		return { n: ordinal(from + k + 1), user: c.username, text: [c.username, file, slot].filter(Boolean).join(' · ') };
	});
}

/**
 * PEERS: one clause per peer from DC-19 `peers` `{user: {successes, failures,
 * score, recent_failure}}`: `[{user, text}]` where the drawer renders
 * `<b>user</b> text`. Empty when the map is empty (reputation resets on restart).
 */
export function peerSentences(peers) {
	const map = parseMaybe(peers);
	if (!map || typeof map !== 'object' || Array.isArray(map)) return [];
	return Object.entries(map).filter(([u, p]) => u && p && typeof p === 'object').map(([user, p]) => {
		const s = Number(p.successes) || 0;
		const f = Number(p.failures) || 0;
		let text;
		if (!s && !f) text = 'first contact';
		else if (!s) text = `has failed you ${f === 1 ? 'once' : `${f} times`} and never delivered`;
		else if (!f) text = `has delivered ${s} of ${s}`;
		else text = `has delivered ${s}, failed ${f}`;
		if (p.recent_failure && f) text += ' (failed in the last 30 min)';
		return { user, text };
	});
}

function daysWord(d) {
	const n = Number(d);
	if (n === 365) return 'a year';
	if (n === 1) return '1 day';
	return `${n} days`;
}

function joinAnd(items) {
	if (items.length <= 1) return items.join('');
	return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`;
}

/**
 * The schedule sentence of a failed tracked download, from DC-7 `ledger`/`next`
 * and DC-12 `limits` (`backoff_days`, `retired_days`). '' when the job did not fail.
 * "9th failure for this track. Zonik tries again in 30 days (Nov 17), then stops for a year."
 */
export function scheduleSentence(job, limits, nowMs = Date.now()) {
	if (!job || job.status !== 'failed') return '';
	const cls = failureClass(job);
	const next = job.next || null;
	const attempts = Number(job.ledger?.attempts) || Number(next?.attempts) || 0;
	const backoff = Array.isArray(limits?.backoff_days) && limits.backoff_days.length ? limits.backoff_days : [1, 7, 30];
	const retired = daysWord(Number(limits?.retired_days) || 365);
	const head = attempts <= 1 ? 'First failure for this track.' : `${cap(ordinal(attempts))} failure for this track.`;

	if (!next || !next.kind || next.kind === 'none') {
		if (cls === 'cancelled' || cls === 'infra' || cls === 'orphan') return 'Not counted against the track; nothing retries it on its own.';
		return 'Nothing retries it on its own.';
	}
	if (next.kind === 'retry') {
		const when = next.at ? relativeIn(next.at, nowMs) : '';
		const date = next.at && when && when !== 'with the next run' ? ` (${shortDate(next.at)})` : '';
		const rest = backoff.slice(Math.max(1, attempts)).map(Number).filter((d) => d > 0);
		const after = rest.length === 1 ? daysWord(rest[0]) : `${joinAnd(rest.map(String))} days`;
		const then = rest.length ? `, then after ${after}, then stops for ${retired}` : `, then stops for ${retired}`;
		return `${head} Zonik tries again ${when || 'on its own'}${date}${then}.`;
	}
	if (next.kind === 'retired') {
		const until = job.ledger?.next_retry_at ? ` (until ${shortDate(job.ledger.next_retry_at)})` : '';
		return `${head} Zonik has stopped trying for ${retired}${until}.`;
	}
	if (next.kind === 'scans') {
		const a = Number(next.attempts) || 0;
		const m = Number(next.max_attempts) || 0;
		if (m && a >= m) return `Upgrade scan ${a} of ${m}; this upgrade is retired.`;
		return m ? `Upgrade scan ${a} of ${m}; the next upgrade scan tries again.` : 'The next upgrade scan tries again.';
	}
	return '';
}

// ---------------------------------------------------------------------------
// Drawer helpers: state sentence, live candidates and queries
// ---------------------------------------------------------------------------

/** The candidates of the latest `picked` event (live jobs have no result yet). */
export function pickedCandidates(log) {
	const events = normaliseLog(log);
	for (let i = events.length - 1; i >= 0; i -= 1) {
		if (events[i].k === 'picked' && Array.isArray(events[i].candidates)) return events[i].candidates;
	}
	return [];
}

/** Queries finished so far from the `query_end` events: `[{q, kind, files, peers}]`. */
export function liveQueries(log) {
	return normaliseLog(log).filter((e) => e.k === 'query_end').map((e) => ({
		q: e.q || '', kind: e.kind || 'variant', files: Number(e.files) || 0, peers: Number(e.peers) || 0,
	}));
}

function limitWords(s) {
	const n = Number(s) || 0;
	return n >= 60 && n % 60 === 0 ? `${n / 60} min` : `${n} s`;
}

const CLASS_HEAD = {
	not_found: 'Not found.',
	no_better: 'Nothing better.',
	rejected: 'Not imported.',
	peer: 'Peers failed.',
	cancelled: 'Cancelled.',
	infra: "Not the track's fault.",
	orphan: 'Stopped.',
};

function qualityWords(track) {
	if (!track) return '';
	const f = (track.format || '').toUpperCase();
	const bits = [];
	if (f) bits.push(f);
	if (Number(track.file_size) > 0) bits.push(`${mb(track.file_size)} MB`);
	if (Number(track.bitrate) > 0) bits.push(`${Number(track.bitrate).toLocaleString('en-US')} kbps`);
	if (Number(track.duration_seconds) > 0) bits.push(mss(track.duration_seconds));
	return bits.join(', ');
}

function playedWords(track) {
	const n = Number(track?.play_count) || 0;
	if (!track) return '';
	if (!n) return 'Not played yet.';
	const times = n === 1 ? 'once' : n === 2 ? 'twice' : `${n} times`;
	const last = track.last_played_at ? `, last at ${clockSeconds(track.last_played_at).slice(0, 5)}` : '';
	return `Played ${times}${last}.`;
}

/**
 * The drawer's state sentence: `{em, text, colour}` — `em` is the coloured lead
 * ("In DJ-Promo's upload queue"), `text` follows it. Live jobs read the
 * resolver; failed ones the class, the failure sentence and the schedule; done
 * ones the outcome and the library row.
 */
export function stateSentence(job, transfer = null, limits = null, nowMs = Date.now()) {
	if (!job) return { em: '', text: '', colour: 'muted' };
	if (job.status === 'failed') {
		const cls = failureClass(job) || 'orphan';
		const why = failureSentenceFor(job);
		const sched = scheduleSentence(job, limits, nowMs);
		const colour = cls === 'peer' || cls === 'rejected' ? 'rose' : 'muted';
		const body = [why ? `${cap(why)}.` : '', sched].filter(Boolean).join(' ');
		return { em: CLASS_HEAD[cls] || 'Failed.', text: body ? ` ${body}` : '', colour };
	}
	if (job.status === 'completed') {
		const outcome = job.outcome || (job.already_in_library ? 'already_had' : 'new');
		const q = qualityWords(job.track);
		if (outcome === 'already_had') return { em: 'You already had this.', text: 'Nothing was added; the downloaded copy was discarded.', colour: 'muted' };
		const played = playedWords(job.track);
		if (outcome === 'replaced') {
			const u = job.upgrade;
			const from = u ? [u.original_format, u.original_bitrate].filter(Boolean).join(' ') : '';
			const what = from ? `your ${from}` : 'your old file';
			return { em: 'Replaced', text: ` ${what}${q ? ` with ${q}` : ''}.${played ? ` ${played}` : ''}`, colour: 'emerald' };
		}
		return { em: 'Added to your library', text: `${q ? ` as ${q}` : ''}.${played ? ` ${played}` : ''}`, colour: 'emerald' };
	}

	const st = resolveStage(job, transfer, limits, nowMs);
	const t0 = firstTrack(job);
	const user = transfer?.username || job.username || t0.username || 'the peer';
	const attempt = Number(job.attempt ?? t0.attempt) || 0;
	const of = Number(job.of ?? t0.of) || 0;
	const elapsed = durationPhrase(st.elapsedS || 0);
	const allowed = st.limitS ? `, for ${elapsed} of the ${limitWords(st.limitS)} allowed` : `, ${elapsed} so far`;
	const moveOn = attempt && of && attempt < of ? 'Zonik moves on to the next peer' : 'Zonik gives up on this peer';
	switch (st.stage) {
		case 'queue_search':
			return { em: 'Waiting for a search slot', text: `${allowed}; ${st.detail}.`, colour: st.colour };
		case 'searching':
			return { em: 'Searching', text: `: ${st.detail}.`, colour: st.colour };
		case 'peer_lock':
			return { em: 'Waiting for the peer', text: `: ${st.detail}${allowed}.`, colour: st.colour };
		case 'waiting_slot':
			return { em: 'Waiting for a transfer slot', text: `: ${st.detail}${allowed}.`, colour: st.colour };
		case 'connecting':
			return { em: `Connecting to ${user}`, text: `, direct and relayed${allowed}. If neither works by then, ${moveOn}.`, colour: st.colour };
		case 'queued_at_peer': {
			const place = transfer?.queue_place ?? job.queue_place ?? t0.queue_place;
			if (place != null) {
				return { em: `In ${user}'s upload queue`, text: ` at place ${place}${allowed}. If they haven't started sending by then, ${moveOn}.`, colour: st.colour };
			}
			return { em: `Asked ${user}`, text: `, waiting for the upload to start${allowed}. If they haven't started sending by then, ${moveOn}.`, colour: st.colour };
		}
		case 'transferring':
			return { em: `Transferring from ${user}`, text: `: ${st.detail} · ${st.big}.`, colour: st.colour };
		case 'importing':
			return { em: 'Importing', text: `: ${st.detail}.`, colour: st.colour };
		default:
			return { em: st.word, text: st.detail ? `: ${st.detail}.` : '', colour: st.colour };
	}
}
