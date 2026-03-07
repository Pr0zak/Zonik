<script>
	import { onMount } from 'svelte';
	import { addToast, discoverTrackStatus } from '$lib/stores.js';
	import { parseUTC } from '$lib/utils.js';
	import { Download, TrendingUp, Users, Music, Check, X, Loader2, RefreshCw, ListMusic, Search, Clock, ArrowUp, ArrowDown, Sparkles, ThumbsUp, ThumbsDown, Info, ChevronDown, ChevronUp } from 'lucide-svelte';
	import { api } from '$lib/api.js';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Button from '../../components/ui/Button.svelte';
	import Badge from '../../components/ui/Badge.svelte';
	import Skeleton from '../../components/ui/Skeleton.svelte';
	import EmptyState from '../../components/ui/EmptyState.svelte';
	import ScheduleControl from '../../components/ui/ScheduleControl.svelte';

	let activeTab = $state('foryou');

	// Top Tracks state
	let topTracks = $state([]);
	let topLoading = $state(false);
	let topLimit = $state(100);
	let topLastScanned = $state(null);

	// Similar Tracks state
	let similarTracks = $state([]);
	let similarLoading = $state(false);
	let similarLimit = $state(50);
	let similarLastScanned = $state(null);

	// Similar Artists state
	let similarArtists = $state([]);
	let artistsLoading = $state(false);

	// For You state
	let recommendations = $state([]);
	let recLoading = $state(false);
	let recRefreshing = $state(false);
	let tasteProfile = $state(null);
	let profileExpanded = $state(false);
	let recTotal = $state(0);
	let recProfileComputedAt = $state(null);

	// Search state
	let searchQuery = $state('');
	let searchResults = $state([]);
	let searchLoading = $state(false);
	let searchDone = $state(false);
	let showOnlyMissing = $state(false);

	// Sort state
	let sortColumn = $state(null);
	let sortDir = $state(null);

	// Shared
	let bulkDownloading = $state(false);
	let trackStatus = $state({...$discoverTrackStatus});
	// Sync track statuses to store for persistence across navigation
	$effect(() => {
		discoverTrackStatus.set({...trackStatus});
	});
	let schedTasks = $state({});
	let schedRunning = $state({});

	const tabs = [
		{ key: 'foryou', label: 'For You', icon: Sparkles },
		{ key: 'top', label: 'Top Tracks', icon: TrendingUp },
		{ key: 'similar', label: 'Similar Tracks', icon: Music },
		{ key: 'artists', label: 'Similar Artists', icon: Users },
		{ key: 'search', label: 'Search', icon: Search },
	];

	function trackKey(t) {
		return `${t.artist}::${t.name}`.toLowerCase();
	}

	function getStatus(t) {
		return trackStatus[trackKey(t)] || null;
	}

	function currentTracks() {
		return activeTab === 'top' ? topTracks : activeTab === 'similar' ? similarTracks : activeTab === 'search' ? searchResults : [];
	}

	let filteredSearchResults = $derived(
		showOnlyMissing ? searchResults.filter(t => !t.in_library) : searchResults
	);

	// --- Sort logic ---

	function toggleSort(column) {
		if (sortColumn === column) {
			if (sortDir === 'asc') {
				sortDir = 'desc';
			} else if (sortDir === 'desc') {
				sortColumn = null;
				sortDir = null;
			}
		} else {
			sortColumn = column;
			sortDir = 'asc';
		}
	}

	function sortTracks(tracks) {
		if (!sortColumn || !sortDir) return tracks;
		const sorted = [...tracks];
		const dir = sortDir === 'asc' ? 1 : -1;
		sorted.sort((a, b) => {
			let va, vb;
			if (sortColumn === 'name') {
				va = (a.name || '').toLowerCase();
				vb = (b.name || '').toLowerCase();
			} else if (sortColumn === 'artist') {
				va = (a.artist || '').toLowerCase();
				vb = (b.artist || '').toLowerCase();
			} else if (sortColumn === 'listeners') {
				va = a.listeners || 0;
				vb = b.listeners || 0;
				return (va - vb) * dir;
			} else if (sortColumn === 'status') {
				// in_library first, then by download status
				const statusOrder = (t) => {
					if (t.in_library) return 0;
					const s = getStatus(t);
					if (s === 'completed') return 1;
					if (s === 'downloading' || s === 'queued') return 2;
					if (s === 'failed') return 3;
					return 4;
				};
				va = statusOrder(a);
				vb = statusOrder(b);
				return (va - vb) * dir;
			} else if (sortColumn === 'source_artist') {
				va = (a.source_artist || '').toLowerCase();
				vb = (b.source_artist || '').toLowerCase();
			} else {
				return 0;
			}
			if (va < vb) return -1 * dir;
			if (va > vb) return 1 * dir;
			return 0;
		});
		return sorted;
	}

	function sortIndicator(column) {
		if (sortColumn !== column) return '';
		return sortDir === 'asc' ? '▲' : '▼';
	}

	// Clear sort when switching tabs
	function switchTab(tab) {
		activeTab = tab;
		sortColumn = null;
		sortDir = null;
		if (tab === 'foryou' && !recommendations.length && !recLoading) loadRecommendations();
		if (tab === 'top' && !topTracks.length && !topLoading) scanTopTracks();
		if (tab === 'similar' && !similarTracks.length && !similarLoading) scanSimilarTracks();
		if (tab === 'artists' && !similarArtists.length && !artistsLoading) scanSimilarArtists();
	}

	let sortedTopTracks = $derived(sortTracks(topTracks));
	let sortedSimilarTracks = $derived(sortTracks(similarTracks));
	let sortedSearchResults = $derived(sortTracks(filteredSearchResults));

	async function discoverSearch() {
		if (!searchQuery.trim()) return;
		searchLoading = true;
		searchDone = false;
		searchResults = [];
		try {
			const data = await fetch(`/api/discovery/search?q=${encodeURIComponent(searchQuery.trim())}&limit=50`).then(r => r.json());
			searchResults = data.tracks || [];
			searchDone = true;
			await syncDownloadStatuses(searchResults);
			if (!searchResults.length) addToast('No results found on Last.fm', 'warning');
		} catch (e) {
			addToast('Search failed', 'error');
		} finally {
			searchLoading = false;
		}
	}

	let missingCount = $derived(
		currentTracks().filter(t => !t.in_library && !getStatus(t)).length
	);
	let inLibraryCount = $derived(
		currentTracks().filter(t => t.in_library).length
	);

	// --- Load from cache (last job result) ---

	async function loadCachedResults(taskType, setter, limitSetter, lastScannedSetter) {
		try {
			const res = await fetch(`/api/jobs?type=${taskType}&limit=1`);
			const data = await res.json();
			const jobs = data.items || data;
			if (!jobs.length) return false;

			const detail = await fetch(`/api/jobs/${jobs[0].id}`).then(r => r.json());
			if (!detail.tracks) return false;

			const trackList = JSON.parse(detail.tracks);
			if (!Array.isArray(trackList) || !trackList.length) return false;

			// Parse result for stats
			let result = {};
			try { result = JSON.parse(detail.result); } catch (e) { console.error('Parse result failed:', e); }

			// Convert job track format to display format
			const displayTracks = trackList.map(t => ({
				name: t.track || t.name,
				artist: t.artist,
				in_library: false,
				source_artist: t.source?.split(' — ')[0] || '',
				source_track: t.source?.split(' — ')[1] || '',
			}));

			setter(displayTracks);
			lastScannedSetter(detail.finished_at);
			return true;
		} catch {
			return false;
		}
	}

	// --- Live scan (API call) ---

	async function syncDownloadStatuses(tracks) {
		// Check recent download jobs to mark tracks that were already downloaded
		try {
			const data = await fetch('/api/jobs?type=download,bulk_download&status=completed&limit=50').then(r => r.json());
			const jobs = data.items || [];
			for (const job of jobs) {
				if (!job.tracks) continue;
				try {
					const jt = JSON.parse(job.tracks);
					for (const t of jt) {
						if (t.status === 'downloaded' || t.status === 'downloading') {
							const key = `${t.artist}::${t.track}`.toLowerCase();
							if (!trackStatus[key]) trackStatus[key] = 'completed';
						}
					}
				} catch {}
			}
		} catch {}
	}

	async function scanTopTracks() {
		topLoading = true;
		try {
			const data = await fetch(`/api/discovery/top-tracks?limit=${topLimit}`).then(r => r.json());
			topTracks = data.tracks || [];
			topLastScanned = new Date().toISOString();
			await syncDownloadStatuses(topTracks);
		} catch (e) {
			addToast('Failed to load top tracks', 'error');
		} finally {
			topLoading = false;
		}
	}

	async function scanSimilarTracks() {
		similarLoading = true;
		try {
			const data = await fetch(`/api/discovery/similar-tracks?limit=${similarLimit}`).then(r => r.json());
			similarTracks = data.tracks || [];
			similarLastScanned = new Date().toISOString();
			await syncDownloadStatuses(similarTracks);
		} catch (e) {
			addToast('Failed to load similar tracks', 'error');
		} finally {
			similarLoading = false;
		}
	}

	async function scanSimilarArtists() {
		artistsLoading = true;
		try {
			const data = await fetch('/api/discovery/similar-artists?limit=30').then(r => r.json());
			similarArtists = data.artists || [];
		} catch (e) {
			addToast('Failed to load similar artists', 'error');
		} finally {
			artistsLoading = false;
		}
	}

	// --- Actions ---

	async function downloadTrack(t) {
		const key = trackKey(t);
		trackStatus[key] = 'downloading';
		try {
			const res = await fetch('/api/download/trigger', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ artist: t.artist, track: t.name }),
			});
			const data = await res.json();
			if (data.error) {
				trackStatus[key] = 'failed';
				return;
			}
			trackStatus[key] = 'queued';
			pollJob(data.job_id, key);
		} catch {
			trackStatus[key] = 'failed';
		}
	}

	async function pollJob(jobId, key) {
		for (let i = 0; i < 180; i++) {
			await new Promise(r => setTimeout(r, 2000));
			try {
				const job = await fetch(`/api/jobs/${jobId}`).then(r => r.json());
				if (job.status === 'completed') { trackStatus[key] = 'completed'; return; }
				if (job.status === 'failed') { trackStatus[key] = 'failed'; return; }
			} catch {}
		}
		trackStatus[key] = 'failed';
	}

	async function downloadAllMissing() {
		const items = currentTracks();
		const missing = items.filter(t => !t.in_library && !getStatus(t));
		if (!missing.length) return;

		bulkDownloading = true;
		for (const t of missing) trackStatus[trackKey(t)] = 'queued';

		let started = 0;
		for (const t of missing) {
			try {
				await fetch('/api/download/trigger', {
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({ artist: t.artist, track: t.name })
				});
				trackStatus[trackKey(t)] = 'downloading';
				started++;
			} catch {
				trackStatus[trackKey(t)] = 'failed';
			}
		}
		addToast(`Queued ${started} individual downloads`, 'success');
		bulkDownloading = false;
	}

	function formatAge(iso) {
		if (!iso) return '';
		const ms = Date.now() - parseUTC(iso).getTime();
		const h = Math.floor(ms / 3600000);
		if (h < 1) return 'just now';
		if (h < 24) return `${h}h ago`;
		const d = Math.floor(h / 24);
		return `${d}d ago`;
	}

	// --- Schedule helpers ---
	async function toggleSched(name) {
		const t = schedTasks[name];
		if (!t) return;
		const newEnabled = !t.enabled;
		await fetch(`/api/schedule/${name}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled: newEnabled }) });
		schedTasks[name] = { ...t, enabled: newEnabled };
	}
	async function updateSched(name, updates) {
		await fetch(`/api/schedule/${name}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(updates) });
		schedTasks[name] = { ...schedTasks[name], ...updates };
	}
	async function runSched(name) {
		schedRunning[name] = true;
		try {
			const res = await fetch(`/api/schedule/${name}/run`, { method: 'POST' });
			const data = await res.json();
			addToast('Task started — check Logs for progress', 'success');
			if (data.job_id) {
				pollSchedJob(name, data.job_id);
			}
		} catch { addToast('Failed to run task', 'error'); schedRunning[name] = false; }
	}

	async function pollSchedJob(name, jobId) {
		for (let i = 0; i < 300; i++) {
			await new Promise(r => setTimeout(r, 3000));
			try {
				const job = await fetch(`/api/jobs/${jobId}`).then(r => r.json());
				if (job.status === 'completed') {
					schedRunning[name] = false;
					schedTasks[name] = { ...schedTasks[name], last_run_at: new Date().toISOString() };
					const taskLabels = { lastfm_top_tracks: 'Top Charts', discover_similar: 'Similar Tracks', discover_artists: 'Similar Artists', recommendation_refresh: 'AI Recommendations' };
					addToast(`${taskLabels[name] || name} completed`, 'success');
					if (name === 'lastfm_top_tracks') scanTopTracks();
					else if (name === 'discover_similar') scanSimilarTracks();
					else if (name === 'discover_artists') scanSimilarArtists();
					else if (name === 'recommendation_refresh') loadRecommendations();
					return;
				}
				if (job.status === 'failed') {
					schedRunning[name] = false;
					addToast('Task failed', 'error');
					return;
				}
			} catch {}
		}
		schedRunning[name] = false;
	}

	async function toggleAutoDownload(name) {
		const t = schedTasks[name];
		if (!t) return;
		const current = t.config?.auto_download || false;
		const newConfig = { auto_download: !current };
		await fetch(`/api/schedule/${name}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ config: newConfig }) });
		schedTasks[name] = { ...t, config: { ...t.config, ...newConfig } };
	}

	// --- For You ---
	async function loadRecommendations() {
		recLoading = true;
		try {
			const [recData, profileData] = await Promise.all([
				api.getRecommendations({ status: 'pending', limit: 50 }),
				api.getTasteProfile(),
			]);
			recommendations = recData.items || [];
			recTotal = recData.total || 0;
			recProfileComputedAt = recData.profile_computed_at;
			tasteProfile = profileData.exists ? profileData : null;
		} catch (e) {
			addToast('Failed to load recommendations', 'error');
		} finally {
			recLoading = false;
		}
	}

	async function refreshRecs() {
		recRefreshing = true;
		try {
			const data = await api.refreshRecommendations(100);
			addToast('Generating recommendations — check Logs for progress', 'success');
			if (data.job_id) {
				for (let i = 0; i < 120; i++) {
					await new Promise(r => setTimeout(r, 3000));
					try {
						const job = await fetch(`/api/jobs/${data.job_id}`).then(r => r.json());
						if (job.status === 'completed') {
							addToast('Recommendations ready!', 'success');
							await loadRecommendations();
							break;
						}
						if (job.status === 'failed') {
							addToast('Recommendation refresh failed', 'error');
							break;
						}
					} catch {}
				}
			}
		} catch {
			addToast('Failed to start refresh', 'error');
		} finally {
			recRefreshing = false;
		}
	}

	async function recFeedback(rec, action) {
		try {
			await api.submitFeedback(rec.id, action);
			if (action === 'thumbs_down' || action === 'dismiss') {
				recommendations = recommendations.filter(r => r.id !== rec.id);
			} else if (action === 'thumbs_up') {
				recommendations = recommendations.map(r =>
					r.id === rec.id ? { ...r, feedback: 'thumbs_up', status: 'accepted' } : r
				);
			}
		} catch {
			addToast('Failed to submit feedback', 'error');
		}
	}

	async function downloadRec(rec) {
		const key = `${rec.artist}::${rec.track}`.toLowerCase();
		trackStatus[key] = 'downloading';
		try {
			const res = await fetch('/api/download/trigger', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ artist: rec.artist, track: rec.track }),
			});
			const data = await res.json();
			if (data.error) { trackStatus[key] = 'failed'; return; }
			trackStatus[key] = 'queued';
			await api.submitFeedback(rec.id, 'download');
			recommendations = recommendations.map(r =>
				r.id === rec.id ? { ...r, status: 'downloaded' } : r
			);
			pollJob(data.job_id, key);
		} catch {
			trackStatus[key] = 'failed';
		}
	}

	function scoreColor(score) {
		if (score >= 0.7) return 'text-green-400';
		if (score >= 0.4) return 'text-yellow-400';
		return 'text-red-400';
	}

	function scoreBg(score) {
		if (score >= 0.7) return 'bg-green-500/20 border-green-500/30';
		if (score >= 0.4) return 'bg-yellow-500/20 border-yellow-500/30';
		return 'bg-red-500/20 border-red-500/30';
	}

	onMount(async () => {
		// Load scheduled task configs
		try {
			const tasks = await fetch('/api/schedule').then(r => r.json());
			for (const t of tasks) schedTasks[t.task_name] = t;
			if (schedTasks.lastfm_top_tracks?.count) topLimit = schedTasks.lastfm_top_tracks.count;
			if (schedTasks.discover_similar?.count) similarLimit = schedTasks.discover_similar.count;
		} catch {}

		// Load For You tab by default
		loadRecommendations();
	});
</script>

<div class="max-w-6xl">
	<PageHeader title="Discover" color="var(--color-discover)" />

	<!-- Tabs -->
	<div class="flex gap-1.5 mb-4 overflow-x-auto">
		{#each tabs as tab}
			{@const Icon = tab.icon}
			<button onclick={() => switchTab(tab.key)}
				class="flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors
					{activeTab === tab.key
						? 'bg-[var(--color-discover)] text-white'
						: 'bg-[var(--bg-hover)] text-[var(--text-secondary)] hover:text-white hover:bg-[var(--bg-active)]'}">
				<Icon class="w-3.5 h-3.5" />
				{tab.label}
			</button>
		{/each}
	</div>

	<!-- Search tab: search bar -->
	{#if activeTab === 'search'}
		<div class="flex gap-3 mb-4">
			<div class="flex-1 relative">
				<Search class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--text-disabled)]" />
				<input type="text" placeholder="Search Last.fm for tracks or artists..." bind:value={searchQuery}
					onkeydown={(e) => e.key === 'Enter' && discoverSearch()}
					class="w-full bg-[var(--bg-secondary)] border border-[var(--border-interactive)] rounded-lg pl-10 pr-4 py-2.5 text-sm text-[var(--text-body)]
						placeholder-[var(--text-disabled)] focus:outline-none focus:ring-1 focus:border-[var(--color-discover)]/50 focus:ring-[var(--color-discover)]/20" />
			</div>
			<Button variant="primary" loading={searchLoading} disabled={!searchQuery.trim()} onclick={discoverSearch}>
				<Search class="w-3.5 h-3.5" />
				Search
			</Button>
		</div>
	{/if}

	<!-- Summary bar + actions -->
	{#if activeTab === 'top' || activeTab === 'similar' || (activeTab === 'search' && searchResults.length)}
		{@const tracks = currentTracks()}
		{@const lastScanned = activeTab === 'top' ? topLastScanned : activeTab === 'similar' ? similarLastScanned : null}
		{@const isLoading = activeTab === 'top' ? topLoading : activeTab === 'similar' ? similarLoading : searchLoading}
		{@const scanFn = activeTab === 'top' ? scanTopTracks : activeTab === 'similar' ? scanSimilarTracks : null}

		{#if tracks.length || isLoading}
			<Card padding="p-4">
				<div class="flex flex-wrap items-center gap-3">
					<!-- Stats -->
					<div class="flex items-center gap-4 flex-1 min-w-0">
						{#if tracks.length}
							<div class="flex items-center gap-1.5">
								<span class="text-2xl font-bold text-[var(--text-primary)]">{missingCount}</span>
								<span class="text-xs text-[var(--text-muted)]">missing</span>
							</div>
							<div class="flex items-center gap-1.5">
								<span class="text-2xl font-bold text-green-400">{inLibraryCount}</span>
								<span class="text-xs text-[var(--text-muted)]">in library</span>
							</div>
							<div class="text-xs text-[var(--text-muted)] font-mono hidden sm:block">
								{tracks.length} total
								{#if lastScanned}
									<span class="mx-1">&middot;</span> scanned {formatAge(lastScanned)}
								{/if}
							</div>
							{#if activeTab === 'search'}
								<label class="flex items-center gap-1.5 text-xs text-[var(--text-muted)] cursor-pointer ml-2">
									<input type="checkbox" bind:checked={showOnlyMissing} class="rounded cursor-pointer" />
									Only missing
								</label>
							{/if}
						{/if}
					</div>

					<!-- Actions -->
					<div class="flex items-center gap-2">
						{#if scanFn}
							<Button variant="default" size="sm" onclick={scanFn} loading={isLoading}>
								<Search class="w-3.5 h-3.5" />
								{activeTab === 'top' ? 'Check Chart' : 'Discover'}
							</Button>
						{/if}
						{#if missingCount > 0}
							<Button variant="success" size="sm" onclick={downloadAllMissing} loading={bulkDownloading}>
								<Download class="w-3.5 h-3.5" />
								Download {missingCount}
							</Button>
						{/if}
					</div>
				</div>
			</Card>
		{/if}
	{/if}

	<!-- Track lists -->
	<div class="mt-4">
		{#if activeTab === 'foryou'}
			<!-- Taste Profile Summary -->
			{#if tasteProfile}
				<Card padding="p-4" class="mb-4">
					<button onclick={() => profileExpanded = !profileExpanded}
						class="w-full flex items-center justify-between">
						<div class="flex items-center gap-3">
							<Sparkles class="w-4 h-4 text-[var(--color-discover)]" />
							<span class="text-sm font-medium text-[var(--text-primary)]">Your Taste Profile</span>
							{#if recProfileComputedAt}
								<span class="text-xs text-[var(--text-muted)] font-mono">{formatAge(recProfileComputedAt)}</span>
							{/if}
						</div>
						<div class="flex items-center gap-3">
							<span class="text-xs text-[var(--text-muted)]">{tasteProfile.track_count} tracks, {tasteProfile.favorite_count} favorites</span>
							{#if profileExpanded}
								<ChevronUp class="w-4 h-4 text-[var(--text-muted)]" />
							{:else}
								<ChevronDown class="w-4 h-4 text-[var(--text-muted)]" />
							{/if}
						</div>
					</button>
					{#if profileExpanded}
						<div class="mt-3 pt-3 border-t border-[var(--border-subtle)] grid grid-cols-1 md:grid-cols-3 gap-4">
							<!-- Genres -->
							<div>
								<span class="text-xs text-[var(--text-muted)] uppercase tracking-wider font-medium">Top Genres</span>
								<div class="mt-2 space-y-1">
									{#each Object.entries(tasteProfile.genre_distribution || {}).slice(0, 8) as [genre, pct]}
										<div class="flex items-center gap-2">
											<div class="flex-1 h-1.5 bg-[var(--bg-hover)] rounded-full overflow-hidden">
												<div class="h-full bg-[var(--color-discover)] rounded-full" style="width: {Math.round(pct * 100)}%"></div>
											</div>
											<span class="text-xs text-[var(--text-secondary)] w-24 truncate">{genre}</span>
											<span class="text-xs text-[var(--text-muted)] font-mono w-8 text-right">{Math.round(pct * 100)}%</span>
										</div>
									{/each}
								</div>
							</div>
							<!-- Top Artists -->
							<div>
								<span class="text-xs text-[var(--text-muted)] uppercase tracking-wider font-medium">Top Artists</span>
								<div class="mt-2 space-y-1">
									{#each (tasteProfile.top_artists || []).slice(0, 8) as artist}
										<div class="flex items-center justify-between">
											<span class="text-xs text-[var(--text-secondary)] truncate">{artist.name}</span>
											<span class="text-xs text-[var(--text-muted)] font-mono">{artist.plays} plays</span>
										</div>
									{/each}
								</div>
							</div>
							<!-- Audio Stats -->
							<div>
								<span class="text-xs text-[var(--text-muted)] uppercase tracking-wider font-medium">Audio Profile</span>
								<div class="mt-2 space-y-2">
									{#if tasteProfile.audio?.avg_bpm}
										<div class="flex justify-between text-xs">
											<span class="text-[var(--text-secondary)]">Avg BPM</span>
											<span class="text-[var(--text-primary)] font-mono">{tasteProfile.audio.avg_bpm}{tasteProfile.audio.bpm_std ? ` ±${tasteProfile.audio.bpm_std}` : ''}</span>
										</div>
									{/if}
									{#if tasteProfile.audio?.avg_energy != null}
										<div class="flex justify-between text-xs">
											<span class="text-[var(--text-secondary)]">Avg Energy</span>
											<span class="text-[var(--text-primary)] font-mono">{(tasteProfile.audio.avg_energy * 100).toFixed(0)}%</span>
										</div>
									{/if}
									{#if tasteProfile.audio?.avg_danceability != null}
										<div class="flex justify-between text-xs">
											<span class="text-[var(--text-secondary)]">Avg Danceability</span>
											<span class="text-[var(--text-primary)] font-mono">{(tasteProfile.audio.avg_danceability * 100).toFixed(0)}%</span>
										</div>
									{/if}
									<div class="flex justify-between text-xs">
										<span class="text-[var(--text-secondary)]">Analyzed</span>
										<span class="text-[var(--text-primary)] font-mono">{tasteProfile.analyzed_count} tracks</span>
									</div>
									{#if tasteProfile.has_clap_centroid}
										<div class="flex items-center gap-1 text-xs text-green-400">
											<Check class="w-3 h-3" /> CLAP vibe centroid active
										</div>
									{/if}
								</div>
							</div>
						</div>
					{/if}
				</Card>
			{/if}

			<!-- Actions bar -->
			<Card padding="p-4" class="mb-4">
				<div class="flex items-center justify-between">
					<div class="flex items-center gap-4">
						<span class="text-2xl font-bold text-[var(--text-primary)]">{recTotal}</span>
						<span class="text-xs text-[var(--text-muted)]">recommendations</span>
					</div>
					<Button variant="primary" size="sm" onclick={refreshRecs} loading={recRefreshing}>
						<RefreshCw class="w-3.5 h-3.5" />
						Refresh
					</Button>
				</div>
			</Card>

			<!-- Recommendation list -->
			{#if recLoading && !recommendations.length}
				<Card padding="p-0">
					<div class="divide-y divide-[var(--border-subtle)]">
						{#each Array(8) as _}
							<div class="px-4 py-4 flex items-center gap-4">
								<Skeleton class="h-8 w-12 rounded" />
								<div class="flex-1 space-y-1.5">
									<Skeleton class="h-4 w-40" />
									<Skeleton class="h-3 w-28" />
								</div>
								<Skeleton class="h-5 w-16 rounded-full" />
							</div>
						{/each}
					</div>
				</Card>
			{:else if recommendations.length}
				<Card padding="p-0">
					<div class="divide-y divide-[var(--border-subtle)]">
						{#each recommendations as rec}
							{@const recKey = `${rec.artist}::${rec.track}`.toLowerCase()}
							{@const dlStatus = trackStatus[recKey] || null}
							<div class="px-4 py-3 flex items-center gap-3 hover:bg-[var(--bg-hover)] transition-colors
								{rec.status === 'downloaded' ? 'bg-green-500/5' : ''}
								{rec.feedback === 'thumbs_up' ? 'bg-green-500/5' : ''}">
								<!-- Score badge -->
								<div class="flex-shrink-0 w-12 text-center">
									<span class="inline-block px-2 py-0.5 rounded text-xs font-bold border {scoreBg(rec.score)} {scoreColor(rec.score)}">
										{Math.round(rec.score * 100)}
									</span>
								</div>

								<!-- Track info -->
								<div class="flex-1 min-w-0">
									<div class="flex items-center gap-2">
										<span class="font-medium text-sm text-[var(--text-primary)] truncate">{rec.track}</span>
										<span class="text-xs text-[var(--text-muted)] px-1.5 py-0.5 rounded bg-[var(--bg-hover)]">{rec.source}</span>
									</div>
									<div class="flex items-center gap-2 mt-0.5">
										<span class="text-xs text-[var(--text-secondary)]">{rec.artist}</span>
										{#if rec.lastfm_listeners}
											<span class="text-xs text-[var(--text-muted)] font-mono">{rec.lastfm_listeners.toLocaleString()} listeners</span>
										{/if}
									</div>
									{#if rec.explanation}
										<p class="text-xs text-[var(--text-muted)] mt-0.5 truncate">{rec.explanation}</p>
									{/if}
								</div>

								<!-- Actions -->
								<div class="flex items-center gap-1.5 flex-shrink-0">
									{#if rec.status === 'downloaded' || dlStatus === 'completed'}
										<span class="text-xs text-green-400 flex items-center gap-1">
											<Check class="w-3.5 h-3.5" /> Downloaded
										</span>
									{:else if dlStatus === 'downloading' || dlStatus === 'queued'}
										<span class="text-xs text-blue-400 flex items-center gap-1">
											<Loader2 class="w-3.5 h-3.5 animate-spin" />
											{dlStatus === 'queued' ? 'Queued' : 'Downloading'}
										</span>
									{:else if dlStatus === 'failed'}
										<button onclick={() => downloadRec(rec)} class="text-xs text-red-400 hover:text-red-300 underline">retry</button>
									{:else}
										<button onclick={() => downloadRec(rec)}
											class="p-1.5 rounded hover:bg-green-500/20 text-[var(--text-muted)] hover:text-green-400 transition-colors"
											title="Download">
											<Download class="w-4 h-4" />
										</button>
									{/if}

									{#if rec.feedback === 'thumbs_up'}
										<span class="p-1.5 text-green-400"><ThumbsUp class="w-4 h-4" /></span>
									{:else if rec.feedback !== 'thumbs_down'}
										<button onclick={() => recFeedback(rec, 'thumbs_up')}
											class="p-1.5 rounded hover:bg-green-500/20 text-[var(--text-muted)] hover:text-green-400 transition-colors"
											title="Like">
											<ThumbsUp class="w-4 h-4" />
										</button>
										<button onclick={() => recFeedback(rec, 'thumbs_down')}
											class="p-1.5 rounded hover:bg-red-500/20 text-[var(--text-muted)] hover:text-red-400 transition-colors"
											title="Not for me">
											<ThumbsDown class="w-4 h-4" />
										</button>
									{/if}
								</div>
							</div>
						{/each}
					</div>
				</Card>
			{:else}
				<Card>
					<EmptyState title="No recommendations yet" description="Click 'Refresh' to build your taste profile and generate personalized recommendations from Last.fm." />
				</Card>
			{/if}

		{:else if activeTab === 'top'}
			{#if topLoading && !topTracks.length}
				<Card padding="p-0">
					<div class="divide-y divide-[var(--border-subtle)]">
						{#each Array(10) as _}
							<div class="px-4 py-3 flex items-center gap-4">
								<Skeleton class="h-4 w-8" />
								<Skeleton class="h-4 w-40" />
								<Skeleton class="h-4 w-28" />
								<Skeleton class="h-5 w-16 rounded-full" />
							</div>
						{/each}
					</div>
				</Card>
			{:else if topTracks.length}
				<Card padding="p-0">
					<table class="w-full text-sm">
						<thead>
							<tr class="border-b border-[var(--border-subtle)] text-left">
								<th class="px-4 py-3 w-8 font-medium text-xs uppercase tracking-wider text-[var(--text-muted)]">#</th>
								<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider cursor-pointer select-none hover:text-[var(--text-secondary)] transition-colors {sortColumn === 'name' ? 'text-[var(--text-primary)]' : 'text-[var(--text-muted)]'}"
									onclick={() => toggleSort('name')}>
									Track {sortIndicator('name')}
								</th>
								<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider cursor-pointer select-none hover:text-[var(--text-secondary)] transition-colors {sortColumn === 'artist' ? 'text-[var(--text-primary)]' : 'text-[var(--text-muted)]'}"
									onclick={() => toggleSort('artist')}>
									Artist {sortIndicator('artist')}
								</th>
								<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider hidden md:table-cell cursor-pointer select-none hover:text-[var(--text-secondary)] transition-colors {sortColumn === 'listeners' ? 'text-[var(--text-primary)]' : 'text-[var(--text-muted)]'}"
									onclick={() => toggleSort('listeners')}>
									Listeners {sortIndicator('listeners')}
								</th>
								<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider text-right cursor-pointer select-none hover:text-[var(--text-secondary)] transition-colors {sortColumn === 'status' ? 'text-[var(--text-primary)]' : 'text-[var(--text-muted)]'}"
									onclick={() => toggleSort('status')}>
									Status {sortIndicator('status')}
								</th>
							</tr>
						</thead>
						<tbody class="divide-y divide-[var(--border-subtle)]">
							{#each sortedTopTracks as t, i}
								{@const status = getStatus(t)}
								<tr class="transition-colors {status === 'completed' ? 'bg-green-500/5' : status === 'failed' ? 'bg-red-500/5' : 'hover:bg-[var(--bg-hover)]'}">
									<td class="px-4 py-3 text-[var(--text-muted)] font-mono text-xs">{i + 1}</td>
									<td class="px-4 py-3 font-medium text-[var(--text-primary)]">{t.name}</td>
									<td class="px-4 py-3 text-[var(--text-secondary)]">{t.artist}</td>
									<td class="px-4 py-3 text-[var(--text-muted)] font-mono text-xs hidden md:table-cell">{t.listeners?.toLocaleString() || ''}</td>
									<td class="px-4 py-3 text-right">
										{#if t.in_library}
											<Badge variant="success">In Library</Badge>
										{:else if status === 'completed'}
											<span class="inline-flex items-center gap-1 text-green-400 text-xs font-medium">
												<Check class="w-3.5 h-3.5" /> Downloaded
											</span>
										{:else if status === 'failed'}
											<span class="inline-flex items-center gap-2">
												<span class="text-red-400 text-xs font-medium inline-flex items-center gap-1">
													<X class="w-3.5 h-3.5" /> Failed
												</span>
												<button onclick={() => downloadTrack(t)}
													class="text-[var(--text-muted)] hover:text-white text-xs underline">retry</button>
											</span>
										{:else if status === 'downloading' || status === 'queued'}
											<span class="inline-flex items-center gap-1.5 text-blue-400 text-xs font-medium">
												<Loader2 class="w-3.5 h-3.5 animate-spin" />
												{status === 'queued' ? 'Queued' : 'Downloading'}
											</span>
										{:else}
											<Button variant="success" size="sm" onclick={() => downloadTrack(t)}>
												<Download class="w-3 h-3" />
											</Button>
										{/if}
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</Card>
			{:else}
				<Card>
					<EmptyState title="No top tracks" description="Click 'Check Chart' to pull the current Last.fm top chart." />
				</Card>
			{/if}

		{:else if activeTab === 'similar'}
			{#if similarLoading && !similarTracks.length}
				<Card padding="p-0">
					<div class="divide-y divide-[var(--border-subtle)]">
						{#each Array(10) as _}
							<div class="px-4 py-3 flex items-center gap-4">
								<Skeleton class="h-4 w-40" />
								<Skeleton class="h-4 w-28" />
								<Skeleton class="h-5 w-16 rounded-full" />
							</div>
						{/each}
					</div>
				</Card>
			{:else if similarTracks.length}
				<Card padding="p-0">
					<table class="w-full text-sm">
						<thead>
							<tr class="border-b border-[var(--border-subtle)] text-left">
								<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider cursor-pointer select-none hover:text-[var(--text-secondary)] transition-colors {sortColumn === 'name' ? 'text-[var(--text-primary)]' : 'text-[var(--text-muted)]'}"
									onclick={() => toggleSort('name')}>
									Track {sortIndicator('name')}
								</th>
								<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider cursor-pointer select-none hover:text-[var(--text-secondary)] transition-colors {sortColumn === 'artist' ? 'text-[var(--text-primary)]' : 'text-[var(--text-muted)]'}"
									onclick={() => toggleSort('artist')}>
									Artist {sortIndicator('artist')}
								</th>
								<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider hidden md:table-cell cursor-pointer select-none hover:text-[var(--text-secondary)] transition-colors {sortColumn === 'source_artist' ? 'text-[var(--text-primary)]' : 'text-[var(--text-muted)]'}"
									onclick={() => toggleSort('source_artist')}>
									Similar to {sortIndicator('source_artist')}
								</th>
								<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider text-right cursor-pointer select-none hover:text-[var(--text-secondary)] transition-colors {sortColumn === 'status' ? 'text-[var(--text-primary)]' : 'text-[var(--text-muted)]'}"
									onclick={() => toggleSort('status')}>
									Status {sortIndicator('status')}
								</th>
							</tr>
						</thead>
						<tbody class="divide-y divide-[var(--border-subtle)]">
							{#each sortedSimilarTracks as t}
								{@const status = getStatus(t)}
								<tr class="transition-colors {status === 'completed' ? 'bg-green-500/5' : status === 'failed' ? 'bg-red-500/5' : 'hover:bg-[var(--bg-hover)]'}">
									<td class="px-4 py-3 font-medium text-[var(--text-primary)]">{t.name}</td>
									<td class="px-4 py-3 text-[var(--text-secondary)]">{t.artist}</td>
									<td class="px-4 py-3 text-[var(--text-muted)] text-xs font-mono hidden md:table-cell">
										{#if t.source_artist}
											{t.source_artist} — {t.source_track}
										{/if}
									</td>
									<td class="px-4 py-3 text-right">
										{#if t.in_library}
											<Badge variant="success">In Library</Badge>
										{:else if status === 'completed'}
											<span class="inline-flex items-center gap-1 text-green-400 text-xs font-medium">
												<Check class="w-3.5 h-3.5" /> Downloaded
											</span>
										{:else if status === 'failed'}
											<span class="inline-flex items-center gap-2">
												<span class="text-red-400 text-xs font-medium inline-flex items-center gap-1">
													<X class="w-3.5 h-3.5" /> Failed
												</span>
												<button onclick={() => downloadTrack(t)}
													class="text-[var(--text-muted)] hover:text-white text-xs underline">retry</button>
											</span>
										{:else if status === 'downloading' || status === 'queued'}
											<span class="inline-flex items-center gap-1.5 text-blue-400 text-xs font-medium">
												<Loader2 class="w-3.5 h-3.5 animate-spin" />
												{status === 'queued' ? 'Queued' : 'Downloading'}
											</span>
										{:else}
											<Button variant="success" size="sm" onclick={() => downloadTrack(t)}>
												<Download class="w-3 h-3" />
											</Button>
										{/if}
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</Card>
			{:else}
				<Card>
					<EmptyState title="No similar tracks" description="Click 'Discover' to find tracks similar to your favorites, or star some tracks first." />
				</Card>
			{/if}

		{:else if activeTab === 'search'}
			{#if searchLoading && !searchResults.length}
				<Card padding="p-0">
					<div class="divide-y divide-[var(--border-subtle)]">
						{#each Array(10) as _}
							<div class="px-4 py-3 flex items-center gap-4">
								<Skeleton class="h-4 w-40" />
								<Skeleton class="h-4 w-28" />
								<Skeleton class="h-5 w-16 rounded-full" />
							</div>
						{/each}
					</div>
				</Card>
			{:else if sortedSearchResults.length}
				<Card padding="p-0">
					<table class="w-full text-sm">
						<thead>
							<tr class="border-b border-[var(--border-subtle)] text-left">
								<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider cursor-pointer select-none hover:text-[var(--text-secondary)] transition-colors {sortColumn === 'name' ? 'text-[var(--text-primary)]' : 'text-[var(--text-muted)]'}"
									onclick={() => toggleSort('name')}>
									Track {sortIndicator('name')}
								</th>
								<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider cursor-pointer select-none hover:text-[var(--text-secondary)] transition-colors {sortColumn === 'artist' ? 'text-[var(--text-primary)]' : 'text-[var(--text-muted)]'}"
									onclick={() => toggleSort('artist')}>
									Artist {sortIndicator('artist')}
								</th>
								<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider hidden md:table-cell cursor-pointer select-none hover:text-[var(--text-secondary)] transition-colors {sortColumn === 'listeners' ? 'text-[var(--text-primary)]' : 'text-[var(--text-muted)]'}"
									onclick={() => toggleSort('listeners')}>
									Listeners {sortIndicator('listeners')}
								</th>
								<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider text-right text-[var(--text-muted)]">Status</th>
							</tr>
						</thead>
						<tbody class="divide-y divide-[var(--border-subtle)]">
							{#each sortedSearchResults as t}
								{@const status = getStatus(t)}
								<tr class="transition-colors {status === 'completed' ? 'bg-green-500/5' : status === 'failed' ? 'bg-red-500/5' : 'hover:bg-[var(--bg-hover)]'}">
									<td class="px-4 py-3 font-medium text-[var(--text-primary)]">{t.name}</td>
									<td class="px-4 py-3 text-[var(--text-secondary)]">{t.artist}</td>
									<td class="px-4 py-3 text-[var(--text-muted)] font-mono text-xs hidden md:table-cell">{t.listeners?.toLocaleString() || ''}</td>
									<td class="px-4 py-3 text-right">
										{#if t.in_library}
											<Badge variant="success">In Library</Badge>
										{:else if status === 'completed'}
											<span class="inline-flex items-center gap-1 text-green-400 text-xs font-medium">
												<Check class="w-3.5 h-3.5" /> Downloaded
											</span>
										{:else if status === 'failed'}
											<span class="inline-flex items-center gap-2">
												<span class="text-red-400 text-xs font-medium inline-flex items-center gap-1">
													<X class="w-3.5 h-3.5" /> Failed
												</span>
												<button onclick={() => downloadTrack(t)}
													class="text-[var(--text-muted)] hover:text-white text-xs underline">retry</button>
											</span>
										{:else if status === 'downloading' || status === 'queued'}
											<span class="inline-flex items-center gap-1 text-[var(--color-accent)] text-xs">
												<Loader2 class="w-3.5 h-3.5 animate-spin" />
											</span>
										{:else}
											<button onclick={() => downloadTrack(t)}
												class="inline-flex items-center gap-1 text-xs text-[var(--text-muted)] hover:text-[var(--color-discover)] transition-colors">
												<Download class="w-3.5 h-3.5" /> Download
											</button>
										{/if}
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</Card>
			{:else if searchDone}
				<Card>
					<EmptyState title="No results" description="Try a different search term." />
				</Card>
			{:else}
				<Card>
					<EmptyState title="Search Last.fm" description="Search for tracks or artists to find music not in your library." />
				</Card>
			{/if}

		{:else if activeTab === 'artists'}
			{#if artistsLoading}
				<Card padding="p-0">
					<div class="divide-y divide-[var(--border-subtle)]">
						{#each Array(10) as _}
							<div class="px-4 py-3 flex items-center gap-4">
								<Skeleton class="h-4 w-40" />
								<Skeleton class="h-5 w-16 rounded-full" />
							</div>
						{/each}
					</div>
				</Card>
			{:else if similarArtists.length}
				<Card padding="p-0">
					<div class="divide-y divide-[var(--border-subtle)]">
						{#each similarArtists as a}
							<div class="px-4 py-3 flex items-center justify-between hover:bg-[var(--bg-hover)] transition-colors">
								<div>
									<span class="font-medium text-[var(--text-primary)]">{a.name}</span>
									<span class="text-xs text-[var(--text-muted)] ml-2 font-mono">similar to {a.source_artist}</span>
								</div>
								<div class="flex items-center gap-2">
									{#if a.in_library}
										<Badge variant="success">In Library</Badge>
									{:else}
										<Badge variant="warning">New</Badge>
									{/if}
								</div>
							</div>
						{/each}
					</div>
				</Card>
			{:else}
				<Card>
					<EmptyState title="No similar artists" description="Star some tracks first to get artist suggestions." />
				</Card>
			{/if}
		{/if}
	</div>

	<!-- Schedule -->
	{#if schedTasks.lastfm_top_tracks || schedTasks.discover_similar || schedTasks.recommendation_refresh}
		<Card padding="p-4" class="mt-6">
			<div class="flex items-center gap-2 mb-2">
				<Clock class="w-4 h-4 text-[var(--text-muted)]" />
				<span class="text-xs text-[var(--text-muted)] font-mono uppercase tracking-wider">Schedule</span>
			</div>
			{#if schedTasks.recommendation_refresh}
				<ScheduleControl taskName="recommendation_refresh" label="AI Recommendations" enabled={schedTasks.recommendation_refresh.enabled} intervalHours={schedTasks.recommendation_refresh.interval_hours} runAt={schedTasks.recommendation_refresh.run_at} lastRunAt={schedTasks.recommendation_refresh.last_run_at} running={schedRunning.recommendation_refresh} onToggle={() => toggleSched('recommendation_refresh')} onUpdate={(u) => updateSched('recommendation_refresh', u)} onRun={() => runSched('recommendation_refresh')} />
			{/if}
			{#if schedTasks.lastfm_top_tracks}
				<ScheduleControl taskName="lastfm_top_tracks" label="Top Charts Scan" enabled={schedTasks.lastfm_top_tracks.enabled} intervalHours={schedTasks.lastfm_top_tracks.interval_hours} runAt={schedTasks.lastfm_top_tracks.run_at} count={schedTasks.lastfm_top_tracks.count} lastRunAt={schedTasks.lastfm_top_tracks.last_run_at} running={schedRunning.lastfm_top_tracks} onToggle={() => toggleSched('lastfm_top_tracks')} onUpdate={(u) => updateSched('lastfm_top_tracks', u)} onRun={() => runSched('lastfm_top_tracks')} autoDownload={schedTasks.lastfm_top_tracks.config?.auto_download || false} onToggleAutoDownload={() => toggleAutoDownload('lastfm_top_tracks')} />
			{/if}
			{#if schedTasks.discover_similar}
				<ScheduleControl taskName="discover_similar" label="Similar Tracks Scan" enabled={schedTasks.discover_similar.enabled} intervalHours={schedTasks.discover_similar.interval_hours} runAt={schedTasks.discover_similar.run_at} count={schedTasks.discover_similar.count} lastRunAt={schedTasks.discover_similar.last_run_at} running={schedRunning.discover_similar} onToggle={() => toggleSched('discover_similar')} onUpdate={(u) => updateSched('discover_similar', u)} onRun={() => runSched('discover_similar')} autoDownload={schedTasks.discover_similar.config?.auto_download || false} onToggleAutoDownload={() => toggleAutoDownload('discover_similar')} />
			{/if}
			{#if schedTasks.discover_artists}
				<ScheduleControl taskName="discover_artists" label="Similar Artists Scan" enabled={schedTasks.discover_artists.enabled} intervalHours={schedTasks.discover_artists.interval_hours} runAt={schedTasks.discover_artists.run_at} count={schedTasks.discover_artists.count} lastRunAt={schedTasks.discover_artists.last_run_at} running={schedRunning.discover_artists} onToggle={() => toggleSched('discover_artists')} onUpdate={(u) => updateSched('discover_artists', u)} onRun={() => runSched('discover_artists')} />
			{/if}

		</Card>
	{/if}
</div>
