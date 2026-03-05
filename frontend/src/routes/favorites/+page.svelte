<script>
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';
	import { currentTrack } from '$lib/stores.js';
	import { Heart } from 'lucide-svelte';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Skeleton from '../../components/ui/Skeleton.svelte';
	import EmptyState from '../../components/ui/EmptyState.svelte';

	let favorites = $state([]);
	let loading = $state(true);

	onMount(async () => {
		try {
			favorites = await api.getFavorites();
		} catch (e) {
			console.error('Failed to load favorites:', e);
		} finally {
			loading = false;
		}
	});
</script>

<div class="max-w-6xl">
	<PageHeader title="Favorites" color="var(--color-favorites)" />

	{#if loading}
		<Card padding="p-0">
			<div class="divide-y divide-[var(--border-subtle)]">
				{#each Array(8) as _}
					<div class="px-4 py-3 flex items-center justify-between">
						<Skeleton class="h-4 w-48" />
						<Skeleton class="h-3 w-20" />
					</div>
				{/each}
			</div>
		</Card>
	{:else if favorites.length}
		<Card padding="p-0">
			<div class="divide-y divide-[var(--border-subtle)]">
				{#each favorites as fav}
					<!-- svelte-ignore a11y_click_events_have_key_events -->
					<!-- svelte-ignore a11y_no_static_element_interactions -->
					<div class="px-4 py-3 flex items-center justify-between hover:bg-[var(--bg-hover)] transition-colors cursor-pointer"
						onclick={() => { if (fav.track_id) $currentTrack = { id: fav.track_id, title: fav.track_title }; }}>
						<div class="flex items-center gap-3">
							<Heart class="w-4 h-4 text-red-400/60" />
							<span class="text-sm text-[var(--text-body)]">{fav.track_title || fav.album_id || fav.artist_id}</span>
						</div>
						<span class="text-xs text-[var(--text-muted)] font-mono">{fav.starred_at ? new Date(fav.starred_at).toLocaleDateString() : ''}</span>
					</div>
				{/each}
			</div>
		</Card>
	{:else}
		<Card>
			<EmptyState
				title="No favorites yet"
				description="Star tracks in Symfonium or the library to see them here."
			>
				{#snippet icon()}<Heart class="w-10 h-10" />{/snippet}
			</EmptyState>
		</Card>
	{/if}
</div>
