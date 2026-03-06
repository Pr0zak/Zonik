<script>
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/stores';
	import { api } from '$lib/api.js';
	import { addToast, activeTransfers } from '$lib/stores.js';
	import { onJobUpdate } from '$lib/websocket.js';
	import { formatSize, formatSpeed, formatETA } from '$lib/utils.js';
	import { Download, Search, Zap, ShieldBan, Trash2, X, ChevronLeft, ChevronRight, ChevronDown, ChevronUp, RotateCcw, Eraser, CircleCheck, Wifi } from 'lucide-svelte';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Button from '../../components/ui/Button.svelte';
	import Badge from '../../components/ui/Badge.svelte';

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
	let jobDetails = $state({});
	const PAGE_LIMIT = 20;
	const AUTO_HIDE_MS = 5 * 60 * 1000;

	let hiddenJobIds = $state(new Set(
		JSON.parse(localStorage.getItem('hiddenDownloadJobs') || '[]')
	));

	let visibleJobs = $derived(
		jobs.filter(j => {
			if (hiddenJobIds.has(j.id)) return false;
			if (j.status === 'completed' && j.finished_at) {
				const age = Date.now() - new Date(j.finished_at).getTime();
				return age < AUTO_HIDE_MS;
			}
			return true;
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

	let hasCleanable = $derived(jobs.some(j => j.status === 'completed' || j.status === 'failed'));

	function getTransferForJob(job) {
		if (job.status !== 'running') return null;
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
		if (job.status === 'completed') return 'completed';
		if (job.status === 'failed') return 'failed';
		if (job.status === 'pending') return 'queued';
		if (transfer) {
			const s = transfer.state;
			if (s === 'transferring' || s === 'connected') return 'downloading';
			if (s === 'queued' || s === 'requested') return 'queued';
			return s;
		}
		const tracks = jobDetails[job.id];
		if (tracks?.length) {
			const t = tracks[0];
			if (t.status === 'downloading' || t.status === 'transferring') return 'downloading';
		}
		const wsDesc = wsDescriptions[job.id] || job.description || '';
		if (wsDesc.includes('(attempt')) return 'downloading';
		return 'searching';
	}

	function statusVariant(status) {
		if (status === 'completed') return 'success';
		if (status === 'failed') return 'error';
		if (status === 'downloading') return 'info';
		return 'default';
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

	function formatUserSpeed(speed) {
		if (!speed) return '';
		if (speed > 1000000) return `${(speed / 1000000).toFixed(1)} MB/s`;
		if (speed > 1000) return `${(speed / 1000).toFixed(0)} KB/s`;
		return `${speed} B/s`;
	}

	async function loadJobs() {
		jobsLoading = true;
		try {
			const data = await api.getDownloadHistory(jobsOffset, PAGE_LIMIT);
			jobs = data.items || data;
			for (const j of jobs) {
				if ((j.status === 'running' || !jobDetails[j.id])) {
					try {
						const detail = await api.getJob(j.id);
						if (detail?.tracks) jobDetails[j.id] = JSON.parse(detail.tracks);
					} catch (e) { console.error('Job detail load failed:', e); }
				}
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
			const body = parts.length >= 2
				? { artist: parts[0], track: parts.slice(1).join(' ') }
				: { query: q };
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
				body: JSON.stringify({ artist, track })
			}).then(r => r.json());
			addToast('Auto-download started', 'success');
		} catch (e) {
			addToast('Download failed: ' + e.message, 'error');
		}
	}

	function handleKeydown(e) {
		if (e.key === 'Enter') searchSoulseek();
	}

	let wsDescriptions = $state({});
	let unsubJobUpdate;
	let autoHideTimer;

	onMount(() => {
		loadBlacklist();
		loadJobs();
		fetch('/api/download/status').then(r => r.json()).then(data => {
			if (data.downloads?.length) activeTransfers.set(data.downloads);
		}).catch(() => {});
		unsubJobUpdate = onJobUpdate(async (wsJob) => {
			if (wsJob.type === 'download' || wsJob.type === 'bulk_download') {
				if (wsJob.description) wsDescriptions[wsJob.id] = wsJob.description;
				// Update inline result statuses from job updates
				for (const [key, rs] of Object.entries(resultStatuses)) {
					if (rs.jobId === wsJob.id) {
						if (wsJob.status === 'completed') resultStatuses[key] = { status: 'completed', jobId: wsJob.id };
						else if (wsJob.status === 'failed') {
							resultStatuses[key] = { status: 'failed', jobId: wsJob.id };
							// Fetch job detail to get failed_sources for cooldown marking
							try {
								const detail = await api.getJob(wsJob.id);
								// Job detail fetched for status tracking
							} catch {}
						}
						else if (wsJob.status === 'running') {
							const desc = wsJob.description || '';
							if (desc.includes('(attempt')) resultStatuses[key] = { status: 'searching', jobId: wsJob.id };
						}
					}
				}
				loadJobs();
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
	});
</script>

<div class="max-w-6xl">
	<PageHeader title="Downloads" color="var(--color-downloads)" />

	<!-- Search Bar -->
	<div class="flex gap-3 mb-6">
		<div class="flex-1 relative">
			<Search class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--text-disabled)]" />
			<input type="text" placeholder="Search P2P network... (e.g. Artist - Track)" bind:value={searchQuery} onkeydown={handleKeydown}
				class="w-full bg-[var(--bg-secondary)] border border-[var(--border-interactive)] rounded-lg pl-10 pr-4 py-2.5 text-sm text-[var(--text-body)]
					placeholder-[var(--text-disabled)] focus:outline-none focus:ring-1 focus:border-[var(--color-downloads)]/50 focus:ring-[var(--color-downloads)]/20" />
		</div>
		<Button variant="primary" loading={searching} disabled={!searchQuery.trim()} onclick={searchSoulseek}>
			<Search class="w-3.5 h-3.5" />
			Search
		</Button>
		<Button variant="success" disabled={!searchQuery.trim()} onclick={autoDownload} title="Auto-pick best result">
			<Zap class="w-3.5 h-3.5" />
		</Button>
	</div>

	<!-- Downloads (unified: active + history) -->
	{#if visibleJobs.length || jobsLoading}
		<Card padding="p-4" class="mb-6">
			<div class="flex items-center justify-between mb-4">
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

			{#if jobsLoading && !jobs.length}
				<p class="text-sm text-[var(--text-muted)] text-center py-6">Loading...</p>
			{:else}
				<div class="space-y-2">
					{#each visibleJobs as job (job.id)}
						{@const transfer = getTransferForJob(job)}
						{@const status = friendlyStatus(job, transfer)}
						{@const jobResult = parseJobResult(job)}
						{@const jobTracks = parseJobTracks(job)}
						<div class="bg-[var(--bg-tertiary)] rounded-lg overflow-hidden group/job">
							<div class="flex items-center gap-3 px-4 py-3">
								<div class="flex-1 min-w-0">
									<p class="text-sm text-[var(--text-primary)] font-medium truncate">{job.description || job.type}</p>
									{#if job.status === 'completed' && (jobResult || jobTracks?.[0])}
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
											<span>{job.finished_at ? new Date(job.finished_at).toLocaleString() : ''}</span>
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
												{#if jobResult?.last_error}
													<span class="text-red-400">{jobResult.last_error}</span>
												{:else if jobResult?.message}
													<span class="text-red-400">{jobResult.message}</span>
												{:else if jobResult?.error}
													<span class="text-red-400">{jobResult.error}</span>
												{/if}
												{#if jobResult?.failed_sources?.length}
													<span class="text-[var(--text-disabled)]">&middot;</span>
													<span class="text-orange-400" title={jobResult.failed_sources.join(', ')}>{jobResult.failed_sources.length} source{jobResult.failed_sources.length > 1 ? 's' : ''} tried</span>
												{/if}
												<span class="text-[var(--text-disabled)]">&middot;</span>
											{/if}
											{#if job.status !== 'running'}
												<span>{job.finished_at ? new Date(job.finished_at).toLocaleString() : job.started_at ? new Date(job.started_at).toLocaleString() : ''}</span>
											{/if}
										</div>
									{/if}
								</div>
								{#if job.status === 'running'}
									<button onclick={() => cancelJob(job.id)}
										class="p-1.5 text-[var(--text-muted)] hover:text-red-400 transition-colors flex-shrink-0" title="Cancel">
										<X class="w-3.5 h-3.5" />
									</button>
								{/if}
								{#if job.status === 'completed' || job.status === 'failed'}
									<button onclick={() => {
										hiddenJobIds = new Set([...hiddenJobIds, job.id]);
										localStorage.setItem('hiddenDownloadJobs', JSON.stringify([...hiddenJobIds]));
									}} class="p-1.5 text-[var(--text-muted)] hover:text-red-400 transition-colors flex-shrink-0 opacity-0 group-hover/job:opacity-100" title="Dismiss">
										<X class="w-3 h-3" />
									</button>
								{/if}
								{#if job.status === 'failed'}
									{#if jobTracks?.[0]?.artist && jobTracks?.[0]?.track}
										<button onclick={() => {
											searchQuery = `${jobTracks[0].artist} - ${jobTracks[0].track}`;
											searchSoulseek();
										}}
											class="p-1.5 text-[var(--text-muted)] hover:text-[var(--color-downloads)] transition-colors flex-shrink-0" title="Search P2P for new sources">
											<Search class="w-3.5 h-3.5" />
										</button>
									{/if}
									<button onclick={() => retryJob(job.id)}
										class="p-1.5 text-[var(--text-muted)] hover:text-[var(--color-downloads)] transition-colors flex-shrink-0" title="Retry">
										<RotateCcw class="w-3.5 h-3.5" />
									</button>
								{/if}
								<Badge variant={statusVariant(status)}>
									{#if status === 'searching' || status === 'downloading'}
										<span class="inline-block w-1.5 h-1.5 rounded-full bg-current animate-pulse mr-1"></span>
									{/if}
									{status}
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
							{:else if job.status === 'running'}
								<div class="h-1 bg-[var(--border-interactive)] overflow-hidden">
									<div class="h-full bg-[var(--color-downloads)] animate-indeterminate w-1/3"></div>
								</div>
							{/if}
							<!-- Expanded details -->
							{#if expandedJob === job.id}
								{#if jobResult?.source_errors?.length}
									<!-- Per-source error breakdown (single download) -->
									<div class="px-4 py-2 space-y-1 border-t border-[var(--border-subtle)] animate-fade-slide-in">
										<p class="text-[10px] font-mono uppercase tracking-wider text-[var(--text-muted)] mb-1">Sources tried</p>
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
									<div class="px-4 py-2 space-y-1 border-t border-[var(--border-subtle)] animate-fade-slide-in">
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
			<div class="px-4 py-3 border-b border-[var(--border-subtle)]">
				<div class="flex items-center justify-between flex-wrap gap-2">
					<p class="text-xs text-[var(--text-muted)]">
						{resultCount} results from {resultUsers} users
						{#if allFilteredResults.length !== results.length}
							· {allFilteredResults.length} shown
						{/if}
					</p>
					<div class="flex items-center gap-3">
						<!-- Format filter tabs -->
						<div class="flex gap-1">
							{#each [
								{ key: 'all', label: 'All', count: formatCounts.all },
								{ key: 'flac', label: 'FLAC', count: formatCounts.flac },
								{ key: '320', label: '320+', count: formatCounts.high },
								{ key: '256', label: '256+', count: formatCounts.mid },
							] as tab}
								<button onclick={() => { formatFilter = tab.key; resultsPage = 0; }}
									class="px-2.5 py-1 rounded-md text-xs font-medium transition-colors
										{formatFilter === tab.key
											? 'bg-[var(--color-downloads)] text-white'
											: 'text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)]'}">
									{tab.label}
									<span class="ml-1 opacity-60">{tab.count}</span>
								</button>
							{/each}
						</div>
						<!-- Per page selector -->
						<select bind:value={resultsPerPage} onchange={() => resultsPage = 0}
							class="bg-[var(--bg-primary)] border border-[var(--border-interactive)] rounded-md px-2 py-1 text-xs text-[var(--text-muted)]">
							{#each [25, 50, 100] as n}
								<option value={n}>{n}/page</option>
							{/each}
						</select>
					</div>
				</div>
			</div>

			{#if filteredResults.length}
				<div class="overflow-x-auto">
					<table class="w-full text-sm min-w-[600px]">
						<thead>
							<tr class="border-b border-[var(--border-subtle)] text-[var(--text-muted)] text-left">
								<th class="px-4 py-2 w-5">
									<button onclick={() => toggleSort('quality')} class="font-medium text-xs uppercase tracking-wider hover:text-[var(--text-primary)] transition-colors"
										title="Sort by quality">
										{sortCol === 'quality' ? (sortAsc ? '▲' : '▼') : '◆'}
									</button>
								</th>
								<th class="px-4 py-2 font-medium text-xs uppercase tracking-wider">Title</th>
								<th class="px-4 py-2 hidden md:table-cell">
									<button onclick={() => toggleSort('user')} class="font-medium text-xs uppercase tracking-wider hover:text-[var(--text-primary)] transition-colors">
										User {sortCol === 'user' ? (sortAsc ? '▲' : '▼') : ''}
									</button>
								</th>
								<th class="px-4 py-2">
									<button onclick={() => toggleSort('format')} class="font-medium text-xs uppercase tracking-wider hover:text-[var(--text-primary)] transition-colors">
										Format {sortCol === 'format' ? (sortAsc ? '▲' : '▼') : ''}
									</button>
								</th>
								<th class="px-4 py-2 hidden sm:table-cell">
									<button onclick={() => toggleSort('bitrate')} class="font-medium text-xs uppercase tracking-wider hover:text-[var(--text-primary)] transition-colors">
										Bitrate {sortCol === 'bitrate' ? (sortAsc ? '▲' : '▼') : ''}
									</button>
								</th>
								<th class="px-4 py-2">
									<button onclick={() => toggleSort('size')} class="font-medium text-xs uppercase tracking-wider hover:text-[var(--text-primary)] transition-colors">
										Size {sortCol === 'size' ? (sortAsc ? '▲' : '▼') : ''}
									</button>
								</th>
								<th class="px-4 py-2"></th>
							</tr>
						</thead>
						<tbody class="divide-y divide-[var(--border-subtle)]">
							{#each filteredResults as r}
								{@const key = r.username + r.filename}
								{@const fname = shortFilename(r.filename)}
								{@const pathArtist = extractArtistFromPath(r.filename)}
								{@const inline = getResultInlineStatus(r)}
								<tr class="hover:bg-[var(--bg-hover)] transition-colors group
									{inline?.status === 'completed' ? 'bg-green-500/5' : inline?.status === 'failed' ? 'bg-red-500/5' : inline?.status === 'downloading' ? 'bg-blue-500/5' : ''}">
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
												<span class="text-[10px] text-[var(--text-muted)] font-mono whitespace-nowrap">
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
										<Badge variant={r.extension === 'flac' ? 'success' : r.extension === 'mp3' ? 'default' : 'warning'}>
											{r.extension.toUpperCase()}
										</Badge>
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
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
				<!-- Results pagination -->
				{#if totalResultPages > 1}
					<div class="flex items-center justify-between px-4 py-2 border-t border-[var(--border-subtle)]">
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
				<p class="text-sm text-[var(--text-muted)] text-center py-6">No results match the current filter.</p>
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
						class="flex-1 bg-[var(--bg-primary)] border border-[var(--border-interactive)] rounded-md px-3 py-1.5 text-sm text-[var(--text-body)]
							placeholder-[var(--text-disabled)] focus:outline-none focus:ring-1 focus:border-[var(--color-accent)]/50 focus:ring-[var(--color-accent)]/20" />
					<Button variant="secondary" size="sm" disabled={!blSearch.trim() || blSearching} onclick={searchLibraryForBlacklist}>
						<Search class="w-3 h-3" />
						Find
					</Button>
				</div>
				{#if blSearchResults.length}
					<div class="space-y-1 mb-3 max-h-48 overflow-y-auto">
						{#each blSearchResults as artist}
							<div class="flex items-center justify-between px-3 py-1.5 bg-[var(--bg-tertiary)] rounded-md text-sm hover:bg-[var(--bg-hover)] transition-colors">
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
					class="flex-1 bg-[var(--bg-primary)] border border-[var(--border-interactive)] rounded-md px-3 py-1.5 text-sm text-[var(--text-body)]
						placeholder-[var(--text-disabled)] focus:outline-none focus:ring-1 focus:border-[var(--color-accent)]/50 focus:ring-[var(--color-accent)]/20" />
				<input type="text" placeholder="Track (blank = entire artist)" bind:value={blTrack}
					class="flex-1 bg-[var(--bg-primary)] border border-[var(--border-interactive)] rounded-md px-3 py-1.5 text-sm text-[var(--text-body)]
						placeholder-[var(--text-disabled)] focus:outline-none focus:ring-1 focus:border-[var(--color-accent)]/50 focus:ring-[var(--color-accent)]/20" />
				<input type="text" placeholder="Reason" bind:value={blReason}
					class="w-48 bg-[var(--bg-primary)] border border-[var(--border-interactive)] rounded-md px-3 py-1.5 text-sm text-[var(--text-body)]
						placeholder-[var(--text-disabled)] focus:outline-none focus:ring-1 focus:border-[var(--color-accent)]/50 focus:ring-[var(--color-accent)]/20" />
				<Button variant="danger" size="sm" disabled={!blArtist.trim()} onclick={addBlacklistEntry}>
					<ShieldBan class="w-3 h-3" />
					Block
				</Button>
			</div>

			{#if blacklist.length > 3}
				<div class="mb-2">
					<input type="text" placeholder="Filter blacklist..." bind:value={blFilter}
						class="w-full sm:w-64 bg-[var(--bg-primary)] border border-[var(--border-interactive)] rounded-md px-3 py-1.5 text-sm text-[var(--text-body)]
							placeholder-[var(--text-disabled)] focus:outline-none focus:ring-1 focus:border-[var(--color-accent)]/50 focus:ring-[var(--color-accent)]/20" />
				</div>
			{/if}
			{#if filteredBlacklist.length}
				<div class="space-y-1 animate-fade-slide-in">
					{#each filteredBlacklist as entry}
						<div class="flex items-center justify-between px-3 py-2 bg-[var(--bg-tertiary)] rounded-md text-sm hover:bg-[var(--bg-hover)] transition-colors">
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
