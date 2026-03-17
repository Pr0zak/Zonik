<script>
	import { addToast } from '$lib/stores.js';
	import { api } from '$lib/api.js';
	import { Loader2, RefreshCw, ListMusic, ExternalLink, Download, Check, X, ChevronLeft, Music, Play, Pause } from 'lucide-svelte';
	import Card from '../../components/ui/Card.svelte';
	import Button from '../../components/ui/Button.svelte';
	import Skeleton from '../../components/ui/Skeleton.svelte';
	import EmptyState from '../../components/ui/EmptyState.svelte';
	import Badge from '../../components/ui/Badge.svelte';

	let { getArtwork, playPreview, previewKey } = $props();

	let playlists = $state([]);
	let loading = $state(false);
	let queries = $state([]);

	// Track detail view
	let selectedPlaylist = $state(null);
	let playlistTracks = $state([]);
	let tracksLoading = $state(false);
	let trackStatus = $state({});

	function trackKey(t) {
		return `${t.artist}::${t.title}`.toLowerCase();
	}

	async function loadPlaylists() {
		loading = true;
		selectedPlaylist = null;
		playlistTracks = [];
		try {
			const data = await api.discoverPlaylists(20);
			playlists = data.playlists || [];
			queries = data.queries || [];
			if (playlists.length > 1) {
				try {
					const ranked = await api.aiRankPlaylists(playlists);
					if (ranked.playlists) playlists = ranked.playlists;
				} catch {}
			}
		} catch (e) { addToast('Failed to discover playlists: ' + e.message, 'error'); }
		finally { loading = false; }
	}

	async function openPlaylist(pl) {
		selectedPlaylist = pl;
		tracksLoading = true;
		playlistTracks = [];
		try {
			const data = await api.fetchExternalPlaylist(pl.id, pl.source);
			if (data.error) {
				addToast('Failed to fetch playlist: ' + data.error, 'error');
				selectedPlaylist = null;
				return;
			}
			playlistTracks = data.tracks || [];
		} catch (e) {
			addToast('Failed to fetch playlist: ' + e.message, 'error');
			selectedPlaylist = null;
		} finally {
			tracksLoading = false;
		}
	}

	function goBack() {
		selectedPlaylist = null;
		playlistTracks = [];
	}

	async function downloadTrack(t) {
		const key = trackKey(t);
		trackStatus[key] = 'downloading';
		try {
			const res = await fetch('/api/download/trigger', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ artist: t.artist, track: t.title, source: 'playlist' }),
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
		const missing = playlistTracks.filter(t => !t.in_library && !trackStatus[trackKey(t)]);
		if (!missing.length) return;

		for (const t of missing) trackStatus[trackKey(t)] = 'queued';

		let started = 0;
		for (const t of missing) {
			try {
				const res = await fetch('/api/download/trigger', {
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({ artist: t.artist, track: t.title, source: 'playlist' }),
				});
				const data = await res.json();
				if (data.error) {
					trackStatus[trackKey(t)] = 'failed';
					continue;
				}
				trackStatus[trackKey(t)] = 'downloading';
				pollJob(data.job_id, trackKey(t));
				started++;
			} catch {
				trackStatus[trackKey(t)] = 'failed';
			}
		}
		addToast(`Queued ${started} downloads`, 'success');
	}

	let missingCount = $derived(
		playlistTracks.filter(t => !t.in_library && !trackStatus[trackKey(t)]).length
	);
	let inLibraryCount = $derived(
		playlistTracks.filter(t => t.in_library).length
	);
</script>

{#if selectedPlaylist}
	<!-- Track detail view -->
	<div class="flex items-center gap-3 mb-4">
		<Button variant="ghost" onclick={goBack}>
			<ChevronLeft class="w-4 h-4" />
			Back
		</Button>
		<div class="flex items-center gap-3 flex-1 min-w-0">
			{#if selectedPlaylist.image_url}
				<img src={selectedPlaylist.image_url} alt="" class="w-10 h-10 rounded-lg object-cover flex-shrink-0" />
			{/if}
			<div class="min-w-0">
				<p class="text-sm font-medium text-[var(--text-primary)] truncate">{selectedPlaylist.name}</p>
				<p class="text-xs text-[var(--text-muted)]">
					{selectedPlaylist.owner} &middot; <span class="capitalize">{selectedPlaylist.source.replace('_', ' ')}</span>
				</p>
			</div>
		</div>
		{#if !tracksLoading && playlistTracks.length}
			<span class="text-xs text-[var(--text-muted)] flex-shrink-0">
				{inLibraryCount}/{playlistTracks.length} in library
			</span>
			{#if missingCount > 0}
				<Button variant="success" size="sm" onclick={downloadAllMissing}>
					<Download class="w-3.5 h-3.5" />
					Download {missingCount} missing
				</Button>
			{/if}
		{/if}
	</div>

	{#if tracksLoading}
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
	{:else if playlistTracks.length}
		<Card padding="p-0">
			<div class="overflow-x-auto">
				<table class="w-full text-sm">
					<thead>
						<tr class="border-b border-[var(--border-subtle)] text-[var(--text-muted)] text-xs">
							<th class="px-4 py-2 text-left w-10">#</th>
							<th class="px-4 py-2 text-left">Track</th>
							<th class="px-4 py-2 text-left hidden sm:table-cell">Artist</th>
							<th class="px-4 py-2 text-right w-32">Status</th>
						</tr>
					</thead>
					<tbody>
						{#each playlistTracks as t, i}
							{@const status = trackStatus[trackKey(t)]}
							{@const art = getArtwork(t.artist, t.title)}
							{@const tKey = trackKey(t)}
							<tr class="border-b border-[var(--border-subtle)] last:border-0 transition-colors {status === 'completed' ? 'bg-green-500/5' : status === 'failed' ? 'bg-red-500/5' : 'hover:bg-[var(--bg-hover)]'}">
								<td class="px-4 py-3 text-[var(--text-disabled)] font-mono text-xs">{i + 1}</td>
								<td class="px-4 py-3">
									<div class="flex items-center gap-3">
										<button onclick={() => playPreview(art?.preview, tKey)}
											class="relative w-8 h-8 rounded overflow-hidden flex-shrink-0 group" disabled={!art?.preview}>
											{#if art?.image}
												<img src={art.image} alt="" class="w-full h-full object-cover" />
											{:else}
												<div class="w-full h-full bg-[var(--bg-tertiary)] flex items-center justify-center">
													<Music class="w-3.5 h-3.5 text-[var(--text-disabled)]" />
												</div>
											{/if}
											{#if art?.preview}
												<div class="absolute inset-0 bg-black/50 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity {previewKey === tKey ? 'opacity-100' : ''}">
													{#if previewKey === tKey}
														<Pause class="w-3.5 h-3.5 text-white" />
													{:else}
														<Play class="w-3.5 h-3.5 text-white" />
													{/if}
												</div>
											{/if}
										</button>
										<div class="min-w-0">
											<span class="font-medium text-[var(--text-primary)] truncate block">{t.title}</span>
											<span class="text-xs text-[var(--text-muted)] truncate block sm:hidden">{t.artist}</span>
										</div>
									</div>
								</td>
								<td class="px-4 py-3 text-[var(--text-secondary)] hidden sm:table-cell">{t.artist}</td>
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
			</div>
		</Card>
	{:else}
		<Card>
			<EmptyState title="No tracks found" description="This playlist appears to be empty." />
		</Card>
	{/if}

{:else}
	<!-- Playlist grid view -->
	<div class="flex items-center gap-3 mb-4">
		<Button variant="ghost" onclick={loadPlaylists} disabled={loading}>
			{#if loading}<Loader2 class="w-4 h-4 animate-spin" />{:else}<RefreshCw class="w-4 h-4" />{/if}
			Discover
		</Button>
		{#if queries.length}
			<span class="text-xs text-[var(--text-muted)]">Based on: {queries.join(', ')}</span>
		{/if}
	</div>

	{#if loading}
		<div class="grid grid-cols-1 md:grid-cols-2 gap-3">
			{#each Array(6) as _}
				<Skeleton class="h-20 rounded-lg" />
			{/each}
		</div>
	{:else if playlists.length}
		<div class="grid grid-cols-1 md:grid-cols-2 gap-3">
			{#each playlists as pl}
				<button onclick={() => openPlaylist(pl)} class="block w-full text-left">
					<Card hover padding="p-3">
						<div class="flex items-center gap-3">
							{#if pl.image_url}
								<img src={pl.image_url} alt="" class="w-12 h-12 rounded-lg object-cover flex-shrink-0" />
							{:else}
								<div class="w-12 h-12 rounded-lg bg-[var(--bg-secondary)] flex items-center justify-center flex-shrink-0">
									<ListMusic class="w-5 h-5 text-[var(--text-disabled)]" />
								</div>
							{/if}
							<div class="flex-1 min-w-0">
								<p class="text-sm font-medium text-[var(--text-primary)] truncate">{pl.name}</p>
								<p class="text-xs text-[var(--text-muted)] truncate">
									{pl.owner} &middot; {pl.track_count} tracks &middot;
									<span class="capitalize">{pl.source.replace('_', ' ')}</span>
								</p>
								{#if pl.matched_query}
									<span class="text-xs text-[var(--text-disabled)]">matched: {pl.matched_query}</span>
								{/if}
							</div>
							{#if pl.ai_score}
								<div class="flex flex-col items-end flex-shrink-0">
									<span class="text-xs font-mono {pl.ai_score >= 0.7 ? 'text-emerald-400' : pl.ai_score >= 0.4 ? 'text-amber-400' : 'text-[var(--text-muted)]'}">{Math.round(pl.ai_score * 100)}%</span>
									{#if pl.ai_reason}
										<span class="text-[9px] text-[var(--text-disabled)] max-w-28 truncate" title={pl.ai_reason}>{pl.ai_reason}</span>
									{/if}
								</div>
							{:else}
								<ExternalLink class="w-3.5 h-3.5 text-[var(--text-disabled)] flex-shrink-0" />
							{/if}
						</div>
					</Card>
				</button>
			{/each}
		</div>
	{:else}
		<Card>
			<EmptyState title="No playlists discovered" description="Click Discover to find playlists matching your library taste.">
				{#snippet icon()}<ListMusic class="w-12 h-12" />{/snippet}
			</EmptyState>
		</Card>
	{/if}
{/if}
