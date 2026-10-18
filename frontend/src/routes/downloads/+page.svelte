<script>
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/stores';
	import { api } from '$lib/api.js';
	import { addToast, activeTransfers, activeUploads, wsState } from '$lib/stores.js';
	import { onJobUpdate } from '$lib/websocket.js';
	import { formatSize, formatSpeed, formatETA, formatDateTime, formatRelativeTime, parseUTC } from '$lib/utils.js';
	import { Download, Search, Zap, ShieldBan, Trash2, X, ChevronLeft, ChevronRight, ChevronDown, ChevronUp, RotateCcw, Eraser, CircleCheck, Wifi, Clock, Upload, Radio, Activity, TriangleAlert, ListOrdered } from 'lucide-svelte';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Button from '../../components/ui/Button.svelte';
	import Badge from '../../components/ui/Badge.svelte';
	import FilterPills from '../../components/ui/FilterPills.svelte';
	import EmptyState from '../../components/ui/EmptyState.svelte';
	import DataTable from '../../components/ui/DataTable.svelte';
	import Modal from '../../components/ui/Modal.svelte';
	import Skeleton from '../../components/ui/Skeleton.svelte';
	import FormatBadge from '../../components/ui/FormatBadge.svelte';
	import { sourceLabel, clockTime, shortDate, resolveStage, firstTrack, failureSentence, nextSentence, doneOutcome, ordinal } from '$lib/downloads/stage.js';

	// Search state
	let searchQuery = $state('');
	let results = $state([]);
	let resultCount = $state(0);
	let resultUsers = $state(0);
	let searching = $state(false);
	let downloading = $state({});
	let formatFilter = $state('all');
	let searchDone = $state(false);
	let sortCol = $state('quality');
	let sortAsc = $state(false);
	let resultsPage = $state(0);
	let resultsPerPage = $state(50);

	// Per-result inline download status: key = username+filename → { status, jobId }
	// status: 'queued' | 'searching' | 'downloading' | 'completed' | 'failed'
	let resultStatuses = $state({});
	// Set when /download/search refused the query: the blacklist reason replaces "No results".
	let searchBlacklisted = $state(null);
	const FORMAT_ORDER = { flac: 0, wav: 1, alac: 1, mp3: 2, m4a: 3, ogg: 3, opus: 3 };

	function sortResults(list) {
		return [...list].sort((a, b) => {
			let cmp = 0;
			if (sortCol === 'quality') {
				// Format → slots_free → size
				cmp = (FORMAT_ORDER[a.extension] ?? 9) - (FORMAT_ORDER[b.extension] ?? 9);
				if (cmp === 0) cmp = (b.slots_free ? 1 : 0) - (a.slots_free ? 1 : 0);
				if (cmp === 0) cmp = b.size - a.size;
			} else if (sortCol === 'format') {
				cmp = (FORMAT_ORDER[a.extension] ?? 9) - (FORMAT_ORDER[b.extension] ?? 9);
			} else if (sortCol === 'bitrate') {
				cmp = (b.bitrate || 0) - (a.bitrate || 0);
			} else if (sortCol === 'size') {
				cmp = b.size - a.size;
			} else if (sortCol === 'user') {
				cmp = a.username.localeCompare(b.username);
			}
			return sortAsc ? -cmp : cmp;
		});
	}

	function toggleSort(col) {
		if (sortCol === col) { sortAsc = !sortAsc; }
		else { sortCol = col; sortAsc = false; }
	}

	let allFilteredResults = $derived(
		sortResults(
			formatFilter === 'all' ? results :
			formatFilter === 'flac' ? results.filter(r => r.extension === 'flac') :
			formatFilter === '320' ? results.filter(r => r.bitrate >= 320 || r.extension === 'flac') :
			formatFilter === '256' ? results.filter(r => r.bitrate >= 256 || r.extension === 'flac') :
			results
		)
	);

	let filteredResults = $derived(
		allFilteredResults.slice(resultsPage * resultsPerPage, (resultsPage + 1) * resultsPerPage)
	);

	let totalResultPages = $derived(Math.ceil(allFilteredResults.length / resultsPerPage));

	let formatCounts = $derived({
		all: results.length,
		flac: results.filter(r => r.extension === 'flac').length,
		high: results.filter(r => r.bitrate >= 320 || r.extension === 'flac').length,
		mid: results.filter(r => r.bitrate >= 256 || r.extension === 'flac').length,
	});

	// Blacklist state
	let blacklist = $state([]);
	let blArtist = $state('');
	let blTrack = $state('');
	let blReason = $state('');
	let showBlacklist = $state(false);
	let blSearch = $state('');
	let blSearching = $state(false);
	let blSearchResults = $state([]);
	let blFilter = $state('');
	let filteredBlacklist = $derived(
		blFilter.trim()
			? blacklist.filter(e =>
				e.artist.toLowerCase().includes(blFilter.toLowerCase()) ||
				(e.track && e.track.toLowerCase().includes(blFilter.toLowerCase())))
			: blacklist
	);

	// Downloads state
	let jobs = $state([]);
	let jobsOffset = $state(0);
	let jobsLoading = $state(true);
	let jobsLoaded = $state(false); // first list response arrived (the skeleton shows only before it)
	let expandedJob = $state(null);
	// Starts unset: once the counts arrive it opens on Active when anything is in flight,
	// otherwise Done. Opening on "All" meant a wall of failures (1,003 at the time).
	let jobStatusFilter = $state(null);
	let failureReason = $state(null);
	let failureGroups = $state([]);
	let retryConfirm = $state(null); // null | { reason, label, count }
	let retrying = $state(false);
	let selectedFailureGroup = $derived(failureReason ? failureGroups.find(g => g.reason === failureReason) : null);
	const STATUS_QUERY = { active: 'pending,running', completed: 'completed', failed: 'failed', queued: 'pending', running: 'running' };
	let jobDetails = $state({});
	const PAGE_LIMIT = 20;

	const STATUS_PRIORITY = { pending: 0, running: 1, completed: 2, failed: 3 };

	let visibleJobs = $derived(
		// Status, failure reason and scope are filtered by the server.
		[...jobs].sort((a, b) => {
			const pa = STATUS_PRIORITY[a.status] ?? 1;
			const pb = STATUS_PRIORITY[b.status] ?? 1;
			if (pa !== pb) return pa - pb;
			const ta = a.started_at || a.created_at || '';
			const tb = b.started_at || b.created_at || '';
			return tb.localeCompare(ta);
		})
	);

	function parseJobResult(job) {
		if (!job.result) return null;
		try { return JSON.parse(job.result); } catch { return null; }
	}

	function parseJobTracks(job) {
		if (!job?.tracks) return null;
		if (Array.isArray(job.tracks)) return job.tracks;
		try { return JSON.parse(job.tracks); } catch { return null; }
	}

	const KNOWN_EXTENSIONS = new Set(['flac', 'mp3', 'wav', 'alac', 'm4a', 'ogg', 'opus', 'aiff', 'ape']);
	function fileExtension(filename) {
		if (!filename || typeof filename !== 'string' || !filename.includes('.')) return '';
		const ext = filename.split('.').pop()?.toLowerCase().trim() || '';
		return KNOWN_EXTENSIONS.has(ext) ? ext : '';
	}

	/**
	 * "Artist — Track" from tracks[0]. Rows written before tracks[0] carried both fall back to
	 * the description's first two " — " parts (the server's progress strings start with them).
	 */
	function jobTitle(job, fallback = 'Unknown track') {
		const t = firstTrack(job);
		if (t.artist && t.track) return `${t.artist} — ${t.track}`;
		const d = (job?.description || '').replace(/^Queued( for slot)?:\s*/i, '').replace(/\s*\(attempt\s+\d+.*?\)/i, '');
		const parts = d.split(' — ').filter(Boolean);
		if (parts.length >= 2) return `${parts[0]} — ${parts[1]}`;
		return d.trim() || fallback;
	}

	function getSearchQueryForJob(job) {
		if (!job) return '';
		const t = parseJobTracks(job)?.[0] || (job.id ? jobDetails[job.id]?.[0] : null);
		if (t?.artist && t?.track) return `${t.artist} - ${t.track}`;
		const title = jobTitle(job, '');
		return title ? title.replace(/\s*—\s*/, ' - ') : '';
	}

	// --- Failed + done row cells (R1-F1) ---------------------------------------------------

	/** HISTORY cell: how often this track failed in the last 30 days. */
	function historyText(job) {
		const n = Number(job?.times_failed_30d);
		if (!Number.isFinite(n) || n <= 0) return '—';
		return n === 1 ? '1st try' : `${ordinal(n)} time`;
	}

	const TONE_TEXT = { rose: 'text-rose-400', muted: 'text-[var(--text-muted)]', default: 'text-[var(--text-secondary)]' };

	// Jobs whose track was blacklisted from this page ("Stop trying"): NEXT reads "blacklisted".
	let stoppedIds = $state(new Set());

	function nextCell(job) {
		if (stoppedIds.has(job.id)) return { text: 'blacklisted', tone: 'rose' };
		return nextSentence(job, tick);
	}

	/** Local "HH:MM" for today, "Oct 17" before that. */
	function whenShort(iso) {
		const d = parseUTC(iso);
		if (!d || Number.isNaN(d.getTime())) return '';
		return d.toDateString() === new Date(tick).toDateString() ? clockTime(iso) : shortDate(iso);
	}

	/** "HH:MM" today, "Oct 17 HH:MM" before. */
	function whenLong(iso) {
		const d = parseUTC(iso);
		if (!d || Number.isNaN(d.getTime())) return '';
		return d.toDateString() === new Date(tick).toDateString() ? clockTime(iso) : `${shortDate(iso)} ${clockTime(iso)}`;
	}

	function trackIdOf(job) {
		return job?.track_id || job?.track?.id || parseJobResult(job || {})?.track_id || null;
	}

	/** PLAYED cell for a done row. */
	function playedText(job, outcome) {
		if (outcome?.kind === 'already_had') return '—';
		const tr = job?.track;
		if (!tr) return '—';
		const n = Number(tr.play_count) || 0;
		if (!n) return 'not yet';
		const last = parseUTC(tr.last_played_at);
		const fin = parseUTC(job.finished_at);
		if (last && fin && last < fin) return `${n}× before`;
		return tr.last_played_at ? `${n}× · last ${whenShort(tr.last_played_at)}` : `${n}×`;
	}

	// Stop trying: blacklist the track, drop its retry schedule, skip pending upgrades (DC-11).
	let stopConfirm = $state(null); // null | { id, title }
	let stopping = $state(false);

	async function confirmStopTrying() {
		if (!stopConfirm) return;
		stopping = true;
		const { id, title } = stopConfirm;
		try {
			const r = await api.stopTrying(id);
			if (r?.error) {
				addToast(`Not blacklisted: ${r.error}`, 'warning');
			} else {
				stoppedIds = new Set([...stoppedIds, id]);
				const bits = [];
				if (r?.attempt_deleted) bits.push('retry schedule removed');
				if (r?.upgrades_skipped) bits.push(`${r.upgrades_skipped} upgrade${r.upgrades_skipped === 1 ? '' : 's'} skipped`);
				addToast(`Stopped trying ${title}: blacklisted${bits.length ? ` · ${bits.join(' · ')}` : ''}`, 'success');
				loadBlacklist();
			}
			stopConfirm = null;
		} catch (e) {
			addToast(`Stop trying failed: ${e.message}`, 'error');
		} finally {
			stopping = false;
		}
	}

	// Done totals (GET /api/jobs/summary, DC-9) — also feeds the quiet state's "last finished".
	let summary = $state(null);
	let summaryLoadedAt = 0;
	async function loadSummary(force = false) {
		if (!force && Date.now() - summaryLoadedAt < 10000) return;
		summaryLoadedAt = Date.now();
		try { summary = await api.getJobsSummary(sinceISO); } catch {}
	}

	let doneTotals = $derived.by(() => {
		const o = summary?.outcomes;
		if (!o) return '';
		const added = (o.new || 0) + (o.replaced || 0);
		const n = added + (o.already_had || 0);
		const parts = [`${n.toLocaleString()} finished ${scopeInfo.phrase}`];
		const extra = [];
		if (summary.bytes_added) extra.push(formatSize(summary.bytes_added));
		if (summary.pct_lossless != null && added) extra.push(`${summary.pct_lossless}% FLAC`);
		parts.push(`${added.toLocaleString()} added${extra.length ? ` (${extra.join(', ')})` : ''}`);
		if (o.already_had) parts.push(`${o.already_had.toLocaleString()} already had`);
		return parts.join(' · ');
	});

	// Quiet state (nothing live): last finish, next scheduled runs, retries coming due today.
	let attemptsSummary = $state(null);
	let firstDueAt = $state(null);
	let quietLoadedAt = 0;
	let localEndOfDayISO = $derived.by(() => {
		const d = new Date(tick);
		d.setHours(23, 59, 59, 999);
		return d.toISOString();
	});

	async function loadQuiet(force = false) {
		if (!force && Date.now() - quietLoadedAt < 30000) return;
		quietLoadedAt = Date.now();
		const eod = localEndOfDayISO;
		const [sum, , due] = await Promise.allSettled([
			api.getAttemptsSummary(eod), loadSummary(force), api.getDownloadAttempts(eod, 1),
		]);
		if (sum.status === 'fulfilled') attemptsSummary = sum.value;
		firstDueAt = due.status === 'fulfilled' ? due.value?.items?.[0]?.next_retry_at || null : null;
	}

	let quietText = $derived.by(() => {
		const parts = [];
		const lf = summary?.last_finished;
		if (lf?.finished_at) {
			const what = [lf.artist, lf.track].filter(Boolean).join(' — ');
			parts.push(`Last job finished ${whenLong(lf.finished_at)} · ${sourceLabel(lf.card)}${what ? ` · ${what}` : ''}.`);
		}
		const runs = attemptsSummary?.next_runs || [];
		if (runs.length) {
			parts.push(`Next scheduled runs: ${runs.slice(0, 4).map(r => `${r.label} ${whenLong(r.next_run_at)}`).join(', ')}.`);
		}
		const dueNow = attemptsSummary?.due_now || 0;
		const dueToday = attemptsSummary?.due_before || 0;
		if (dueNow) parts.push(`${plural(dueNow, 'track')} in backoff ${dueNow === 1 ? 'is' : 'are'} due again now.`);
		else if (dueToday) parts.push(`${plural(dueToday, 'track')} in backoff come${dueToday === 1 ? 's' : ''} due again${firstDueAt ? ` from ${clockTime(firstDueAt)}` : ' today'}.`);
		return parts.join(' ');
	});

	let backoffOpen = $state(false);
	let backoffRows = $state([]);
	let backoffLoading = $state(false);
	async function openBackoffList() {
		backoffOpen = true;
		backoffLoading = true;
		try { backoffRows = (await api.getDownloadAttempts(null, 200))?.items || []; } catch { backoffRows = []; }
		finally { backoffLoading = false; }
	}

	let runningRetries = $state(false);
	async function runRetriesNow() {
		runningRetries = true;
		try {
			const r = await api.runDueRetries(localEndOfDayISO);
			const n = r?.queued ?? 0;
			addToast(n ? `Queued ${plural(n, 'retry', 'retries')} — they show up under Active as they start` : 'Nothing was due — no retries queued', n ? 'success' : 'info');
			loadQuiet(true);
		} catch (e) {
			addToast(`Retries not queued: ${e.message}`, 'error');
		} finally {
			runningRetries = false;
		}
	}

	// One scope (DC-7/DC-8): Today / 7 days / 30 days, sent as `since` = local midnight
	// (0, 6 or 29 days back) in UTC. It drives the Done/Failed lists, the pill counts, the
	// failure buckets, the bulk actions and the footers. Never "All time": retention is 30 days.
	const SCOPES = [
		{ value: 'today', label: 'Today', days: 0, phrase: 'today' },
		{ value: 'week', label: '7 days', days: 6, phrase: 'in the last 7 days' },
		{ value: 'month', label: '30 days', days: 29, phrase: 'in the last 30 days' },
	];
	let scope = $state('today');
	let scopeInfo = $derived(SCOPES.find(x => x.value === scope) || SCOPES[0]);
	let sinceISO = $derived.by(() => {
		const d = new Date(tick);
		d.setHours(0, 0, 0, 0);
		d.setDate(d.getDate() - scopeInfo.days);
		return d.toISOString();
	});

	// Server-side counts (independent of pagination), scoped by `since`.
	let jobStatusCounts = $state({ all: 0, active: 0, queued: 0, running: 0, completed: 0, failed: 0 });

	async function loadJobCounts() {
		try {
			const c = await api.getJobCounts('download,bulk_download', sinceISO);
			jobStatusCounts = {
				all: c.all || 0,
				active: c.active ?? ((c.pending || 0) + (c.running || 0)),
				queued: c.pending || 0,
				running: c.running || 0,
				// Older servers lack the scoped keys: fall back to the all-time ones.
				completed: c.completed_since ?? c.completed ?? 0,
				failed: c.failed_since ?? c.failed ?? 0,
			};
			if (jobStatusFilter === null) {
				setJobFilter(jobStatusCounts.active > 0 ? 'active' : jobStatusCounts.completed > 0 ? 'completed' : 'all');
			}
		} catch {}
	}

	// A burst of job_update frames (one per stage change) refreshes the counts at most twice a second.
	let countsTimer;
	function refreshCountsSoon() {
		if (countsTimer) return;
		countsTimer = setTimeout(() => { countsTimer = null; loadJobCounts(); }, 500);
	}

	function setScope(v) {
		if (v === scope) return;
		scope = v;
		jobsOffset = 0;
		doneLimit = 10;
		bucketSamples = {};
		expandedFailureBucket = null;
		loadJobs();
		if (jobStatusFilter === 'failed') loadFailureGroups();
		loadSummary(true);
	}

	function getTransferForJob(job) {
		if (job.status !== 'running') return null;
		// Direct lookup via job_id (set when the transfer is created).
		const direct = $activeTransfers.find(tr => tr.job_id === job.id);
		if (direct) return direct;
		// Fallback for legacy transfers that pre-date the job_id link.
		let tracks;
		try { tracks = jobDetails[job.id]; } catch { return null; }
		if (!tracks?.length) return null;
		const t = tracks.find(t => t.username && t.filename);
		if (!t) return null;
		return $activeTransfers.find(tr =>
			tr.username === t.username &&
			(tr.filename?.endsWith(t.filename) || tr.filename?.split(/[/\\]/).pop() === t.filename)
		);
	}

	function getJobForTransfer(transfer) {
		if (!transfer) return null;
		if (transfer.job_id) {
			const found = jobs.find(j => j.id === transfer.job_id);
			if (found) return found;
		}
		return jobs.find(j => {
			const t = jobDetails[j.id]?.[0];
			if (t && t.username === transfer.username && transfer.filename?.includes(t.filename)) return true;
			return false;
		});
	}

	async function cancelActiveItem(item) {
		if (item.job?.id) {
			await cancelJob(item.job.id);
		} else if (item.transfer) {
			try {
				await api.cancelTransfer(item.transfer.username, item.transfer.filename);
				addToast('Transfer cancelled', 'success');
			} catch { addToast('Cancel failed', 'error'); }
		}
	}

	// Hero cards: only transfers that are moving bytes (state === 'transferring').
	let liveTransfers = $derived($activeTransfers.filter(tr => tr.state === 'transferring'));
	let totalTransferSpeed = $derived(
		liveTransfers.reduce((acc, tr) => acc + (tr.speed || 0), 0)
	);
	// Session median speed of the running transfers: a row under 10 % of it reads "slow".
	let medianSpeed = $derived.by(() => {
		const v = liveTransfers.map(tr => Number(tr.speed) || 0).filter(x => x > 0).sort((a, b) => a - b);
		if (!v.length) return 0;
		const m = Math.floor(v.length / 2);
		return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
	});

	let activeHeroItems = $derived(liveTransfers.map(tr => ({
		transfer: tr,
		job: getJobForTransfer(tr),
		id: tr.job_id || `${tr.username}-${tr.filename}`,
	})));

	let heroJobIds = $derived(new Set(activeHeroItems.map(item => item.job?.id).filter(Boolean)));

	/** What a job is doing now (stage.js resolver), recomputed on the 1 s tick. */
	function stageOf(job, transfer) {
		return resolveStage(job, transfer, limits, tick, { pacer, medianSpeed });
	}

	const COLOUR_TEXT = {
		sky: 'text-sky-400', amber: 'text-amber-400', indigo: 'text-indigo-400',
		muted: 'text-[var(--text-muted)]', emerald: 'text-emerald-400', rose: 'text-rose-400',
	};
	const COLOUR_DOT = {
		sky: 'bg-sky-400', amber: 'bg-amber-400', indigo: 'bg-indigo-400',
		muted: 'bg-[var(--text-disabled)]', emerald: 'bg-emerald-400', rose: 'bg-rose-400',
	};

	let displayJobs = $derived.by(() => {
		// When active transfer hero cards are shown on Active/All tab, exclude those active jobs from the rows below
		if (activeHeroItems.length > 0 && (jobStatusFilter === 'active' || jobStatusFilter === 'all' || jobStatusFilter === null)) {
			return visibleJobs.filter(j => !heroJobIds.has(j.id));
		}
		return visibleJobs;
	});

	// Done tab density (how many rows of the scope are shown)
	let doneLimit = $state(10);
	let clearCompletedConfirm = $state(false);
	let clearingCompleted = $state(false);

	let displayedCompletedJobs = $derived(
		jobs.filter(j => j.status === 'completed').slice(0, doneLimit)
	);

	function expandDoneList(step = 25) {
		doneLimit += step;
		loadJobs(false);
	}

	async function handleClearCompleted() {
		clearingCompleted = true;
		try {
			const r = await api.clearDownloadHistory('completed', null, sinceISO);
			const n = r?.deleted ?? 0;
			addToast(n ? `Deleted ${n} completed download record${n === 1 ? '' : 's'} on the server` : 'Nothing to clear', n ? 'success' : 'info');
			clearCompletedConfirm = false;
			await loadJobCounts();
			await loadJobs();
		} catch (e) {
			addToast(`Clear failed: ${e.message}`, 'error');
		} finally {
			clearingCompleted = false;
		}
	}

	// Failed tab triage bucket state
	let expandedFailureBucket = $state(null);
	let bucketSamples = $state({});
	let bucketLoading = $state(false);
	let dismissNonCriticalConfirm = $state(false);
	let dismissingNonCritical = $state(false);

	const FAILURE_CARD_CONFIG = [
		{
			reason: 'peer',
			title: 'Peer Offline / Disconnected',
			description: 'Uploader timed out, disconnected, or max queue limits reached.',
			icon: Wifi,
			iconColor: 'text-amber-400',
			iconBg: 'bg-amber-500/15',
			primaryAction: 'retry',
			primaryLabel: 'Retry All',
		},
		{
			reason: 'no_better',
			title: 'Equal or Higher Quality Exists',
			description: 'Your library already contains this track at equal or better bitrate.',
			icon: CircleCheck,
			iconColor: 'text-sky-400',
			iconBg: 'bg-sky-500/15',
			primaryAction: 'dismiss',
			primaryLabel: 'Delete All',
		},
		{
			reason: 'not_found',
			title: 'No Peers Sharing Track Online',
			description: 'Track was not found on Soulseek during central server search.',
			icon: Search,
			iconColor: 'text-purple-400',
			iconBg: 'bg-purple-500/15',
			primaryAction: 'retry',
			primaryLabel: 'Retry All',
		},
		{
			reason: 'rejected',
			title: 'Import Rejected / Corrupted Stream',
			description: 'File was incomplete, wrong track, or unreadable audio container.',
			icon: ShieldBan,
			iconColor: 'text-rose-400',
			iconBg: 'bg-rose-500/15',
			primaryAction: 'dismiss',
			primaryLabel: 'Delete All',
		},
		{
			reason: 'infra',
			title: "Not the track's fault",
			description: 'Cancelled, restart or outage — not counted against the track',
			icon: TriangleAlert,
			iconColor: 'text-slate-300',
			iconBg: 'bg-slate-500/15',
			primaryAction: 'retry',
			primaryLabel: 'Retry All',
		},
	];

	function getBucketCount(reason) {
		return failureGroups.find(g => g.reason === reason)?.count || 0;
	}

	async function toggleInspectBucket(reason) {
		if (expandedFailureBucket === reason) {
			expandedFailureBucket = null;
			return;
		}
		expandedFailureBucket = reason;
		if (!bucketSamples[reason]) {
			bucketLoading = true;
			try {
				const data = await api.getDownloadHistory(0, 5, 'failed', reason, null, sinceISO);
				bucketSamples[reason] = data.items || data;
			} catch (e) {
				console.error(e);
			} finally {
				bucketLoading = false;
			}
		}
	}

	async function dismissFailedByReason(reason, label) {
		try {
			const r = await api.clearDownloadHistory('failed', reason, sinceISO);
			const n = r?.deleted ?? 0;
			addToast(n ? `Deleted ${n} failed download record${n === 1 ? '' : 's'} (${label}) on the server` : 'Nothing to delete', n ? 'success' : 'info');
			delete bucketSamples[reason];
			if (expandedFailureBucket === reason) expandedFailureBucket = null;
			await loadJobCounts();
			await loadFailureGroups();
			await loadJobs();
		} catch (e) {
			addToast(`Delete failed: ${e.message}`, 'error');
		}
	}

	async function handleDismissNonCritical() {
		dismissingNonCritical = true;
		try {
			const a = await api.clearDownloadHistory('failed', 'no_better', sinceISO);
			const b = await api.clearDownloadHistory('failed', 'rejected', sinceISO);
			const n = (a?.deleted ?? 0) + (b?.deleted ?? 0);
			addToast(n ? `Deleted ${n} non-critical failure record${n === 1 ? '' : 's'} on the server` : 'Nothing to delete', n ? 'success' : 'info');
			bucketSamples = {};
			expandedFailureBucket = null;
			dismissNonCriticalConfirm = false;
			await loadJobCounts();
			await loadFailureGroups();
			await loadJobs();
		} catch (e) {
			addToast(`Delete failed: ${e.message}`, 'error');
		} finally {
			dismissingNonCritical = false;
		}
	}

	let nonCriticalCount = $derived(
		(failureGroups.find(g => g.reason === 'no_better')?.count || 0) +
		(failureGroups.find(g => g.reason === 'rejected')?.count || 0)
	);

	function getResultInlineStatus(r) {
		const key = r.username + r.filename;
		// Check active transfers first for live progress
		const transfer = $activeTransfers.find(tr =>
			tr.username === r.username &&
			(tr.filename === r.filename || tr.filename?.endsWith(r.filename.split(/[/\\]/).pop()))
		);
		if (transfer) {
			const s = transfer.state;
			if (s === 'transferring' || s === 'connected') {
				return { status: 'downloading', progress: transfer.progress || 0, speed: transfer.speed, eta: transfer.eta_seconds, received: transfer.received_bytes, total: transfer.total_bytes };
			}
			if (s === 'completed') return { status: 'completed' };
			if (s === 'failed' || s === 'denied') return { status: 'failed' };
			return { status: 'queued' };
		}
		// Fall back to tracked status
		const tracked = resultStatuses[key];
		if (tracked) return tracked;
		return null;
	}

	function shortFilename(filename) {
		return filename?.split(/[/\\]/).pop() || filename;
	}

	function extractArtistFromPath(filename) {
		const parts = filename?.split(/[/\\]/) || [];
		if (parts.length >= 3) return parts[parts.length - 3];
		if (parts.length >= 2) return parts[parts.length - 2];
		return '';
	}

	function formatBitrate(br) {
		if (!br) return '';
		return `${br}k`;
	}

	function formatUserSpeed(speed) {
		if (!speed) return '';
		if (speed > 1000000) return `${(speed / 1000000).toFixed(1)} MB/s`;
		if (speed > 1000) return `${(speed / 1000).toFixed(0)} KB/s`;
		return `${speed} B/s`;
	}

	function setJobFilter(v) {
		jobStatusFilter = v;
		failureReason = null;
		jobsOffset = 0;
		expandedJob = null;
		if (v === 'failed') loadFailureGroups();
		loadJobs(false);
	}

	function setFailureReason(reason) {
		failureReason = failureReason === reason ? null : reason;
		jobsOffset = 0;
		loadJobs(false);
	}

	async function loadFailureGroups() {
		try { failureGroups = await api.getDownloadFailures(sinceISO); } catch { failureGroups = []; }
	}

	async function retryFailed() {
		if (!retryConfirm) return;
		retrying = true;
		try {
			const r = await api.retryFailedDownloads(retryConfirm.reason, sinceISO);
			if (r?.error) throw new Error(r.error);
			const n = r?.tracks ?? 0;
			addToast(n ? `Re-queued ${n} download${n === 1 ? '' : 's'}` : 'Nothing to retry in this period', n ? 'success' : 'info');
			bucketSamples = {};
			retryConfirm = null;
			failureReason = null;
			await loadFailureGroups();
			await loadJobs();
		} catch (e) {
			addToast(`Retry failed: ${e.message}`, 'error');
		} finally {
			retrying = false;
		}
	}

	async function loadJobs(withCounts = true) {
		jobsLoading = true;
		if (withCounts) loadJobCounts();
		try {
			const status = jobStatusFilter && jobStatusFilter !== 'all' ? STATUS_QUERY[jobStatusFilter] : null;
			const limit = jobStatusFilter === 'completed' ? Math.max(25, doneLimit) : PAGE_LIMIT;
			// Finished rows are scoped; live rows are not (a job queued before midnight is still live).
			const scoped = jobStatusFilter === 'completed' || jobStatusFilter === 'failed';
			const data = await api.getDownloadHistory(jobsOffset, limit, status, jobStatusFilter === 'failed' ? failureReason : null, null, scoped ? sinceISO : null);
			jobs = data.items || data;
			if (jobStatusFilter === 'completed') loadSummary();
			if (jobStatusFilter === 'active' && !jobs.length) loadQuiet();
			// Only fetch details for active RUNNING jobs (not queued/pending) — limit to 10 to avoid hammering API
			const needDetails = jobs
				.filter(j => j.status === 'running' && !jobDetails[j.id])
				.slice(0, 10);
			if (needDetails.length) {
				const details = await Promise.allSettled(needDetails.map(j => api.getJob(j.id)));
				details.forEach((r, i) => {
					if (r.status === 'fulfilled' && r.value?.tracks) {
						jobDetails[needDetails[i].id] = JSON.parse(r.value.tracks);
					}
				});
			}
		} catch (e) { console.error('Download history load failed:', e); }
		finally { jobsLoading = false; jobsLoaded = true; }
	}

	async function toggleJobDetail(jobId) {
		if (expandedJob === jobId) { expandedJob = null; return; }
		expandedJob = jobId;
		if (!jobDetails[jobId]) {
			try {
				const detail = await api.getJob(jobId);
				if (detail?.tracks) jobDetails[jobId] = JSON.parse(detail.tracks);
			} catch (e) { console.error('Job detail load failed:', e); }
		}
	}

	/** Drop a row locally (the server already removed or replaced it). */
	function dropJobLocally(jobId) {
		jobs = jobs.filter(j => j.id !== jobId);
		for (const k of Object.keys(bucketSamples)) {
			bucketSamples[k] = (bucketSamples[k] || []).filter(s => s.id !== jobId);
		}
	}

	async function retryJob(jobId) {
		try {
			const r = await api.retryJob(jobId);
			if (r?.error) {
				addToast(`Not retried: ${r.error}`, 'warning');
				return;
			}
			addToast(`Retry started${r?.total > 1 ? ` (${r.total} tracks)` : ''}`, 'success');
			if (r?.replaced_job_id) dropJobLocally(r.replaced_job_id);
			if (jobStatusFilter === 'failed') loadFailureGroups();
			await loadJobs();
		} catch (e) { addToast(`Retry failed: ${e.message}`, 'error'); }
	}

	async function cancelJob(jobId) {
		try {
			const r = await api.cancelJob(jobId);
			if (r?.error) {
				addToast(r.error === 'Job not cancellable' ? 'Not cancelled: it already finished' : `Not cancelled: ${r.error}`, 'warning');
				await loadJobs();
				return;
			}
			addToast('Download cancelled', 'success');
			await loadJobs();
		} catch (e) { addToast(`Cancel failed: ${e.message}`, 'error'); }
	}

	// Remove = delete the row on the server, behind a confirm (local hiding is gone).
	let removeConfirm = $state(null); // null | { id, title }
	let removing = $state(false);

	function askRemove(job) {
		const t = parseJobTracks(job)?.[0];
		const title = t?.artist && t?.track ? `${t.artist} — ${t.track}` : jobTitle(job);
		removeConfirm = { id: job.id, title, status: job.status };
	}

	async function confirmRemove() {
		if (!removeConfirm) return;
		removing = true;
		const { id, status: wasStatus } = removeConfirm;
		try {
			const r = await api.deleteJob(id);
			if (r?.error) {
				addToast(r.error === 'Job is active' ? 'Not removed: it is still running — cancel it first' : `Not removed: ${r.error}`, 'warning');
			} else {
				addToast('Removed on the server', 'success');
				dropJobLocally(id);
				loadJobCounts();
				if (wasStatus === 'failed') loadFailureGroups();
			}
			removeConfirm = null;
		} catch (e) {
			addToast(`Remove failed: ${e.message}`, 'error');
		} finally {
			removing = false;
		}
	}

	/**
	 * Toast what a /api/download/trigger reply actually says. Returns the job id when a
	 * download was queued (or one was already running), else null. `key` resets the
	 * inline status of a search-result row that did not start.
	 */
	function handleTriggerReply(resp, key = null, startedLabel = 'Download started') {
		const reset = () => { if (key) delete resultStatuses[key]; };
		if (!resp || typeof resp !== 'object') {
			reset();
			addToast('Download not started: no reply from the server', 'warning');
			return null;
		}
		if (resp.error === 'blacklisted' || resp.blacklisted) {
			reset();
			addToast(`Not downloaded: blacklisted${resp.reason ? ` (${resp.reason})` : ''}`, 'warning');
			return null;
		}
		if (resp.status === 'in_library') {
			reset();
			addToast('Already in your library', 'info', 6000,
				resp.track_id ? { href: `/library?track=${encodeURIComponent(resp.track_id)}`, label: 'Open track' } : null);
			return null;
		}
		if (resp.status === 'already_downloading') {
			if (key) resultStatuses[key] = { status: 'searching', jobId: resp.job_id };
			addToast('Already downloading', 'info');
			return resp.job_id || null;
		}
		if (resp.status === 'skipped') {
			reset();
			addToast(`Skipped: ${resp.reason || 'not downloaded'}`, 'warning');
			return null;
		}
		if (resp.job_id) {
			if (key) resultStatuses[key] = { status: 'searching', jobId: resp.job_id };
			addToast(startedLabel, 'success');
			return resp.job_id;
		}
		reset();
		addToast(`Not downloaded: ${resp.error || resp.detail || 'the server did not queue it'}`, 'warning');
		return null;
	}

	async function postTrigger(body) {
		const r = await fetch('/api/download/trigger', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(body),
		});
		let data = null;
		try { data = await r.json(); } catch {}
		if (!r.ok) {
			const d = data?.detail;
			throw new Error(typeof d === 'string' ? d : `API error: ${r.status}`);
		}
		return data;
	}

	// Blacklist
	async function searchLibraryForBlacklist() {
		if (!blSearch.trim()) return;
		blSearching = true;
		try {
			const data = await api.getArtists({ search: blSearch.trim(), limit: 20 });
			const artists = (data.artists || data || []).map(a => a.name).filter(Boolean);
			blSearchResults = artists;
			if (!artists.length) addToast('No matching artists found', 'warning');
		} catch (e) { addToast('Search failed', 'error'); }
		finally { blSearching = false; }
	}

	async function loadBlacklist() {
		try {
			blacklist = await fetch('/api/download/blacklist').then(r => r.json());
		} catch (e) { console.error(e); }
	}

	async function addBlacklistEntry() {
		if (!blArtist.trim()) return;
		try {
			await fetch('/api/download/blacklist', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					artist: blArtist.trim(),
					track: blTrack.trim() || null,
					reason: blReason.trim() || null,
				})
			});
			blArtist = ''; blTrack = ''; blReason = '';
			await loadBlacklist();
			addToast('Added to blacklist', 'success');
		} catch (e) { addToast('Failed to add', 'error'); }
	}

	async function removeBlacklistEntry(id) {
		try {
			await fetch(`/api/download/blacklist/${id}`, { method: 'DELETE' });
			await loadBlacklist();
		} catch (e) { addToast('Failed to remove', 'error'); }
	}

	// Soulseek Search
	async function searchSoulseek() {
		if (!searchQuery.trim()) return;
		searching = true;
		results = [];
		searchDone = false;
		formatFilter = 'all';
		resultsPage = 0;
		resultStatuses = {};
		searchBlacklisted = null;
		try {
			// Try to split "Artist - Track" for blacklist check, otherwise send as query
			const q = searchQuery.trim();
			const parts = q.split(/\s*[-–—]\s*/);
			// ai: this page shows the AI download advisor's pick (the server skips it otherwise)
			const body = parts.length >= 2
				? { artist: parts[0], track: parts.slice(1).join(' '), ai: true }
				: { query: q, ai: true };
			const data = await fetch('/api/download/search', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(body)
			}).then(r => r.json());
			results = data.results || [];
			resultCount = data.count || 0;
			resultUsers = data.users || 0;
			searchDone = true;
			if (data.blacklisted) searchBlacklisted = { reason: data.reason || '' };
			else if (!results.length) addToast('No results found', 'warning');
		} catch (e) {
			addToast('Search failed: ' + e.message, 'error');
		} finally {
			searching = false;
		}
	}

	function parseQuery() {
		const q = searchQuery.trim();
		const parts = q.split(/\s*[-–—]\s*/);
		if (parts.length >= 2) return { artist: parts[0], track: parts.slice(1).join(' ') };
		return { artist: q, track: q };
	}

	async function downloadFile(result) {
		const key = result.username + result.filename;
		downloading[key] = true;
		resultStatuses[key] = { status: 'queued' };
		try {
			const { artist, track } = parseQuery();
			const resp = await postTrigger({
				artist, track,
				username: result.username,
				filename: result.filename,
				source: 'manual',
			});
			handleTriggerReply(resp, key);
		} catch (e) {
			resultStatuses[key] = { status: 'failed' };
			addToast('Download failed: ' + e.message, 'error');
		} finally {
			downloading[key] = false;
		}
	}

	async function autoDownload() {
		try {
			const { artist, track } = parseQuery();
			const resp = await postTrigger({ artist, track, source: 'manual' });
			handleTriggerReply(resp, null, 'Auto-download started');
		} catch (e) {
			addToast('Download failed: ' + e.message, 'error');
		}
	}

	function handleKeydown(e) {
		if (e.key === 'Enter') searchSoulseek();
	}

	// Uploads: files peers pulled from our shared library. Live via the WebSocket
	// `upload_progress` message; `sharing` mirrors the share_library setting.
	let sharing = $state(false);
	const UPLOAD_RANK = { transferring: 0, connected: 0, requested: 1, queued: 2, completed: 3, failed: 4, denied: 4 };
	const UPLOAD_BADGE = { transferring: 'info', connected: 'info', requested: 'default', queued: 'default', completed: 'success', failed: 'error', denied: 'warning' };
	const UPLOAD_LABEL = { transferring: 'sending', connected: 'connecting', requested: 'requested' };

	// Queue order is list order; the place counts only files still waiting for a slot.
	let uploadRows = $derived.by(() => {
		let place = 0;
		const rows = $activeUploads.map(u => ({ ...u, place: u.state === 'queued' ? ++place : 0 }));
		return rows
			.map((u, i) => [u, i])
			.sort((a, b) => (UPLOAD_RANK[a[0].state] ?? 5) - (UPLOAD_RANK[b[0].state] ?? 5) || a[1] - b[1])
			.map(([u]) => u);
	});
	let uploadSending = $derived($activeUploads.filter(u => u.state === 'transferring' || u.state === 'connected').length);
	let uploadSpeed = $derived($activeUploads.reduce((n, u) => n + (u.state === 'transferring' ? (u.speed || 0) : 0), 0));
	const baseName = (path) => (path || '').split(/[\\/]/).filter(Boolean).pop() || path;

	// WS job_update keys copied onto the list row (DC-3; final frame adds the outcome keys).
	const WS_MERGE_KEYS = ['tracks', 'card', 'stage', 'stage_since', 'attempt', 'of', 'username', 'queue_place', 'search',
		'failure_class', 'source_errors', 'track_id', 'already_in_library', 'failed_sources', 'error'];
	// Completion toasts only for downloads someone started by hand, and only when a file was added.
	const TOAST_CARDS = new Set(['dl:manual', 'dl:search', 'dl']);
	const toastedJobs = new Set();

	function maybeCompletionToast(wsJob, prev) {
		if (wsJob.already_in_library || toastedJobs.has(wsJob.id)) return;
		const card = wsJob.card ?? prev?.card;
		if (!TOAST_CARDS.has(card)) return;
		toastedJobs.add(wsJob.id);
		const t = parseJobTracks(prev || {})?.[0] || parseJobTracks(wsJob)?.[0] || {};
		let artist = t.artist, track = t.track;
		if (!artist || !track) {
			const parts = (wsJob.description || prev?.description || '').split(' — ');
			artist = artist || parts[0] || '';
			track = track || parts[1] || '';
		}
		const result = (prev && parseJobResult(prev)) || {};
		const fname = t.filename || result.filename || '';
		const fmt = fileExtension(fname.split(/[/\\]/).pop()).toUpperCase();
		const size = t.file_size || result.file_size || 0;
		const tail = [fmt, size ? formatSize(size) : ''].filter(Boolean).join(' ');
		const title = [artist, track].filter(Boolean).join(' — ') || 'download';
		addToast(`Added ${title}${tail ? ` · ${tail}` : ''}`, 'success', 7000,
			wsJob.track_id ? { href: `/library?track=${encodeURIComponent(wsJob.track_id)}`, label: 'Open track' } : null);
	}

	let unsubJobUpdate;
	let loadJobsTimer;

	// Live status (GET /api/download/status, DC-12): limits from settings, stage counts over every
	// active job, the search pacer and the Soulseek connection. Polled every 5 s while anything is
	// live, every 30 s otherwise; it also seeds the transfer/upload stores the WebSocket keeps live.
	let status = $state(null);
	let limits = $derived(status?.limits ?? null);
	let stages = $derived(status?.stages ?? null);
	let pacer = $derived(status?.pacer ?? null);
	let slsk = $derived(status?.soulseek ?? null);
	// 1 s clock: drives relative times, chip ages and elapsed cells.
	let tick = $state(Date.now());
	let statusTimer;
	let tickTimer;
	let lastFallbackAt = 0;
	let destroyed = false;

	async function loadStatus() {
		try {
			const data = await api.getDownloadStatus();
			status = data;
			// With the socket down the poll is the only source, so an empty list must clear too.
			if (data.downloads?.length || !$wsState.connected) activeTransfers.set(data.downloads || []);
			activeUploads.set(data.uploads || []);
		} catch {}
	}

	function scheduleStatus() {
		clearTimeout(statusTimer);
		if (destroyed) return;
		statusTimer = setTimeout(async () => {
			await loadStatus();
			scheduleStatus();
		}, (stages?.live ?? 0) > 0 ? 5000 : 30000);
	}

	const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

	let subtitle = $derived(limits && limits.transfer_slots != null
		? `Limits from settings: ${plural(limits.transfer_slots, 'transfer slot')} · ${plural(limits.search_slots, 'search slot')} · ${limits.searches_per_minute} searches a minute, ${limits.search_min_interval_s} s apart`
		: 'Limits from settings');

	/** Relative time that re-renders with the 1 s tick. */
	function rel(iso) {
		void tick;
		return formatRelativeTime(iso);
	}

	// Tab-title badge: files moving bytes right now.
	let transferringCount = $derived(stages?.transferring ?? $activeTransfers.filter(t => t.state === 'transferring').length);

	let wsAgeS = $derived($wsState.lastMessageAt ? Math.max(0, Math.round((tick - $wsState.lastMessageAt) / 1000)) : null);

	onMount(() => {
		loadBlacklist();
		// Deep link from the dashboard, e.g. /downloads?status=failed&reason=not_found
		const qs = new URLSearchParams(window.location.search);
		const wantStatus = qs.get('status');
		if (wantStatus && STATUS_QUERY[wantStatus]) {
			jobStatusFilter = wantStatus;
			if (wantStatus === 'failed') {
				failureReason = qs.get('reason');
				loadFailureGroups();
			}
		}
		loadJobs();
		loadStatus().then(scheduleStatus);
		api.getServices().then(d => { sharing = !!d.slsk_share_library; }).catch(() => {});
		unsubJobUpdate = onJobUpdate(async (wsJob) => {
			if (wsJob.type === 'download' || wsJob.type === 'bulk_download') {
				// Update inline result statuses from job updates
				for (const [key, rs] of Object.entries(resultStatuses)) {
					if (rs.jobId === wsJob.id) {
						if (wsJob.status === 'completed') resultStatuses[key] = { status: 'completed', jobId: wsJob.id, trackId: wsJob.track_id || null };
						else if (wsJob.status === 'failed') resultStatuses[key] = { status: 'failed', jobId: wsJob.id };
						else if (wsJob.status === 'running' && ['connecting', 'queued_at_peer', 'transferring'].includes(wsJob.stage)) {
							resultStatuses[key] = { status: 'downloading', jobId: wsJob.id };
						}
					}
				}
				// Update job in-place from WS data for instant UI feedback (DC-3 fields merged).
				const idx = jobs.findIndex(j => j.id === wsJob.id);
				const prev = idx >= 0 ? jobs[idx] : null;
				if (idx >= 0) {
					const merged = { ...jobs[idx], status: wsJob.status, progress: wsJob.progress, total: wsJob.total, description: wsJob.description || jobs[idx].description, result: wsJob.result || jobs[idx].result, finished_at: wsJob.finished_at || jobs[idx].finished_at };
					for (const k of WS_MERGE_KEYS) {
						if (wsJob[k] !== undefined && wsJob[k] !== null) merged[k] = wsJob[k];
					}
					jobs[idx] = merged;
				}
				if (wsJob.status === 'completed') maybeCompletionToast(wsJob, prev);
				refreshCountsSoon();
				// Something went live while the status poll sleeps 30 s: refresh it now.
				if ((wsJob.status === 'running' || wsJob.status === 'pending') && !((stages?.live ?? 0) > 0)) {
					loadStatus().then(scheduleStatus);
				}
				// Debounce full reload — longer delay when many active jobs to avoid API hammering
				clearTimeout(loadJobsTimer);
				const activeCount = jobs.filter(j => j.status === 'running' || j.status === 'pending').length;
				const debounceMs = activeCount > 20 ? 10000 : activeCount > 5 ? 5000 : 2000;
				loadJobsTimer = setTimeout(loadJobs, debounceMs);
			}
		});
		lastFallbackAt = Date.now();
		tickTimer = setInterval(() => {
			tick = Date.now();
			// Socket down: missed job_update/transfer_progress frames are recovered by polling.
			if (!$wsState.connected && tick - lastFallbackAt >= 10000) {
				lastFallbackAt = tick;
				loadJobs();
				loadStatus();
			}
		}, 1000);

		// Handle URL params from global search bar
		const params = $page.url.searchParams;
		const paramArtist = params.get('artist');
		const paramTrack = params.get('track');
		const paramSearch = params.get('search');
		if (paramArtist && paramTrack) {
			searchQuery = `${paramArtist} - ${paramTrack}`;
			searchSoulseek();
		} else if (paramSearch) {
			searchQuery = paramSearch;
			searchSoulseek();
		}
	});

	onDestroy(() => {
		if (unsubJobUpdate) unsubJobUpdate();
		destroyed = true;
		clearInterval(tickTimer);
		clearTimeout(statusTimer);
		clearTimeout(loadJobsTimer);
		clearTimeout(countsTimer);
	});
</script>

<svelte:head>
	<title>{transferringCount ? `(${transferringCount}) ` : ''}Downloads · Zonik</title>
</svelte:head>

<div class="max-w-6xl">
	<PageHeader
		title="Downloads"
		{subtitle}
		icon={Download}
		color="var(--color-downloads)">
		{#snippet actions()}
			{#if slsk}
				{#if slsk.connected}
					<span title={slsk.username ? `Logged in as ${slsk.username}${slsk.reconnects ? ` · ${plural(slsk.reconnects, 'reconnect')}` : ''}` : ''}>
						<Badge variant="success">
							<span class="inline-block w-1.5 h-1.5 rounded-full bg-current animate-pulse mr-1.5"></span>
							Soulseek connected
						</Badge>
					</span>
				{:else}
					<Badge variant="error">
						{slsk.disconnected_since ? `Not connected since ${clockTime(slsk.disconnected_since * 1000)}` : 'Soulseek not connected'}{slsk.reconnecting ? ' · reconnecting…' : ''}
					</Badge>
				{/if}
			{/if}
			{#if $wsState.connected}
				<Badge variant="info">Live{wsAgeS != null ? ` · updated ${wsAgeS} s ago` : ''}</Badge>
			{:else}
				<Badge variant="warning">Reconnecting{wsAgeS != null ? ` · last update ${wsAgeS} s ago` : ''}</Badge>
			{/if}
		{/snippet}
	</PageHeader>

	<!-- Search Bar -->
	<div class="flex gap-2.5 mb-6">
		<div class="flex-1 relative">
			<Search class="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--text-disabled)]" />
			<input type="text" placeholder="Search P2P network... (e.g. Artist - Track)" bind:value={searchQuery} onkeydown={handleKeydown}
				class="w-full bg-[var(--surface-base)] ghost-border rounded-lg pl-10 pr-4 py-2.5 text-sm text-[var(--text-body)]
					placeholder-[var(--text-disabled)] focus:outline-none focus:ring-1 focus:border-[var(--color-downloads)]/50 focus:ring-[var(--color-downloads)]/20" />
		</div>
		<Button variant="primary" loading={searching} disabled={!searchQuery.trim()} onclick={searchSoulseek}>
			<Search class="w-3.5 h-3.5" />
			Search
		</Button>
		<Button variant="success" disabled={!searchQuery.trim()} onclick={autoDownload} title="Auto-pick and download best match">
			<Zap class="w-3.5 h-3.5" />
			<span class="hidden sm:inline">Auto-Pick</span>
		</Button>
	</div>

	<!-- Search Results -->
	{#if searching}
		<Card padding="p-4" class="mb-6">
			<div class="flex flex-col items-center gap-3">
				<div class="w-6 h-6 border-2 border-[var(--color-downloads)] border-t-transparent rounded-full animate-spin"></div>
				<p class="text-sm text-[var(--text-muted)]">Searching P2P network...</p>
			</div>
		</Card>
	{:else if searchDone}
		<Card padding="p-0" class="mb-6">
			<!-- Results header -->
			<div class="px-4 py-3 ">
				<div class="flex items-center justify-between flex-wrap gap-2">
					<p class="text-xs text-[var(--text-muted)]">
						{resultCount} results from {resultUsers} users
						{#if allFilteredResults.length !== results.length}
							· {allFilteredResults.length} shown
						{/if}
					</p>
					<div class="flex items-center gap-3">
						<FilterPills
							options={[
								{ value: 'all', label: 'All', count: formatCounts.all, color: 'downloads' },
								{ value: 'flac', label: 'FLAC', count: formatCounts.flac, color: 'downloads' },
								{ value: '320', label: '320+', count: formatCounts.high, color: 'downloads' },
								{ value: '256', label: '256+', count: formatCounts.mid, color: 'downloads' },
							]}
							value={formatFilter}
							onchange={(v) => { formatFilter = v; resultsPage = 0; }}
						/>
						<!-- Per page selector -->
						<select bind:value={resultsPerPage} onchange={() => resultsPage = 0}
							class="bg-[var(--surface-lowest)] ghost-border rounded-md px-2 py-1 text-xs text-[var(--text-muted)]">
							{#each [25, 50, 100] as n}
								<option value={n}>{n}/page</option>
							{/each}
						</select>
					</div>
				</div>
			</div>

			{#if filteredResults.length}
				{@const resultColumns = [
					{ key: 'quality', label: '' },
					{ key: 'title', label: 'Title' },
					{ key: 'user', label: 'User' },
					{ key: 'format', label: 'Format' },
					{ key: 'bitrate', label: 'Bitrate' },
					{ key: 'size', label: 'Size' },
					{ key: 'actions', label: '' },
				]}
				<DataTable
					columns={resultColumns}
					rows={filteredResults}
					rowKey={(r) => r.username + r.filename}
					minWidth="600px"
					rowClass={(r) => {
						const inline = getResultInlineStatus(r);
						if (inline?.status === 'completed') return 'bg-green-500/5 group';
						if (inline?.status === 'failed') return 'bg-red-500/5 group';
						if (inline?.status === 'downloading') return 'bg-blue-500/5 group';
						return 'group';
					}}>
					{#snippet header()}
						<th class="px-4 py-2 w-5">
							<button onclick={() => toggleSort('quality')} class="font-medium text-xs uppercase tracking-wider whitespace-nowrap hover:text-[var(--text-primary)] transition-colors"
								title="Sort by quality">
								{sortCol === 'quality' ? (sortAsc ? '↑' : '↓') : '◆'}
							</button>
						</th>
						<th class="px-4 py-2 font-medium text-xs uppercase tracking-wider">Title</th>
						<th class="px-4 py-2 hidden md:table-cell">
							<button onclick={() => toggleSort('user')} class="font-medium text-xs uppercase tracking-wider whitespace-nowrap hover:text-[var(--text-primary)] transition-colors">
								User {sortCol === 'user' ? (sortAsc ? '↑' : '↓') : ''}
							</button>
						</th>
						<th class="px-4 py-2">
							<button onclick={() => toggleSort('format')} class="font-medium text-xs uppercase tracking-wider whitespace-nowrap hover:text-[var(--text-primary)] transition-colors">
								Format {sortCol === 'format' ? (sortAsc ? '↑' : '↓') : ''}
							</button>
						</th>
						<th class="px-4 py-2 hidden sm:table-cell">
							<button onclick={() => toggleSort('bitrate')} class="font-medium text-xs uppercase tracking-wider whitespace-nowrap hover:text-[var(--text-primary)] transition-colors">
								Bitrate {sortCol === 'bitrate' ? (sortAsc ? '↑' : '↓') : ''}
							</button>
						</th>
						<th class="px-4 py-2">
							<button onclick={() => toggleSort('size')} class="font-medium text-xs uppercase tracking-wider whitespace-nowrap hover:text-[var(--text-primary)] transition-colors">
								Size {sortCol === 'size' ? (sortAsc ? '↑' : '↓') : ''}
							</button>
						</th>
						<th class="px-4 py-2"></th>
					{/snippet}
					{#snippet row(r)}
						{@const key = r.username + r.filename}
						{@const fname = shortFilename(r.filename)}
						{@const pathArtist = extractArtistFromPath(r.filename)}
						{@const inline = getResultInlineStatus(r)}
						<td class="px-4 py-2">
							{#if r.slots_free}
								<Wifi class="w-3.5 h-3.5 text-green-400" />
							{:else}
								<Wifi class="w-3.5 h-3.5 text-[var(--text-disabled)]" />
							{/if}
						</td>
						<td class="px-4 py-2 max-w-xs">
							<p class="text-[var(--text-body)] truncate" title={r.filename}>{fname}</p>
							{#if inline?.status === 'downloading' && inline.progress > 0}
								<div class="mt-1 flex items-center gap-2">
									<div class="flex-1 h-1 bg-[var(--border-interactive)] rounded-full overflow-hidden">
										<div class="h-full bg-[var(--color-downloads)] rounded-full transition-all duration-300"
											style="width: {inline.progress}%"></div>
									</div>
									<span class="text-xs text-[var(--text-muted)] font-mono whitespace-nowrap">
										{inline.speed > 0 ? formatSpeed(inline.speed) : `${Math.round(inline.progress)}%`}
									</span>
								</div>
							{:else if pathArtist}
								<p class="text-xs text-[var(--text-muted)] truncate">{pathArtist}</p>
							{/if}
						</td>
						<td class="px-4 py-2 text-[var(--text-secondary)] hidden md:table-cell">
							<span class="truncate block max-w-[120px]" title={r.username}>
								{r.username}
							</span>
						</td>
						<td class="px-4 py-2">
							<div class="flex items-center gap-1">
								<Badge variant={r.extension === 'flac' ? 'success' : r.extension === 'mp3' ? 'default' : 'warning'}>
									{r.extension.toUpperCase()}
								</Badge>
								{#if r.ai_pick}
									<Badge variant="warning">AI Pick</Badge>
								{/if}
							</div>
						</td>
						<td class="px-4 py-2 text-[var(--text-muted)] font-mono text-xs hidden sm:table-cell">
							{formatBitrate(r.bitrate) || '—'}
						</td>
						<td class="px-4 py-2 text-[var(--text-muted)] font-mono text-xs">
							{formatSize(r.size)}
						</td>
						<td class="px-4 py-2">
							{#if inline?.status === 'completed'}
								{#if inline.trackId}
									<a href="/library?track={encodeURIComponent(inline.trackId)}" title="Open track">
										<Badge variant="success">
											<CircleCheck class="w-3 h-3 mr-0.5" />
											done &rarr;
										</Badge>
									</a>
								{:else}
									<Badge variant="success">
										<CircleCheck class="w-3 h-3 mr-0.5" />
										done
									</Badge>
								{/if}
							{:else if inline?.status === 'failed'}
								<div class="flex items-center gap-1">
									<Badge variant="error">failed</Badge>
									<button onclick={() => downloadFile(r)} class="p-1 text-[var(--text-muted)] hover:text-[var(--color-downloads)] transition-colors" title="Retry">
										<RotateCcw class="w-3 h-3" />
									</button>
								</div>
							{:else if inline?.status === 'downloading'}
								<Badge variant="info">
									<span class="inline-block w-1.5 h-1.5 rounded-full bg-current animate-pulse mr-1"></span>
									{inline.progress > 0 ? `${Math.round(inline.progress)}%` : 'dl'}
								</Badge>
							{:else if inline?.status === 'searching' || inline?.status === 'queued'}
								<Badge variant="default">
									<span class="inline-block w-1.5 h-1.5 rounded-full bg-current animate-pulse mr-1"></span>
									{inline.status === 'searching' ? 'search' : 'wait'}
								</Badge>
							{:else}
								<Button variant="success" size="sm" loading={downloading[key]} onclick={() => downloadFile(r)}>
									<Download class="w-3 h-3" />
								</Button>
							{/if}
						</td>
					{/snippet}
				</DataTable>
				<!-- Results pagination -->
				{#if totalResultPages > 1}
					<div class="flex items-center justify-between px-4 py-2 ">
						<Button variant="ghost" size="sm" disabled={resultsPage === 0}
							onclick={() => resultsPage--}>
							<ChevronLeft class="w-3.5 h-3.5" /> Prev
						</Button>
						<span class="text-xs text-[var(--text-muted)]">
							Page {resultsPage + 1} of {totalResultPages}
						</span>
						<Button variant="ghost" size="sm" disabled={resultsPage >= totalResultPages - 1}
							onclick={() => resultsPage++}>
							Next <ChevronRight class="w-3.5 h-3.5" />
						</Button>
					</div>
				{/if}
			{:else}
				{#if searchBlacklisted}
					<EmptyState title="Blacklisted" description={`Not searched: this artist or track is on your download blacklist${searchBlacklisted.reason ? ` (${searchBlacklisted.reason})` : ''}.`}>
						{#snippet icon()}<ShieldBan class="w-10 h-10" />{/snippet}
					</EmptyState>
				{:else}
					<EmptyState title="No results" description="No P2P results match the current filter.">
						{#snippet icon()}<Search class="w-10 h-10" />{/snippet}
					</EmptyState>
				{/if}
			{/if}
		</Card>
	{/if}

	<!-- Downloads (unified: active + history). Always mounted: pills, scope and empty states render at 0. -->
	{#snippet sourceChip(job)}
		<span class="px-1.5 py-0.5 rounded bg-[var(--surface-container-high)] text-[var(--text-muted)] text-[10px] font-medium flex-shrink-0 whitespace-nowrap">{sourceLabel(job)}</span>
	{/snippet}

	{#snippet extBadge(ext)}
		{#if ext}
			<Badge size="sm" variant={ext === 'flac' ? 'success' : ext === 'mp3' ? 'default' : 'warning'}>{ext.toUpperCase()}</Badge>
		{/if}
	{/snippet}

	{#snippet removeButton(job)}
		<Button variant="icon" size="sm" class="hover:!text-rose-400" title="Remove (deletes the row on the server)" aria-label="Remove"
			onclick={() => askRemove(job)}>
			<Trash2 class="w-3.5 h-3.5" />
		</Button>
	{/snippet}

	{#snippet doneRow(job)}
		{@const jobResult = parseJobResult(job)}
		{@const t = parseJobTracks(job)?.[0]}
		{@const rawTitle = jobTitle(job)}
		{@const outcome = doneOutcome(job)}
		{@const muted = outcome?.kind === 'already_had'}
		{@const fname = t?.filename || jobResult?.filename?.split(/[/\\]/).pop() || ''}
		{@const fmt = job.track?.format || fileExtension(fname)}
		{@const fsize = job.track?.file_size || t?.file_size || t?.size || jobResult?.file_size || jobResult?.size || 0}
		{@const peer = t?.username || jobResult?.username || ''}
		{@const attemptNo = Number(job.attempt ?? t?.attempt) || 0}
		{@const trackId = trackIdOf(job)}
		{@const timeIso = job.finished_at || job.started_at || job.created_at}
		<div class="grid grid-cols-[10px_minmax(0,1.3fr)_196px_52px_62px_150px_44px_100px_100px_28px] max-md:grid-cols-[10px_minmax(0,1fr)_28px] items-center gap-x-2.5 gap-y-1 px-3 py-2 rounded-lg bg-[var(--surface-container)] hover:bg-[var(--surface-container-high)] transition-colors text-xs {muted ? 'opacity-60' : ''}">
			<span class="w-2 h-2 rounded-full {muted ? 'bg-[var(--text-disabled)]' : 'bg-emerald-400'} max-md:row-span-2 max-md:self-start max-md:mt-1.5" title={outcome?.label || 'Completed'}></span>
			<div class="min-w-0 flex items-center gap-2 max-md:col-start-2 max-md:row-start-1">
				<span class="font-medium text-[var(--text-primary)] truncate" title={rawTitle}>{rawTitle}</span>
				{@render sourceChip(job)}
			</div>
			<!-- Metadata cells: grid columns from md up, one wrapped line under the title below md -->
			<div class="md:contents max-md:col-start-2 max-md:row-start-2 max-md:flex max-md:flex-wrap max-md:items-center max-md:gap-x-2 max-md:gap-y-0.5 min-w-0">
				<span class="min-w-0 truncate" title={outcome?.label || ''}>
					{#if outcome}<Badge size="sm" variant={outcome.badgeVariant}>{outcome.label}</Badge>{/if}
				</span>
				<span class="md:text-center">{#if fmt}<FormatBadge format={fmt} class="!text-[10px] !py-0" />{/if}</span>
				<span class="text-[var(--text-muted)] font-mono text-[11px] md:text-right truncate">{fsize > 0 ? formatSize(fsize) : '—'}</span>
				<span class="text-[var(--text-muted)] text-[11px] truncate min-w-0" title={peer ? `from ${peer}${attemptNo > 1 ? ` (${ordinal(attemptNo)} peer tried)` : ''}` : ''}>
					{peer || '—'}{#if peer && attemptNo > 1}<span class="text-[var(--text-disabled)]"> · {ordinal(attemptNo)} peer</span>{/if}
				</span>
				<span class="text-[var(--text-muted)] font-mono text-[11px] md:text-right whitespace-nowrap" title={timeIso ? formatDateTime(timeIso) : ''}>{timeIso ? whenShort(timeIso) : '—'}</span>
				<span class="text-[var(--text-muted)] text-[11px] truncate">{playedText(job, outcome)}</span>
				{#if trackId}
					<a href="/library?track={encodeURIComponent(trackId)}" class="text-sky-400 hover:text-sky-300 font-medium transition-colors md:text-right whitespace-nowrap">
						{muted ? 'Open existing' : 'Open track'} <span aria-hidden="true">&rarr;</span>
					</a>
				{:else}
					<a href="/library?search={encodeURIComponent(getSearchQueryForJob(job).replace(' - ', ' '))}" class="text-sky-400 hover:text-sky-300 font-medium transition-colors md:text-right whitespace-nowrap" title="Search the library">
						In library <span aria-hidden="true">&rarr;</span>
					</a>
				{/if}
			</div>
			<div class="flex justify-end max-md:col-start-3 max-md:row-start-1">{@render removeButton(job)}</div>
		</div>
	{/snippet}

	{#snippet failedActions(job)}
		{@const searchQ = getSearchQueryForJob(job)}
		{#if searchQ}
			<Button variant="icon" size="sm" title="Search P2P by hand" aria-label="Search by hand"
				onclick={() => { searchQuery = searchQ; searchSoulseek(); window.scrollTo({ top: 0, behavior: 'smooth' }); }}>
				<Search class="w-3.5 h-3.5" />
			</Button>
		{/if}
		<Button variant="icon" size="sm" class="hover:!text-emerald-400" title="Retry (replaces this row)" aria-label="Retry" onclick={() => retryJob(job.id)}>
			<RotateCcw class="w-3.5 h-3.5" />
		</Button>
		<Button variant="icon" size="sm" class="hover:!text-orange-400" title="Stop trying (blacklist this track)" aria-label="Stop trying"
			disabled={stoppedIds.has(job.id)} onclick={() => stopConfirm = { id: job.id, title: jobTitle(job) }}>
			<ShieldBan class="w-3.5 h-3.5" />
		</Button>
		{@render removeButton(job)}
	{/snippet}

	{#snippet failedRow(job)}
		{@const rawTitle = jobTitle(job)}
		{@const sentence = failureSentence(job)}
		{@const next = nextCell(job)}
		{@const cls = job.failure_class}
		<div class="grid grid-cols-[10px_minmax(0,1.05fr)_minmax(0,1.5fr)_76px_132px_120px] max-md:grid-cols-[10px_minmax(0,1fr)_28px] items-center gap-x-2.5 gap-y-1 px-3 py-2 rounded-lg bg-[var(--surface-container)] hover:bg-[var(--surface-container-high)] transition-colors text-xs">
			<span class="w-2 h-2 rounded-full {cls === 'cancelled' || cls === 'infra' || cls === 'orphan' ? 'bg-[var(--text-disabled)]' : 'bg-rose-400'} max-md:row-span-3 max-md:self-start max-md:mt-1.5" title="Failed"></span>
			<div class="min-w-0 flex items-center gap-2 max-md:col-start-2 max-md:row-start-1">
				<span class="font-medium text-[var(--text-primary)] truncate" title={rawTitle}>{rawTitle}</span>
				{@render sourceChip(job)}
			</div>
			<p class="min-w-0 whitespace-normal text-[var(--text-secondary)] leading-snug max-md:col-start-2 max-md:row-start-2">{sentence || 'Failed'}</p>
			<!-- HISTORY + NEXT: two columns from md up, one line below md -->
			<div class="md:contents max-md:col-start-2 max-md:row-start-3 max-md:flex max-md:flex-wrap max-md:gap-x-2 text-[11px]">
				<span class="text-[var(--text-muted)] font-mono whitespace-nowrap">{historyText(job)}</span>
				<span class="{TONE_TEXT[next.tone] || TONE_TEXT.default} min-w-0">{next.text}</span>
			</div>
			<div class="flex items-center justify-end gap-0.5 max-md:col-start-2 max-md:row-start-4 max-md:justify-start">
				{@render failedActions(job)}
			</div>
		</div>
	{/snippet}

	{#snippet pager()}
		{#if jobs.length >= PAGE_LIMIT || jobsOffset > 0}
			<div class="flex items-center justify-between mt-4">
				<Button variant="ghost" size="sm" disabled={jobsOffset === 0}
					onclick={() => { jobsOffset = Math.max(0, jobsOffset - PAGE_LIMIT); loadJobs(); }}>
					<ChevronLeft class="w-3.5 h-3.5" />
					Prev
				</Button>
				<span class="text-xs text-[var(--text-muted)]">
					{jobsOffset + 1}–{jobsOffset + jobs.length}
				</span>
				<Button variant="ghost" size="sm" disabled={jobs.length < PAGE_LIMIT}
					onclick={() => { jobsOffset += PAGE_LIMIT; loadJobs(); }}>
					Next
					<ChevronRight class="w-3.5 h-3.5" />
				</Button>
			</div>
		{/if}
	{/snippet}

	{#snippet liveRow(job)}
		{@const transfer = getTransferForJob(job)}
		{@const st = stageOf(job, transfer)}
		{@const jobResult = parseJobResult(job)}
		{@const t = parseJobTracks(job)?.[0]}
		{@const rawTitle = jobTitle(job)}
		{@const fname = t?.filename || jobResult?.filename?.split(/[/\\]/).pop() || transfer?.filename?.split(/[/\\]/).pop() || ''}
		{@const ext = fileExtension(fname)}
		{@const fsize = t?.file_size || t?.size || jobResult?.file_size || jobResult?.size || transfer?.total_bytes || 0}
		{@const peer = transfer?.username || t?.username || jobResult?.username || (job.id ? jobDetails[job.id]?.[0]?.username : '') || ''}
		<div class="grid grid-cols-[10px_minmax(0,1fr)_224px_28px] max-md:grid-cols-[10px_minmax(0,1fr)_28px] items-center gap-x-2.5 gap-y-1 px-3 py-2 rounded-lg bg-[var(--surface-container)] hover:bg-[var(--surface-container-high)] transition-colors text-xs">
			<span class="w-2 h-2 rounded-full {COLOUR_DOT[st.colour] || COLOUR_DOT.muted} {st.stage === 'transferring' || st.stage === 'searching' ? 'animate-pulse' : ''} max-md:row-span-2 max-md:self-start max-md:mt-1.5" title={st.word}></span>
			<div class="min-w-0 max-md:col-start-2 max-md:row-start-1">
				<div class="flex items-center gap-2 min-w-0">
					<span class="font-medium text-[var(--text-primary)] truncate" title={rawTitle}>{rawTitle}</span>
					{@render sourceChip(job)}
					{@render extBadge(ext)}
					{#if fsize > 0 || peer}
						<span class="text-[11px] text-[var(--text-muted)] truncate min-w-0">
							{#if fsize > 0}<span class="font-mono">{formatSize(fsize)}</span>{/if}{#if fsize > 0 && peer} · {/if}{#if peer}<span title="from {peer}">{peer}</span>{/if}
						</span>
					{/if}
				</div>
				<p class="mt-0.5 text-[11px] min-w-0 whitespace-normal leading-snug">
					<span class="font-medium {COLOUR_TEXT[st.colour] || COLOUR_TEXT.muted}">{st.word}</span>{#if st.detail}<span class="text-[var(--text-muted)]"> · {st.detail}</span>{/if}
				</p>
				{#if st.stage === 'transferring' && st.progress != null}
					<div class="mt-1 h-1 rounded-full overflow-hidden bg-[var(--border-interactive)]">
						<div class="h-full rounded-full bg-[var(--color-downloads)] transition-all duration-300" style="width: {st.progress}%"></div>
					</div>
				{/if}
			</div>
			<div class="min-w-0 md:text-right font-mono text-[11px] leading-tight max-md:col-start-2 max-md:row-start-2" title={job.started_at ? `created ${rel(job.started_at)}` : ''}>
				<div class="truncate {st.amber ? 'text-amber-400' : 'text-[var(--text-secondary)]'}">{st.big}</div>
				{#if st.small}<div class="truncate text-[var(--text-muted)]">{st.small}</div>{/if}
			</div>
			<div class="flex justify-end max-md:col-start-3 max-md:row-start-1">
				<Button variant="icon" size="sm" class="hover:!text-rose-400" title="Cancel" aria-label="Cancel" onclick={() => cancelJob(job.id)}>
					<X class="w-3.5 h-3.5" />
				</Button>
			</div>
		</div>
	{/snippet}

	<Card padding="p-4" class="mb-6">
		<div class="flex items-center justify-between mb-3">
			<div class="flex items-center gap-2">
				<Download class="w-4 h-4 text-[var(--color-downloads)]" />
				<h2 class="text-base font-semibold text-[var(--text-primary)]">Downloads</h2>
			</div>
		</div>
		<div class="flex items-center justify-between flex-wrap gap-2 mb-4">
		<FilterPills
			options={[
				{ value: 'active', label: 'Active', color: 'downloads', count: stages?.live ?? jobStatusCounts.active ?? 0 },
				{ value: 'completed', label: 'Done', color: 'downloads', count: jobStatusCounts.completed || 0 },
				{ value: 'failed', label: 'Failed', color: 'downloads', count: jobStatusCounts.failed || 0 },
				{ value: 'all', label: 'All', color: 'downloads' },
			]}
			value={jobStatusFilter}
			onchange={setJobFilter}
		/>
			<!-- One scope for lists, pill counts, buckets and footers -->
			<div class="inline-flex rounded-lg p-0.5 bg-[var(--surface-container)] text-xs" role="group" aria-label="Period">
				{#each SCOPES as sc (sc.value)}
					<button type="button" onclick={() => setScope(sc.value)} aria-pressed={scope === sc.value}
						class="px-3 py-1.5 rounded-md font-medium transition-all {scope === sc.value ? 'bg-[var(--surface-container-high)] text-[var(--text-primary)] shadow-sm' : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'}">
						{sc.label}
					</button>
				{/each}
			</div>
		</div>

		{#if !jobsLoaded}
			<Skeleton variant="list-item" tone="high" count={5} />
		{:else if jobStatusFilter === 'completed'}
			{#if doneTotals || jobStatusCounts.completed > 0}
				<div class="flex items-center justify-between flex-wrap gap-2 mb-3">
					<p class="text-xs text-[var(--text-muted)]">{doneTotals}</p>
					<Button variant="secondary" size="sm" disabled={!jobStatusCounts.completed} onclick={() => clearCompletedConfirm = true}>
						<Eraser class="w-3.5 h-3.5" />
						Clear completed history on the server
					</Button>
				</div>
			{/if}

			{#if displayedCompletedJobs.length === 0}
				<EmptyState compact title="No downloads finished in this period">
					{#snippet icon()}<Download class="w-6 h-6" />{/snippet}
				</EmptyState>
			{:else}
				<div class="grid grid-cols-[10px_minmax(0,1.3fr)_196px_52px_62px_150px_44px_100px_100px_28px] gap-x-2.5 px-3 pb-1 text-[10px] uppercase tracking-wider text-[var(--text-disabled)] max-md:hidden">
					<span></span><span>Track</span><span>Outcome</span><span class="text-center">Format</span><span class="text-right">Size</span><span>From</span><span class="text-right">At</span><span>Played</span><span></span><span></span>
				</div>
				<div class="space-y-1.5">
					{#each displayedCompletedJobs as job (job.id)}
						{@render doneRow(job)}
					{/each}
				</div>

				{@const totalInTimeframe = jobStatusCounts.completed}
				{#if totalInTimeframe > displayedCompletedJobs.length}
					<div class="mt-4 pt-3 flex items-center justify-between flex-wrap gap-2 text-xs text-[var(--text-muted)]">
						<span>
							Showing <span class="font-medium text-[var(--text-secondary)]">{displayedCompletedJobs.length}</span> of <span class="font-medium text-[var(--text-secondary)]">{totalInTimeframe.toLocaleString()}</span>
						</span>
						<div class="flex items-center gap-2">
							<button onclick={() => expandDoneList(25)} class="text-sky-400 hover:text-sky-300 font-medium hover:underline transition-colors">
								View earlier ({Math.min(25, totalInTimeframe - displayedCompletedJobs.length)} more) &darr;
							</button>
							{#if totalInTimeframe - displayedCompletedJobs.length > 25}
								<span>&middot;</span>
								<button onclick={() => expandDoneList(totalInTimeframe)} class="text-sky-400 hover:text-sky-300 font-medium hover:underline transition-colors">
									View all ({totalInTimeframe.toLocaleString()})
								</button>
							{/if}
						</div>
					</div>
				{/if}
			{/if}

		{:else if jobStatusFilter === 'failed'}
			{@const peerCount = getBucketCount('peer')}
			<div class="mb-4 flex items-center justify-between flex-wrap gap-3">
				<p class="text-xs text-[var(--text-muted)]">
					{(jobStatusCounts.failed || 0).toLocaleString()} failed {scopeInfo.phrase}, grouped by why they failed. Remove deletes a row on the server; Stop trying adds the track to the blacklist.
				</p>
				<div class="flex items-center gap-2 flex-wrap">
					{#if nonCriticalCount > 0}
						<Button variant="warning" size="sm" onclick={() => dismissNonCriticalConfirm = true}>
							<Trash2 class="w-3.5 h-3.5" />
							Delete Non-Critical ({nonCriticalCount.toLocaleString()})
						</Button>
					{/if}
					<!-- Peer problems only: never resurrects cancelled or infra rows -->
					<Button variant="secondary" size="sm" disabled={!peerCount}
						onclick={() => retryConfirm = { reason: 'peer', label: 'Peer problems', count: peerCount }}>
						<RotateCcw class="w-3.5 h-3.5" />
						Retry {peerCount.toLocaleString()} peer problem{peerCount === 1 ? '' : 's'}
					</Button>
				</div>
			</div>

			<div class="grid grid-cols-1 md:grid-cols-2 gap-3 mb-4">
				{#each FAILURE_CARD_CONFIG as cfg (cfg.reason)}
					{@const count = getBucketCount(cfg.reason)}
					{@const isInspecting = expandedFailureBucket === cfg.reason}
					{@const IconComp = cfg.icon}
					<div class="p-4 rounded-lg bg-[var(--surface-container)] {isInspecting || failureReason === cfg.reason ? 'ring-1 ring-sky-500/50' : ''} transition-all flex flex-col justify-between">
						<div>
							<div class="flex items-start justify-between gap-2 mb-2">
								<div class="flex items-center gap-2.5 min-w-0">
									<div class="w-8 h-8 rounded-lg {cfg.iconBg} flex items-center justify-center flex-shrink-0">
										<IconComp class="w-4 h-4 {cfg.iconColor}" />
									</div>
									<div class="min-w-0">
										<button type="button" class="text-left text-sm font-semibold leading-tight hover:text-sky-300 transition-colors {failureReason === cfg.reason ? 'text-sky-300' : 'text-[var(--text-primary)]'}"
											title={failureReason === cfg.reason ? 'Show every failed row' : 'Show only these rows below'} onclick={() => setFailureReason(cfg.reason)}>{cfg.title}</button>
										<span class="text-xs font-mono font-bold {cfg.iconColor}">{count.toLocaleString()} track{count === 1 ? '' : 's'}</span>
									</div>
								</div>
								<Button variant="icon" size="sm" class="hover:!text-rose-400" disabled={count === 0}
									title="Delete all {cfg.title} {scopeInfo.phrase} on the server" onclick={() => dismissFailedByReason(cfg.reason, cfg.title)}>
									<Trash2 class="w-3.5 h-3.5" />
								</Button>
							</div>
							<p class="text-xs text-[var(--text-muted)] leading-relaxed mb-4">{cfg.description}</p>
						</div>
						<div class="flex items-center justify-between gap-2 pt-3 mt-auto">
							{#if cfg.primaryAction === 'retry'}
								<Button variant="secondary" size="sm" disabled={count === 0}
									onclick={() => retryConfirm = { reason: cfg.reason, label: cfg.title, count }}>
									<RotateCcw class="w-3.5 h-3.5" />
									Retry All ({count.toLocaleString()})
								</Button>
							{:else}
								<Button variant="secondary" size="sm" disabled={count === 0}
									onclick={() => dismissFailedByReason(cfg.reason, cfg.title)}>
									<Trash2 class="w-3.5 h-3.5" />
									Delete All ({count.toLocaleString()})
								</Button>
							{/if}
							<Button variant="ghost" size="sm" disabled={count === 0} onclick={() => toggleInspectBucket(cfg.reason)}>
								Inspect (5)
								{#if isInspecting}<ChevronUp class="w-3.5 h-3.5" />{:else}<ChevronDown class="w-3.5 h-3.5" />{/if}
							</Button>
						</div>
					</div>
				{/each}
			</div>

			{#if expandedFailureBucket}
				{@const cfg = FAILURE_CARD_CONFIG.find(c => c.reason === expandedFailureBucket)}
				{@const samples = bucketSamples[expandedFailureBucket] || []}
				{@const DrawerIcon = cfg?.icon}
				<div class="p-4 rounded-lg bg-[var(--surface-container-high)] mb-5 space-y-3 animate-fade-slide-in">
					<div class="flex items-center justify-between">
						<div class="flex items-center gap-2">
							{#if DrawerIcon}<DrawerIcon class="w-4 h-4 {cfg?.iconColor}" />{/if}
							<h4 class="text-xs font-semibold text-[var(--text-primary)]">
								Sample tracks: <span class="text-sky-300">{cfg?.title}</span>
							</h4>
						</div>
						<Button variant="icon" size="sm" title="Close" onclick={() => expandedFailureBucket = null}>
							<X class="w-3.5 h-3.5" />
						</Button>
					</div>
					{#if bucketLoading}
						<Skeleton variant="list-item" count={3} />
					{:else if samples.length === 0}
						<p class="text-xs text-[var(--text-muted)] text-center py-4">No remaining samples in this category.</p>
					{:else}
						<div class="space-y-1.5">
							{#each samples as sample (sample.id)}
								{@const sampleTitle = jobTitle(sample)}
								<div class="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 px-3 py-2 rounded-lg bg-[var(--surface-container)] text-xs">
									<div class="min-w-0">
										<p class="font-medium text-[var(--text-primary)] truncate" title={sampleTitle}>{sampleTitle}</p>
										<p class="text-[11px] text-[var(--text-muted)] whitespace-normal leading-snug mt-0.5">{failureSentence(sample) || 'Failed'}</p>
									</div>
									<div class="flex items-center gap-0.5">
										{@render failedActions(sample)}
									</div>
								</div>
							{/each}
						</div>
					{/if}
				</div>
			{/if}

			<!-- Failed rows in the scope (filtered to one bucket when a card title is picked) -->
			{#if failureReason}
				{@const fcfg = FAILURE_CARD_CONFIG.find(c => c.reason === failureReason)}
				<div class="flex items-center gap-2 mb-2 text-xs text-[var(--text-muted)]">
					<span>Showing <span class="text-[var(--text-secondary)] font-medium">{fcfg?.title || failureReason}</span></span>
					<Button variant="ghost" size="sm" onclick={() => setFailureReason(failureReason)}>Show all</Button>
				</div>
			{/if}
			{#if jobs.length === 0}
				<EmptyState compact title="Nothing failed in this period">
					{#snippet icon()}<CircleCheck class="w-6 h-6" />{/snippet}
				</EmptyState>
			{:else}
				<div class="grid grid-cols-[10px_minmax(0,1.05fr)_minmax(0,1.5fr)_76px_132px_120px] gap-x-2.5 px-3 pb-1 text-[10px] uppercase tracking-wider text-[var(--text-disabled)] max-md:hidden">
					<span></span><span>Track</span><span>What happened</span><span>History</span><span>Next</span><span></span>
				</div>
				<div class="space-y-1">
					{#each jobs.filter(j => j.status === 'failed') as job (job.id)}
						{@render failedRow(job)}
					{/each}
				</div>
				{@render pager()}
			{/if}

		{:else}
			<!-- Active transfers: only what is moving data -->
			{#if activeHeroItems.length > 0}
				<div class="mb-5 p-4 rounded-lg bg-[var(--surface-container)] space-y-3">
					<div class="flex items-center justify-between flex-wrap gap-2">
						<div class="flex items-center gap-2">
							<span class="inline-flex items-center justify-center w-5 h-5 rounded-md bg-sky-500/20 text-sky-400 text-xs font-bold font-mono">{activeHeroItems.length}</span>
							<h3 class="text-sm font-semibold text-[var(--text-primary)]">Active Transfers</h3>
							<span class="text-xs text-[var(--text-muted)] font-mono">
								({activeHeroItems.length}{#if limits?.transfer_slots != null} of {limits.transfer_slots}{/if} slots active{#if totalTransferSpeed > 0} · {formatSpeed(totalTransferSpeed)} total{/if})
							</span>
						</div>
					</div>
					<div class="grid grid-cols-1 md:grid-cols-2 gap-3">
						{#each activeHeroItems as item (item.id)}
							{@const tr = item.transfer}
							{@const job = item.job}
							{@const st = stageOf(job, tr)}
							{@const fname = tr?.filename?.split(/[/\\]/).pop() || ''}
							{@const ext = fileExtension(fname)}
							{@const rawTitle = job ? jobTitle(job, fname || 'Downloading file') : (fname || 'Downloading file')}
							{@const peer = tr?.username || ''}
							<div class="rounded-lg p-4 space-y-3 relative overflow-hidden bg-gradient-to-br from-sky-500/10 via-[var(--surface-container-high)] to-[var(--surface-container)]">
								<div class="flex items-start justify-between gap-2">
									<div class="min-w-0 flex-1">
										<h4 class="text-sm font-semibold text-[var(--text-primary)] truncate" title={rawTitle}>{rawTitle}</h4>
										<div class="flex items-center gap-2 text-xs text-[var(--text-muted)] mt-0.5 flex-wrap">
											{#if peer}
												<span>from <span class="text-[var(--text-secondary)] font-medium">{peer}</span></span>
											{/if}
											{@render extBadge(ext)}
											{#if job}{@render sourceChip(job)}{/if}
											{#if st.small}<span>{st.small}</span>{/if}
										</div>
									</div>
									<Button variant="icon" size="sm" class="hover:!text-rose-400 flex-shrink-0" title="Cancel download" aria-label="Cancel download" onclick={() => cancelActiveItem(item)}>
										<X class="w-3.5 h-3.5" />
									</Button>
								</div>
								<div class="space-y-1.5">
									<div class="flex justify-between items-center gap-2 text-xs font-mono">
										<span class="text-[var(--text-muted)] truncate">{st.detail}</span>
										<span class="font-semibold whitespace-nowrap {st.amber ? 'text-amber-400' : 'text-sky-400'}">{st.big}</span>
									</div>
									{#if st.stage === 'transferring'}
										<div class="w-full h-1 rounded-full overflow-hidden bg-[var(--border-interactive)]">
											<div class="h-full rounded-full bg-[var(--color-downloads)] transition-all duration-300" style="width: {st.progress ?? 0}%"></div>
										</div>
									{/if}
								</div>
							</div>
						{/each}
					</div>
				</div>
			{/if}

			{#if displayJobs.length === 0}
				{#if activeHeroItems.length > 0}
					<p class="text-xs text-[var(--text-muted)] text-center py-4">No additional jobs in queue.</p>
				{:else}
					{#if jobStatusFilter === 'all'}
						<EmptyState compact title="No downloads yet">
							{#snippet icon()}<Download class="w-6 h-6" />{/snippet}
						</EmptyState>
					{:else}
						{@const dueToday = attemptsSummary?.due_before || 0}
						{@const backoffTotal = attemptsSummary?.total || 0}
						<EmptyState compact title="Nothing is downloading." description={quietText}>
							{#snippet icon()}<Download class="w-6 h-6" />{/snippet}
							{#snippet action()}
								{#if backoffTotal || dueToday}
									<div class="flex items-center justify-center gap-2 flex-wrap">
										{#if backoffTotal}
											<Button variant="secondary" size="sm" onclick={openBackoffList}>
												<ListOrdered class="w-3.5 h-3.5" />
												Backoff list ({backoffTotal.toLocaleString()})
											</Button>
										{/if}
										{#if dueToday}
											<Button variant="secondary" size="sm" loading={runningRetries} onclick={runRetriesNow}>
												<RotateCcw class="w-3.5 h-3.5" />
												Run the {dueToday.toLocaleString()} {dueToday === 1 ? 'retry' : 'retries'} now
											</Button>
										{/if}
									</div>
								{/if}
							{/snippet}
						</EmptyState>
					{/if}
				{/if}
			{:else}
				<div class="space-y-1">
					{#each displayJobs as job (job.id)}
						{#if job.status === 'completed'}
							{@render doneRow(job)}
						{:else if job.status === 'failed'}
							{@render failedRow(job)}
						{:else}
							{@render liveRow(job)}
						{/if}
					{/each}
				</div>
			{/if}

			{@render pager()}
		{/if}
	</Card>

	<!-- Uploads: shared library files peers are pulling from us -->
	{#if uploadRows.length || sharing}
		<Card padding="p-4" class="mb-6">
			<div class="flex items-center justify-between mb-3">
				<div class="flex items-center gap-2">
					<Upload class="w-4 h-4 text-[var(--color-discover)]" />
					<h2 class="text-base font-semibold text-[var(--text-primary)]">Uploads</h2>
					{#if uploadRows.length}
						<span class="text-xs text-[var(--text-muted)] font-mono">{uploadRows.length}</span>
					{/if}
				</div>
				{#if uploadSending > 0}
					<span class="text-xs text-[var(--text-muted)] font-mono">
						{uploadSending} sending{uploadSpeed > 0 ? ` · ${formatSpeed(uploadSpeed)}` : ''}
					</span>
				{/if}
			</div>
			{#if uploadRows.length}
				<div class="space-y-2">
					{#each uploadRows as up (up.username + '\u0000' + up.filename)}
						<div class="bg-[var(--surface-container)] rounded-lg overflow-hidden">
							<div class="flex items-center gap-3 px-3 py-2.5">
								<div class="flex-1 min-w-0">
									<p class="text-sm text-[var(--text-primary)] truncate" title={up.filename}>{baseName(up.filename)}</p>
									<div class="flex items-center gap-3 text-xs text-[var(--text-muted)] mt-0.5 flex-wrap">
										<span>to {up.username}</span>
										{#if up.state === 'queued' && up.place > 0}
											<span class="font-mono">place {up.place} in queue</span>
										{/if}
										{#if up.state === 'transferring' && up.speed > 0}
											<span class="font-mono">{formatSpeed(up.speed)}</span>
										{/if}
										{#if up.state === 'transferring' && up.eta_seconds > 0}
											<span class="font-mono">{formatETA(up.eta_seconds)}</span>
										{/if}
										{#if up.total_bytes > 0 && up.state !== 'queued' && up.state !== 'requested'}
											<span class="font-mono">{formatSize((up.offset || 0) + (up.sent_bytes ?? up.received_bytes ?? 0))} / {formatSize(up.total_bytes)}</span>
										{:else if up.total_bytes > 0}
											<span class="font-mono">{formatSize(up.total_bytes)}</span>
										{/if}
										{#if up.error && (up.state === 'failed' || up.state === 'denied')}
											<span class="text-red-400 truncate max-w-[240px]" title={up.error}>{up.error}</span>
										{/if}
									</div>
								</div>
								<Badge variant={UPLOAD_BADGE[up.state] || 'default'}>{UPLOAD_LABEL[up.state] || up.state}</Badge>
							</div>
							{#if up.state === 'transferring' || up.state === 'connected'}
								<div class="h-1 bg-[var(--border-interactive)]">
									<div class="h-full bg-[var(--color-discover)] transition-all duration-300"
										style="width: {up.progress || 0}%"></div>
								</div>
							{/if}
						</div>
					{/each}
				</div>
			{:else}
				<p class="text-sm text-[var(--text-muted)]">Sharing is on. Nobody is downloading from you right now.</p>
			{/if}
		</Card>
	{/if}

	<!-- Blacklist -->
	<Card padding="p-4">
		<div class="flex items-center justify-between mb-4">
			<div class="flex items-center gap-2">
				<ShieldBan class="w-4 h-4 text-red-400" />
				<h2 class="text-base font-semibold text-[var(--text-primary)]">Download Blacklist</h2>
			</div>
			<button onclick={() => showBlacklist = !showBlacklist}
				class="text-xs text-[var(--text-muted)] hover:text-white transition-colors font-mono">
				{showBlacklist ? 'Hide' : 'Show'} ({blacklist.length})
			</button>
		</div>

		{#if showBlacklist}
			<!-- Search library to blacklist -->
			<div class="mb-4 animate-fade-slide-in">
				<div class="flex flex-col sm:flex-row gap-2 mb-2">
					<input type="text" placeholder="Search library to blacklist..." bind:value={blSearch}
						onkeydown={(e) => e.key === 'Enter' && searchLibraryForBlacklist()}
						class="flex-1 bg-[var(--surface-lowest)] ghost-border rounded-md px-3 py-1.5 text-sm text-[var(--text-body)]
							placeholder-[var(--text-disabled)] focus:outline-none focus:ring-1 focus:border-[var(--color-accent)]/50 focus:ring-[var(--color-accent)]/20" />
					<Button variant="secondary" size="sm" disabled={!blSearch.trim() || blSearching} onclick={searchLibraryForBlacklist}>
						<Search class="w-3 h-3" />
						Find
					</Button>
				</div>
				{#if blSearchResults.length}
					<div class="space-y-1 mb-3 max-h-48 overflow-y-auto">
						{#each blSearchResults as artist}
							<div class="flex items-center justify-between px-3 py-1.5 bg-[var(--surface-container)] rounded-md text-sm hover:bg-[var(--surface-container-high)] transition-colors">
								<span class="text-[var(--text-primary)]">{artist}</span>
								<button onclick={async () => {
									try {
										await fetch('/api/download/blacklist', {
											method: 'POST',
											headers: { 'Content-Type': 'application/json' },
											body: JSON.stringify({ artist })
										});
										await loadBlacklist();
										blSearchResults = blSearchResults.filter(a => a !== artist);
										addToast(`Blacklisted: ${artist}`, 'success');
									} catch { addToast('Failed to blacklist', 'error'); }
								}} class="flex items-center gap-1 text-xs text-orange-400 hover:text-orange-300 transition-colors">
									<ShieldBan class="w-3 h-3" /> Block
								</button>
							</div>
						{/each}
					</div>
				{/if}
			</div>
			<!-- Manual add -->
			<div class="flex flex-col sm:flex-row gap-2 mb-4 animate-fade-slide-in">
				<input type="text" placeholder="Artist *" bind:value={blArtist}
					class="flex-1 bg-[var(--surface-lowest)] ghost-border rounded-md px-3 py-1.5 text-sm text-[var(--text-body)]
						placeholder-[var(--text-disabled)] focus:outline-none focus:ring-1 focus:border-[var(--color-accent)]/50 focus:ring-[var(--color-accent)]/20" />
				<input type="text" placeholder="Track (blank = entire artist)" bind:value={blTrack}
					class="flex-1 bg-[var(--surface-lowest)] ghost-border rounded-md px-3 py-1.5 text-sm text-[var(--text-body)]
						placeholder-[var(--text-disabled)] focus:outline-none focus:ring-1 focus:border-[var(--color-accent)]/50 focus:ring-[var(--color-accent)]/20" />
				<input type="text" placeholder="Reason" bind:value={blReason}
					class="w-48 bg-[var(--surface-lowest)] ghost-border rounded-md px-3 py-1.5 text-sm text-[var(--text-body)]
						placeholder-[var(--text-disabled)] focus:outline-none focus:ring-1 focus:border-[var(--color-accent)]/50 focus:ring-[var(--color-accent)]/20" />
				<Button variant="danger" size="sm" disabled={!blArtist.trim()} onclick={addBlacklistEntry}>
					<ShieldBan class="w-3 h-3" />
					Block
				</Button>
			</div>

			{#if blacklist.length > 3}
				<div class="mb-2">
					<input type="text" placeholder="Filter blacklist..." bind:value={blFilter}
						class="w-full sm:w-64 bg-[var(--surface-lowest)] ghost-border rounded-md px-3 py-1.5 text-sm text-[var(--text-body)]
							placeholder-[var(--text-disabled)] focus:outline-none focus:ring-1 focus:border-[var(--color-accent)]/50 focus:ring-[var(--color-accent)]/20" />
				</div>
			{/if}
			{#if filteredBlacklist.length}
				<div class="space-y-1 animate-fade-slide-in">
					{#each filteredBlacklist as entry}
						<div class="flex items-center justify-between px-3 py-2 bg-[var(--surface-container)] rounded-md text-sm hover:bg-[var(--surface-container-high)] transition-colors">
							<div>
								<span class="font-medium text-[var(--text-primary)]">{entry.artist}</span>
								{#if entry.track}
									<span class="text-[var(--text-secondary)]"> - {entry.track}</span>
								{:else}
									<Badge variant="error" class="ml-2">all tracks</Badge>
								{/if}
								{#if entry.reason}
									<span class="text-[var(--text-muted)] text-xs ml-2">({entry.reason})</span>
								{/if}
							</div>
							<button onclick={() => removeBlacklistEntry(entry.id)}
								class="text-[var(--text-disabled)] hover:text-red-400 transition-colors">
								<Trash2 class="w-3.5 h-3.5" />
							</button>
						</div>
					{/each}
				</div>
			{:else}
				<p class="text-[var(--text-muted)] text-sm">{blFilter ? 'No matching entries.' : 'No blacklisted artists or tracks.'}</p>
			{/if}
		{/if}
	</Card>
</div>

{#if retryConfirm}
	<Modal title="Retry failed downloads" onclose={() => retryConfirm = null} maxWidth="max-w-md">
		{#snippet children()}
			<p class="text-sm text-[var(--text-primary)]">
				Re-queue <span class="font-bold">{retryConfirm.count.toLocaleString()}</span> failed download{retryConfirm.count === 1 ? '' : 's'}
				({retryConfirm.label.toLowerCase()})?
			</p>
			<p class="text-xs text-[var(--text-muted)] mt-2">
				Each one is searched for again and gets a new entry; the failed entry it replaces is removed.
				{#if retryConfirm.reason === 'not_found' || retryConfirm.reason === 'no_better'}These weren't found last time, so most will likely fail again unless new peers have them.{/if}
				{#if retryConfirm.reason === 'infra'}These stopped for reasons outside the track (cancelled, a restart or an outage), so a retry usually works.{/if}
				{#if retryConfirm.reason === 'rejected'}These downloaded fine but weren't kept (already in the library, no better, or the wrong song), so retrying usually won't change anything.{/if}
			</p>
		{/snippet}
		{#snippet footer()}
			<Button variant="secondary" size="sm" onclick={() => retryConfirm = null}>Cancel</Button>
			<Button variant="primary" size="sm" disabled={retrying} onclick={retryFailed}>
				<RotateCcw class="w-3.5 h-3.5 mr-1" /> {retrying ? 'Re-queuing…' : 'Retry'}
			</Button>
		{/snippet}
	</Modal>
{/if}

{#if clearCompletedConfirm}
	<Modal title="Clear completed history on the server" onclose={() => clearCompletedConfirm = false} maxWidth="max-w-md">
		{#snippet children()}
			<p class="text-sm text-[var(--text-primary)]">
				Delete the <span class="font-bold">{jobStatusCounts.completed.toLocaleString()}</span> completed download records from {scopeInfo.phrase} on the server?
			</p>
			<p class="text-xs text-[var(--text-muted)] mt-2">
				Only the download log rows go. Files in your music library stay.
			</p>
		{/snippet}
		{#snippet footer()}
			<Button variant="secondary" size="sm" onclick={() => clearCompletedConfirm = false}>Cancel</Button>
			<Button variant="danger" size="sm" disabled={clearingCompleted} onclick={handleClearCompleted}>
				<Eraser class="w-3.5 h-3.5 mr-1" /> {clearingCompleted ? 'Clearing…' : 'Clear History'}
			</Button>
		{/snippet}
	</Modal>
{/if}

{#if dismissNonCriticalConfirm}
	<Modal title="Delete non-critical failures" onclose={() => dismissNonCriticalConfirm = false} maxWidth="max-w-md">
		{#snippet children()}
			<p class="text-sm text-[var(--text-primary)]">
				Delete <span class="font-bold">{nonCriticalCount.toLocaleString()}</span> non-critical failure records from {scopeInfo.phrase} on the server?
			</p>
			<p class="text-xs text-[var(--text-muted)] mt-2">
				This removes tracks where equal or higher quality already exists in your library, as well as rejected duplicate imports.
			</p>
		{/snippet}
		{#snippet footer()}
			<Button variant="secondary" size="sm" onclick={() => dismissNonCriticalConfirm = false}>Cancel</Button>
			<Button variant="primary" size="sm" disabled={dismissingNonCritical} onclick={handleDismissNonCritical}>
				<Trash2 class="w-3.5 h-3.5 mr-1" /> {dismissingNonCritical ? 'Deleting…' : 'Delete'}
			</Button>
		{/snippet}
	</Modal>
{/if}

{#if removeConfirm}
	<Modal title="Remove download" onclose={() => removeConfirm = null} maxWidth="max-w-md">
		{#snippet children()}
			<p class="text-sm text-[var(--text-primary)]">Remove <span class="font-semibold">{removeConfirm.title}</span> from the download history?</p>
			<p class="text-xs text-[var(--text-muted)] mt-2">
				This deletes the row on the server. Files in your library and the track's retry schedule are not touched.
			</p>
		{/snippet}
		{#snippet footer()}
			<Button variant="secondary" size="sm" onclick={() => removeConfirm = null}>Cancel</Button>
			<Button variant="danger" size="sm" disabled={removing} onclick={confirmRemove}>
				<Trash2 class="w-3.5 h-3.5 mr-1" /> {removing ? 'Removing…' : 'Remove'}
			</Button>
		{/snippet}
	</Modal>
{/if}

{#if stopConfirm}
	<Modal title="Stop trying this track" onclose={() => stopConfirm = null} maxWidth="max-w-md">
		{#snippet children()}
			<p class="text-sm text-[var(--text-primary)]">Blacklist <span class="font-semibold">{stopConfirm.title}</span>?</p>
			<p class="text-xs text-[var(--text-muted)] mt-2">
				This also removes its retry schedule; scheduler, bulk and playlist runs skip it from now on. You can undo it from the Download Blacklist below.
			</p>
		{/snippet}
		{#snippet footer()}
			<Button variant="secondary" size="sm" onclick={() => stopConfirm = null}>Cancel</Button>
			<Button variant="danger" size="sm" disabled={stopping} onclick={confirmStopTrying}>
				<ShieldBan class="w-3.5 h-3.5 mr-1" /> {stopping ? 'Blacklisting…' : 'Stop trying'}
			</Button>
		{/snippet}
	</Modal>
{/if}

{#if backoffOpen}
	<Modal title="Backoff list" onclose={() => backoffOpen = false} maxWidth="max-w-xl">
		{#snippet children()}
			<p class="text-xs text-[var(--text-muted)] mb-3">Tracks the automatic runs failed to find, soonest retry first. They are searched again when their backoff ends.</p>
			{#if backoffLoading}
				<Skeleton variant="list-item" count={4} />
			{:else if !backoffRows.length}
				<p class="text-sm text-[var(--text-muted)]">Nothing is waiting in backoff.</p>
			{:else}
				<div class="space-y-1">
					{#each backoffRows as row (row.key)}
						<div class="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 px-3 py-2 rounded-lg bg-[var(--surface-container-high)] text-xs">
							<div class="min-w-0">
								<p class="font-medium text-[var(--text-primary)] truncate">{row.artist} — {row.track}</p>
								<p class="text-[11px] text-[var(--text-muted)] truncate" title={row.last_error || ''}>
									{sourceLabel(row.source ? `dl:${row.source}` : null)} · {plural(row.attempts || 0, 'attempt')}{row.last_error ? ` · ${row.last_error}` : ''}
								</p>
							</div>
							<span class="font-mono text-[11px] whitespace-nowrap {row.retired ? 'text-rose-400' : 'text-[var(--text-secondary)]'}">
								{row.retired ? 'retired' : row.next_retry_at ? whenLong(row.next_retry_at) : '—'}
							</span>
						</div>
					{/each}
				</div>
			{/if}
		{/snippet}
	</Modal>
{/if}
