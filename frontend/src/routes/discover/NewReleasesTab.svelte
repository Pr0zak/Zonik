<script>
	import { onDestroy } from 'svelte';
	import { addToast } from '$lib/stores.js';
	import { downloadAndPoll } from '$lib/download.js';
	import { Loader2, RefreshCw, Download, Check, X, Music, Disc3, ExternalLink } from 'lucide-svelte';
	import Card from '../../components/ui/Card.svelte';
	import Button from '../../components/ui/Button.svelte';
	import Badge from '../../components/ui/Badge.svelte';
	import Skeleton from '../../components/ui/Skeleton.svelte';
	import EmptyState from '../../components/ui/EmptyState.svelte';

	let { trackStatus = $bindable({}) } = $props();

	let tracks = $state([]);
	let loading = $state(false);
	let fetchedAt = $state(null);
	let cached = $state(false);
	let errorMessage = $state(null);
	let bulkDownloading = $state(false);
	let groupByAlbum = $state(true);

	let _destroyed = false;
	onDestroy(() => { _destroyed = true; });

	function trackKey(t) {
		return `${t.artist}::${t.track}`.toLowerCase();
	}

	let inLibraryCount = $derived(tracks.filter(t => t.in_library).length);
	let missingCount = $derived(
		tracks.filter(t => !t.in_library && !trackStatus[trackKey(t)]).length
	);
	let total = $derived(tracks.length);

	let groupedByAlbum = $derived.by(() => {
		const groups = new Map();
		for (const t of tracks) {
			const key = t.album_id || `${t.album}::${t.artist}`;
			if (!groups.has(key)) {
				groups.set(key, {
					album: t.album,
					artist: t.artist,
					year: t.year,
					cover_url: t.cover_url,
					spotify_url: t.spotify_url,
					release_date: t.release_date,
					tracks: [],
				});
			}
			groups.get(key).tracks.push(t);
		}
		return [...groups.values()];
	});

	async function load() {
		loading = true;
		errorMessage = null;
		try {
			const data = await fetch('/api/discovery/new-releases').then(r => r.json());
			if (data.error) {
				errorMessage = data.error;
				tracks = [];
			} else {
				tracks = data.tracks || [];
				fetchedAt = data.fetched_at;
				cached = !!data.cached;
			}
		} catch (e) {
			errorMessage = 'Failed to load new releases';
			addToast('Failed to load new releases', 'error');
		} finally {
			loading = false;
		}
	}

	async function downloadOne(t) {
		const key = trackKey(t);
		await downloadAndPoll({
			artist: t.artist,
			track: t.track,
			source: 'new-releases',
			key,
			onStatus: (k, s) => { trackStatus[k] = s; },
			isDestroyed: () => _destroyed,
		});
	}

	async function downloadAllMissing() {
		const missing = tracks.filter(t => !t.in_library && !trackStatus[trackKey(t)]);
		if (!missing.length) return;
		bulkDownloading = true;
		for (const t of missing) trackStatus[trackKey(t)] = 'queued';
		let started = 0;
		for (const t of missing) {
			try {
				const res = await fetch('/api/download/trigger', {
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({ artist: t.artist, track: t.track, source: 'new-releases' }),
				});
				const data = await res.json();
				if (data.error) { trackStatus[trackKey(t)] = 'failed'; continue; }
				trackStatus[trackKey(t)] = 'downloading';
				started++;
			} catch {
				trackStatus[trackKey(t)] = 'failed';
			}
		}
		addToast(`Queued ${started} downloads`, 'success');
		bulkDownloading = false;
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

	$effect(() => { if (!tracks.length && !loading && !errorMessage) load(); });
</script>

{#snippet trackRow(t)}
	{@const status = trackStatus[trackKey(t)]}
	<div class="px-4 py-3 flex items-center gap-3 hover:bg-[var(--surface-container-high)] transition-colors
		{status === 'completed' ? 'bg-green-500/5' : ''}
		{status === 'failed' ? 'bg-red-500/5' : ''}">
		<div class="flex-shrink-0 w-10 h-10 rounded overflow-hidden bg-[var(--surface-container-high)]">
			{#if t.cover_url}
				<img src={t.cover_url} alt="" class="w-full h-full object-cover" loading="lazy" />
			{:else}
				<div class="w-full h-full flex items-center justify-center">
					<Music class="w-4 h-4 text-[var(--text-disabled)]" />
				</div>
			{/if}
		</div>
		<div class="flex-1 min-w-0">
			<div class="font-medium text-sm text-[var(--text-primary)] truncate">{t.track}</div>
			<div class="text-xs text-[var(--text-secondary)] truncate">
				{t.artist}
				{#if t.album}
					<span class="text-[var(--text-muted)]"> &middot; {t.album}</span>
				{/if}
				{#if t.year}
					<span class="text-[var(--text-disabled)]"> &middot; {t.year}</span>
				{/if}
			</div>
		</div>
		<div class="flex items-center gap-2 flex-shrink-0">
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
					<button onclick={() => downloadOne(t)}
						class="text-[var(--text-muted)] hover:text-white text-xs underline">retry</button>
				</span>
			{:else if status === 'downloading' || status === 'queued'}
				<span class="inline-flex items-center gap-1.5 text-blue-400 text-xs font-medium">
					<Loader2 class="w-3.5 h-3.5 animate-spin" />
					{status === 'queued' ? 'Queued' : 'Downloading'}
				</span>
			{:else}
				<Button variant="success" size="sm" onclick={() => downloadOne(t)}>
					<Download class="w-3 h-3" />
					Get
				</Button>
			{/if}
		</div>
	</div>
{/snippet}

<!-- Header / actions -->
<Card padding="p-4" class="mb-4">
	<div class="flex flex-wrap items-center gap-3">
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
					{total} tracks &middot; {groupedByAlbum.length} albums
					{#if fetchedAt}
						<span class="mx-1">&middot;</span> fetched {formatAge(fetchedAt)}{cached ? ' (cached)' : ''}
					{/if}
				</div>
				<label class="flex items-center gap-1.5 text-xs text-[var(--text-muted)] cursor-pointer ml-2">
					<input type="checkbox" bind:checked={groupByAlbum} class="rounded cursor-pointer" />
					Group by album
				</label>
			{:else}
				<span class="text-xs text-[var(--text-muted)]">Recent album drops from Spotify</span>
			{/if}
		</div>
		<div class="flex items-center gap-2">
			<Button variant="default" size="sm" onclick={load} loading={loading}>
				<RefreshCw class="w-3.5 h-3.5" />
				Refresh
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

{#if loading && !tracks.length}
	<Card padding="p-0">
		<div class="space-y-0.5">
			{#each Array(8) as _}
				<div class="px-4 py-4 flex items-center gap-4">
					<Skeleton class="h-10 w-10 rounded" />
					<div class="flex-1 space-y-1.5">
						<Skeleton class="h-4 w-40" />
						<Skeleton class="h-3 w-28" />
					</div>
					<Skeleton class="h-5 w-16 rounded-full" />
				</div>
			{/each}
		</div>
	</Card>
{:else if errorMessage}
	<Card>
		<EmptyState title="Spotify not configured" description={errorMessage === 'Spotify not configured' ? 'Add Spotify client credentials in Settings to enable New Releases.' : errorMessage}>
			{#snippet icon()}<Disc3 class="w-12 h-12" />{/snippet}
		</EmptyState>
	</Card>
{:else if !tracks.length}
	<Card>
		<EmptyState title="No new releases" description="Spotify didn't return any new releases. Try Refresh in a few hours.">
			{#snippet icon()}<Disc3 class="w-12 h-12" />{/snippet}
		</EmptyState>
	</Card>
{:else if groupByAlbum}
	<div class="space-y-4">
		{#each groupedByAlbum as g}
			<Card padding="p-0">
				<div class="px-4 py-3 flex items-center gap-3 bg-[var(--surface-container)]">
					{#if g.cover_url}
						<img src={g.cover_url} alt="" class="w-12 h-12 rounded object-cover flex-shrink-0" />
					{:else}
						<div class="w-12 h-12 rounded bg-[var(--surface-container-high)] flex items-center justify-center flex-shrink-0">
							<Disc3 class="w-5 h-5 text-[var(--text-disabled)]" />
						</div>
					{/if}
					<div class="flex-1 min-w-0">
						<div class="font-semibold text-sm text-[var(--text-primary)] truncate">{g.album}</div>
						<div class="text-xs text-[var(--text-secondary)] truncate">
							{g.artist}
							{#if g.release_date}
								<span class="text-[var(--text-disabled)]"> &middot; {g.release_date}</span>
							{/if}
							<span class="text-[var(--text-muted)]"> &middot; {g.tracks.length} tracks</span>
						</div>
					</div>
					{#if g.spotify_url}
						<a href={g.spotify_url} target="_blank" rel="noopener noreferrer"
							class="text-[var(--text-muted)] hover:text-[var(--color-discover)] transition-colors flex-shrink-0"
							title="Open on Spotify">
							<ExternalLink class="w-4 h-4" />
						</a>
					{/if}
				</div>
				<div class="space-y-0.5">
					{#each g.tracks as t}
						{@render trackRow(t)}
					{/each}
				</div>
			</Card>
		{/each}
	</div>
{:else}
	<Card padding="p-0">
		<div class="space-y-0.5">
			{#each tracks as t}
				{@render trackRow(t)}
			{/each}
		</div>
	</Card>
{/if}
