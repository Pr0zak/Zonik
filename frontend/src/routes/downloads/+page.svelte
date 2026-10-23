<script>
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { api } from '$lib/api.js';
	import { addToast, activeTransfers, activeUploads, wsState } from '$lib/stores.js';
	import { currentUser, can } from '$lib/auth.js';
	import { onJobUpdate } from '$lib/websocket.js';
	import { formatSize, formatSpeed, formatETA, parseUTC } from '$lib/utils.js';
	import { Download, Search, Zap, ShieldBan, Trash2, ChevronLeft, ChevronRight, RotateCcw, Eraser, CircleCheck, Wifi, Upload, ListOrdered, Pause, Ban } from 'lucide-svelte';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Button from '../../components/ui/Button.svelte';
	import Badge from '../../components/ui/Badge.svelte';
	import FilterPills from '../../components/ui/FilterPills.svelte';
	import Segmented from '../../components/ui/Segmented.svelte';
	import EmptyState from '../../components/ui/EmptyState.svelte';
	import DataTable from '../../components/ui/DataTable.svelte';
	import Modal from '../../components/ui/Modal.svelte';
	import Skeleton from '../../components/ui/Skeleton.svelte';
	import Pagination from '../../components/ui/Pagination.svelte';
	import HealthStrip from '../../components/downloads/HealthStrip.svelte';
	import IncidentBanner from '../../components/downloads/IncidentBanner.svelte';
	import GroupedList from '../../components/downloads/GroupedList.svelte';
	import LiveRow from '../../components/downloads/LiveRow.svelte';
	import FailedRow, { FAILED_GRID, FAILED_COLUMNS } from '../../components/downloads/FailedRow.svelte';
	import DoneRow, { DONE_GRID, DONE_COLUMNS } from '../../components/downloads/DoneRow.svelte';
	import BatchLine from '../../components/downloads/BatchLine.svelte';
	import RunRow from '../../components/downloads/RunRow.svelte';
	import JobDrawer from '../../components/downloads/JobDrawer.svelte';
	import { sourceLabel, clockTime, shortDate, firstTrack, failureClass, doneOutcome, plural } from '$lib/downloads/stage.js';
	import { groups, runs, batchOf } from '$lib/downloads/groups.js';

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

	// --- Downloads card ------------------------------------------------------------------
	// Three tabs (Live / Done / Failed) over one scope (Today / 7 days / 30 days). The scope
	// is sent as `since` = local midnight (0, 6 or 29 days back) in UTC and drives the Done
	// and Failed lists, the pill counts, the strip's Added tile, runs and footers. Live rows
	// are never scoped (a job queued before midnight is still live).
	const SCOPES = [
		{ value: 'today', label: 'Today', days: 0, phrase: 'today' },
		{ value: 'week', label: '7 days', days: 6, phrase: 'in the last 7 days' },
		{ value: 'month', label: '30 days', days: 29, phrase: 'in the last 30 days' },
	];
	const STATUS_QUERY = { live: 'pending,running', completed: 'completed', failed: 'failed' };
	const LIVE_LIMIT = 200; // live rows per request; more than this pages
	const DONE_PAGE = 200; // Done rows per request ("Show all" past this pages)
	const GROUP_LIMIT = 25; // rows per group before "Show N more"
	const LIVE_GRID = 'grid-cols-[10px_minmax(0,1fr)_224px_28px]';
	const LIVE_COLUMNS = [{ label: '' }, { label: 'Track · stage · detail' }, { label: 'Time', align: 'right' }, { label: '' }];

	// 1 s clock: relative times, chip ages, elapsed cells.
	let tick = $state(Date.now());
	let scope = $state('today');
	let scopeInfo = $derived(SCOPES.find(x => x.value === scope) || SCOPES[0]);
	let sinceISO = $derived.by(() => {
		const d = new Date(tick);
		d.setHours(0, 0, 0, 0);
		d.setDate(d.getDate() - scopeInfo.days);
		return d.toISOString();
	});

	let jobStatusFilter = $state('live'); // 'live' | 'completed' | 'failed'
	let stageFilter = $state(null); // Live tab narrowed from a strip tile: 'transferring' | 'searching'
	let liveJobs = $state([]);
	let liveOffset = $state(0);
	let doneJobs = $state([]);
	let doneLimit = $state(25);
	let doneOffset = $state(0);
	let doneOutcomeFilter = $state('all');
	let failedItems = $state([]); // GET /jobs/failed-tracks items reshaped as list items (one per track)
	let failedClass = $state(null); // Failed pill: a bucket key or null (all)
	let failureGroups = $state([]); // GET /jobs/failures: [{reason, label, count}] (job rows per bucket)
	let failedWeekCount = $state(null);
	let loadedTabs = $state({});
	let apiRuns = $state(null); // GET /jobs/runs items | null (not loaded / older server)
	let runPool = $state(null); // up to 200 completed rows of the scope, loaded when a run is expanded
	let openRuns = $state({});

	// Server-side counts (independent of paging), scoped by `since`.
	let jobStatusCounts = $state({ active: 0, completed: 0, failed: 0 });

	const n = (v) => (Number.isFinite(Number(v)) ? Number(v) : 0);
	const nowNaiveISO = () => new Date().toISOString().replace('Z', '');

	function parseJobResult(job) {
		if (!job?.result) return null;
		if (typeof job.result === 'object') return job.result;
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

	/** "Artist — Track" from tracks[0], else the description's first two " — " parts. */
	function jobTitle(job, fallback = 'Unknown track') {
		const t = firstTrack(job);
		if (t.artist && t.track) return `${t.artist} — ${t.track}`;
		const d = (job?.description || '').replace(/^Queued( for slot)?:\s*/i, '').replace(/\s*\(attempt\s+\d+.*?\)/i, '');
		const parts = d.split(' — ').filter(Boolean);
		if (parts.length >= 2) return `${parts[0]} — ${parts[1]}`;
		return d.trim() || fallback;
	}

	/** "HH:MM" today, "HH:MM tomorrow", else "Oct 17 HH:MM". */
	function whenLong(iso) {
		const d = parseUTC(iso);
		if (!d || Number.isNaN(d.getTime())) return '';
		if (d.toDateString() === new Date(tick).toDateString()) return clockTime(iso);
		if (d.toDateString() === new Date(tick + 86400000).toDateString()) return `${clockTime(iso)} tomorrow`;
		return `${shortDate(iso)} ${clockTime(iso)}`;
	}

	// --- Live status (GET /api/download/status, DC-12) ----------------------------------
	// Limits from settings, stage counts over every active job, the pacer and the Soulseek
	// connection. Polled every 5 s while anything is live, every 30 s otherwise; it also
	// seeds the transfer/upload stores the WebSocket keeps live, and refreshes the batches.
	let status = $state(null);
	let limits = $derived(status?.limits ?? null);
	let stages = $derived(status?.stages ?? null);
	let pacer = $derived(status?.pacer ?? null);
	let batches = $state([]); // GET /download/batches items | null (older server: backlog not counted)
	let statusTimer;
	let tickTimer;
	let lastFallbackAt = 0;
	let statusKickAt = 0;
	let destroyed = false;

	async function loadStatus() {
		try {
			const data = await api.getDownloadStatus();
			status = data;
			// With the socket down the poll is the only source, so an empty list must clear too.
			if (data.downloads?.length || !$wsState.connected) activeTransfers.set(data.downloads || []);
			activeUploads.set(data.uploads || []);
		} catch {}
		try { batches = (await api.getDownloadBatches())?.items || []; } catch { batches = null; }
	}

	function scheduleStatus() {
		clearTimeout(statusTimer);
		if (destroyed) return;
		statusTimer = setTimeout(async () => {
			await loadStatus();
			scheduleStatus();
		}, (stages?.live ?? 0) > 0 ? 5000 : 30000);
	}

	let subtitle = $derived(limits && limits.transfer_slots != null
		? `Limits from settings: ${plural(limits.transfer_slots, 'transfer slot')} · ${plural(limits.search_slots, 'search slot')} · ${limits.searches_per_minute} searches a minute, ${limits.search_min_interval_s} s apart`
		: 'Limits from settings');

	// Tab-title badge: files moving bytes right now.
	let transferringCount = $derived(stages?.transferring ?? $activeTransfers.filter(t => t.state === 'transferring').length);
	let wsAgeS = $derived($wsState.lastMessageAt ? Math.max(0, Math.round((tick - $wsState.lastMessageAt) / 1000)) : null);

	// --- Counts, summary, quiet-state facts ---------------------------------------------
	// Scoped loads drop a reply that arrives after the scope changed, so a quick
	// Today → 7 days toggle never leaves one tab's numbers on the other scope.
	async function loadJobCounts() {
		const s = sinceISO;
		try {
			const c = await api.getJobCounts('download,bulk_download', s);
			if (s !== sinceISO) return;
			jobStatusCounts = {
				active: c.active ?? ((c.pending || 0) + (c.running || 0)),
				// Older servers lack the scoped keys: fall back to the all-time ones.
				completed: c.completed_since ?? c.completed ?? 0,
				failed: c.failed_since ?? c.failed ?? 0,
			};
		} catch {}
		loadSummary();
	}

	// A burst of job_update frames (one per stage change) refreshes the counts at most twice a second.
	let countsTimer;
	function refreshCountsSoon() {
		if (countsTimer) return;
		countsTimer = setTimeout(() => { countsTimer = null; loadJobCounts(); }, 500);
	}

	// GET /api/jobs/summary (DC-9): outcomes, failed buckets, next, last finished.
	let summary = $state(null);
	let summaryLoadedAt = 0;
	async function loadSummary(force = false) {
		if (!force && Date.now() - summaryLoadedAt < 10000) return;
		summaryLoadedAt = Date.now();
		const s = sinceISO;
		try {
			const d = await api.getJobsSummary(s);
			if (s === sinceISO) summary = d;
		} catch {}
	}

	// Backoff ledger summary: next scheduled runs (Queue tile, quiet state) and retries due today.
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
		const [sum, due] = await Promise.allSettled([api.getAttemptsSummary(eod), api.getDownloadAttempts(eod, 1)]);
		if (sum.status === 'fulfilled') attemptsSummary = sum.value;
		firstDueAt = due.status === 'fulfilled' ? due.value?.items?.[0]?.next_retry_at || null : null;
		loadSummary(force);
		loadRuns();
	}

	let nextRun = $derived.by(() => {
		const r = attemptsSummary?.next_runs?.[0];
		return r?.next_run_at ? { at: r.next_run_at, label: r.label } : null;
	});

	let quietText = $derived.by(() => {
		const parts = [];
		const lf = summary?.last_finished;
		if (lf?.finished_at) {
			const what = [lf.artist, lf.track].filter(Boolean).join(' — ');
			parts.push(`Last job finished ${whenLong(lf.finished_at)} · ${sourceLabel(lf.card)}${what ? ` · ${what}` : ''}.`);
		}
		const next = attemptsSummary?.next_runs || [];
		if (next.length) {
			parts.push(`Next scheduled runs: ${next.slice(0, 4).map(r => `${r.label} ${whenLong(r.next_run_at)}`).join(', ')}.`);
		}
		const dueNow = attemptsSummary?.due_now || 0;
		const dueToday = attemptsSummary?.due_before || 0;
		if (dueNow) parts.push(`${plural(dueNow, 'track')} in backoff ${dueNow === 1 ? 'is' : 'are'} due again now.`);
		else if (dueToday) parts.push(`${plural(dueToday, 'track')} in backoff come${dueToday === 1 ? 's' : ''} due again${firstDueAt ? ` tonight from ${clockTime(firstDueAt)}` : ' today'}.`);
		return parts.join(' ');
	});

	const FAILED_WORDS = [
		['not_found', 'not found', 'not found'], ['peer', 'peer problem', 'peer problems'], ['rejected', 'not imported', 'not imported'],
		['no_better', 'nothing better', 'nothing better'], ['infra', "not the track's fault", "not the track's fault"],
	];

	/** "16 finished (14 added, 2 already had) · 4 failed (3 not found, 1 peer problem)" */
	let quietTotals = $derived.by(() => {
		const o = summary?.outcomes;
		if (!o) return '';
		const added = n(o.new) + n(o.replaced);
		const fin = added + n(o.already_had);
		const f = summary.failed || {};
		const failedTotal = n(f.total);
		const bits = FAILED_WORDS.filter(([k]) => n(f[k]) > 0).map(([k, one, many]) => `${n(f[k])} ${n(f[k]) === 1 ? one : many}`);
		let s = `${fin.toLocaleString()} finished (${added.toLocaleString()} added, ${n(o.already_had).toLocaleString()} already had)`;
		s += ` · ${failedTotal.toLocaleString()} failed${bits.length ? ` (${bits.join(', ')})` : ''}`;
		return s;
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
			const q = r?.queued ?? 0;
			addToast(q ? `Queued ${plural(q, 'retry', 'retries')} — they show up under Live as they start` : 'Nothing was due — no retries queued', q ? 'success' : 'info');
			loadQuiet(true);
		} catch (e) {
			addToast(`Retries not queued: ${e.message}`, 'error');
		} finally {
			runningRetries = false;
		}
	}

	// --- Incidents (DC-17): one banner for restart / outage waves ------------------------
	let incidents = $state([]);
	let incidentBusy = $state(false);
	let incidentsAt = 0;
	async function loadIncidents() {
		incidentsAt = Date.now();
		// Server default window (7 days): yesterday's restart still shows on Today.
		try { incidents = (await api.getIncidents())?.items || []; } catch {}
	}

	async function retryIncident(inc) {
		incidentBusy = inc.id;
		try {
			const r = await api.retryIncident(inc.id);
			if (r?.error) throw new Error(r.error);
			const t = r?.tracks ?? 0;
			addToast(t ? `Re-queued ${plural(t, 'download')} from the incident` : 'Nothing left to retry in this incident', t ? 'success' : 'info');
			await loadIncidents();
			loadJobs();
		} catch (e) {
			addToast(`Not retried: ${e.message}`, 'error');
		} finally {
			incidentBusy = false;
		}
	}

	async function dismissIncident(inc) {
		incidentBusy = inc.id;
		try {
			const r = await api.dismissIncident(inc.id);
			if (r?.error) throw new Error(r.error);
			const d = r?.dismissed ?? 0;
			if (d) {
				incidents = incidents.map(i => (i.id === inc.id ? { ...i, dismissed: true } : i));
				addToast(`Dismissed: ${plural(d, 'row')} marked on the server`, 'success');
			} else {
				addToast('Not dismissed: the server found no rows for this incident', 'warning');
			}
			loadIncidents();
		} catch (e) {
			addToast(`Not dismissed: ${e.message}`, 'error');
		} finally {
			incidentBusy = false;
		}
	}

	/** "yesterday's 142 are in the banner" for the infra group's reason clause. */
	let incidentNote = $derived.by(() => {
		const inc = incidents.find(i => i && !i.dismissed);
		if (!inc) return '';
		const d = parseUTC(inc.start);
		const c = n(inc.count);
		const verb = c === 1 ? 'is' : 'are';
		if (!d || Number.isNaN(d.getTime())) return `${c} more ${verb} in the banner`;
		const today = new Date(tick);
		const yesterday = new Date(tick - 86400000);
		if (d.toDateString() === today.toDateString()) return `today's ${c} ${verb} in the banner`;
		if (d.toDateString() === yesterday.toDateString()) return `yesterday's ${c} ${verb} in the banner`;
		return `the ${c} from ${shortDate(inc.start)} ${verb} in the banner`;
	});

	// --- Tabs, scope, strip filters -------------------------------------------------------
	function setJobFilter(v) {
		if (!STATUS_QUERY[v]) return;
		const changed = v !== jobStatusFilter;
		jobStatusFilter = v;
		if (v !== 'live') stageFilter = null;
		if (changed) selectedJobId = null;
		if (v === 'failed') loadIncidents();
		loadJobs(false);
	}

	function setScope(v) {
		if (v === scope) return;
		scope = v;
		doneLimit = 25;
		doneOffset = 0;
		runPool = null;
		apiRuns = null;
		openRuns = {};
		failedWeekCount = null;
		loadJobs();
		loadSummary(true);
		loadRuns(); // the quiet state's run rows follow the scope too
	}

	let activeTile = $derived(
		jobStatusFilter === 'completed' ? 'added'
			: jobStatusFilter === 'live' ? (stageFilter || ((stages?.live ?? 0) > 0 ? 'queue' : null))
				: null
	);

	function onTile(key) {
		if (key === 'soulseek') { goto('/stats'); return; }
		if (key === 'added') { setJobFilter('completed'); return; }
		if (key === 'transferring' || key === 'searching') {
			stageFilter = jobStatusFilter === 'live' && stageFilter === key ? null : key;
		} else {
			stageFilter = null;
		}
		if (jobStatusFilter !== 'live') setJobFilter('live');
	}

	// --- Loading --------------------------------------------------------------------------
	let loadSeq = 0;
	async function loadJobs(withCounts = true) {
		if (withCounts) loadJobCounts();
		const tab = jobStatusFilter;
		const seq = ++loadSeq;
		try {
			if (tab === 'failed') {
				loadFailureGroups();
				loadSummary();
				if (scope === 'today' && failedWeekCount == null) loadFailedWeek();
				await loadFailedTracks(seq);
			} else if (tab === 'completed') {
				const data = await api.getDownloadHistory(doneOffset, Math.min(Math.max(25, doneLimit), DONE_PAGE), STATUS_QUERY.completed, null, null, sinceISO);
				if (seq !== loadSeq) return;
				doneJobs = data.items || data;
				loadRuns();
				loadSummary();
			} else {
				const data = await api.getDownloadHistory(liveOffset, LIVE_LIMIT, STATUS_QUERY.live);
				if (seq !== loadSeq) return;
				liveJobs = data.items || data;
				if (!liveJobs.length) loadQuiet();
			}
		} catch (e) {
			console.error('Download list load failed:', e);
		}
		if (seq === loadSeq) loadedTabs = { ...loadedTabs, [tab]: true };
	}

	async function loadFailureGroups() {
		const s = sinceISO;
		let d = [];
		try { d = await api.getDownloadFailures(s); } catch {}
		if (s === sinceISO) failureGroups = d;
	}

	async function loadFailedWeek() {
		const d = new Date(tick);
		d.setHours(0, 0, 0, 0);
		d.setDate(d.getDate() - 6);
		try {
			const c = await api.getJobCounts('download,bulk_download', d.toISOString());
			failedWeekCount = c.failed_since ?? null;
		} catch {}
	}

	/** A failed-tracks item (DC-20) in the list-item shape the rows and groups read. */
	function failedItemToJob(it) {
		const lj = it.last_job || {};
		return {
			...it,
			id: lj.id ?? it.attempt_key,
			status: 'failed',
			failure_class: it.class ?? null,
			finished_at: lj.finished_at ?? null,
			source_errors: lj.source_errors ?? [],
			search: lj.search ?? null,
			result: JSON.stringify({ message: lj.message ?? '', source_errors: lj.source_errors ?? [], search: lj.search ?? null }),
			tracks: JSON.stringify([{ artist: it.artist, track: it.track }]),
		};
	}

	async function loadFailedTracks(seq) {
		try {
			const d = await api.getFailedTracks(sinceISO);
			if (seq !== loadSeq) return;
			failedItems = (d?.items || []).map(failedItemToJob);
		} catch {
			// Older server: the plain failed list, one row per job.
			const d = await api.getDownloadHistory(0, 200, STATUS_QUERY.failed, null, null, sinceISO);
			if (seq !== loadSeq) return;
			failedItems = d.items || d;
		}
	}

	async function loadRuns() {
		const s = sinceISO;
		let r = null;
		try { r = (await api.getDownloadRuns(s))?.items || []; } catch {}
		if (s === sinceISO) apiRuns = r;
	}

	async function ensureRunPool() {
		if (runPool) return;
		const s = sinceISO;
		let pool = [];
		try {
			const d = await api.getDownloadHistory(0, 200, STATUS_QUERY.completed, null, null, s);
			pool = d.items || d;
		} catch {}
		if (s === sinceISO) runPool = pool;
	}

	function toggleRun(run) {
		const open = !openRuns[run.id];
		openRuns = { ...openRuns, [run.id]: open };
		if (open) ensureRunPool();
	}

	/** Quiet state: a run row opens Done with that run expanded. */
	function openRunInDone(run) {
		openRuns = { [run.id]: true };
		ensureRunPool();
		setJobFilter('completed');
	}

	// --- Transfers ------------------------------------------------------------------------
	function getTransferForJob(job) {
		if (!job || job.status !== 'running') return null;
		const direct = $activeTransfers.find(tr => tr.job_id === job.id);
		if (direct) return direct;
		// Legacy transfers that pre-date the job_id link: match tracks[0] peer + file.
		const t = firstTrack(job);
		if (!t.username || !t.filename) return null;
		return $activeTransfers.find(tr =>
			tr.username === t.username &&
			(tr.filename?.endsWith(t.filename) || tr.filename?.split(/[/\\]/).pop() === t.filename)
		) || null;
	}

	// Session median speed of the running transfers: a row under 10 % of it reads "slow".
	let medianSpeed = $derived.by(() => {
		const v = $activeTransfers.filter(tr => tr.state === 'transferring').map(tr => Number(tr.speed) || 0).filter(x => x > 0).sort((a, b) => a - b);
		if (!v.length) return 0;
		const m = Math.floor(v.length / 2);
		return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
	});

	// --- Live tab -------------------------------------------------------------------------
	const STAGE_FILTER_GROUPS = { transferring: ['transferring'], searching: ['searching', 'queue_search'] };
	const STAGE_FILTER_LABEL = { transferring: 'transferring', searching: 'searching and waiting to search' };

	let liveRowCount = $derived(liveJobs.filter(j => j.status === 'pending' || j.status === 'running').length);
	let liveGroupList = $derived.by(() => {
		const all = groups(liveJobs, 'live', {
			limits, nowMs: tick, transferFor: getTransferForJob, pacer, medianSpeed, batches: batches || [],
		});
		const keep = stageFilter ? STAGE_FILTER_GROUPS[stageFilter] : null;
		return keep ? all.filter(g => keep.includes(g.key)) : all;
	});
	let backlogCount = $derived(batches == null ? null : batches.reduce((s, b) => s + (b && !b.cancelled ? n(b.pending) : 0), 0));
	let showQuiet = $derived(!!loadedTabs.live && liveRowCount === 0 && !(backlogCount > 0));

	// Newest added track per batch (from completion frames), for the batch line.
	let lastAdded = $state({});

	/** The batch line's "1 added (Beck — Scarecrow, 07:09)": a completion frame, else the
	 *  summary's last finished row when it came from this import after it started. */
	function lastAddedFor(batch) {
		if (!batch) return null;
		if (lastAdded[batch.id]) return lastAdded[batch.id];
		const lf = summary?.last_finished;
		const src = String(batch.source || '').replace(/^dl:/, '');
		const fin = parseUTC(lf?.finished_at);
		const start = parseUTC(batch.started_at);
		if (!lf || lf.status !== 'completed' || !src || lf.card !== `dl:${src}` || !fin || !start || fin < start) return null;
		return { title: [lf.artist, lf.track].filter(Boolean).join(' — '), at: lf.finished_at };
	}

	// One line per running import: the registry entries, or (older server) the live rows'
	// batch stamps degrading to "8 live from a playlist import".
	let batchLines = $derived.by(() => {
		if (batches) {
			return batches
				.filter(b => b && !b.cancelled && (n(b.live) > 0 || n(b.pending) > 0))
				.map(b => ({ key: b.id, batch: b, live: n(b.live), source: sourceLabel(b.source ? `dl:${String(b.source).replace(/^dl:/, '')}` : null) }));
		}
		const byBatch = new Map();
		for (const j of liveJobs) {
			if (j.status !== 'pending' && j.status !== 'running') continue;
			const b = batchOf(j);
			if (!b) continue;
			const cur = byBatch.get(b.id) || { key: b.id, batch: null, live: 0, source: sourceLabel(j.card) };
			cur.live += 1;
			byBatch.set(b.id, cur);
		}
		return [...byBatch.values()];
	});

	let cancellingIds = $state(new Set());
	let cancellingBatch = $state(null);

	async function cancelBatch(batch) {
		cancellingBatch = batch.id;
		try {
			const r = await api.cancelBatch(batch.id);
			if (r?.cancelled) {
				const rem = r.remaining ?? 0;
				addToast(`Import cancelled: ${plural(rem, 'track')} will not be submitted; live downloads keep going`, 'success');
			} else {
				addToast(`Not cancelled: ${r?.error || r?.detail || 'the server did not confirm'}`, 'warning');
			}
		} catch (e) {
			addToast(`Not cancelled: ${e.message}`, 'error');
		} finally {
			cancellingBatch = null;
			loadStatus();
		}
	}

	// --- Done tab -------------------------------------------------------------------------
	function playedSince(job) {
		const tr = job?.track;
		if (!tr || !(Number(tr.play_count) > 0)) return false;
		const last = parseUTC(tr.last_played_at);
		const fin = parseUTC(job.finished_at);
		return !!last && (!fin || last >= fin);
	}

	let doneFiltered = $derived(
		doneOutcomeFilter === 'all' ? doneJobs
			: doneOutcomeFilter === 'played' ? doneJobs.filter(playedSince)
				: doneJobs.filter(j => doneOutcome(j)?.kind === doneOutcomeFilter)
	);
	let doneGroupList = $derived(groups(doneFiltered.slice(0, doneLimit), 'done'));
	let doneTotal = $derived.by(() => {
		const o = summary?.outcomes || {};
		if (doneOutcomeFilter === 'new') return n(o.new);
		if (doneOutcomeFilter === 'replaced') return n(o.replaced);
		if (doneOutcomeFilter === 'already_had') return n(o.already_had);
		if (doneOutcomeFilter === 'played') return n(summary?.played_since);
		return jobStatusCounts.completed;
	});
	let doneShown = $derived(Math.min(doneFiltered.length, doneLimit));
	let donePills = $derived.by(() => {
		const o = summary?.outcomes || {};
		return [
			{ value: 'all', label: 'All', count: jobStatusCounts.completed },
			{ value: 'new', label: 'New', count: n(o.new) },
			{ value: 'replaced', label: 'Replaced', count: n(o.replaced) },
			{ value: 'already_had', label: 'Already had', count: n(o.already_had) },
			{ value: 'played', label: 'Played since', count: n(summary?.played_since) },
		].map(p => ({ ...p, color: 'downloads' }));
	});

	let doneTotals = $derived.by(() => {
		const o = summary?.outcomes;
		if (!o) return null;
		const added = n(o.new) + n(o.replaced);
		const fin = added + n(o.already_had);
		if (!fin) return null;
		const extra = [];
		if (summary.bytes_added) extra.push(formatSize(summary.bytes_added));
		if (summary.pct_lossless != null && added) extra.push(`${summary.pct_lossless} % FLAC`);
		const rest = [`${added.toLocaleString()} added${extra.length ? ` (${extra.join(', ')})` : ''}`];
		if (n(o.already_had)) rest.push(`${n(o.already_had).toLocaleString()} already had`);
		return { head: `${fin.toLocaleString()} finished ${scopeInfo.phrase}`, rest: rest.join(' · ') };
	});

	const RUN_KIND_LABEL = { playlist: 'Playlist import', bulk: 'Download all', recommendation: 'Recommendations' };
	// A run that is a registered batch still submitting gets its true size and waiting count.
	let runList = $derived(runs(runPool ?? doneJobs, apiRuns).map((r) => {
		const b = batches?.find(x => x && x.id === r.id);
		const kindLabel = RUN_KIND_LABEL[r.kind];
		const label = kindLabel && r.label && r.label !== kindLabel ? `${kindLabel} · ${r.label}` : r.label;
		if (!b) return { ...r, label };
		return { ...r, label, counts: { ...r.counts, total: Math.max(n(b.total), n(r.counts?.total)), pending: n(b.pending) } };
	}));

	function showMoreDone(step) {
		const total = doneTotal;
		doneLimit = step === 'all' ? Math.min(Math.max(total, 25), DONE_PAGE) : Math.min(doneLimit + step, DONE_PAGE);
		loadJobs(false);
	}

	let clearCompletedConfirm = $state(false);
	let clearingCompleted = $state(false);
	async function handleClearCompleted() {
		clearingCompleted = true;
		try {
			const r = await api.clearDownloadHistory('completed', null, sinceISO);
			const d = r?.deleted ?? 0;
			addToast(d ? `Deleted ${d} completed download record${d === 1 ? '' : 's'} on the server` : 'Nothing to clear', d ? 'success' : 'info');
			clearCompletedConfirm = false;
			runPool = null;
			await loadJobs();
		} catch (e) {
			addToast(`Clear failed: ${e.message}`, 'error');
		} finally {
			clearingCompleted = false;
		}
	}

	// --- Failed tab -----------------------------------------------------------------------
	const BUCKET_OF_CLASS = { not_found: 'not_found', no_better: 'no_better', rejected: 'rejected', peer: 'peer', cancelled: 'infra', infra: 'infra', orphan: 'infra' };
	const FAILED_PILLS = [
		{ value: 'not_found', label: 'Not found', always: true },
		{ value: 'peer', label: 'Peer problems', always: true },
		{ value: 'rejected', label: 'Not imported' },
		{ value: 'no_better', label: 'Nothing better' },
		{ value: 'infra', label: "Not the track's fault", always: true },
	];

	/** Server row count of one bucket (GET /jobs/failures): what retry-failed?reason= re-queues. */
	function bucketCount(reason) {
		return n(failureGroups.find(g => g.reason === reason)?.count);
	}

	// An item stands for `count` failed rows of one track and its newest row decides the
	// class. Pills and groups both count rows per item bucket, so pills = groups = footer
	// even when one track failed in two classes within the scope.
	const itemBucket = (j) => BUCKET_OF_CLASS[failureClass(j) || 'orphan'] || 'infra';
	const itemRows = (j) => n(j.count) || 1;
	let failedBucketRows = $derived.by(() => {
		const t = {};
		for (const j of failedItems) t[itemBucket(j)] = (t[itemBucket(j)] || 0) + itemRows(j);
		return t;
	});
	let failedRowsListed = $derived(failedItems.reduce((s, j) => s + itemRows(j), 0));

	let failedPills = $derived([
		{ value: 'all', label: 'All', count: jobStatusCounts.failed, color: 'downloads' },
		...FAILED_PILLS.filter(p => p.always || n(failedBucketRows[p.value]) > 0)
			.map(p => ({ value: p.value, label: p.label, count: n(failedBucketRows[p.value]), color: 'downloads' })),
	]);

	let failedFiltered = $derived(failedClass ? failedItems.filter(j => itemBucket(j) === failedClass) : failedItems);
	let failedGroupList = $derived(
		groups(failedFiltered, 'failed', { incidentNote }).map(g => ({ ...g, count: g.rows.reduce((s, r) => s + itemRows(r), 0) }))
	);
	let failedNext = $derived.by(() => {
		const x = summary?.next;
		if (x) return { retry: n(x.retry), retired: n(x.retired), none: n(x.none) };
		const t = { retry: 0, retired: 0, none: 0 };
		for (const j of failedItems) {
			const k = j.next?.kind;
			if (k === 'retry') t.retry += 1; else if (k === 'retired') t.retired += 1; else t.none += 1;
		}
		return t;
	});
	let peerCount = $derived(bucketCount('peer'));

	// Jobs whose track was blacklisted from this page ("Stop trying"): NEXT reads "blacklisted".
	let stoppedIds = $state(new Set());
	let retiredRows = $derived(failedItems.filter(j => j.next?.kind === 'retired' && !stoppedIds.has(j.id)));

	let retryConfirm = $state(null); // null | { reason, label, count }
	let retrying = $state(false);
	async function retryFailed() {
		if (!retryConfirm) return;
		retrying = true;
		try {
			const r = await api.retryFailedDownloads(retryConfirm.reason, sinceISO);
			if (r?.error) throw new Error(r.error);
			const t = r?.tracks ?? 0;
			addToast(t ? `Re-queued ${t} download${t === 1 ? '' : 's'}` : 'Nothing to retry in this period', t ? 'success' : 'info');
			retryConfirm = null;
			await loadJobs();
		} catch (e) {
			addToast(`Retry failed: ${e.message}`, 'error');
		} finally {
			retrying = false;
		}
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

	// Stop retrying every retired track in the scope (one blacklist row each).
	let stopRetiredConfirm = $state(false);
	let stoppingRetired = $state(false);
	async function stopRetired() {
		stoppingRetired = true;
		const rows = [...retiredRows];
		let ok = 0;
		const done = new Set(stoppedIds);
		for (const j of rows) {
			try {
				const r = await api.stopTrying(j.id);
				if (!r?.error) { ok += 1; done.add(j.id); }
			} catch {}
		}
		stoppedIds = done;
		addToast(ok === rows.length ? `Blacklisted ${plural(ok, 'retired track')}` : `Blacklisted ${ok} of ${plural(rows.length, 'retired track')}`, ok ? 'success' : 'warning');
		stoppingRetired = false;
		stopRetiredConfirm = false;
		loadBlacklist();
		loadJobs();
	}

	// --- Row actions (honest: toast only what the server confirmed) -----------------------
	function searchByHand(q) {
		if (!q) return;
		searchQuery = q;
		searchSoulseek();
		window.scrollTo({ top: 0, behavior: 'smooth' });
	}

	function searchByHandFor(job) {
		const t = firstTrack(job);
		searchByHand(t.artist && t.track ? `${t.artist} - ${t.track}` : jobTitle(job, '').replace(/\s*—\s*/, ' - '));
	}

	/** Drop a row locally (the server already removed or replaced it). */
	function dropJobLocally(jobId) {
		liveJobs = liveJobs.filter(j => j.id !== jobId);
		doneJobs = doneJobs.filter(j => j.id !== jobId);
		failedItems = failedItems.filter(j => j.id !== jobId);
		if (runPool) runPool = runPool.filter(j => j.id !== jobId);
		if (selectedJobId === jobId) selectedJobId = null;
	}

	async function retryJob(jobId) {
		try {
			const r = await api.retryJob(jobId);
			if (r?.error) {
				addToast(`Not retried: ${r.error}`, 'warning');
				return;
			}
			addToast(`Retry started${r?.total > 1 ? ` (${r.total} tracks)` : ''} — it shows up under Live`, 'success');
			dropJobLocally(r?.replaced_job_id || jobId);
			await loadJobs();
		} catch (e) { addToast(`Retry failed: ${e.message}`, 'error'); }
	}

	async function cancelJob(jobId) {
		cancellingIds = new Set([...cancellingIds, jobId]);
		try {
			const r = await api.cancelJob(jobId);
			if (r?.error) {
				addToast(r.error === 'Job not cancellable' ? 'Not cancelled: it already finished' : `Not cancelled: ${r.error}`, 'warning');
				cancellingIds = new Set([...cancellingIds].filter(x => x !== jobId));
				await loadJobs();
				return;
			}
			addToast('Download cancelled', 'success');
		} catch (e) {
			cancellingIds = new Set([...cancellingIds].filter(x => x !== jobId));
			addToast(`Cancel failed: ${e.message}`, 'error');
		}
	}

	// Remove = delete the row on the server, behind a confirm.
	let removeConfirm = $state(null); // null | { id, title, status }
	let removing = $state(false);
	function askRemove(job) {
		removeConfirm = { id: job.id, title: jobTitle(job), status: job.status, count: n(job.count) || 1 };
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
				if (wasStatus === 'failed') loadJobs(false);
			}
			removeConfirm = null;
		} catch (e) {
			addToast(`Remove failed: ${e.message}`, 'error');
		} finally {
			removing = false;
		}
	}

	function askStop(job) {
		stopConfirm = { id: job.id, title: jobTitle(job) };
	}

	// --- Drawer (R2-E1) -------------------------------------------------------------------
	let selectedJobId = $state(null);
	let detailVersion = $state(0);
	let detailBumpAt = 0;
	let detailBumpTimer;

	function openRow(id) {
		selectedJobId = selectedJobId === id ? null : id;
	}

	/** Refetch the drawer's detail on a job_update for it, at most every 2 s. */
	function bumpDetailSoon() {
		const wait = Math.max(0, 2000 - (Date.now() - detailBumpAt));
		clearTimeout(detailBumpTimer);
		detailBumpTimer = setTimeout(() => { detailBumpAt = Date.now(); detailVersion += 1; }, wait);
	}

	let selectedRow = $derived(
		selectedJobId
			? liveJobs.find(j => j.id === selectedJobId) || failedItems.find(j => j.id === selectedJobId)
				|| doneJobs.find(j => j.id === selectedJobId) || runPool?.find(j => j.id === selectedJobId) || null
			: null
	);
	// Only the Live rows fit beside the 25rem column (compact); the Failed and Done grids
	// would crush their titles, so there the drawer opens as a bottom sheet at every width.
	let drawerSheet = $derived(jobStatusFilter !== 'live');
	let drawerColumn = $derived(!!selectedJobId && !drawerSheet);

	const drawerActions = {
		cancel: (job) => cancelJob(job.id),
		retry: async (job) => { await retryJob(job.id); selectedJobId = null; },
		stopTrying: isDlAdmin ? (job) => askStop(job) : undefined,
		remove: isDlAdmin ? (job) => askRemove(job) : undefined,
		// Same "Artist - Track" query as the row button, so the search's blacklist check applies.
		searchByHand: (q, job) => { selectedJobId = null; if (job) searchByHandFor(job); else searchByHand(q); },
	};

	// Escape on a confirm opened from the drawer closes only the confirm: the drawer's
	// window handler runs first and sees the modal still open.
	function closeDrawer() {
		if (removeConfirm || stopConfirm || retryConfirm || clearCompletedConfirm || stopRetiredConfirm || backoffOpen) return;
		selectedJobId = null;
	}

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

	function mergeWs(row, wsJob) {
		const merged = {
			...row, status: wsJob.status, progress: wsJob.progress, total: wsJob.total,
			description: wsJob.description || row.description, result: wsJob.result || row.result,
			finished_at: wsJob.finished_at || row.finished_at,
		};
		for (const k of WS_MERGE_KEYS) {
			if (wsJob[k] !== undefined && wsJob[k] !== null) merged[k] = wsJob[k];
		}
		return merged;
	}

	function onDownloadUpdate(wsJob) {
		// Inline result statuses of the search results
		for (const [key, rs] of Object.entries(resultStatuses)) {
			if (rs.jobId === wsJob.id) {
				if (wsJob.status === 'completed') resultStatuses[key] = { status: 'completed', jobId: wsJob.id, trackId: wsJob.track_id || null };
				else if (wsJob.status === 'failed') resultStatuses[key] = { status: 'failed', jobId: wsJob.id };
				else if (wsJob.status === 'running' && ['connecting', 'queued_at_peer', 'transferring'].includes(wsJob.stage)) {
					resultStatuses[key] = { status: 'downloading', jobId: wsJob.id };
				}
			}
		}
		const live = wsJob.status === 'running' || wsJob.status === 'pending';
		const idx = liveJobs.findIndex(j => j.id === wsJob.id);
		const prev = idx >= 0 ? liveJobs[idx] : null;
		if (idx >= 0) {
			liveJobs[idx] = mergeWs(liveJobs[idx], wsJob);
		} else if (live && jobStatusFilter === 'live') {
			// Optimistic insert: a job the list has not loaded yet shows at once.
			liveJobs = [mergeWs({ id: wsJob.id, type: wsJob.type, started_at: nowNaiveISO() }, wsJob), ...liveJobs];
		}
		if (cancellingIds.has(wsJob.id)) cancellingIds = new Set([...cancellingIds].filter(x => x !== wsJob.id));
		if (wsJob.status === 'completed') {
			maybeCompletionToast(wsJob, prev);
			const b = batchOf(prev || wsJob);
			if (b) lastAdded = { ...lastAdded, [b.id]: { title: jobTitle(prev || wsJob, ''), at: wsJob.finished_at || nowNaiveISO() } };
		}
		if (wsJob.id === selectedJobId) bumpDetailSoon();
		// A finished job lifts the summary's 10 s throttle; the debounced counts refresh
		// reloads it, so a burst of terminal frames costs one summary request, not one each.
		if (!live) summaryLoadedAt = 0;
		refreshCountsSoon();
		// Something went live while the status poll sleeps 30 s: refresh it now (at most every 3 s).
		if (live && !((stages?.live ?? 0) > 0) && Date.now() - statusKickAt > 3000) {
			statusKickAt = Date.now();
			loadStatus().then(scheduleStatus);
		}
		// Debounced reload — longer when many jobs are active, to spare the API.
		clearTimeout(loadJobsTimer);
		const activeCount = liveJobs.filter(j => j.status === 'running' || j.status === 'pending').length;
		loadJobsTimer = setTimeout(() => loadJobs(false), activeCount > 20 ? 10000 : activeCount > 5 ? 5000 : 2000);
	}

	// Blacklist editing, bulk clear/retry and row deletion are admin-only on the server too.
	let isDlAdmin = $derived(can($currentUser, 'downloads.admin'));

	onMount(() => {
		if (isDlAdmin) loadBlacklist();
		// Deep links, e.g. /downloads?status=failed&reason=not_found (dashboard) or ?status=active
		const qs = new URLSearchParams(window.location.search);
		const wantStatus = qs.get('status') === 'active' ? 'live' : qs.get('status');
		if (wantStatus && STATUS_QUERY[wantStatus]) {
			jobStatusFilter = wantStatus;
			if (wantStatus === 'failed') failedClass = BUCKET_OF_CLASS[qs.get('reason')] || null;
		}
		loadJobs();
		loadStatus().then(scheduleStatus);
		loadIncidents();
		loadQuiet();
		api.getServices().then(d => { sharing = !!d.slsk_share_library; }).catch(() => {});
		unsubJobUpdate = onJobUpdate((wsJob) => {
			if (wsJob.type === 'download' || wsJob.type === 'bulk_download') onDownloadUpdate(wsJob);
		});
		lastFallbackAt = Date.now();
		tickTimer = setInterval(() => {
			tick = Date.now();
			if (tick - incidentsAt >= 60000) loadIncidents();
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
		clearTimeout(detailBumpTimer);
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
			<!-- The Soulseek connection lives in the strip's first tile; this chip is the WebSocket. -->
			{#if $wsState.connected}
				<Badge variant="info">
					<span class="inline-block w-1.5 h-1.5 rounded-full bg-current animate-pulse mr-1.5"></span>
					Live{wsAgeS != null ? ` · updated ${wsAgeS} s ago` : ''}
				</Badge>
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
					placeholder-[var(--text-disabled)] focus:outline-none focus:ring-1 focus:border-[color:color-mix(in_srgb,var(--color-downloads)_50%,transparent)] focus:ring-[color:color-mix(in_srgb,var(--color-downloads)_20%,transparent)]" />
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

	<!-- Incident banner (only while an un-dismissed restart/outage wave exists) + health strip -->
	<IncidentBanner {incidents} onRetry={isDlAdmin ? retryIncident : null} onDismiss={isDlAdmin ? dismissIncident : null} busy={incidentBusy} now={tick} class="mb-4" />
	<HealthStrip {status} {summary} backlog={backlogCount} {nextRun}
		scopeLabel={scope === 'today' ? 'today' : scopeInfo.label} activeFilter={activeTile} onFilter={onTile} now={tick} class="mb-4" />

	<!-- Downloads card: always mounted; pills, scope and empty states render at 0. The drawer
	     is a sticky column beside it at >= 1280 px and a bottom sheet below. -->
	<div class="grid gap-4 mb-6 items-start {drawerColumn ? 'xl:grid-cols-[minmax(0,1fr)_25rem]' : ''}">
		<Card padding="p-4" class="min-w-0">
			<div class="flex items-center justify-between flex-wrap gap-2 mb-3">
				<FilterPills
					options={[
						{ value: 'live', label: 'Live', color: 'downloads', count: stages?.live ?? jobStatusCounts.active ?? 0 },
						{ value: 'completed', label: 'Done', color: 'downloads', count: jobStatusCounts.completed || 0 },
						{ value: 'failed', label: 'Failed', color: 'downloads', count: jobStatusCounts.failed || 0 },
					]}
					value={jobStatusFilter}
					onchange={setJobFilter}
				/>
				<Segmented options={SCOPES} value={scope} onchange={setScope} label="Period" />
			</div>

			{#if !loadedTabs[jobStatusFilter]}
				<Skeleton variant="list-item" tone="high" count={5} />
			{:else if jobStatusFilter === 'completed'}
				<!-- DONE: outcome pills + totals, run rows, then the feed -->
				<div class="flex items-center justify-between flex-wrap gap-x-4 gap-y-2 mb-3">
					<FilterPills variant="outline" options={donePills} value={doneOutcomeFilter} onchange={(v) => (doneOutcomeFilter = v)} />
					{#if doneTotals}
						<p class="text-xs text-[var(--text-muted)]"><b class="font-semibold text-[var(--text-primary)]">{doneTotals.head}</b> · {doneTotals.rest}</p>
					{/if}
				</div>

				{#if runList.length}
					<div class="space-y-1.5 mb-2">
						{#each runList as run (run.id)}
							<RunRow {run} open={!!openRuns[run.id]} ontoggle={toggleRun} now={tick}>
								{@const rows = run.rows.filter(r => r.status === 'completed')}
								{#if rows.length}
									<div class="divide-y divide-[var(--border-subtle)]">
										{#each rows as job (job.id)}
											<DoneRow {job} now={tick} selected={selectedJobId === job.id} onRemove={isDlAdmin ? askRemove : null} onOpen={openRow} />
										{/each}
									</div>
								{:else}
									<p class="px-3 py-2 text-xs text-[var(--text-muted)]">{runPool ? 'No finished rows of this run in the period.' : 'Loading the rows…'}</p>
								{/if}
							</RunRow>
						{/each}
					</div>
				{/if}

				<GroupedList groups={doneGroupList} columns={DONE_COLUMNS} grid={DONE_GRID}>
					{#snippet row(job)}
						<DoneRow {job} now={tick} selected={selectedJobId === job.id} onRemove={isDlAdmin ? askRemove : null} onOpen={openRow} />
					{/snippet}
					{#snippet empty()}
						<EmptyState compact title={doneOutcomeFilter === 'all' ? 'No downloads finished in this period' : 'No rows match this filter'}>
							{#snippet icon()}<Download class="w-6 h-6" />{/snippet}
						</EmptyState>
					{/snippet}
					{#snippet footer()}
						<span>Showing {doneShown.toLocaleString()} of {doneTotal.toLocaleString()} · newest first</span>
						<span class="flex items-center gap-3 flex-wrap">
							{#if doneTotal > doneShown && doneLimit < DONE_PAGE}
								<button type="button" class="text-sky-400 hover:text-sky-300 font-medium transition-colors" onclick={() => showMoreDone(25)}>Show 25 more</button>
								<button type="button" class="text-sky-400 hover:text-sky-300 font-medium transition-colors" onclick={() => showMoreDone('all')}>Show all {doneTotal.toLocaleString()}</button>
							{/if}
							{#if isDlAdmin}
							<button type="button" class="inline-flex items-center gap-1 hover:text-rose-400 transition-colors disabled:opacity-50" disabled={!jobStatusCounts.completed}
								onclick={() => (clearCompletedConfirm = true)}>
								<Eraser class="w-3.5 h-3.5" />Clear completed history on the server
							</button>
							{/if}
						</span>
					{/snippet}
				</GroupedList>
				{#if doneLimit >= DONE_PAGE && jobStatusCounts.completed > DONE_PAGE}
					<Pagination total={jobStatusCounts.completed} offset={doneOffset} limit={DONE_PAGE} limitOptions={[]}
						onchange={(o) => { doneOffset = o; loadJobs(false); }} />
				{/if}

			{:else if jobStatusFilter === 'failed'}
				<!-- FAILED: class pills + sized bulk actions, summary, groups by class -->
				<div class="flex items-center justify-between flex-wrap gap-x-4 gap-y-2 mb-2">
					<FilterPills variant="outline" options={failedPills} value={failedClass ?? 'all'} onchange={(v) => (failedClass = v === 'all' ? null : v)} />
					<div class="flex items-center gap-2 flex-wrap">
						{#if isDlAdmin && peerCount > 0}
							<!-- Peer problems only: never resurrects cancelled or infra rows -->
							<Button variant="secondary" size="sm" onclick={() => (retryConfirm = { reason: 'peer', label: 'Peer problems', count: peerCount })}>
								<RotateCcw class="w-3.5 h-3.5" />Retry {plural(peerCount, 'peer problem')}
							</Button>
						{/if}
						{#if isDlAdmin && retiredRows.length}
							<Button variant="ghost" size="sm" class="!text-rose-400" onclick={() => (stopRetiredConfirm = true)}>
								<Ban class="w-3.5 h-3.5" />Stop retrying {plural(retiredRows.length, 'retired track')}
							</Button>
						{/if}
					</div>
				</div>
				<p class="text-xs text-[var(--text-muted)] mb-1">
					<b class="font-semibold text-[var(--text-primary)]">{jobStatusCounts.failed.toLocaleString()} failed {scopeInfo.phrase}</b>
					· {failedNext.retry.toLocaleString()} will retry on their own · {failedNext.retired.toLocaleString()} retired · {failedNext.none.toLocaleString()} nothing scheduled
				</p>

				<GroupedList groups={failedGroupList} columns={FAILED_COLUMNS} grid={FAILED_GRID}>
					{#snippet row(job)}
						<FailedRow {job} now={tick} selected={selectedJobId === job.id} stopped={stoppedIds.has(job.id)}
							onSearch={searchByHandFor} onRetry={(j) => retryJob(j.id)} onStopTrying={isDlAdmin ? askStop : null} onRemove={isDlAdmin ? askRemove : null} onOpen={openRow} />
					{/snippet}
					{#snippet empty()}
						<EmptyState compact title={failedClass ? 'Nothing of this kind failed in this period' : 'Nothing failed in this period'}>
							{#snippet icon()}<CircleCheck class="w-6 h-6" />{/snippet}
						</EmptyState>
					{/snippet}
					{#snippet footer()}
						<span>
							{jobStatusCounts.failed.toLocaleString()} failed {scopeInfo.phrase}{#if failedGroupList.length > 1}{` · ${failedGroupList.map(g => g.count).join(' + ')}`}{/if}
							{#if failedRowsListed < jobStatusCounts.failed}{` (the newest ${failedRowsListed.toLocaleString()} listed)`}{/if}
							· Remove deletes the row on the server, Stop trying adds to the blacklist
						</span>
						{#if scope === 'today' && failedWeekCount != null}
							<button type="button" class="text-sky-400 hover:text-sky-300 font-medium transition-colors" onclick={() => setScope('week')}>
								Failed in 7 days ({failedWeekCount.toLocaleString()})
							</button>
						{/if}
					{/snippet}
				</GroupedList>

			{:else}
				<!-- LIVE: batch lines, then one list grouped by stage -->
				{#each batchLines as bl (bl.key)}
					<BatchLine batch={bl.batch} liveCount={bl.live} sourceLabel={bl.source} lastAdded={lastAddedFor(bl.batch)}
						cancelling={!!bl.batch && cancellingBatch === bl.batch.id} onCancel={bl.batch ? cancelBatch : null} class="mb-2" />
				{/each}
				{#if stageFilter}
					<p class="text-xs text-[var(--text-muted)] px-3 py-1">
						Showing only {STAGE_FILTER_LABEL[stageFilter]} ·
						<button type="button" class="text-sky-400 hover:text-sky-300 font-medium" onclick={() => (stageFilter = null)}>Show all live</button>
					</p>
				{/if}

				{#if showQuiet}
					{@const dueToday = attemptsSummary?.due_before || 0}
					{@const backoffTotal = attemptsSummary?.total || 0}
					<div class="flex items-start gap-4 flex-wrap px-3 py-4">
						<div class="w-11 h-11 rounded-2xl bg-[var(--surface-container-high)] flex items-center justify-center flex-shrink-0 text-[var(--text-disabled)]">
							<Pause class="w-5 h-5" />
						</div>
						<div class="flex-1 min-w-[14rem]">
							<h3 class="text-sm font-semibold text-[var(--text-primary)] mb-1">Nothing is downloading</h3>
							{#if quietText}<p class="text-xs text-[var(--text-muted)] leading-relaxed">{quietText}</p>{/if}
						</div>
						{#if backoffTotal || dueToday}
							<div class="flex items-center gap-2 flex-wrap self-center">
								{#if backoffTotal}
									<Button variant="secondary" size="sm" onclick={openBackoffList}>
										<ListOrdered class="w-3.5 h-3.5" />Backoff list ({backoffTotal.toLocaleString()})
									</Button>
								{/if}
								{#if dueToday && isDlAdmin}
									<Button variant="secondary" size="sm" loading={runningRetries} onclick={runRetriesNow}>
										<RotateCcw class="w-3.5 h-3.5" />Run the {dueToday.toLocaleString()} {dueToday === 1 ? 'retry' : 'retries'} now
									</Button>
								{/if}
							</div>
						{/if}
					</div>
					{#if apiRuns?.length}
						<div class="flex items-center gap-2 px-3 pt-1 pb-1.5 text-[11px] font-semibold text-[var(--text-secondary)]">
							Runs {scopeInfo.phrase}<span class="font-mono font-medium text-[var(--text-muted)]">{apiRuns.length}</span>
						</div>
						<div class="space-y-1.5">
							{#each apiRuns as run (run.id)}
								<RunRow {run} now={tick} ontoggle={openRunInDone} />
							{/each}
						</div>
					{/if}
					{#if quietTotals}
						<p class="px-3 pt-3 text-xs text-[var(--text-muted)]">
							{quietTotals} · open
							<button type="button" class="text-sky-400 hover:text-sky-300" onclick={() => setJobFilter('completed')}>Done</button> or
							<button type="button" class="text-sky-400 hover:text-sky-300" onclick={() => setJobFilter('failed')}>Failed</button> for the rows.
						</p>
					{/if}
				{:else}
					<GroupedList groups={liveGroupList} columns={LIVE_COLUMNS} grid={LIVE_GRID} groupLimit={GROUP_LIMIT}>
						{#snippet row(job)}
							<LiveRow {job} transfer={job.backlog ? null : getTransferForJob(job)} {limits} {pacer} {medianSpeed} now={tick}
								selected={selectedJobId === job.id} cancelling={cancellingIds.has(job.id)} compact={drawerColumn}
								onCancel={(j) => cancelJob(j.id)} onOpen={openRow} />
						{/snippet}
						{#snippet empty()}
							<p class="px-3 py-4 text-xs text-[var(--text-muted)]">Nothing live in this stage right now.</p>
						{/snippet}
						{#snippet footer()}
							<span>{liveRowCount.toLocaleString()} live · sorted by stage · TIME is time in the current stage, hover for age since created · amber past 75 % of a limit · click a row for its full story</span>
							<span class="flex items-center gap-4">
								<a href="/stats" class="text-sky-400 hover:text-sky-300">Soulseek stats</a>
								<a href="/settings" class="text-sky-400 hover:text-sky-300">Settings</a>
							</span>
						{/snippet}
					</GroupedList>
					{#if jobStatusCounts.active > LIVE_LIMIT}
						<Pagination total={jobStatusCounts.active} offset={liveOffset} limit={LIVE_LIMIT} limitOptions={[]}
							onchange={(o) => { liveOffset = o; loadJobs(false); }} />
					{/if}
				{/if}
			{/if}
		</Card>

		{#if selectedJobId}
			<JobDrawer jobId={selectedJobId} row={selectedRow} {limits} now={tick} version={detailVersion}
				transfer={getTransferForJob(selectedRow)} sheet={drawerSheet}
				onclose={closeDrawer} actions={drawerActions} />
		{/if}
	</div>

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

	<!-- Blacklist (admins only) -->
	{#if isDlAdmin}
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
							placeholder-[var(--text-disabled)] focus:outline-none focus:ring-1 focus:border-[color:color-mix(in_srgb,var(--color-accent)_50%,transparent)] focus:ring-[color:color-mix(in_srgb,var(--color-accent)_20%,transparent)]" />
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
						placeholder-[var(--text-disabled)] focus:outline-none focus:ring-1 focus:border-[color:color-mix(in_srgb,var(--color-accent)_50%,transparent)] focus:ring-[color:color-mix(in_srgb,var(--color-accent)_20%,transparent)]" />
				<input type="text" placeholder="Track (blank = entire artist)" bind:value={blTrack}
					class="flex-1 bg-[var(--surface-lowest)] ghost-border rounded-md px-3 py-1.5 text-sm text-[var(--text-body)]
						placeholder-[var(--text-disabled)] focus:outline-none focus:ring-1 focus:border-[color:color-mix(in_srgb,var(--color-accent)_50%,transparent)] focus:ring-[color:color-mix(in_srgb,var(--color-accent)_20%,transparent)]" />
				<input type="text" placeholder="Reason" bind:value={blReason}
					class="w-48 bg-[var(--surface-lowest)] ghost-border rounded-md px-3 py-1.5 text-sm text-[var(--text-body)]
						placeholder-[var(--text-disabled)] focus:outline-none focus:ring-1 focus:border-[color:color-mix(in_srgb,var(--color-accent)_50%,transparent)] focus:ring-[color:color-mix(in_srgb,var(--color-accent)_20%,transparent)]" />
				<Button variant="danger" size="sm" disabled={!blArtist.trim()} onclick={addBlacklistEntry}>
					<ShieldBan class="w-3 h-3" />
					Block
				</Button>
			</div>

			{#if blacklist.length > 3}
				<div class="mb-2">
					<input type="text" placeholder="Filter blacklist..." bind:value={blFilter}
						class="w-full sm:w-64 bg-[var(--surface-lowest)] ghost-border rounded-md px-3 py-1.5 text-sm text-[var(--text-body)]
							placeholder-[var(--text-disabled)] focus:outline-none focus:ring-1 focus:border-[color:color-mix(in_srgb,var(--color-accent)_50%,transparent)] focus:ring-[color:color-mix(in_srgb,var(--color-accent)_20%,transparent)]" />
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
	{/if}
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

{#if stopRetiredConfirm}
	<Modal title="Stop retrying retired tracks" onclose={() => (stopRetiredConfirm = false)} maxWidth="max-w-md">
		{#snippet children()}
			<p class="text-sm text-[var(--text-primary)]">
				Blacklist the <span class="font-bold">{retiredRows.length.toLocaleString()}</span> retired track{retiredRows.length === 1 ? '' : 's'} that failed {scopeInfo.phrase}?
			</p>
			<p class="text-xs text-[var(--text-muted)] mt-2">
				Each gets a blacklist row and loses its retry schedule, so scheduler, bulk and playlist runs stop picking it again. You can undo any of them from the Download Blacklist below.
			</p>
		{/snippet}
		{#snippet footer()}
			<Button variant="secondary" size="sm" onclick={() => (stopRetiredConfirm = false)}>Cancel</Button>
			<Button variant="danger" size="sm" disabled={stoppingRetired} onclick={stopRetired}>
				<Ban class="w-3.5 h-3.5 mr-1" /> {stoppingRetired ? 'Blacklisting…' : 'Stop retrying'}
			</Button>
		{/snippet}
	</Modal>
{/if}

{#if removeConfirm}
	<Modal title="Remove download" onclose={() => removeConfirm = null} maxWidth="max-w-md">
		{#snippet children()}
			<p class="text-sm text-[var(--text-primary)]">Remove <span class="font-semibold">{removeConfirm.title}</span> from the download history?</p>
			<p class="text-xs text-[var(--text-muted)] mt-2">
				{#if removeConfirm.count > 1}
					This deletes its newest failed row on the server; the other {plural(removeConfirm.count - 1, 'failed row')} of this track in the period stay listed.
				{:else}
					This deletes the row on the server.
				{/if}
				Files in your library and the track's retry schedule are not touched.
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
