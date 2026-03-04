<script>
	import { onMount } from 'svelte';
	import { addToast } from '$lib/stores.js';

	let activeTab = $state('top');
	let topTracks = $state([]);
	let similarTracks = $state([]);
	let similarArtists = $state([]);
	let loading = $state(false);

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

	async function downloadTrack(artist, track) {
		try {
			await fetch('/api/download/trigger', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ artist, track })
			});
			addToast(`Downloading: ${artist} - ${track}`, 'success');
		} catch (e) {
			addToast('Download failed', 'error');
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
	<h1 class="text-2xl font-bold mb-6">Discover</h1>

	<div class="flex gap-2 mb-6">
		{#each [['top', 'Top Tracks'], ['similar', 'Similar Tracks'], ['artists', 'Similar Artists']] as [key, label]}
			<button on:click={() => switchTab(key)}
				class="px-4 py-2 rounded-lg text-sm font-medium transition
					{activeTab === key ? 'bg-accent-600 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'}">
				{label}
			</button>
		{/each}
	</div>

	{#if loading}
		<div class="text-gray-400 p-8 text-center">Loading...</div>
	{:else if activeTab === 'top'}
		<div class="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
			<table class="w-full text-sm">
				<thead>
					<tr class="border-b border-gray-800 text-gray-400 text-left">
						<th class="px-4 py-3 w-8">#</th>
						<th class="px-4 py-3">Track</th>
						<th class="px-4 py-3">Artist</th>
						<th class="px-4 py-3 hidden md:table-cell">Listeners</th>
						<th class="px-4 py-3">Status</th>
						<th class="px-4 py-3"></th>
					</tr>
				</thead>
				<tbody class="divide-y divide-gray-800/50">
					{#each topTracks as t, i}
						<tr class="hover:bg-gray-800/50">
							<td class="px-4 py-3 text-gray-500">{i + 1}</td>
							<td class="px-4 py-3 font-medium">{t.name}</td>
							<td class="px-4 py-3 text-gray-400">{t.artist}</td>
							<td class="px-4 py-3 text-gray-400 hidden md:table-cell">{t.listeners?.toLocaleString()}</td>
							<td class="px-4 py-3">
								{#if t.in_library}
									<span class="px-2 py-0.5 bg-green-900/50 text-green-400 rounded text-xs">In Library</span>
								{:else}
									<span class="px-2 py-0.5 bg-yellow-900/50 text-yellow-400 rounded text-xs">Missing</span>
								{/if}
							</td>
							<td class="px-4 py-3">
								{#if !t.in_library}
									<button on:click={() => downloadTrack(t.artist, t.name)}
										class="px-3 py-1 bg-green-700 hover:bg-green-800 rounded text-xs transition">
										Download
									</button>
								{/if}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{:else if activeTab === 'similar'}
		<div class="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
			{#if similarTracks.length}
				<table class="w-full text-sm">
					<thead>
						<tr class="border-b border-gray-800 text-gray-400 text-left">
							<th class="px-4 py-3">Track</th>
							<th class="px-4 py-3">Artist</th>
							<th class="px-4 py-3 hidden md:table-cell">Similar to</th>
							<th class="px-4 py-3">Status</th>
							<th class="px-4 py-3"></th>
						</tr>
					</thead>
					<tbody class="divide-y divide-gray-800/50">
						{#each similarTracks as t}
							<tr class="hover:bg-gray-800/50">
								<td class="px-4 py-3 font-medium">{t.name}</td>
								<td class="px-4 py-3 text-gray-400">{t.artist}</td>
								<td class="px-4 py-3 text-gray-500 text-xs hidden md:table-cell">
									{t.source_artist} - {t.source_track}
								</td>
								<td class="px-4 py-3">
									{#if t.in_library}
										<span class="px-2 py-0.5 bg-green-900/50 text-green-400 rounded text-xs">In Library</span>
									{:else}
										<span class="px-2 py-0.5 bg-yellow-900/50 text-yellow-400 rounded text-xs">Missing</span>
									{/if}
								</td>
								<td class="px-4 py-3">
									{#if !t.in_library}
										<button on:click={() => downloadTrack(t.artist, t.name)}
											class="px-3 py-1 bg-green-700 hover:bg-green-800 rounded text-xs transition">
											Download
										</button>
									{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{:else}
				<p class="p-6 text-gray-400">Star some tracks first to get similar track suggestions.</p>
			{/if}
		</div>
	{:else if activeTab === 'artists'}
		<div class="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
			{#if similarArtists.length}
				<div class="divide-y divide-gray-800/50">
					{#each similarArtists as a}
						<div class="px-4 py-3 flex items-center justify-between hover:bg-gray-800/50">
							<div>
								<span class="font-medium">{a.name}</span>
								<span class="text-xs text-gray-500 ml-2">similar to {a.source_artist}</span>
							</div>
							<div class="flex items-center gap-2">
								{#if a.in_library}
									<span class="px-2 py-0.5 bg-green-900/50 text-green-400 rounded text-xs">In Library</span>
								{:else}
									<span class="px-2 py-0.5 bg-yellow-900/50 text-yellow-400 rounded text-xs">New</span>
								{/if}
							</div>
						</div>
					{/each}
				</div>
			{:else}
				<p class="p-6 text-gray-400">Star some tracks first to get artist suggestions.</p>
			{/if}
		</div>
	{/if}
</div>
