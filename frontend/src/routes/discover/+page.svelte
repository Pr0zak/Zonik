<script>
	import { onMount } from 'svelte';
	import { addToast } from '$lib/stores.js';
	import { Download, TrendingUp, Users, Music, Check, X, Loader2, RefreshCw, ListMusic, Search } from 'lucide-svelte';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Button from '../../components/ui/Button.svelte';
	import Badge from '../../components/ui/Badge.svelte';
	import Skeleton from '../../components/ui/Skeleton.svelte';
	import EmptyState from '../../components/ui/EmptyState.svelte';

	let activeTab = $state('top');

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

	// Shared
	let bulkDownloading = $state(false);
	let trackStatus = $state({});

	const tabs = [
		{ key: 'top', label: 'Top Tracks', icon: TrendingUp },
		{ key: 'similar', label: 'Similar Tracks', icon: Music },
		{ key: 'artists', label: 'Similar Artists', icon: Users },
	];

	function trackKey(t) {
		return `${t.artist}::${t.name}`.toLowerCase();
	}

	function getStatus(t) {
		return trackStatus[trackKey(t)] || null;
	}

	function currentTracks() {
		return activeTab === 'top' ? topTracks : activeTab === 'similar' ? similarTracks : [];
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
			const jobs = await res.json();
			if (!jobs.length) return false;

			const detail = await fetch(`/api/jobs/${jobs[0].id}`).then(r => r.json());
			if (!detail.tracks) return false;

			const trackList = JSON.parse(detail.tracks);
			if (!Array.isArray(trackList) || !trackList.length) return false;

			// Parse result for stats
			let result = {};
			try { result = JSON.parse(detail.result); } catch {}

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

	async function scanTopTracks() {
		topLoading = true;
		try {
			const data = await fetch(`/api/discovery/top-tracks?limit=${topLimit}`).then(r => r.json());
			topTracks = data.tracks || [];
			topLastScanned = new Date().toISOString();
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

		try {
			const res = await fetch('/api/download/bulk', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ tracks: missing.map(t => ({ artist: t.artist, track: t.name })) })
			});
			const data = await res.json();
			if (data.job_id) {
				addToast(`Downloading ${missing.length} tracks`, 'success');
				pollBulkJob(data.job_id);
			}
		} catch (e) {
			addToast('Bulk download failed', 'error');
			for (const t of missing) trackStatus[trackKey(t)] = 'failed';
		} finally {
			bulkDownloading = false;
		}
	}

	async function pollBulkJob(jobId) {
		for (let i = 0; i < 300; i++) {
			await new Promise(r => setTimeout(r, 2000));
			try {
				const job = await fetch(`/api/jobs/${jobId}`).then(r => r.json());
				if (job.tracks) {
					try {
						for (const tj of JSON.parse(job.tracks)) {
							const key = `${tj.artist}::${tj.track}`.toLowerCase();
							if (tj.status === 'downloaded' || tj.status === 'downloading') trackStatus[key] = 'completed';
							else if (tj.status === 'failed' || tj.status === 'skipped') trackStatus[key] = 'failed';
						}
					} catch {}
				}
				if (job.status === 'completed' || job.status === 'failed') return;
			} catch {}
		}
	}

	function formatAge(iso) {
		if (!iso) return '';
		const ms = Date.now() - new Date(iso).getTime();
		const h = Math.floor(ms / 3600000);
		if (h < 1) return 'just now';
		if (h < 24) return `${h}h ago`;
		const d = Math.floor(h / 24);
		return `${d}d ago`;
	}

	function switchTab(tab) {
		activeTab = tab;
		if (tab === 'top' && !topTracks.length && !topLoading) scanTopTracks();
		if (tab === 'similar' && !similarTracks.length && !similarLoading) scanSimilarTracks();
		if (tab === 'artists' && !similarArtists.length && !artistsLoading) scanSimilarArtists();
	}

	onMount(async () => {
		// Load scheduled task configs for limits
		try {
			const tasks = await fetch('/api/schedule').then(r => r.json());
			const topTask = tasks.find(t => t.task_name === 'lastfm_top_tracks');
			if (topTask?.count) topLimit = topTask.count;
			const simTask = tasks.find(t => t.task_name === 'discover_similar');
			if (simTask?.count) similarLimit = simTask.count;
		} catch {}

		// Try loading cached results first, fall back to live scan
		const hasCached = await loadCachedResults('lastfm_top_tracks', v => topTracks = v, v => topLimit = v, v => topLastScanned = v);
		if (!hasCached) scanTopTracks();
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

	<!-- Summary bar + actions -->
	{#if activeTab === 'top' || activeTab === 'similar'}
		{@const tracks = currentTracks()}
		{@const lastScanned = activeTab === 'top' ? topLastScanned : similarLastScanned}
		{@const isLoading = activeTab === 'top' ? topLoading : similarLoading}
		{@const scanFn = activeTab === 'top' ? scanTopTracks : scanSimilarTracks}

		{#if tracks.length || isLoading}
			<Card padding="p-3">
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
									<span class="mx-1">·</span> scanned {formatAge(lastScanned)}
								{/if}
							</div>
						{/if}
					</div>

					<!-- Actions -->
					<div class="flex items-center gap-2">
						<Button variant="default" size="sm" onclick={scanFn} loading={isLoading}>
							<Search class="w-3.5 h-3.5" />
							{activeTab === 'top' ? 'Check Chart' : 'Discover'}
						</Button>
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
		{#if activeTab === 'top'}
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
							<tr class="border-b border-[var(--border-subtle)] text-[var(--text-muted)] text-left">
								<th class="px-4 py-3 w-8 font-medium text-xs uppercase tracking-wider">#</th>
								<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider">Track</th>
								<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider">Artist</th>
								<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider hidden md:table-cell">Listeners</th>
								<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider text-right">Status</th>
							</tr>
						</thead>
						<tbody class="divide-y divide-[var(--border-subtle)]">
							{#each topTracks as t, i}
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
							<tr class="border-b border-[var(--border-subtle)] text-[var(--text-muted)] text-left">
								<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider">Track</th>
								<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider">Artist</th>
								<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider hidden md:table-cell">Similar to</th>
								<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider text-right">Status</th>
							</tr>
						</thead>
						<tbody class="divide-y divide-[var(--border-subtle)]">
							{#each similarTracks as t}
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
</div>
