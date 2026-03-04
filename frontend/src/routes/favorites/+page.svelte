<script>
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';
	import { currentTrack } from '$lib/stores.js';

	let favorites = $state([]);

	onMount(async () => {
		try {
			favorites = await api.getFavorites();
		} catch (e) {
			console.error('Failed to load favorites:', e);
		}
	});
</script>

<div class="max-w-6xl">
	<h1 class="text-2xl font-bold mb-6">Favorites</h1>

	{#if favorites.length}
		<div class="bg-gray-900 rounded-xl border border-gray-800 divide-y divide-gray-800">
			{#each favorites as fav}
				<div class="px-4 py-3 flex items-center justify-between hover:bg-gray-800/50 transition cursor-pointer"
					on:click={() => { if (fav.track_id) $currentTrack = { id: fav.track_id, title: fav.track_title }; }}>
					<span class="text-sm">{fav.track_title || fav.album_id || fav.artist_id}</span>
					<span class="text-xs text-gray-400">{fav.starred_at ? new Date(fav.starred_at).toLocaleDateString() : ''}</span>
				</div>
			{/each}
		</div>
	{:else}
		<div class="bg-gray-900 rounded-xl border border-gray-800 p-6">
			<p class="text-gray-400">No favorites yet. Star tracks in Symfonium or the library.</p>
		</div>
	{/if}
</div>
