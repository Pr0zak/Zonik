<script>
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';
	import { currentTrack, addToast } from '$lib/stores.js';
	import { formatDuration, formatSize, debounce } from '$lib/utils.js';

	let tracks = $state([]);
	let total = $state(0);
	let search = $state('');
	let offset = $state(0);
	let limit = 50;
	let sort = $state('title');
	let order = $state('asc');

	async function loadTracks() {
		try {
			const result = await api.getTracks({ offset, limit, sort, order, search: search || undefined });
			tracks = result.tracks;
			total = result.total;
		} catch (e) {
			console.error('Failed to load tracks:', e);
		}
	}

	onMount(loadTracks);

	const debouncedSearch = debounce(() => {
		offset = 0;
		loadTracks();
	}, 300);

	function playTrack(track) {
		$currentTrack = track;
	}

	function toggleSort(col) {
		if (sort === col) {
			order = order === 'asc' ? 'desc' : 'asc';
		} else {
			sort = col;
			order = 'asc';
		}
		loadTracks();
	}
</script>

<div class="max-w-7xl">
	<div class="flex items-center justify-between mb-6">
		<h1 class="text-2xl font-bold">Library</h1>
		<div class="flex items-center gap-4">
			<input type="text" placeholder="Search tracks..."
				bind:value={search} on:input={debouncedSearch}
				class="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm w-64
					focus:outline-none focus:border-accent-500" />
			<span class="text-sm text-gray-400">{total.toLocaleString()} tracks</span>
		</div>
	</div>

	<div class="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
		<table class="w-full text-sm">
			<thead>
				<tr class="border-b border-gray-800 text-gray-400 text-left">
					<th class="px-4 py-3 cursor-pointer hover:text-white" on:click={() => toggleSort('title')}>Title</th>
					<th class="px-4 py-3 cursor-pointer hover:text-white" on:click={() => toggleSort('artist')}>Artist</th>
					<th class="px-4 py-3 cursor-pointer hover:text-white hidden md:table-cell" on:click={() => toggleSort('album')}>Album</th>
					<th class="px-4 py-3 hidden lg:table-cell">Duration</th>
					<th class="px-4 py-3 hidden lg:table-cell">Format</th>
				</tr>
			</thead>
			<tbody class="divide-y divide-gray-800/50">
				{#each tracks as track}
					<tr class="hover:bg-gray-800/50 cursor-pointer transition"
						on:click={() => playTrack(track)}>
						<td class="px-4 py-3 font-medium">{track.title}</td>
						<td class="px-4 py-3 text-gray-400">{track.artist || '-'}</td>
						<td class="px-4 py-3 text-gray-400 hidden md:table-cell">{track.album || '-'}</td>
						<td class="px-4 py-3 text-gray-400 hidden lg:table-cell">{formatDuration(track.duration)}</td>
						<td class="px-4 py-3 hidden lg:table-cell">
							<span class="px-2 py-0.5 bg-gray-800 rounded text-xs uppercase">{track.format || '-'}</span>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>

	{#if total > limit}
		<div class="flex justify-center gap-2 mt-4">
			<button on:click={() => { offset = Math.max(0, offset - limit); loadTracks(); }}
				disabled={offset === 0}
				class="px-3 py-1 bg-gray-800 rounded text-sm disabled:opacity-50">Prev</button>
			<span class="text-sm text-gray-400 py-1">
				{offset + 1}-{Math.min(offset + limit, total)} of {total}
			</span>
			<button on:click={() => { offset += limit; loadTracks(); }}
				disabled={offset + limit >= total}
				class="px-3 py-1 bg-gray-800 rounded text-sm disabled:opacity-50">Next</button>
		</div>
	{/if}
</div>
