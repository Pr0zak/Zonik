<script>
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';
	import { addToast, playTrack as storePlayTrack } from '$lib/stores.js';
	import { formatDuration, coverUrl } from '$lib/utils.js';
	import { Heart, Music, Play, Upload, Shuffle, Search } from 'lucide-svelte';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Button from '../../components/ui/Button.svelte';
	import Skeleton from '../../components/ui/Skeleton.svelte';
	import EmptyState from '../../components/ui/EmptyState.svelte';
	import Modal from '../../components/ui/Modal.svelte';
	import Pagination from '../../components/ui/Pagination.svelte';

	let favorites = $state([]);
	let total = $state(0);
	let offset = $state(0);
	let limit = $state(25);
	let loading = $state(true);
	let showImport = $state(false);
	let importFile = $state(null);
	let importing = $state(false);
	let filterQuery = $state('');

	let filteredFavorites = $derived(
		filterQuery.trim()
			? favorites.filter(f =>
				(f.title || '').toLowerCase().includes(filterQuery.toLowerCase()) ||
				(f.artist || '').toLowerCase().includes(filterQuery.toLowerCase()) ||
				(f.album || '').toLowerCase().includes(filterQuery.toLowerCase())
			)
			: favorites
	);

	onMount(async () => {
		await loadFavorites();
	});

	async function loadFavorites() {
		loading = true;
		try {
			const data = await api.getFavorites(offset, limit);
			favorites = data.items;
			total = data.total;
		} catch (e) {
			console.error('Failed to load favorites:', e);
		} finally {
			loading = false;
		}
	}

	function handlePageChange(newOffset, newLimit) {
		offset = newOffset;
		limit = newLimit;
		loadFavorites();
	}

	async function unstar(fav) {
		if (!window.confirm(`Remove "${fav.title || fav.name}" from favorites?`)) return;
		try {
			if (fav.track_id) await api.unstar({ track_id: fav.track_id });
			else if (fav.album_id) await api.unstar({ album_id: fav.album_id });
			else if (fav.artist_id) await api.unstar({ artist_id: fav.artist_id });
			favorites = favorites.filter(f => f.id !== fav.id);
			total--;
		} catch { addToast('Failed to unstar', 'error'); }
	}

	function playTrack(fav) {
		if (fav.track_id) {
			const queue = favorites.filter(f => f.track_id).map(f => ({ id: f.track_id, title: f.title, artist: f.artist }));
			storePlayTrack({ id: fav.track_id, title: fav.title, artist: fav.artist }, queue);
		}
	}

	function playAllFavorites(shuffle = false) {
		const playable = favorites.filter(f => f.track_id).map(f => ({ id: f.track_id, title: f.title, artist: f.artist }));
		if (!playable.length) return;
		const queue = shuffle ? [...playable].sort(() => Math.random() - 0.5) : playable;
		storePlayTrack(queue[0], queue);
	}

	async function handleImport() {
		if (!importFile) return;
		importing = true;
		try {
			const text = await importFile.text();
			const tracks = JSON.parse(text);
			const result = await api.importFavorites(tracks);
			addToast(`Imported ${result.imported}, skipped ${result.skipped}, not found ${result.not_found}`, 'success');
			showImport = false;
			importFile = null;
			offset = 0;
			await loadFavorites();
		} catch (e) {
			addToast('Import failed: ' + e.message, 'error');
		} finally {
			importing = false;
		}
	}
</script>

<div class="max-w-6xl">
	<PageHeader
		title="Favorites"
		icon={Heart}
		color="var(--color-favorites)"
		subtitle={!loading && total ? `${total} starred tracks` : ''}>
		{#snippet actions()}
			{#if favorites.length}
				<div class="relative hidden sm:block">
					<Search class="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-disabled)]" />
					<input type="text" bind:value={filterQuery} placeholder="Filter page..."
						class="bg-[var(--surface-lowest)] ghost-border rounded-lg pl-8 pr-3 py-1.5 text-xs w-44 text-[var(--text-body)] placeholder-[var(--text-disabled)] focus:outline-none focus:border-[var(--border-focus)]" />
				</div>
				<Button variant="primary" size="sm" onclick={() => playAllFavorites(false)}>
					<Play class="w-3.5 h-3.5" fill="currentColor" /> Play All
				</Button>
				<Button variant="secondary" size="sm" onclick={() => playAllFavorites(true)}>
					<Shuffle class="w-3.5 h-3.5" /> Shuffle
				</Button>
			{/if}
			<Button variant="secondary" size="sm" onclick={() => showImport = true}>
				<Upload class="w-3.5 h-3.5" /> Import
			</Button>
		{/snippet}
	</PageHeader>

	{#if loading}
		<Card padding="p-0">
			<Skeleton variant="list-item" count={8} />
		</Card>
	{:else if favorites.length}
		<Card padding="p-0">
			<div class="divide-y divide-white/[0.03]">
				{#each filteredFavorites as fav, idx}
					<div class="flex items-center gap-3 px-4 py-2.5 hover:bg-[var(--surface-container-high)] transition-colors group">
						<span class="w-6 text-right text-xs font-mono text-[var(--text-disabled)] select-none">{offset + idx + 1}</span>
						<button class="flex items-center gap-3 flex-1 min-w-0 text-left" onclick={() => playTrack(fav)}>
							<div class="relative w-10 h-10 rounded-lg bg-[var(--surface-base)] overflow-hidden flex-shrink-0 ghost-border">
								{#if coverUrl(fav.cover_art)}
									<img src={coverUrl(fav.cover_art)} alt="" class="w-full h-full object-cover" loading="lazy" />
								{:else}
									<div class="flex items-center justify-center w-full h-full"
										style="background: radial-gradient(circle at 30% 30%, #2a1f2d, #141316 75%);">
										<Music class="w-4 h-4 text-[var(--color-favorites)]/60" />
									</div>
								{/if}
								{#if fav.track_id}
									<div class="absolute inset-0 bg-black/0 group-hover:bg-black/45 transition-colors flex items-center justify-center">
										<Play class="w-4 h-4 text-white opacity-0 group-hover:opacity-100 transition-opacity" fill="currentColor" />
									</div>
								{/if}
							</div>
							<div class="flex-1 min-w-0">
								<p class="text-sm font-medium text-[var(--text-primary)] truncate group-hover:text-white transition-colors">{fav.title || 'Unknown'}</p>
								<p class="text-xs text-[var(--text-muted)] truncate">
									{#if fav.artist}<span class="text-[var(--text-secondary)]">{fav.artist}</span>{/if}
									{#if fav.album}<span class="text-[var(--text-disabled)]"> &middot; {fav.album}</span>{/if}
								</p>
							</div>
							{#if fav.duration}
								<span class="text-xs text-[var(--text-muted)] font-mono hidden sm:block">{formatDuration(fav.duration)}</span>
							{/if}
						</button>
						<button onclick={() => unstar(fav)}
							class="p-2 min-w-[40px] min-h-[40px] flex items-center justify-center text-[var(--color-favorites)] hover:scale-110 transition-transform flex-shrink-0"
							title="Remove from favorites">
							<Heart class="w-4 h-4" fill="currentColor" />
						</button>
					</div>
				{/each}
			</div>
		</Card>

		<Pagination {total} {offset} {limit} onchange={handlePageChange} />
	{:else if total === 0}
		<EmptyState
			title="No favorites yet"
			description="Star tracks, albums, or artists from the Library page, or use Zonik-mobile.">
			{#snippet icon()}<Heart class="w-10 h-10" />{/snippet}
		</EmptyState>
	{/if}
</div>

<Modal bind:open={showImport} title="Import Favorites">
	{#snippet children()}
		<p class="text-sm text-[var(--text-secondary)] mb-4">
			Upload a JSON file with an array of tracks to import as favorites.
			Each entry should have <code class="text-xs bg-[var(--bg-primary)] px-1 py-0.5 rounded">title</code>,
			<code class="text-xs bg-[var(--bg-primary)] px-1 py-0.5 rounded">artist</code>, and optionally
			<code class="text-xs bg-[var(--bg-primary)] px-1 py-0.5 rounded">file_path</code>.
		</p>
		<input type="file" accept=".json"
			onchange={(e) => importFile = e.target.files[0]}
			class="w-full text-sm text-[var(--text-body)] file:mr-3 file:py-2 file:px-4 file:rounded-md file:border-0
				file:text-sm file:font-medium file:bg-[var(--surface-container-high)] file:text-[var(--text-primary)]
				file:cursor-pointer hover:file:bg-[var(--surface-container)]" />
	{/snippet}
	{#snippet footer()}
		<div class="flex justify-end">
			<Button variant="primary" size="sm" loading={importing} disabled={!importFile} onclick={handleImport}>
				<Upload class="w-3.5 h-3.5" /> Import
			</Button>
		</div>
	{/snippet}
</Modal>
