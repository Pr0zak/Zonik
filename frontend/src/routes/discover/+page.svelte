<script>
	import { onMount, onDestroy } from 'svelte';
	import { addToast, activeJobs } from '$lib/stores.js';
	import { Download, TrendingUp, Users, Music, Check, X, Loader2 } from 'lucide-svelte';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Button from '../../components/ui/Button.svelte';
	import Badge from '../../components/ui/Badge.svelte';
	import Skeleton from '../../components/ui/Skeleton.svelte';
	import EmptyState from '../../components/ui/EmptyState.svelte';

	let activeTab = $state('top');
	let topTracks = $state([]);
	let similarTracks = $state([]);
	let similarArtists = $state([]);
	let loading = $state(false);
	let bulkDownloading = $state(false);

	/** Per-track download status: key = "artist::name", value = "downloading" | "queued" | "completed" | "failed" */
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

	let missingCount = $derived(
		activeTab === 'top'
			? topTracks.filter(t => !t.in_library && !getStatus(t)).length
			: activeTab === 'similar'
				? similarTracks.filter(t => !t.in_library && !getStatus(t)).length
				: 0
	);

	async function loadTopTracks() {
		loading = true;
		try {
			const data = await fetch('/api/discovery/top-tracks?limit=50').then(r => r.json());
			topTracks = data.tracks || [];
		} catch (e) {
			addToast('Failed to load top tracks', 'error');
		} finally {
			loading = false;
		}
	}

	async function loadSimilarTracks() {
		loading = true;
		try {
			const data = await fetch('/api/discovery/similar-tracks?limit=30').then(r => r.json());
			similarTracks = data.tracks || [];
		} catch (e) {
			addToast('Failed to load similar tracks', 'error');
		} finally {
			loading = false;
		}
	}

	async function loadSimilarArtists() {
		loading = true;
		try {
			const data = await fetch('/api/discovery/similar-artists?limit=30').then(r => r.json());
			similarArtists = data.artists || [];
		} catch (e) {
			addToast('Failed to load similar artists', 'error');
		} finally {
			loading = false;
		}
	}

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
			// Poll job until done
			pollJob(data.job_id, key);
		} catch {
			trackStatus[key] = 'failed';
		}
	}

	async function pollJob(jobId, key) {
		const maxPolls = 180; // 6 minutes max
		for (let i = 0; i < maxPolls; i++) {
			await new Promise(r => setTimeout(r, 2000));
			try {
				const res = await fetch(`/api/jobs/${jobId}`);
				const job = await res.json();
				if (job.status === 'completed') {
					trackStatus[key] = 'completed';
					return;
				} else if (job.status === 'failed') {
					trackStatus[key] = 'failed';
					return;
				}
				// still running
			} catch {
				// network blip, keep polling
			}
		}
		trackStatus[key] = 'failed';
	}

	async function downloadAllMissing() {
		const items = activeTab === 'top' ? topTracks : similarTracks;
		const missing = items.filter(t => !t.in_library && !getStatus(t));
		if (!missing.length) return;

		bulkDownloading = true;
		// Mark all as queued
		for (const t of missing) {
			trackStatus[trackKey(t)] = 'queued';
		}

		try {
			const res = await fetch('/api/download/bulk', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					tracks: missing.map(t => ({ artist: t.artist, track: t.name }))
				})
			});
			const data = await res.json();
			if (data.job_id) {
				addToast(`Downloading ${missing.length} tracks`, 'success');
				// Poll bulk job for per-track updates
				pollBulkJob(data.job_id, missing);
			}
		} catch (e) {
			addToast('Bulk download failed', 'error');
			for (const t of missing) {
				trackStatus[trackKey(t)] = 'failed';
			}
		} finally {
			bulkDownloading = false;
		}
	}

	async function pollBulkJob(jobId, tracks) {
		const maxPolls = 300; // 10 minutes
		for (let i = 0; i < maxPolls; i++) {
			await new Promise(r => setTimeout(r, 2000));
			try {
				const res = await fetch(`/api/jobs/${jobId}`);
				const job = await res.json();

				// Update per-track status from job.tracks
				if (job.tracks) {
					try {
						const trackList = JSON.parse(job.tracks);
						for (const tj of trackList) {
							const key = `${tj.artist}::${tj.track}`.toLowerCase();
							if (tj.status === 'downloaded' || tj.status === 'downloading') {
								trackStatus[key] = 'completed';
							} else if (tj.status === 'failed') {
								trackStatus[key] = 'failed';
							} else if (tj.status === 'skipped') {
								trackStatus[key] = 'failed';
							}
							// pending stays as queued
						}
					} catch {}
				}

				if (job.status === 'completed' || job.status === 'failed') {
					return;
				}
			} catch {}
		}
	}

	function switchTab(tab) {
		activeTab = tab;
		if (tab === 'top' && !topTracks.length) loadTopTracks();
		if (tab === 'similar' && !similarTracks.length) loadSimilarTracks();
		if (tab === 'artists' && !similarArtists.length) loadSimilarArtists();
	}

	onMount(() => loadTopTracks());
</script>

<div class="max-w-6xl">
	<PageHeader title="Discover" color="var(--color-discover)">
		{#if missingCount > 0}
			<Button variant="success" size="sm" onclick={downloadAllMissing} loading={bulkDownloading}>
				<Download class="w-3.5 h-3.5" />
				Download {missingCount} Missing
			</Button>
		{/if}
	</PageHeader>

	<div class="flex gap-1.5 mb-6 overflow-x-auto">
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

	{#if loading}
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
	{:else if activeTab === 'top'}
		<Card padding="p-0">
			{#if topTracks.length}
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
								<td class="px-4 py-3 text-[var(--text-muted)] font-mono text-xs hidden md:table-cell">{t.listeners?.toLocaleString()}</td>
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
			{:else}
				<EmptyState title="No top tracks" description="Could not load Last.fm top charts. Check Last.fm API key in Settings." />
			{/if}
		</Card>
	{:else if activeTab === 'similar'}
		<Card padding="p-0">
			{#if similarTracks.length}
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
									{t.source_artist} - {t.source_track}
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
			{:else}
				<EmptyState title="No similar tracks" description="Star some tracks first to get similar track suggestions." />
			{/if}
		</Card>
	{:else if activeTab === 'artists'}
		<Card padding="p-0">
			{#if similarArtists.length}
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
			{:else}
				<EmptyState title="No similar artists" description="Star some tracks first to get artist suggestions." />
			{/if}
		</Card>
	{/if}
</div>
