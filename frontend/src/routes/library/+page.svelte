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

	// Similar tracks modal
	let showSimilar = $state(false);
	let similarSource = $state(null);
	let similarTracks = $state([]);
	let similarLoading = $state(false);
	let similarTab = $state('lastfm'); // 'lastfm' or 'vibe'

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

	async function findSimilar(track, e) {
		e.stopPropagation();
		similarSource = track;
		showSimilar = true;
		similarTracks = [];
		similarLoading = true;
		similarTab = 'lastfm';
		await loadSimilarLastfm();
	}

	async function loadSimilarLastfm() {
		if (!similarSource?.artist) {
			similarTracks = [];
			similarLoading = false;
			return;
		}
		similarLoading = true;
		try {
			const data = await api.getSimilarTracks(similarSource.artist, similarSource.title);
			similarTracks = data.tracks || [];
		} catch (e) {
			addToast('Failed to find similar tracks', 'error');
			similarTracks = [];
		} finally {
			similarLoading = false;
		}
	}

	async function loadSimilarVibe() {
		if (!similarSource?.id) {
			similarTracks = [];
			similarLoading = false;
			return;
		}
		similarLoading = true;
		try {
			const data = await api.echoMatch(similarSource.id);
			similarTracks = (data.tracks || []).map(t => ({
				name: t.title,
				artist: t.artist,
				in_library: true,
				track_id: t.id,
				match: t.similarity,
			}));
		} catch (e) {
			similarTracks = [];
		} finally {
			similarLoading = false;
		}
	}

	async function switchTab(tab) {
		similarTab = tab;
		if (tab === 'lastfm') await loadSimilarLastfm();
		else await loadSimilarVibe();
	}

	async function downloadSimilar(t) {
		try {
			await fetch('/api/download/trigger', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ artist: t.artist, track: t.name })
			});
			addToast(`Downloading: ${t.artist} - ${t.name}`, 'success');
		} catch (e) {
			addToast('Download failed', 'error');
		}
	}

	async function downloadAllMissing() {
		const missing = similarTracks.filter(t => !t.in_library);
		if (!missing.length) return;
		try {
			await fetch('/api/download/bulk', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					tracks: missing.map(t => ({ artist: t.artist, track: t.name }))
				})
			});
			addToast(`Downloading ${missing.length} tracks`, 'success');
		} catch (e) {
			addToast('Bulk download failed', 'error');
		}
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
					<th class="px-4 py-3 w-10"></th>
				</tr>
			</thead>
			<tbody class="divide-y divide-gray-800/50">
				{#each tracks as track}
					<tr class="hover:bg-gray-800/50 cursor-pointer transition group"
						on:click={() => playTrack(track)}>
						<td class="px-4 py-3 font-medium">{track.title}</td>
						<td class="px-4 py-3 text-gray-400">{track.artist || '-'}</td>
						<td class="px-4 py-3 text-gray-400 hidden md:table-cell">{track.album || '-'}</td>
						<td class="px-4 py-3 text-gray-400 hidden lg:table-cell">{formatDuration(track.duration)}</td>
						<td class="px-4 py-3 hidden lg:table-cell">
							<span class="px-2 py-0.5 bg-gray-800 rounded text-xs uppercase">{track.format || '-'}</span>
						</td>
						<td class="px-4 py-3">
							<button on:click={(e) => findSimilar(track, e)}
								title="Find similar tracks"
								class="opacity-0 group-hover:opacity-100 px-2 py-1 bg-accent-600/80 hover:bg-accent-600
									rounded text-xs transition-opacity">
								Similar
							</button>
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

<!-- Similar Tracks Modal -->
{#if showSimilar}
	<div class="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4"
		on:click={() => showSimilar = false} role="dialog">
		<div class="bg-gray-900 border border-gray-700 rounded-xl max-w-2xl w-full max-h-[80vh] flex flex-col"
			on:click|stopPropagation role="document">
			<!-- Header -->
			<div class="p-4 border-b border-gray-800">
				<div class="flex items-center justify-between">
					<div>
						<h2 class="text-lg font-semibold">Find Similar</h2>
						<p class="text-sm text-gray-400">
							{similarSource?.title} - {similarSource?.artist}
						</p>
					</div>
					<button on:click={() => showSimilar = false}
						class="text-gray-500 hover:text-white text-xl px-2">x</button>
				</div>

				<!-- Tabs -->
				<div class="flex gap-1 mt-3">
					<button on:click={() => switchTab('lastfm')}
						class="px-3 py-1 rounded text-xs transition
							{similarTab === 'lastfm' ? 'bg-accent-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-white'}">
						Last.fm Similar
					</button>
					<button on:click={() => switchTab('vibe')}
						class="px-3 py-1 rounded text-xs transition
							{similarTab === 'vibe' ? 'bg-purple-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-white'}">
						Vibe Match
					</button>
				</div>
			</div>

			<!-- Content -->
			<div class="flex-1 overflow-y-auto p-4">
				{#if similarLoading}
					<p class="text-gray-400 text-center py-8">Searching for similar tracks...</p>
				{:else if similarTracks.length}
					<div class="space-y-1">
						{#each similarTracks as t}
							<div class="flex items-center justify-between px-3 py-2 rounded hover:bg-gray-800/50 text-sm">
								<div class="flex-1 min-w-0">
									<span class="font-medium">{t.name}</span>
									<span class="text-gray-400"> - {t.artist}</span>
								</div>
								<div class="flex items-center gap-2 ml-3 shrink-0">
									{#if t.match != null}
										<span class="text-xs text-gray-500">{Math.round((t.match || 0) * 100)}%</span>
									{/if}
									{#if t.in_library}
										<span class="px-2 py-0.5 bg-green-900/50 text-green-400 rounded text-xs">In Library</span>
									{:else}
										<button on:click={() => downloadSimilar(t)}
											class="px-2 py-0.5 bg-accent-600 hover:bg-accent-700 rounded text-xs transition">
											Download
										</button>
									{/if}
								</div>
							</div>
						{/each}
					</div>
				{:else}
					<p class="text-gray-500 text-center py-8">
						{similarTab === 'vibe' ? 'No vibe embeddings for this track yet. Run audio analysis first.' : 'No similar tracks found.'}
					</p>
				{/if}
			</div>

			<!-- Footer -->
			{#if similarTracks.some(t => !t.in_library)}
				<div class="p-4 border-t border-gray-800 flex items-center justify-between">
					<span class="text-xs text-gray-400">
						{similarTracks.filter(t => !t.in_library).length} not in library
					</span>
					<button on:click={downloadAllMissing}
						class="px-4 py-1.5 bg-green-700 hover:bg-green-800 rounded text-xs font-medium transition">
						Download All Missing
					</button>
				</div>
			{/if}
		</div>
	</div>
{/if}
