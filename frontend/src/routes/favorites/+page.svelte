<script>
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';
	import { currentTrack, addToast } from '$lib/stores.js';
	import { formatDuration } from '$lib/utils.js';
	import { Heart, Music, Play, Upload, ChevronLeft, ChevronRight } from 'lucide-svelte';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Button from '../../components/ui/Button.svelte';
	import Skeleton from '../../components/ui/Skeleton.svelte';
	import EmptyState from '../../components/ui/EmptyState.svelte';
	import Modal from '../../components/ui/Modal.svelte';

	let favorites = $state([]);
	let total = $state(0);
	let offset = $state(0);
	let limit = $state(25);
	const limitOptions = [25, 50, 100, 200];
	let loading = $state(true);
	let showImport = $state(false);
	let importFile = $state(null);
	let importing = $state(false);

	function coverUrl(id) {
		if (!id) return null;
		return `/rest/getCoverArt?id=${id}`;
	}

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

	function prevPage() {
		offset = Math.max(0, offset - limit);
		loadFavorites();
	}

	function nextPage() {
		if (offset + limit < total) {
			offset += limit;
			loadFavorites();
		}
	}

	async function unstar(fav) {
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
			$currentTrack = { id: fav.track_id, title: fav.title, artist: fav.artist };
		}
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
	<PageHeader title="Favorites" color="var(--color-favorites)">
		{#if !loading && total}
			<span class="text-sm text-[var(--text-muted)] font-mono">{total} total</span>
		{/if}
		<Button variant="secondary" size="sm" onclick={() => showImport = true}>
			<Upload class="w-3.5 h-3.5" /> Import
		</Button>
	</PageHeader>

	{#if loading}
		<div class="space-y-2">
			{#each Array(8) as _}
				<Skeleton class="h-16 rounded-lg" />
			{/each}
		</div>
	{:else if favorites.length}
		<Card padding="p-0">
			<div class="divide-y divide-[var(--border-subtle)]">
				{#each favorites as fav}
					<div class="flex items-center gap-3 px-4 py-3 hover:bg-[var(--bg-hover)] transition-colors group">
						<button class="flex items-center gap-3 flex-1 min-w-0 text-left" onclick={() => playTrack(fav)}>
							<div class="relative w-10 h-10 rounded bg-[var(--bg-secondary)] overflow-hidden flex-shrink-0">
								{#if coverUrl(fav.cover_art)}
									<img src={coverUrl(fav.cover_art)} alt="" class="w-full h-full object-cover" loading="lazy" />
								{:else}
									<div class="flex items-center justify-center w-full h-full">
										<Music class="w-4 h-4 text-[var(--text-disabled)]" />
									</div>
								{/if}
								{#if fav.track_id}
									<div class="absolute inset-0 bg-black/0 group-hover:bg-black/40 transition-colors flex items-center justify-center">
										<Play class="w-5 h-5 text-white opacity-0 group-hover:opacity-100 transition-opacity" />
									</div>
								{/if}
							</div>
							<div class="flex-1 min-w-0">
								<p class="text-sm font-medium text-[var(--text-primary)] truncate">{fav.title || 'Unknown'}</p>
								<p class="text-xs text-[var(--text-muted)] truncate">
									{#if fav.artist}{fav.artist}{/if}
									{#if fav.album}<span class="text-[var(--text-disabled)]"> &middot; {fav.album}</span>{/if}
								</p>
							</div>
							{#if fav.duration}
								<span class="text-xs text-[var(--text-muted)] font-mono hidden sm:block">{formatDuration(fav.duration)}</span>
							{/if}
						</button>
						<button onclick={() => unstar(fav)}
							class="p-1.5 text-red-400 hover:text-red-300 transition-colors flex-shrink-0">
							<Heart class="w-4 h-4" fill="currentColor" />
						</button>
					</div>
				{/each}
			</div>
		</Card>

		<div class="flex justify-center items-center gap-3 mt-4">
			{#if total > limit}
				<Button variant="secondary" size="sm" disabled={offset === 0} onclick={prevPage}>
					<ChevronLeft class="w-4 h-4" /> Prev
				</Button>
				<span class="text-sm text-[var(--text-muted)] font-mono">
					{offset + 1}-{Math.min(offset + limit, total)} of {total}
				</span>
				<Button variant="secondary" size="sm" disabled={offset + limit >= total} onclick={nextPage}>
					Next <ChevronRight class="w-4 h-4" />
				</Button>
			{/if}
			<select value={limit}
				onchange={(e) => { limit = parseInt(e.target.value); offset = 0; loadFavorites(); }}
				class="bg-[var(--bg-secondary)] border border-[var(--border-interactive)] rounded-md px-2 py-1 text-xs text-[var(--text-body)] focus:outline-none">
				{#each limitOptions as opt}
					<option value={opt} selected={opt === limit}>{opt} / page</option>
				{/each}
			</select>
		</div>
	{:else if total === 0}
		<Card>
			<EmptyState
				title="No favorites yet"
				description="Star tracks, albums, or artists from the Library page, or use Symfonium."
			>
				{#snippet icon()}<Heart class="w-10 h-10" />{/snippet}
			</EmptyState>
		</Card>
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
				file:text-sm file:font-medium file:bg-[var(--bg-hover)] file:text-[var(--text-primary)]
				file:cursor-pointer hover:file:bg-[var(--bg-tertiary)]" />
	{/snippet}
	{#snippet footer()}
		<div class="flex justify-end">
			<Button variant="primary" size="sm" loading={importing} disabled={!importFile} onclick={handleImport}>
				<Upload class="w-3.5 h-3.5" /> Import
			</Button>
		</div>
	{/snippet}
</Modal>
