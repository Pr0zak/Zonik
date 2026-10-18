/**
 * Downloads page: the stage resolver and the copy table every row reads.
 *
 * Pure module: no Svelte imports, so vitest can run it in node. Every sentence
 * a download row shows is built here from the server's structured fields
 * (`stage`, `attempt`/`of`, `source_errors`, `search`, `failure_class`, `next`,
 * `outcome`, …; see plans/downloads-feedback-ui/phase4-plan.md DC-1, DC-5..DC-7,
 * DC-12, DC-18). Regexes over raw strings exist only as a fallback for rows
 * written before those fields existed (`failure_class` null).
 */
import { formatSize, formatSpeed, parseUTC } from '../utils.js';

// ---------------------------------------------------------------------------
// Source labels
// ---------------------------------------------------------------------------

/** Job `card` -> short source label shown in the source chip. */
export const SOURCE_LABELS = {
	'dl:upgrade': 'Upgrade',
	'dl:discovery': 'Discovery',
	'dl:similar': 'Similar',
	'dl:remix': 'Remix',
	'dl:recommendation': 'For You',
	'dl:playlist': 'Playlist',
	'dl:manual': 'Manual',
	'dl:weekly-radar': 'Weekly Radar',
	'dl:radar': 'Radar',
	'dl:new-releases': 'New Releases',
	'dl:search': 'Search',
	'dl:worker': 'Worker',
	dl: 'Phone',
	'dl:library': 'Library',
	'dl:upgrade_scan': 'Upgrade scan',
};

/**
 * Label for a job's source. Accepts a card string or a job object. Never empty:
 * an unknown card falls back to the card without its `dl:` prefix, a missing
 * card to "Download".
 */
export function sourceLabel(cardOrJob) {
	const card = typeof cardOrJob === 'string' ? cardOrJob : cardOrJob?.card;
	if (!card) return 'Download';
	if (SOURCE_LABELS[card]) return SOURCE_LABELS[card];
	const bare = card.replace(/^dl:/, '');
	return bare || 'Download';
}

// ---------------------------------------------------------------------------
// Small formatters
// ---------------------------------------------------------------------------

/** 1 -> "1st", 2 -> "2nd", 11 -> "11th", 23 -> "23rd". */
export function ordinal(n) {
	const v = Math.trunc(Number(n));
	if (!Number.isFinite(v)) return '';
	const abs = Math.abs(v);
	const mod100 = abs % 100;
	if (mod100 >= 11 && mod100 <= 13) return `${v}th`;
	switch (abs % 10) {
		case 1: return `${v}st`;
		case 2: return `${v}nd`;
		case 3: return `${v}rd`;
		default: return `${v}th`;
	}
}

/**
 * Seconds -> compact duration for the mono cells:
 * 48 -> "48 s", 185 -> "3 m 05 s", 4380 -> "1 h 13 m", 100000 -> "1 d 3 h".
 */
export function formatDurationWords(s) {
	if (s == null || !Number.isFinite(Number(s))) return '';
	const sec = Math.max(0, Math.floor(Number(s)));
	if (sec < 60) return `${sec} s`;
	if (sec < 3600) {
		const m = Math.floor(sec / 60);
		return `${m} m ${String(sec % 60).padStart(2, '0')} s`;
	}
	if (sec < 86400) {
		const h = Math.floor(sec / 3600);
		return `${h} h ${String(Math.floor((sec % 3600) / 60)).padStart(2, '0')} m`;
	}
	const d = Math.floor(sec / 86400);
	return `${d} d ${Math.floor((sec % 86400) / 3600)} h`;
}

/** Naive-UTC ISO from the API -> local "HH:MM" (24 h). Empty when missing. */
export function clockTime(iso) {
	const d = typeof iso === 'number' ? new Date(iso) : parseUTC(iso);
	if (!d || Number.isNaN(d.getTime())) return '';
	return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

/** Naive-UTC ISO -> local "Oct 1". */
export function shortDate(iso) {
	const d = parseUTC(iso);
	if (!d || Number.isNaN(d.getTime())) return '';
	return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function plural(n, one, many = `${one}s`) {
	return `${n} ${n === 1 ? one : many}`;
}

function mb(bytes) {
	return (Math.max(0, Number(bytes) || 0) / 1048576).toFixed(1);
}

// ---------------------------------------------------------------------------
// Job field access (list item, WS job_update payload or job detail)
// ---------------------------------------------------------------------------

function parseMaybe(v) {
	if (v == null) return null;
	if (typeof v !== 'string') return v;
	try { return JSON.parse(v); } catch { return null; }
}

/** `tracks[0]` of a job as an object (`{}` when absent or unparseable). */
export function firstTrack(job) {
	const tracks = parseMaybe(job?.tracks);
	return Array.isArray(tracks) && tracks[0] && typeof tracks[0] === 'object' ? tracks[0] : {};
}

/** `Job.result` as an object (`null` when absent or unparseable). */
export function jobResult(job) {
	const r = parseMaybe(job?.result);
	return r && typeof r === 'object' && !Array.isArray(r) ? r : null;
}

/** A field from the job's top level first (list items, WS), then `tracks[0]`. */
function field(job, t0, key) {
	const v = job?.[key];
	return v !== undefined && v !== null ? v : t0[key] ?? null;
}

function sourceErrorsOf(job, t0, result) {
	const fromJob = parseMaybe(job?.source_errors);
	if (Array.isArray(fromJob) && fromJob.length) return fromJob;
	if (Array.isArray(result?.source_errors) && result.source_errors.length) return result.source_errors;
	if (Array.isArray(t0.source_errors) && t0.source_errors.length) return t0.source_errors;
	return [];
}

// ---------------------------------------------------------------------------
// Stage limits
// ---------------------------------------------------------------------------

/** Defaults (seconds), used when GET /api/download/status has no `limits` yet. */
export const STAGE_LIMITS = {
	connecting: 20,
	peer_lock: 60,
	queued_at_peer: 120,
	transferring: 60, // no-data stall limit
	importing: 10,
};

/** STAGE_LIMITS resolved against DC-12 `limits` (missing keys keep the defaults). */
export function resolveStageLimits(limits) {
	const l = limits || {};
	const num = (v, d) => (Number.isFinite(Number(v)) && Number(v) > 0 ? Number(v) : d);
	return {
		connecting: num(l.peer_connect_s, STAGE_LIMITS.connecting),
		peer_lock: num(l.peer_busy_wait_s, STAGE_LIMITS.peer_lock),
		queued_at_peer: num(l.peer_queue_s, STAGE_LIMITS.queued_at_peer),
		transferring: num(l.stall_s, STAGE_LIMITS.transferring),
		importing: STAGE_LIMITS.importing,
	};
}

/** The eight live stages, pipeline order (furthest from done first). */
export const LIVE_STAGES = [
	'queue_search', 'searching', 'peer_lock', 'waiting_slot',
	'connecting', 'queued_at_peer', 'transferring', 'importing',
];

const TRANSFER_STAGES = new Set(['connecting', 'queued_at_peer', 'transferring']);

/** Soulseek transfer state -> page stage (DC-18). */
const TRANSFER_STATE_STAGE = {
	requested: 'queued_at_peer',
	queued: 'queued_at_peer',
	connected: 'connecting',
	transferring: 'transferring',
};

/** A transferring row counts as stalled after this long without bytes. */
export const NO_DATA_AFTER_MS = 5000;
/** Below this fraction of the session's median speed a transfer is "slow". */
export const SLOW_FRACTION = 0.1;

// ---------------------------------------------------------------------------
// Failure classification (legacy fallback mirror of DC-6) and sentences
// ---------------------------------------------------------------------------

const INFRA_PREFIXES = [
	'Soulseek download backend unreachable',
	'Soulseek server not connected',
	'Interrupted by restart',
	'Internal error:',
	'Soulseek native client not available',
];

function isInfraError(text) {
	const e = (text || '').trim();
	return e === 'Cancelled by user' || INFRA_PREFIXES.some((p) => e.startsWith(p));
}

/**
 * The job's failure class: the server's `failure_class` when present, else the
 * same rules as backend/services/download_failures.failure_class over the raw
 * strings (rows written before the field existed). `null` unless failed.
 */
export function failureClass(job) {
	if (!job || job.status !== 'failed') return null;
	if (job.failure_class) return job.failure_class;
	const result = jobResult(job);
	if (!result) {
		// A WS final payload carries `error` instead of the result string.
		if (!job.error) return 'orphan';
		return classifyText(job.error, firstTrack(job).error, job.error);
	}
	const error = typeof result.error === 'string' ? result.error : '';
	const message = typeof result.message === 'string' ? result.message : '';
	if (error === 'Cancelled by user') return 'cancelled';
	return classifyText(error || message, firstTrack(job).error, message);
}

function classifyText(errorOrMessage, trackError, message) {
	if ((errorOrMessage || '').trim() === 'Cancelled by user') return 'cancelled';
	if (isInfraError(errorOrMessage)) return 'infra';
	const msg = (message || '').trim();
	if (msg.startsWith('No results for') || msg.startsWith('No other sources for')) return 'not_found';
	if (msg.startsWith('No source better than')) return 'no_better';
	const te = (typeof trackError === 'string' ? trackError : '').trim();
	if (te.startsWith('Not imported:') || te.includes('Import rejected') || msg.startsWith('Not imported:')) return 'rejected';
	return 'peer';
}

const DENIAL_REASONS = /^(too many (files|megabytes)|file not shared|banned|disallowed extension|pending shutdown|file read error|remote file error|queue full)/i;

/** One clause for one peer's error: "DJ-Promo queued us at place 7, then nothing for 120 s". */
export function peerErrorClause(user, error) {
	const who = user && user !== 'unknown' ? user : 'a peer';
	const e = (error || '').trim();
	let m;
	if (!e) return `${who} failed`;
	if ((m = e.match(/^Peer never answered in (\d+) s/i))) return `${who} never answered in ${m[1]} s`;
	if ((m = e.match(/^Peer queued us \(place (\d+)\) but did not start in (\d+) s/i)))
		return `${who} queued us at place ${m[1]}, then nothing for ${m[2]} s`;
	if ((m = e.match(/^Peer queued us but did not start in (\d+) s/i))) return `${who} queued us, then nothing for ${m[1]} s`;
	if (/^Peer did not respond in time/i.test(e)) return `${who} never answered`;
	if (/^Queue timeout/i.test(e)) return `${who} queued us, then never started`;
	if (/^Connection timeout/i.test(e)) return `${who} could not be reached, direct or relayed`;
	if (/^Connection failed/i.test(e)) return `${who} refused the connection`;
	if (/^Peer busy with another download/i.test(e)) return `${who} was busy with another of your downloads`;
	if ((m = e.match(/^Not imported:\s*(.*)$/i))) return `${who}'s file was not imported (${m[1] || 'no reason given'})`;
	if (/Import rejected/i.test(e)) return `${who}'s file was empty, truncated or unreadable`;
	if (/^No data received/i.test(e)) return `${who} connected but sent no data`;
	if ((m = e.match(/^Incomplete:\s*(\d+)\/(\d+)/i))) {
		const pct = Number(m[2]) > 0 ? Math.floor((Number(m[1]) / Number(m[2])) * 100) : 0;
		return `${who} stopped sending at ${pct} %`;
	}
	if (/^cancel+ed$/i.test(e)) return `${who} cancelled the upload`;
	if (DENIAL_REASONS.test(e)) return `${who} refused “${e.replace(/\.$/, '')}”`;
	return `${who}: ${e}`;
}

const REJECT_WORDS = [
	['title', 'wrong title'],
	['duration', 'wrong length'],
	['size', 'wrong size'],
	['ext', 'wrong format'],
	['quality', 'low quality'],
	['artist_path', 'wrong artist'],
	['score', 'poor match'],
];

function notFoundSentence(search, message) {
	if (!search || typeof search !== 'object') {
		if (/^No other sources for/i.test(message || '')) return 'No other peer shared a matching file';
		return 'No peer shared a file that passed the title, length and quality checks';
	}
	const queries = Array.isArray(search.queries) ? search.queries.length : 0;
	const head = `${plural(queries, 'query', 'queries')}${search.album_query ? ' + album query' : ''}`;
	const seen = Number(search.files_seen) || 0;
	const kept = Number(search.kept) || 0;
	if (!seen) return `${head}, no files found`;
	const rejected = search.rejected || {};
	const parts = [`${seen} seen`];
	for (const [key, word] of REJECT_WORDS) {
		const n = Number(rejected[key]) || 0;
		if (n) parts.push(`${n} ${word}`);
	}
	return `${head}, ${kept} files kept · ${parts.join(', ')}`;
}

function peersSentence(errors) {
	const clauses = errors.map((e) => peerErrorClause(e?.user, e?.error));
	return `${plural(errors.length, 'peer')}: ${clauses.join(' · ')}`;
}

const STOPPED_AT = {
	queue_search: 'while waiting to search',
	searching: 'while searching',
	peer_lock: 'while waiting for the peer',
	waiting_slot: 'while waiting for a transfer slot',
	connecting: 'while connecting',
	queued_at_peer: 'in a peer\'s queue',
	transferring: 'mid-transfer',
	importing: 'while importing',
};

function cancelledWhere(stage, user) {
	switch (stage) {
		case 'queued_at_peer': return user ? ` while it sat in ${user}'s queue` : ' while it sat in a peer\'s queue';
		case 'transferring': return user ? ` while transferring from ${user}` : ' mid-transfer';
		case 'connecting': return user ? ` while connecting to ${user}` : ' while connecting';
		case 'searching': return ' while it was searching';
		case 'queue_search': return ' before it searched';
		case 'waiting_slot': return ' while it waited for a transfer slot';
		case 'peer_lock': return ' while it waited for the peer';
		case 'importing': return ' while importing';
		default: return '';
	}
}

/**
 * "What happened" for a failed row (wraps, never truncated). Empty string for a
 * job that did not fail.
 */
export function failureSentence(job) {
	const cls = failureClass(job);
	if (!cls) return '';
	const t0 = firstTrack(job);
	const result = jobResult(job) || {};
	const message = typeof result.message === 'string' ? result.message : '';
	const errors = sourceErrorsOf(job, t0, result);
	const stage = field(job, t0, 'stage');
	const user = field(job, t0, 'username') || result.username || null;
	const at = job.finished_at || job.started_at;
	const search = parseMaybe(job.search) || result.search || null;

	switch (cls) {
		case 'not_found':
			return notFoundSentence(search, message);
		case 'no_better': {
			const what = message.replace(/^No source better than\s*/i, '').replace(/\s+for\s+.*$/i, '').trim()
				|| 'the current file';
			const copies = Number(search?.files_seen) || (Array.isArray(result.candidates) ? result.candidates.length : 0);
			const yours = what.replace(/^the current\s*/i, 'your ');
			return copies ? `${plural(copies, 'copy', 'copies')} found, none better than ${yours}` : `No source better than ${yours}`;
		}
		case 'rejected': {
			if (errors.length) return peersSentence(errors);
			const why = (t0.error || message || '').replace(/^Not imported:\s*/i, '').trim();
			return why ? `The file arrived but was not imported (${why})` : 'The file arrived but was not imported';
		}
		case 'peer': {
			if (errors.length) return peersSentence(errors);
			const failed = parseMaybe(job.failed_sources) || result.failed_sources || [];
			const err = result.last_error || result.error || t0.error || job.error || message;
			if (Array.isArray(failed) && failed.length === 1) return `1 peer: ${peerErrorClause(failed[0], err)}`;
			if (Array.isArray(failed) && failed.length > 1) {
				return `${plural(failed.length, 'peer')} failed${err ? ` · last: ${peerErrorClause(failed[failed.length - 1], err)}` : ''}`;
			}
			if (user) return `1 peer: ${peerErrorClause(user, err)}`;
			return err || 'A peer had the file but did not deliver it';
		}
		case 'cancelled':
			return `You cancelled it${at ? ` at ${clockTime(at)}` : ''}${cancelledWhere(stage, user)}`;
		case 'infra': {
			const text = result.error || message || job.error || '';
			const when = at ? ` at ${clockTime(at)}` : '';
			if (/Interrupted by restart/.test(text)) return `Zonik restarted${when} and ended it mid-flight · not the track's fault`;
			if (/Soulseek server not connected/.test(text)) return `Soulseek was not connected${when} · not the track's fault`;
			if (/native client not available/.test(text)) return `The Soulseek client was not running${when} · not the track's fault`;
			if (/backend unreachable/.test(text)) return `The download service was unreachable${when} · not the track's fault`;
			if (/Internal error:/.test(text)) return `Zonik hit an internal error${when} (${text.replace(/^.*Internal error:\s*/, '')}) · not the track's fault`;
			if (text === 'Cancelled by user') return `You cancelled it${when}${cancelledWhere(stage, user)}`;
			return `${text || 'Stopped'}${when} · not the track's fault`;
		}
		case 'orphan':
		default: {
			const where = STOPPED_AT[stage] ? ` ${STOPPED_AT[stage]}` : '';
			const date = at ? ` on ${shortDate(at)}` : '';
			let tail = '';
			if (stage === 'transferring' && user) tail = ` (from ${user})`;
			return `Stopped${where}${date} with no reason recorded${tail}`;
		}
	}
}

// ---------------------------------------------------------------------------
// Done outcome and next-try sentence
// ---------------------------------------------------------------------------

function qualityLabel(format, bitrate) {
	const f = (format || '').toUpperCase();
	if (!f) return bitrate ? `${bitrate} kbps` : '';
	return bitrate && !['FLAC', 'ALAC', 'WAV', 'AIFF', 'APE', 'WV'].includes(f) ? `${f} ${bitrate}` : f;
}

/**
 * Outcome of a completed download: `{kind: new|replaced|already_had, label,
 * badgeVariant}` (Badge variants). `null` for jobs that did not complete.
 */
export function doneOutcome(job) {
	if (!job || job.status !== 'completed') return null;
	const result = jobResult(job) || {};
	let kind = job.outcome;
	if (!kind) {
		if (job.already_in_library || result.already_in_library) kind = 'already_had';
		else if (job.upgrade?.status === 'completed' || job.card === 'dl:upgrade') kind = 'replaced';
		else kind = 'new';
	}
	if (kind === 'already_had') return { kind, label: 'Already had · file discarded', badgeVariant: 'default' };
	if (kind === 'replaced') {
		const u = job.upgrade;
		const from = u ? qualityLabel(u.original_format, u.original_bitrate) : '';
		const to = u ? qualityLabel(u.upgraded_format || job.track?.format, u.upgraded_bitrate) : '';
		const label = from && to ? `Replaced · ${from} → ${to}` : 'Replaced';
		return { kind, label, badgeVariant: 'info' };
	}
	return { kind: 'new', label: 'New', badgeVariant: 'success' };
}

function relativeIn(atIso, nowMs) {
	const at = parseUTC(atIso);
	if (!at || Number.isNaN(at.getTime())) return '';
	const diffS = (at.getTime() - nowMs) / 1000;
	if (diffS <= 0) return 'with the next run';
	const days = Math.round(diffS / 86400);
	if (days >= 1) return `in ${plural(days, 'day')}`;
	const hours = Math.round(diffS / 3600);
	if (hours >= 1) return `in ${plural(hours, 'hour')}`;
	return `in ${plural(Math.max(1, Math.round(diffS / 60)), 'minute')}`;
}

/**
 * The NEXT cell of a failed row from DC-7 `next`: `{text, tone}` with tone
 * `rose` (retired), `muted` (nothing scheduled) or `default`.
 */
export function nextSentence(job, nowMs = Date.now()) {
	if (!job || job.status !== 'failed') return { text: '', tone: 'muted' };
	const next = job.next;
	if (!next || !next.kind || next.kind === 'none') return { text: 'nothing scheduled', tone: 'muted' };
	if (next.kind === 'retired') return { text: 'retired for a year', tone: 'rose' };
	if (next.kind === 'scans') {
		const a = Number(next.attempts) || 0;
		const m = Number(next.max_attempts) || 0;
		if (m && a >= m) return { text: `${a} of ${m} scans · upgrade retired`, tone: 'rose' };
		return { text: m ? `${a} of ${m} scans` : `${plural(a, 'scan')} so far`, tone: 'default' };
	}
	if (next.kind === 'retry') {
		const when = next.at ? relativeIn(next.at, nowMs) : '';
		return { text: when ? `retries ${when}` : 'retries on its own', tone: 'default' };
	}
	return { text: 'nothing scheduled', tone: 'muted' };
}

// ---------------------------------------------------------------------------
// The resolver
// ---------------------------------------------------------------------------

function attemptLine(attempt, of) {
	if (attempt && of) return `attempt ${attempt} of ${of}`;
	if (attempt) return `attempt ${attempt}`;
	return '';
}

function slotsBusy(n) {
	if (n === 1) return 'the transfer slot is busy';
	if (n === 2) return 'both slots busy';
	return n ? `all ${n} slots busy` : 'all slots busy';
}

function toMs(v) {
	if (v == null) return null;
	if (typeof v === 'number') return v * 1000; // epoch seconds (Transfer.to_dict)
	const d = parseUTC(v);
	return d && !Number.isNaN(d.getTime()) ? d.getTime() : null;
}

/**
 * Resolve what a row is doing right now.
 *
 * @param {object} job       list item / WS job (may be null for a bare transfer)
 * @param {object} transfer  matching `transfer_progress` entry (DC-4) or null
 * @param {object} limits    DC-12 `limits` (or null: defaults apply)
 * @param {number} nowMs     current time (ms), the page's 1 s tick
 * @param {object} [ctx]     `{pacer, medianSpeed}` from GET /api/download/status
 * @returns {{stage, word, colour, detail, big, small, amber, progress, elapsedS, limitS}}
 *
 * Precedence (DC-18): job completed/failed -> the job's stage (`stage`, else
 * `tracks[0].stage`) -> transfer.state -> pending -> searching. Inside the
 * transfer phase (connecting / queued_at_peer / transferring) a live transfer's
 * state refines the stored stage, since transfer_progress arrives first.
 */
export function resolveStage(job, transfer, limits, nowMs = Date.now(), ctx = {}) {
	const t0 = firstTrack(job);
	const lim = resolveStageLimits(limits);
	const now = Number(nowMs) || Date.now();

	if (job?.status === 'completed') {
		const o = doneOutcome(job);
		return {
			stage: 'completed', word: 'Done', colour: 'emerald', detail: o?.label || '',
			big: clockTime(job.finished_at), small: '', amber: false, progress: 100, elapsedS: null, limitS: null,
		};
	}
	if (job?.status === 'failed') {
		const cls = failureClass(job);
		const cancelled = cls === 'cancelled';
		return {
			stage: 'failed', word: cancelled ? 'Cancelled' : 'Failed', colour: cancelled || cls === 'infra' || cls === 'orphan' ? 'muted' : 'rose',
			detail: failureSentence(job), big: clockTime(job.finished_at), small: '', amber: false,
			progress: null, elapsedS: null, limitS: null,
		};
	}

	const storedStage = field(job, t0, 'stage');
	const transferStage = transfer ? TRANSFER_STATE_STAGE[transfer.state] || null : null;
	let stage = storedStage && LIVE_STAGES.includes(storedStage) ? storedStage : null;
	let fromTransfer = false;
	if (transferStage && (!stage || TRANSFER_STAGES.has(stage))) {
		fromTransfer = stage !== transferStage || !field(job, t0, 'stage_since');
		stage = transferStage;
	}
	if (!stage) stage = job?.status === 'pending' ? 'queue_search' : 'searching';

	const stageSinceMs = toMs(field(job, t0, 'stage_since'));
	const transferSinceMs = toMs(transfer?.state_since);
	const startedMs = toMs(job?.started_at);
	const sinceMs = (fromTransfer ? transferSinceMs ?? stageSinceMs : stageSinceMs ?? transferSinceMs) ?? startedMs;
	const elapsedS = sinceMs != null ? Math.max(0, Math.floor((now - sinceMs) / 1000)) : 0;
	const elapsed = formatDurationWords(elapsedS);

	const attempt = field(job, t0, 'attempt');
	const of = field(job, t0, 'of');
	const peer = transfer?.username || field(job, t0, 'username') || null;
	const attemptText = attemptLine(attempt, of);

	const out = {
		stage, word: '', colour: 'amber', detail: '', big: elapsed, small: attemptText,
		amber: false, progress: null, elapsedS, limitS: null,
	};
	const withLimit = (limitS) => {
		out.limitS = limitS;
		out.big = `${elapsedS} s of ${limitS} s`;
		out.amber = elapsedS >= 0.75 * limitS;
	};

	switch (stage) {
		case 'queue_search': {
			const nextIn = Number(ctx?.pacer?.next_slot_in_s);
			out.word = 'Waiting to search';
			out.colour = 'muted';
			out.detail = nextIn > 0 ? `next search opens in ${Math.ceil(nextIn)} s` : 'waiting for a search slot';
			out.small = 'in line for a search';
			break;
		}
		case 'searching': {
			const s = parseMaybe(job?.search) || t0.search || null;
			out.word = 'Searching';
			out.colour = 'indigo';
			if (s && s.query_index) {
				const q = s.query ? ` “${s.query}”` : '';
				const seen = Number(s.files_seen) || 0;
				const kept = Number(s.kept) || 0;
				out.detail = `query ${s.query_index} of ${s.query_total || '?'}${q} · ${seen} files seen, ${kept} kept`;
				out.big = `query ${s.query_index} of ${s.query_total || '?'} · ${elapsed}`;
				const rem = (Number(s.query_total) || 0) - Number(s.query_index);
				out.small = rem > 0 ? `then ${rem} more ${rem === 1 ? 'query' : 'queries'}` : 'last query';
			} else {
				out.detail = 'asking the network who shares it';
				out.small = attemptText;
			}
			break;
		}
		case 'peer_lock':
			out.word = 'Waiting for the peer';
			out.detail = peer ? `another download of yours is using ${peer}` : 'another download of yours is using this peer';
			withLimit(lim.peer_lock);
			out.small = 'then next peer';
			break;
		case 'waiting_slot': {
			const slots = Number(limits?.transfer_slots) || 0;
			out.word = 'Waiting for a slot';
			out.detail = attempt && of
				? `file picked (${attempt} of ${of} peers), ${slotsBusy(slots)}`
				: `file picked, ${slotsBusy(slots)}`;
			out.small = 'waiting for a transfer slot';
			break;
		}
		case 'connecting':
			out.word = 'Connecting';
			out.detail = 'direct and relayed';
			withLimit(lim.connecting);
			break;
		case 'queued_at_peer': {
			const place = transfer?.queue_place ?? field(job, t0, 'queue_place');
			if (place != null && peer) {
				out.word = `In ${peer}'s queue`;
				out.detail = `place ${place}`;
			} else if (place != null) {
				out.word = 'In the peer\'s queue';
				out.detail = `place ${place}`;
			} else {
				out.word = 'Asked the peer';
				out.detail = peer ? `waiting for ${peer} to start the upload` : 'waiting for the upload to start';
			}
			withLimit(lim.queued_at_peer);
			break;
		}
		case 'transferring': {
			const total = Number(transfer?.total_bytes) || Number(t0.file_size) || 0;
			const rx = Number(transfer?.received_bytes) || 0;
			const pct = total ? Math.min(100, Math.floor((rx / total) * 100)) : null;
			const speed = Number(transfer?.speed) || 0;
			const eta = transfer?.eta_seconds;
			out.word = 'Transferring';
			out.colour = 'sky';
			out.progress = pct;
			out.detail = total ? `${mb(rx)} of ${mb(total)} MB` : rx ? `${formatSize(rx)} so far` : 'starting';
			const median = Number(ctx?.medianSpeed) || 0;
			if (speed > 0 && median > 0 && speed < SLOW_FRACTION * median) out.detail += ' · slow';
			const lastMs = toMs(transfer?.last_progress_at);
			const noDataMs = lastMs != null ? now - lastMs : 0;
			if (transfer && lastMs != null && noDataMs > NO_DATA_AFTER_MS) {
				const noDataS = Math.floor(noDataMs / 1000);
				out.big = `no data for ${noDataS} s of ${lim.transferring} s`;
				out.amber = true;
				out.elapsedS = noDataS;
				out.limitS = lim.transferring;
			} else {
				const bits = [];
				if (pct != null) bits.push(`${pct} %`);
				if (speed > 0) bits.push(formatSpeed(speed));
				if (eta != null && eta > 0) bits.push(`${formatDurationWords(eta)} left`);
				out.big = bits.length ? bits.join(' · ') : elapsed;
			}
			break;
		}
		case 'importing':
			out.word = 'Importing';
			out.colour = 'sky';
			out.detail = 'checking tags, duplicates and quality';
			out.big = elapsed;
			out.limitS = lim.importing;
			out.amber = elapsedS >= 0.75 * lim.importing;
			out.small = `usually under ${lim.importing} s`;
			break;
	}
	return out;
}
