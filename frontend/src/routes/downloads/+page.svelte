<script>
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/stores';
	import { api } from '$lib/api.js';
	import { addToast, activeTransfers, activeUploads } from '$lib/stores.js';
	import { onJobUpdate } from '$lib/websocket.js';
	import { formatSize, formatSpeed, formatETA, formatDateTime } from '$lib/utils.js';
	import { Download, Search, Zap, ShieldBan, Trash2, X, ChevronLeft, ChevronRight, ChevronDown, ChevronUp, RotateCcw, Eraser, CircleCheck, Wifi, Clock, Upload, Radio, Activity } from 'lucide-svelte';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Button from '../../components/ui/Button.svelte';
	import Badge from '../../components/ui/Badge.svelte';
	import FilterPills from '../../components/ui/FilterPills.svelte';
	import EmptyState from '../../components/ui/EmptyState.svelte';
	import DataTable from '../../components/ui/DataTable.svelte';
	import Modal from '../../components/ui/Modal.svelte';

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
	let jobsLoading = $state(false);
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

	let hiddenJobIds = $state(new Set(
		typeof localStorage !== 'undefined' ? JSON.parse(localStorage.getItem('hiddenDownloadJobs') || '[]') : []
	));

	const STATUS_PRIORITY = { pending: 0, running: 1, completed: 2, failed: 3 };

	let visibleJobs = $derived(
		jobs.filter(j => {
			if (hiddenJobIds.has(j.id)) return false;
			// Status (and failure reason) are filtered by the server now; the old client-side
			// filter only ever saw the 20 jobs on the current page.
			return true;
		}).sort((a, b) => {
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
		if (!job.tracks) return null;
		try { return JSON.parse(job.tracks); } catch { return null; }
	}

	function fileExtension(filename) {
		if (!filename) return '';
		const ext = filename.split('.').pop()?.toLowerCase() || '';
		return ext;
	}

	const SOURCE_LABELS = {
		'dl:upgrade': 'Upgrade',
		'dl:discovery': 'Discovery',
		'dl:similar': 'Similar',
		'dl:remix': 'Remix',
		'dl:recommendation': 'For You',
		'dl:playlist': 'Playlist',
		'dl:manual': 'Manual',
	};
	function sourceLabel(job) {
		if (!job?.card) return '';
		return SOURCE_LABELS[job.card] || '';
	}

	function formatJobTitle(raw) {
		if (!raw) return 'Unknown Track';
		let s = raw;
		s = s.replace(/^Queued for slot:\s*/i, '');
		s = s.replace(/^Queued:\s*/i, '');
		s = s.replace(/\s*\(attempt\s+\d+.*?\)/i, '');
		s = s.replace(/\s*—\s*\d+\s+sources/i, '');
		return s.trim();
	}

	function getSearchQueryForJob(job) {
		if (!job) return '';
		const t = parseJobTracks(job)?.[0] || (job.id ? jobDetails[job.id]?.[0] : null);
		if (t?.artist && t?.track) return `${t.artist} - ${t.track}`;
		if (job.description) {
			return formatJobTitle(job.description).replace(/\s*—\s*/, ' - ');
		}
		return '';
	}

	function friendlyFailure(job, jobResult) {
		const raw = jobResult?.last_error || jobResult?.message || jobResult?.error || (job?.id ? jobDetails[job.id]?.[0]?.error : '') || '';
		const rawLower = raw.toLowerCase();

		if (!raw) {
			return { title: 'Download failed', detail: 'Unknown error occurred', category: 'unknown' };
		}
		if (rawLower.includes('cancel')) {
			return { title: 'Cancelled', detail: 'Cancelled by user', category: 'cancelled' };
		}
		if (rawLower.includes('no candidates') || rawLower.includes('no results') || rawLower.includes('not found') || rawLower.includes('no matches')) {
			return { title: 'No peers online', detail: 'Track is not currently shared by any online Soulseek peers', category: 'not_found' };
		}
		if (rawLower.includes('already in library') || rawLower.includes('no better') || rawLower.includes('equal or better')) {
			return { title: 'Already in library', detail: 'Existing library copy is equal or higher quality', category: 'no_better' };
		}
		if (rawLower.includes('timed out') || rawLower.includes('timeout') || rawLower.includes('connection reset') || rawLower.includes('closed by peer') || rawLower.includes('connectionrefused')) {
			return { title: 'Peer offline / timed out', detail: 'The uploader disconnected or their client did not respond', category: 'timeout' };
		}
		if (rawLower.includes('queue') && (rawLower.includes('full') || rawLower.includes('limit'))) {
			return { title: 'Peer upload queue full', detail: 'Uploader has reached their max simultaneous transfer limit', category: 'queue_full' };
		}
		if (rawLower.includes('leech') || rawLower.includes('share') || rawLower.includes('denied')) {
			return { title: 'Access denied by peer', detail: 'Uploader restricts downloads to peers sharing files', category: 'denied' };
		}
		if (rawLower.includes('corrupt') || rawLower.includes('size mismatch') || rawLower.includes('eof')) {
			return { title: 'File transfer incomplete', detail: 'File received was incomplete or truncated', category: 'corrupt' };
		}
		return { title: 'Transfer error', detail: raw, category: 'other' };
	}

	// Server-side counts (independent of pagination) — fetched alongside loadJobs.
	let jobStatusCounts = $state({ all: 0, queued: 0, running: 0, completed: 0, failed: 0 });

	async function loadJobCounts() {
		try {
			const r = await fetch('/api/jobs/counts?type=download');
			if (!r.ok) return;
			const c = await r.json();
			jobStatusCounts = {
				all: c.all || 0,
				active: (c.pending || 0) + (c.running || 0),
				queued: c.pending || 0,
				running: c.running || 0,
				completed: c.completed || 0,
				failed: c.failed || 0,
			};
			if (jobStatusFilter === null) {
				setJobFilter(jobStatusCounts.active > 0 ? 'active' : jobStatusCounts.completed > 0 ? 'completed' : 'all');
			}
		} catch {}
	}

	let hasCleanable = $derived(jobs.some(j => j.status === 'completed' || j.status === 'failed'));

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

	function friendlyStatus(job, transfer) {
		if (!job) {
			if (transfer) {
				const s = transfer.state;
				if (s === 'transferring' || s === 'connected') return 'downloading';
				if (s === 'queued' || s === 'requested') return 'queued';
				return s;
			}
			return 'downloading';
		}
		if (job.status === 'completed') return 'completed';
		if (job.status === 'failed') return 'failed';
		if (job.status === 'pending') return 'queued';
		if (transfer) {
			const s = transfer.state;
			if (s === 'transferring' || s === 'connected') return 'downloading';
			if (s === 'queued' || s === 'requested') return 'queued';
			return s;
		}
		const tracks = parseJobTracks(job) || (job.id ? jobDetails[job.id] : null);
		if (tracks?.length) {
			const t = tracks[0];
			if (t.status === 'downloading' || t.status === 'transferring') return 'downloading';
			if (t.status === 'queued') return 'queued';
		}
		const wsDesc = (job.id ? wsDescriptions[job.id] : null) || job.description || '';
		if (wsDesc.includes('Queued for') || wsDesc.startsWith('Queued:')) return 'queued';
		if (wsDesc.includes('(attempt')) return 'downloading';
		return 'searching';
	}

	function statusVariant(status) {
		if (status === 'completed') return 'success';
		if (status === 'failed') return 'error';
		if (status === 'downloading') return 'info';
		if (status === 'queued') return 'warning';
		return 'default';
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

	// Active live transfers (actually transferring or connected)
	let liveTransfers = $derived(
		$activeTransfers.filter(tr => tr.state === 'transferring' || tr.state === 'connected' || (tr.speed && tr.speed > 0))
	);
	let totalTransferSpeed = $derived(
		liveTransfers.reduce((acc, tr) => acc + (tr.speed || 0), 0)
	);

	// Active hero cards items (active transfers in flight)
	let activeHeroItems = $derived.by(() => {
		const items = [];
		const seenJobIds = new Set();

		for (const tr of liveTransfers) {
			if (tr.job_id) seenJobIds.add(tr.job_id);
			items.push({
				type: 'transfer',
				transfer: tr,
				job: getJobForTransfer(tr),
				id: tr.job_id || `${tr.username}-${tr.filename}`,
			});
		}

		for (const j of visibleJobs) {
			if (j.status === 'running' && !seenJobIds.has(j.id)) {
				const tr = getTransferForJob(j);
				const status = friendlyStatus(j, tr);
				if (status === 'downloading') {
					seenJobIds.add(j.id);
					items.push({
						type: 'job',
						transfer: tr,
						job: j,
						id: j.id,
					});
				}
			}
		}
		return items;
	});

	let heroJobIds = $derived(new Set(activeHeroItems.map(item => item.job?.id).filter(Boolean)));

	// Currently searching job (pacing query on Soulseek central server)
	let searchingJob = $derived(
		visibleJobs.find(j => j.status === 'running' && friendlyStatus(j, getTransferForJob(j)) === 'searching')
	);

	// Queue rank derivation for jobs waiting for slot (FIFO: oldest queued first)
	let queuedJobsList = $derived(
		visibleJobs
			.filter(j => friendlyStatus(j, getTransferForJob(j)) === 'queued')
			.sort((a, b) => {
				const ta = a.started_at || a.created_at || '';
				const tb = b.started_at || b.created_at || '';
				return ta.localeCompare(tb);
			})
	);

	function getQueueRank(jobId) {
		const idx = queuedJobsList.findIndex(j => j.id === jobId);
		return idx >= 0 ? idx + 1 : null;
	}

	let displayJobs = $derived.by(() => {
		// When active transfer hero cards are shown on Active/All tab, exclude those active jobs from the rows below
		if (activeHeroItems.length > 0 && (jobStatusFilter === 'active' || jobStatusFilter === 'all' || jobStatusFilter === null)) {
			return visibleJobs.filter(j => !heroJobIds.has(j.id));
		}
		return visibleJobs;
	});

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
		try { failureGroups = await api.getDownloadFailures(); } catch { failureGroups = []; }
	}

	async function retryFailed() {
		if (!retryConfirm) return;
		retrying = true;
		try {
			const r = await api.retryFailedDownloads(retryConfirm.reason);
			if (r?.error) throw new Error(r.error);
			addToast(`Re-queued ${r.tracks} download${r.tracks === 1 ? '' : 's'}`, 'success');
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
			const data = await api.getDownloadHistory(jobsOffset, PAGE_LIMIT, status, jobStatusFilter === 'failed' ? failureReason : null);
			jobs = data.items || data;
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
		finally { jobsLoading = false; }
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

	async function retryJob(jobId) {
		try {
			await api.retryJob(jobId);
			addToast('Retry started', 'success');
			await loadJobs();
		} catch { addToast('Retry failed', 'error'); }
	}

	async function cancelJob(jobId) {
		try {
			await api.cancelJob(jobId);
			addToast('Download cancelled', 'success');
			await loadJobs();
		} catch { addToast('Cancel failed', 'error'); }
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
			if (!results.length) addToast('No results found', 'warning');
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
			const resp = await fetch('/api/download/trigger', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					artist, track,
					username: result.username,
					filename: result.filename,
					source: 'manual',
				})
			}).then(r => r.json());
			resultStatuses[key] = { status: 'searching', jobId: resp.job_id };
			addToast('Download started', 'success');
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
			await fetch('/api/download/trigger', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ artist, track, source: 'manual' })
			}).then(r => r.json());
			addToast('Auto-download started', 'success');
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

	let wsDescriptions = $state({});
	let unsubJobUpdate;
	let autoHideTimer;
	let loadJobsTimer;

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
		fetch('/api/download/status').then(r => r.json()).then(data => {
			if (data.downloads?.length) activeTransfers.set(data.downloads);
			activeUploads.set(data.uploads || []);
		}).catch(() => {});
		api.getServices().then(d => { sharing = !!d.slsk_share_library; }).catch(() => {});
		unsubJobUpdate = onJobUpdate(async (wsJob) => {
			if (wsJob.type === 'download' || wsJob.type === 'bulk_download') {
				if (wsJob.description) wsDescriptions[wsJob.id] = wsJob.description;
				// Update inline result statuses from job updates
				for (const [key, rs] of Object.entries(resultStatuses)) {
					if (rs.jobId === wsJob.id) {
						if (wsJob.status === 'completed') resultStatuses[key] = { status: 'completed', jobId: wsJob.id };
						else if (wsJob.status === 'failed') resultStatuses[key] = { status: 'failed', jobId: wsJob.id };
						else if (wsJob.status === 'running') {
							const desc = wsJob.description || '';
							if (desc.includes('(attempt')) resultStatuses[key] = { status: 'searching', jobId: wsJob.id };
						}
					}
				}
				// Update job in-place from WS data for instant UI feedback
				const idx = jobs.findIndex(j => j.id === wsJob.id);
				if (idx >= 0) {
					jobs[idx] = { ...jobs[idx], status: wsJob.status, progress: wsJob.progress, total: wsJob.total, description: wsJob.description || jobs[idx].description, result: wsJob.result || jobs[idx].result, finished_at: wsJob.finished_at || jobs[idx].finished_at };
				}
				// Debounce full reload — longer delay when many active jobs to avoid API hammering
				clearTimeout(loadJobsTimer);
				const activeCount = jobs.filter(j => j.status === 'running' || j.status === 'pending').length;
				const debounceMs = activeCount > 20 ? 10000 : activeCount > 5 ? 5000 : 2000;
				loadJobsTimer = setTimeout(loadJobs, debounceMs);
			}
		});
		autoHideTimer = setInterval(() => { jobs = [...jobs]; }, 30000);

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
		if (autoHideTimer) clearInterval(autoHideTimer);
		clearTimeout(loadJobsTimer);
	});
</script>

<div class="max-w-6xl">
	<PageHeader
		title="Downloads"
		subtitle="P2P Transfer Queue: 2 concurrent download slots · Soulseek Server Pacer: 6 searches/min"
		icon={Download}
		color="var(--color-downloads)">
		{#snippet actions()}
			<span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
				<span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
				Soulseek Connected
			</span>
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
								<Badge variant="success">
									<CircleCheck class="w-3 h-3 mr-0.5" />
									done
								</Badge>
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
				<EmptyState title="No results" description="No P2P results match the current filter.">
					{#snippet icon()}<Search class="w-10 h-10" />{/snippet}
				</EmptyState>
			{/if}
		</Card>
	{/if}

	<!-- Downloads (unified: active + history) -->
	{#if jobs.length || jobsLoading}
		<Card padding="p-4" class="mb-6">
			<div class="flex items-center justify-between mb-3">
				<div class="flex items-center gap-2">
					<Download class="w-4 h-4 text-[var(--color-downloads)]" />
					<h2 class="text-base font-semibold text-[var(--text-primary)]">Downloads</h2>
				</div>
				{#if hasCleanable}
					<button onclick={() => {
						const cleared = jobs.filter(j => j.status === 'completed' || j.status === 'failed').map(j => j.id);
						hiddenJobIds = new Set([...hiddenJobIds, ...cleared]);
						localStorage.setItem('hiddenDownloadJobs', JSON.stringify([...hiddenJobIds]));
						expandedJob = null;
					}} class="flex items-center gap-1.5 text-xs text-[var(--text-muted)] hover:text-red-400 transition-colors">
						<Eraser class="w-3.5 h-3.5" />
						Clear
					</button>
				{/if}
			</div>
			<FilterPills
				class="mb-4"
				options={[
					{ value: 'active', label: 'Active', color: 'downloads', count: jobStatusCounts.active },
					{ value: 'completed', label: 'Done', color: 'downloads', count: jobStatusCounts.completed },
					{ value: 'failed', label: 'Failed', color: 'downloads', count: jobStatusCounts.failed },
					{ value: 'all', label: 'All', color: 'downloads' },
				].filter(opt => opt.value === 'all' || opt.value === 'active' || (jobStatusCounts[opt.value] || 0) > 0)}
				value={jobStatusFilter}
				onchange={setJobFilter}
			/>

			{#if jobStatusFilter === 'failed' && failureGroups.length}
				<!-- Failures grouped by why they failed, so one kind can be retried or ignored. -->
				<div class="flex flex-wrap items-center gap-2 mb-4 -mt-1">
					<span class="text-xs text-[var(--text-muted)]">Why:</span>
					{#each failureGroups as g (g.reason)}
						<button onclick={() => setFailureReason(g.reason)}
							class="text-xs px-2.5 py-1 rounded-full border transition-colors
								{failureReason === g.reason
									? 'border-red-400/60 bg-red-500/15 text-red-300'
									: 'border-[var(--border-subtle)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]'}">
							{g.label} <span class="font-mono text-[var(--text-muted)]">{g.count.toLocaleString()}</span>
						</button>
					{/each}
					<Button variant="secondary" size="sm" class="ml-auto"
						onclick={() => retryConfirm = selectedFailureGroup
							? { reason: selectedFailureGroup.reason, label: selectedFailureGroup.label, count: selectedFailureGroup.count }
							: { reason: null, label: 'All failures', count: jobStatusCounts.failed }}>
						<RotateCcw class="w-3.5 h-3.5 mr-1" />
						{selectedFailureGroup ? `Retry ${selectedFailureGroup.count.toLocaleString()}` : 'Retry all'}
					</Button>
				</div>
			{/if}

			{#if jobsLoading && !jobs.length}
				<p class="text-sm text-[var(--text-muted)] text-center py-6">Loading...</p>
			{:else}
			<!-- TIER 1: ACTIVE TRANSFERS (Only what is moving data!) -->
			{#if activeHeroItems.length > 0 && (jobStatusFilter === 'active' || jobStatusFilter === 'all' || jobStatusFilter === null)}
				<div class="mb-5 p-4 rounded-xl bg-[var(--surface-container)] border border-[var(--border-subtle)] space-y-3">
					<div class="flex items-center justify-between flex-wrap gap-2">
						<div class="flex items-center gap-2">
							<span class="inline-flex items-center justify-center w-5 h-5 rounded-md bg-sky-500/20 text-sky-400 text-xs font-bold font-mono">{activeHeroItems.length}</span>
							<h3 class="text-sm font-semibold text-[var(--text-primary)]">Active Transfers</h3>
							<span class="text-xs text-[var(--text-muted)] font-mono">
								({activeHeroItems.length} of 2 slots active{#if totalTransferSpeed > 0} · {formatSpeed(totalTransferSpeed)} total{/if})
							</span>
						</div>
						<span class="text-xs text-sky-400/90 font-medium hidden sm:inline">Restricting concurrency to prevent peer choke</span>
					</div>

					<div class="grid grid-cols-1 md:grid-cols-2 gap-3">
						{#each activeHeroItems as item (item.id)}
							{@const tr = item.transfer}
							{@const job = item.job}
							{@const fname = tr?.filename?.split(/[/\\]/).pop() || ''}
							{@const ext = fileExtension(fname)}
							{@const rawTitle = formatJobTitle(job?.description || fname || 'Downloading file')}
							{@const peer = tr?.username || (job?.id ? jobDetails[job.id]?.[0]?.username : '') || ''}
							{@const progress = tr?.progress ?? (job?.total > 0 ? (job.progress / job.total) * 100 : 0)}
							{@const speed = tr?.speed || 0}
							{@const eta = tr?.eta_seconds || 0}
							{@const received = tr?.received_bytes || 0}
							{@const total = tr?.total_bytes || 0}

							<div class="rounded-xl p-4 space-y-3 relative overflow-hidden bg-gradient-to-br from-sky-500/10 via-[var(--surface-container-high)] to-[var(--surface-container)] border border-sky-500/30 shadow-sm">
								<div class="flex items-start justify-between gap-2">
									<div class="min-w-0 flex-1">
										<h4 class="text-sm font-semibold text-[var(--text-primary)] truncate" title={rawTitle}>
											{rawTitle}
										</h4>
										<div class="flex items-center gap-2 text-xs text-[var(--text-muted)] mt-0.5 flex-wrap">
											{#if peer}
												<span>Peer: <span class="text-[var(--text-secondary)] font-medium">{peer}</span></span>
											{/if}
											{#if ext}
												{#if peer}<span>&middot;</span>{/if}
												<Badge variant={ext === 'flac' ? 'success' : ext === 'mp3' ? 'default' : 'warning'}>
													{ext.toUpperCase()}
												</Badge>
											{/if}
											{#if sourceLabel(job)}
												<span>&middot;</span>
												<span class="px-1.5 py-0.5 rounded bg-[var(--surface-container-high)] text-[var(--text-muted)] text-[10px] font-medium">{sourceLabel(job)}</span>
											{/if}
										</div>
									</div>
									<button
										onclick={() => cancelActiveItem(item)}
										class="min-w-[32px] min-h-[32px] flex items-center justify-center text-[var(--text-muted)] hover:text-rose-400 transition-colors flex-shrink-0 -mr-1 -mt-1"
										title="Cancel download"
									>
										<X class="w-4 h-4" />
									</button>
								</div>

								<div class="space-y-1.5">
									<div class="flex justify-between items-center text-xs font-mono text-[var(--text-secondary)]">
										<span>
											{progress > 0 ? `${progress.toFixed(1)}%` : 'Connecting...'}
											{#if total > 0}
												<span class="text-[var(--text-muted)]">({formatSize(received)} / {formatSize(total)})</span>
											{/if}
										</span>
										<span class="text-sky-400 font-semibold">
											{#if speed > 0}
												{formatSpeed(speed)}{#if eta > 0} · ETA: {formatETA(eta)}{/if}
											{:else}
												<span class="text-[var(--text-muted)]">negotiating slot</span>
											{/if}
										</span>
									</div>
									<div class="w-full bg-[var(--surface-lowest)] rounded-full h-2 overflow-hidden border border-[var(--border-subtle)]">
										<div
											class="bg-gradient-to-r from-sky-500 to-sky-400 h-2 rounded-full transition-all duration-300"
											style="width: {Math.min(100, Math.max(progress > 0 ? 3 : 0, progress))}%"
										></div>
									</div>
								</div>
							</div>
						{/each}
					</div>
				</div>
			{/if}

			<!-- TIER 2: SEARCH PACER BANNER -->
			{#if searchingJob && (jobStatusFilter === 'active' || jobStatusFilter === 'all' || jobStatusFilter === null)}
				<div class="mb-4 rounded-xl p-3 flex items-center justify-between border border-indigo-500/25 bg-indigo-950/20 text-xs">
					<div class="flex items-center gap-3 min-w-0">
						<div class="relative flex items-center justify-center w-3 h-3 flex-shrink-0">
							<span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75"></span>
							<span class="relative inline-flex rounded-full h-2 w-2 bg-indigo-500"></span>
						</div>
						<div class="truncate text-[var(--text-secondary)]">
							<span class="text-white font-medium">Soulseek Central Server Pacer:</span>
							<span class="ml-1">Currently querying <span class="text-indigo-300 font-medium">“{formatJobTitle(wsDescriptions[searchingJob.id] || searchingJob.description || searchingJob.type)}”</span></span>
							<span class="text-[var(--text-muted)] hidden sm:inline ml-1">· Paced to protect central search quota (1 query / 8s)</span>
						</div>
					</div>
					<span class="text-[10px] px-2 py-0.5 rounded bg-indigo-500/20 text-indigo-300 font-mono flex-shrink-0 ml-2">Server Safe</span>
				</div>
			{/if}

			<!-- TIER 3: QUEUE & HISTORY ROWS -->
			{#if displayJobs.length === 0}
				{#if activeHeroItems.length > 0}
					<p class="text-xs text-[var(--text-muted)] text-center py-4">No additional jobs in queue.</p>
				{:else}
					<EmptyState title="No downloads" description="No download jobs match the current filter.">
						{#snippet icon()}<Download class="w-10 h-10" />{/snippet}
					</EmptyState>
				{/if}
			{:else}
				<div class="space-y-2">
					{#each displayJobs as job (job.id)}
						{@const transfer = getTransferForJob(job)}
						{@const status = friendlyStatus(job, transfer)}
						{@const queueRank = status === 'queued' ? getQueueRank(job.id) : null}
						{@const jobResult = parseJobResult(job)}
						{@const jobTracks = parseJobTracks(job)}
						{@const title = formatJobTitle(wsDescriptions[job.id] || job.description || job.type)}
						<div class="{status === 'completed' ? 'bg-emerald-500/5' : status === 'failed' ? 'bg-red-500/5' : status === 'downloading' ? 'bg-blue-500/5' : status === 'queued' ? 'bg-amber-500/5' : 'bg-[var(--surface-container)]'} rounded-lg overflow-hidden group/job">
							<div class="flex items-center gap-3 px-4 py-3">
								<div class="flex-1 min-w-0">
									<div class="flex items-center gap-2">
										{#if queueRank}
											<span class="text-xs font-bold font-mono px-2 py-0.5 rounded-md flex-shrink-0 {queueRank === 1 ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30' : queueRank === 2 ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20' : 'bg-[var(--surface-container-high)] text-[var(--text-muted)] border border-[var(--border-subtle)]'}">
												{queueRank === 1 ? '#1 NEXT' : queueRank === 2 ? '#2 IN LINE' : `#${queueRank}`}
											</span>
										{/if}
										<p class="text-sm text-[var(--text-primary)] font-medium truncate">
											{title}
											{#if sourceLabel(job)}<span class="ml-1.5 text-xs font-medium px-1.5 py-0.5 rounded bg-[var(--surface-container-high)] text-[var(--text-muted)]">{sourceLabel(job)}</span>{/if}
										</p>
									</div>

									{#if status === 'queued'}
										<div class="flex items-center gap-2 text-xs text-[var(--text-muted)] mt-0.5 flex-wrap">
											<span class="text-amber-400/90 font-medium">Waiting for transfer slot</span>
											{#if jobTracks?.[0]?.username}
												<span class="text-[var(--text-disabled)]">&middot;</span>
												<span>from {jobTracks[0].username}</span>
											{/if}
											{#if jobTracks?.[0]?.filename}
												{@const ext = fileExtension(jobTracks[0].filename)}
												{#if ext}
													<span class="text-[var(--text-disabled)]">&middot;</span>
													<Badge variant={ext === 'flac' ? 'success' : ext === 'mp3' ? 'default' : 'warning'}>{ext.toUpperCase()}</Badge>
												{/if}
											{/if}
											<span class="text-[var(--text-disabled)]">&middot;</span>
											<span>{job.created_at ? formatDateTime(job.created_at) : ''}</span>
										</div>
									{:else if status === 'searching'}
										<div class="flex items-center gap-2 text-xs text-[var(--text-muted)] mt-0.5">
											<span class="text-indigo-400 font-medium">Querying Soulseek network</span>
											<span class="text-[var(--text-disabled)]">&middot;</span>
											<span>Waiting for response from online peers</span>
										</div>
									{:else if job.status === 'completed' && (jobResult || jobTracks?.[0])}
										{@const t = jobTracks?.[0]}
										{@const fname = t?.filename || jobResult?.filename?.split(/[/\\]/).pop() || ''}
										{@const ext = fileExtension(fname)}
										{@const fsize = t?.file_size || t?.size || jobResult?.file_size || jobResult?.size || 0}
										<div class="flex items-center gap-2 text-xs text-[var(--text-muted)] mt-0.5 flex-wrap">
											{#if fname}
												{@const searchTerm = t?.track ? (t?.artist ? `${t.artist} ${t.track}` : t.track) : fname.replace(/\.\w+$/, '')}
												<a href="/library?search={encodeURIComponent(searchTerm)}"
													class="text-[var(--text-secondary)] font-medium truncate max-w-[300px] hover:text-[var(--color-accent)] transition-colors"
													title={jobResult?.filename || fname}>{fname}</a>
											{/if}
											{#if ext}
												<Badge variant={ext === 'flac' ? 'success' : ext === 'mp3' ? 'default' : 'warning'}>{ext.toUpperCase()}</Badge>
											{/if}
											{#if fsize > 0}
												<span class="font-mono">{formatSize(fsize)}</span>
											{/if}
											{#if t?.username || jobResult?.username}
												<span class="text-[var(--text-disabled)]">&middot;</span>
												<span>from {t?.username || jobResult?.username}</span>
											{/if}
											{#if jobResult?.strategy}
												<span class="text-[var(--text-disabled)]">&middot;</span>
												<span>{jobResult.sources_tried || 1} source{(jobResult.sources_tried || 1) > 1 ? 's' : ''}</span>
											{:else if jobResult?.attempt > 1}
												<span class="text-[var(--text-disabled)]">&middot;</span>
												<span>attempt {jobResult.attempt}</span>
											{/if}
											<span class="text-[var(--text-disabled)]">&middot;</span>
											<span>{job.finished_at ? formatDateTime(job.finished_at) : ''}</span>
										</div>
									{:else}
										<div class="flex items-center gap-2 text-xs text-[var(--text-muted)] flex-wrap">
											{#if transfer?.username}
												<span>from {transfer.username}</span>
												<span class="text-[var(--text-disabled)]">&middot;</span>
											{:else if job.status === 'running' && jobDetails[job.id]?.[0]?.username}
												<span>from {jobDetails[job.id][0].username}</span>
												<span class="text-[var(--text-disabled)]">&middot;</span>
											{/if}
											{#if transfer && transfer.speed > 0}
												<span class="font-mono">{formatSpeed(transfer.speed)}</span>
												<span class="text-[var(--text-disabled)]">&middot;</span>
											{/if}
											{#if transfer?.eta_seconds > 0}
												<span class="font-mono">{formatETA(transfer.eta_seconds)}</span>
												<span class="text-[var(--text-disabled)]">&middot;</span>
											{/if}
											{#if transfer && transfer.total_bytes > 0}
												<span class="font-mono hidden sm:inline">{formatSize(transfer.received_bytes)} / {formatSize(transfer.total_bytes)}</span>
											{:else if job.total > 1}
												<span>{job.progress || 0}/{job.total} tracks</span>
											{/if}
											{#if job.status === 'failed'}
												{@const fail = friendlyFailure(job, jobResult)}
												<span class="text-rose-400 font-medium">{fail.title}</span>
												<span class="text-[var(--text-disabled)]">&middot;</span>
												<span class="text-[var(--text-muted)] truncate max-w-md">{fail.detail}</span>
												{#if jobResult?.failed_sources?.length}
													<span class="text-[var(--text-disabled)]">&middot;</span>
													<span class="text-orange-400 font-mono" title={jobResult.failed_sources.join(', ')}>{jobResult.failed_sources.length} source{jobResult.failed_sources.length > 1 ? 's' : ''} tried</span>
												{/if}
												<span class="text-[var(--text-disabled)]">&middot;</span>
											{/if}
											{#if job.status !== 'running'}
												<span>{job.finished_at ? formatDateTime(job.finished_at) : job.started_at ? formatDateTime(job.started_at) : ''}</span>
											{/if}
										</div>
									{/if}
								</div>
								{#if job.status === 'running'}
									<button onclick={() => cancelJob(job.id)}
										class="min-w-[44px] min-h-[44px] flex items-center justify-center text-[var(--text-muted)] hover:text-red-400 transition-colors flex-shrink-0" title="Cancel">
										<X class="w-3.5 h-3.5" />
									</button>
								{/if}
								{#if job.status === 'completed' || job.status === 'failed'}
									<button onclick={() => {
										hiddenJobIds = new Set([...hiddenJobIds, job.id]);
										localStorage.setItem('hiddenDownloadJobs', JSON.stringify([...hiddenJobIds]));
									}} class="min-w-[44px] min-h-[44px] flex items-center justify-center text-[var(--text-muted)] hover:text-red-400 transition-colors flex-shrink-0 opacity-0 group-hover/job:opacity-100" title="Dismiss">
										<X class="w-3 h-3" />
									</button>
								{/if}
								{#if job.status === 'failed'}
									{@const searchQ = getSearchQueryForJob(job)}
									{#if searchQ}
										<button onclick={() => {
											searchQuery = searchQ;
											searchSoulseek();
											window.scrollTo({ top: 0, behavior: 'smooth' });
										}}
											class="min-w-[44px] min-h-[44px] flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--color-downloads)] transition-colors flex-shrink-0" title="Search P2P for alternative sources">
											<Search class="w-3.5 h-3.5" />
										</button>
									{/if}
									<button onclick={() => retryJob(job.id)}
										class="min-w-[44px] min-h-[44px] flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--color-downloads)] transition-colors flex-shrink-0" title="Retry download">
										<RotateCcw class="w-3.5 h-3.5" />
									</button>
								{/if}
								<Badge variant={statusVariant(status)}>
									{#if status === 'searching' || status === 'downloading'}
										<span class="inline-block w-1.5 h-1.5 rounded-full bg-current animate-pulse mr-1"></span>
									{:else if status === 'queued'}
										<Clock class="w-3 h-3 mr-0.5 inline-block" />
									{/if}
									{status === 'queued' ? 'Queued for slot' : status}
								</Badge>
								{#if job.total > 1 || (job.status === 'failed' && jobResult?.source_errors?.length)}
									<button onclick={() => toggleJobDetail(job.id)}
										class="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors flex-shrink-0">
										{#if expandedJob === job.id}
											<ChevronUp class="w-3.5 h-3.5" />
										{:else}
											<ChevronDown class="w-3.5 h-3.5" />
										{/if}
									</button>
								{/if}
							</div>
							<!-- Progress bar -->
							{#if transfer && (status === 'downloading' || job.status === 'running')}
								<div class="h-1 bg-[var(--border-interactive)]">
									<div class="h-full bg-[var(--color-downloads)] transition-all duration-300"
										style="width: {transfer.progress}%"></div>
								</div>
							{:else if job.status === 'running' && job.total > 1}
								<div class="h-1 bg-[var(--border-interactive)]">
									<div class="h-full bg-[var(--color-downloads)] transition-all duration-500"
										style="width: {((job.progress || 0) / job.total) * 100}%"></div>
								</div>
							{:else if job.status === 'running' && status === 'searching'}
								<div class="h-1 bg-[var(--border-interactive)] overflow-hidden relative">
									<div class="h-full animate-search"></div>
								</div>
							{/if}
							<!-- Expanded details -->
							{#if expandedJob === job.id}
								{#if jobResult?.source_errors?.length}
									<!-- Per-source error breakdown (single download) -->
									<div class="px-4 py-2 space-y-1 animate-fade-slide-in">
										<p class="text-xs font-mono uppercase tracking-wider text-[var(--text-muted)] mb-1">Sources tried</p>
										{#each jobResult.source_errors as se, i}
											<div class="flex items-center gap-2 text-xs py-1">
												<span class="w-4 text-center text-[var(--text-disabled)]">{i + 1}</span>
												<span class="text-[var(--text-body)] truncate max-w-[160px]">{se.user}</span>
												<span class="text-red-400 flex-1 truncate" title={se.error}>{se.error}</span>
												<Badge variant="error">failed</Badge>
											</div>
										{/each}
									</div>
								{:else if jobDetails[job.id]}
									<!-- Bulk track details -->
									<div class="px-4 py-2 space-y-1 animate-fade-slide-in">
										{#each jobDetails[job.id] as t, i}
											<div class="flex items-center gap-2 text-xs py-1 flex-wrap">
												<span class="w-4 text-center text-[var(--text-disabled)]">{i + 1}</span>
												<span class="flex-1 min-w-0 truncate text-[var(--text-body)]">
													{t.artist} — {t.track}
												</span>
												{#if t.username}
													<span class="text-[var(--text-disabled)] hidden md:inline">from {t.username}</span>
												{/if}
												{#if t.error}
													<span class="text-red-400 truncate max-w-[200px]" title={t.error}>{t.error}</span>
												{:else if t.reason}
													<span class="text-orange-400 truncate max-w-[200px]" title={t.reason}>{t.reason}</span>
												{/if}
												<Badge variant={
													t.status === 'downloaded' ? 'success' :
													t.status === 'downloading' || t.status === 'transferring' ? 'info' :
													t.status === 'pending' ? 'default' :
													t.status === 'skipped' ? 'warning' : 'error'
												}>{t.status}</Badge>
											</div>
										{/each}
									</div>
								{/if}
							{/if}
						</div>
					{/each}
				</div>
			{/if}

				<!-- Pagination -->
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
			{/if}
		</Card>
	{/if}

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
