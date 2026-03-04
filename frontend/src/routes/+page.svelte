<script>
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';
	import { formatSize, formatDuration } from '$lib/utils.js';
	import { addToast } from '$lib/stores.js';

	let stats = $state(null);
	let recent = $state([]);
	let scanning = $state(false);

	onMount(async () => {
		try {
			[stats, recent] = await Promise.all([
				api.getStats(),
				api.getRecent(10)
			]);
		} catch (e) {
			console.error('Failed to load dashboard:', e);
		}
	});

	async function scanLibrary() {
		scanning = true;
		try {
			const result = await api.scanLibrary();
			addToast('Library scan started', 'success');
		} catch (e) {
			addToast('Scan failed: ' + e.message, 'error');
		}
	}
</script>

<div class="max-w-6xl">
	<div class="flex items-center justify-between mb-6">
		<h1 class="text-2xl font-bold">Dashboard</h1>
		<button on:click={scanLibrary} disabled={scanning}
			class="px-4 py-2 bg-accent-600 hover:bg-accent-700 rounded-lg text-sm font-medium
				disabled:opacity-50 transition">
			{scanning ? 'Scanning...' : 'Scan Library'}
		</button>
	</div>

	{#if stats}
		<div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
			<div class="bg-gray-900 rounded-xl p-4 border border-gray-800">
				<p class="text-2xl font-bold">{stats.tracks.toLocaleString()}</p>
				<p class="text-sm text-gray-400">Tracks</p>
			</div>
			<div class="bg-gray-900 rounded-xl p-4 border border-gray-800">
				<p class="text-2xl font-bold">{stats.artists.toLocaleString()}</p>
				<p class="text-sm text-gray-400">Artists</p>
			</div>
			<div class="bg-gray-900 rounded-xl p-4 border border-gray-800">
				<p class="text-2xl font-bold">{stats.albums.toLocaleString()}</p>
				<p class="text-sm text-gray-400">Albums</p>
			</div>
			<div class="bg-gray-900 rounded-xl p-4 border border-gray-800">
				<p class="text-2xl font-bold">{formatSize(stats.total_size_bytes)}</p>
				<p class="text-sm text-gray-400">Total Size</p>
			</div>
		</div>

		{#if stats.formats && Object.keys(stats.formats).length}
			<div class="bg-gray-900 rounded-xl p-4 border border-gray-800 mb-8">
				<h2 class="text-sm font-medium text-gray-400 mb-3">Formats</h2>
				<div class="flex flex-wrap gap-2">
					{#each Object.entries(stats.formats) as [fmt, count]}
						<span class="px-3 py-1 bg-gray-800 rounded-full text-sm">
							{fmt.toUpperCase()} <span class="text-gray-400">{count}</span>
						</span>
					{/each}
				</div>
			</div>
		{/if}
	{:else}
		<div class="text-gray-500">Loading...</div>
	{/if}

	<div class="bg-gray-900 rounded-xl border border-gray-800">
		<h2 class="text-sm font-medium text-gray-400 p-4 border-b border-gray-800">Recent Additions</h2>
		{#if recent.length}
			<div class="divide-y divide-gray-800">
				{#each recent as track}
					<div class="px-4 py-3 flex items-center justify-between text-sm">
						<span>{track.title}</span>
						<span class="text-gray-500 text-xs">{track.created_at ? new Date(track.created_at).toLocaleDateString() : ''}</span>
					</div>
				{/each}
			</div>
		{:else}
			<p class="p-4 text-gray-500 text-sm">No tracks yet. Scan your library to get started.</p>
		{/if}
	</div>
</div>
