<script>
	import { onMount } from 'svelte';
	import { formatSize, formatDuration } from '$lib/utils.js';

	let data = $state(null);

	onMount(async () => {
		try {
			data = await fetch('/api/library/stats/detailed').then(r => r.json());
		} catch (e) {
			console.error('Failed to load stats:', e);
		}
	});

	function barWidth(value, max) {
		if (!max) return '0%';
		return Math.max(2, (value / max) * 100) + '%';
	}

	let maxFmt = $derived(data ? Math.max(...Object.values(data.formats), 1) : 1);
	let maxArt = $derived(data?.top_artists?.length ? data.top_artists[0].count : 1);
	let maxGenre = $derived(data?.genres?.length ? data.genres[0].count : 1);
	let maxBr = $derived(data ? Math.max(...Object.values(data.bitrates), 1) : 1);
	let maxYear = $derived(data?.years?.length ? Math.max(...data.years.map(y => y.count)) : 1);
</script>

<div class="max-w-6xl">
	<h1 class="text-2xl font-bold mb-6">Library Stats</h1>

	{#if data}
		<!-- Overview Cards -->
		<div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4 mb-8">
			<div class="bg-gray-900 rounded-xl p-4 border border-gray-800">
				<p class="text-2xl font-bold">{data.tracks.toLocaleString()}</p>
				<p class="text-xs text-gray-400">Tracks</p>
			</div>
			<div class="bg-gray-900 rounded-xl p-4 border border-gray-800">
				<p class="text-2xl font-bold">{data.artists.toLocaleString()}</p>
				<p class="text-xs text-gray-400">Artists</p>
			</div>
			<div class="bg-gray-900 rounded-xl p-4 border border-gray-800">
				<p class="text-2xl font-bold">{data.albums.toLocaleString()}</p>
				<p class="text-xs text-gray-400">Albums</p>
			</div>
			<div class="bg-gray-900 rounded-xl p-4 border border-gray-800">
				<p class="text-2xl font-bold">{formatSize(data.total_size_bytes)}</p>
				<p class="text-xs text-gray-400">Total Size</p>
			</div>
			<div class="bg-gray-900 rounded-xl p-4 border border-gray-800">
				<p class="text-2xl font-bold">{formatDuration(data.total_duration_seconds)}</p>
				<p class="text-xs text-gray-400">Total Duration</p>
			</div>
			<div class="bg-gray-900 rounded-xl p-4 border border-gray-800">
				<p class="text-2xl font-bold">{data.favorites.toLocaleString()}</p>
				<p class="text-xs text-gray-400">Favorites</p>
			</div>
		</div>

		<!-- Processing Status -->
		<div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
			<div class="bg-gray-900 rounded-xl p-4 border border-gray-800">
				<h3 class="text-sm text-gray-400 mb-2">Audio Analyzed</h3>
				<p class="text-lg font-bold">{data.analyzed} <span class="text-sm text-gray-500">/ {data.tracks}</span></p>
				{#if data.tracks > 0}
					<div class="mt-2 h-1.5 bg-gray-800 rounded-full overflow-hidden">
						<div class="h-full bg-accent-600 rounded-full" style="width: {(data.analyzed / data.tracks * 100).toFixed(1)}%"></div>
					</div>
				{/if}
			</div>
			<div class="bg-gray-900 rounded-xl p-4 border border-gray-800">
				<h3 class="text-sm text-gray-400 mb-2">Vibe Embeddings</h3>
				<p class="text-lg font-bold">{data.embedded} <span class="text-sm text-gray-500">/ {data.tracks}</span></p>
				{#if data.tracks > 0}
					<div class="mt-2 h-1.5 bg-gray-800 rounded-full overflow-hidden">
						<div class="h-full bg-purple-600 rounded-full" style="width: {(data.embedded / data.tracks * 100).toFixed(1)}%"></div>
					</div>
				{/if}
			</div>
			<div class="bg-gray-900 rounded-xl p-4 border border-gray-800">
				<h3 class="text-sm text-gray-400 mb-2">Playlists</h3>
				<p class="text-lg font-bold">{data.playlists}</p>
			</div>
		</div>

		<div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
			<!-- Formats -->
			<div class="bg-gray-900 rounded-xl p-5 border border-gray-800">
				<h2 class="text-sm font-semibold text-gray-400 mb-4">Formats</h2>
				<div class="space-y-2">
					{#each Object.entries(data.formats).sort((a, b) => b[1] - a[1]) as [fmt, count]}
						<div class="flex items-center gap-3 text-sm">
							<span class="w-16 text-right text-gray-400 uppercase font-mono text-xs">{fmt}</span>
							<div class="flex-1 h-5 bg-gray-800 rounded overflow-hidden">
								<div class="h-full bg-accent-600/60 rounded" style="width: {barWidth(count, maxFmt)}"></div>
							</div>
							<span class="w-12 text-right text-gray-500 text-xs">{count}</span>
						</div>
					{/each}
				</div>
			</div>

			<!-- Top Artists -->
			<div class="bg-gray-900 rounded-xl p-5 border border-gray-800">
				<h2 class="text-sm font-semibold text-gray-400 mb-4">Top Artists by Tracks</h2>
				<div class="space-y-2">
					{#each data.top_artists as artist}
						<div class="flex items-center gap-3 text-sm">
							<span class="w-32 truncate text-right" title={artist.name}>{artist.name}</span>
							<div class="flex-1 h-5 bg-gray-800 rounded overflow-hidden">
								<div class="h-full bg-green-600/60 rounded" style="width: {barWidth(artist.count, maxArt)}"></div>
							</div>
							<span class="w-10 text-right text-gray-500 text-xs">{artist.count}</span>
						</div>
					{/each}
				</div>
			</div>

			<!-- Genres -->
			<div class="bg-gray-900 rounded-xl p-5 border border-gray-800">
				<h2 class="text-sm font-semibold text-gray-400 mb-4">Top Genres</h2>
				<div class="space-y-2">
					{#each data.genres as genre}
						<div class="flex items-center gap-3 text-sm">
							<span class="w-32 truncate text-right" title={genre.name}>{genre.name}</span>
							<div class="flex-1 h-5 bg-gray-800 rounded overflow-hidden">
								<div class="h-full bg-purple-600/60 rounded" style="width: {barWidth(genre.count, maxGenre)}"></div>
							</div>
							<span class="w-10 text-right text-gray-500 text-xs">{genre.count}</span>
						</div>
					{/each}
				</div>
			</div>

			<!-- Bitrate Distribution -->
			<div class="bg-gray-900 rounded-xl p-5 border border-gray-800">
				<h2 class="text-sm font-semibold text-gray-400 mb-4">Bitrate Distribution</h2>
				<div class="space-y-2">
					{#each Object.entries(data.bitrates).sort() as [range, count]}
						<div class="flex items-center gap-3 text-sm">
							<span class="w-20 text-right text-gray-400 text-xs">{range} kbps</span>
							<div class="flex-1 h-5 bg-gray-800 rounded overflow-hidden">
								<div class="h-full bg-blue-600/60 rounded" style="width: {barWidth(count, maxBr)}"></div>
							</div>
							<span class="w-10 text-right text-gray-500 text-xs">{count}</span>
						</div>
					{/each}
				</div>
			</div>
		</div>

		<!-- Year Distribution -->
		{#if data.years.length}
			<div class="bg-gray-900 rounded-xl p-5 border border-gray-800 mb-8">
				<h2 class="text-sm font-semibold text-gray-400 mb-4">Year Distribution</h2>
				<div class="flex items-end gap-px h-32">
					{#each data.years as yr}
						<div class="flex-1 flex flex-col items-center justify-end h-full group relative">
							<div class="w-full bg-accent-600/60 rounded-t min-h-[2px] transition-colors group-hover:bg-accent-500"
								style="height: {barWidth(yr.count, maxYear)}"></div>
							<div class="hidden group-hover:block absolute bottom-full mb-1 bg-gray-800 text-xs px-2 py-1 rounded whitespace-nowrap z-10">
								{yr.year}: {yr.count} tracks
							</div>
						</div>
					{/each}
				</div>
				<div class="flex justify-between text-xs text-gray-500 mt-1">
					<span>{data.years[0]?.year}</span>
					<span>{data.years[data.years.length - 1]?.year}</span>
				</div>
			</div>
		{/if}

		<!-- Most Played -->
		{#if data.most_played.length}
			<div class="bg-gray-900 rounded-xl p-5 border border-gray-800 mb-8">
				<h2 class="text-sm font-semibold text-gray-400 mb-4">Most Played</h2>
				<div class="space-y-2">
					{#each data.most_played as track, i}
						<div class="flex items-center gap-3 text-sm">
							<span class="w-6 text-right text-gray-500">{i + 1}.</span>
							<span class="flex-1 truncate">{track.title}</span>
							<span class="text-gray-400 truncate max-w-48">{track.artist || 'Unknown'}</span>
							<span class="text-accent-400 text-xs font-mono w-12 text-right">{track.plays}x</span>
						</div>
					{/each}
				</div>
			</div>
		{/if}

		<!-- Job Stats -->
		{#if data.job_stats.length}
			<div class="bg-gray-900 rounded-xl p-5 border border-gray-800">
				<h2 class="text-sm font-semibold text-gray-400 mb-4">Job History Summary</h2>
				<div class="grid grid-cols-2 md:grid-cols-4 gap-3">
					{#each data.job_stats as js}
						<div class="bg-gray-800/50 rounded-lg p-3">
							<p class="text-xs text-gray-400">{js.type}</p>
							<p class="text-sm font-medium">{js.completed} <span class="text-gray-500">/ {js.total}</span></p>
						</div>
					{/each}
				</div>
			</div>
		{/if}
	{:else}
		<p class="text-gray-500">Loading stats...</p>
	{/if}
</div>
