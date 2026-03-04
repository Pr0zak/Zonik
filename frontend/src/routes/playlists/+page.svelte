<script>
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';

	let playlists = $state([]);

	onMount(async () => {
		try {
			playlists = await api.getPlaylists();
		} catch (e) {
			console.error('Failed to load playlists:', e);
		}
	});
</script>

<div class="max-w-6xl">
	<div class="flex items-center justify-between mb-6">
		<h1 class="text-2xl font-bold">Playlists</h1>
	</div>

	{#if playlists.length}
		<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
			{#each playlists as playlist}
				<div class="bg-gray-900 rounded-xl border border-gray-800 p-4 hover:border-gray-700 transition cursor-pointer">
					<h3 class="font-medium">{playlist.name}</h3>
					<p class="text-sm text-gray-400 mt-1">{playlist.track_count} tracks</p>
				</div>
			{/each}
		</div>
	{:else}
		<div class="bg-gray-900 rounded-xl border border-gray-800 p-6">
			<p class="text-gray-400">No playlists yet.</p>
		</div>
	{/if}
</div>
