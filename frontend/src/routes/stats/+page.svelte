<script>
	import { onMount } from 'svelte';
	import { formatSize, formatDuration } from '$lib/utils.js';
	import { BarChart3 } from 'lucide-svelte';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Skeleton from '../../components/ui/Skeleton.svelte';

	let data = $state(null);
	let loading = $state(true);

	onMount(async () => {
		try {
			data = await fetch('/api/library/stats/detailed').then(r => r.json());
		} catch (e) {
			console.error('Failed to load stats:', e);
		} finally {
			loading = false;
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

	const barColors = {
		formats: 'bg-[var(--color-accent)]',
		artists: 'bg-emerald-500',
		genres: 'bg-purple-500',
		bitrates: 'bg-blue-500',
	};
</script>

<div class="max-w-6xl">
	<PageHeader title="Library Stats" color="var(--color-stats)" />

	{#if loading}
		<div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4 mb-8">
			{#each Array(6) as _}
				<Skeleton class="h-20 rounded-lg" />
			{/each}
		</div>
		<div class="grid grid-cols-1 md:grid-cols-2 gap-6">
			{#each Array(4) as _}
				<Skeleton class="h-64 rounded-lg" />
			{/each}
		</div>
	{:else if data}
		<!-- Overview Cards -->
		<div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4 mb-8">
			{#each [
				{ v: data.tracks.toLocaleString(), l: 'Tracks' },
				{ v: data.artists.toLocaleString(), l: 'Artists' },
				{ v: data.albums.toLocaleString(), l: 'Albums' },
				{ v: formatSize(data.total_size_bytes), l: 'Total Size' },
				{ v: formatDuration(data.total_duration_seconds), l: 'Duration' },
				{ v: data.favorites.toLocaleString(), l: 'Favorites' },
			] as card}
				<Card padding="p-4">
					<p class="text-2xl font-bold text-[var(--text-primary)]">{card.v}</p>
					<p class="text-xs text-[var(--text-muted)]">{card.l}</p>
				</Card>
			{/each}
		</div>

		<!-- Processing Status -->
		<div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
			<Card padding="p-4">
				<h3 class="text-xs text-[var(--text-muted)] font-mono uppercase tracking-wider mb-2">Audio Analyzed</h3>
				<p class="text-lg font-bold text-[var(--text-primary)]">{data.analyzed} <span class="text-sm text-[var(--text-muted)] font-normal">/ {data.tracks}</span></p>
				{#if data.tracks > 0}
					<div class="mt-2 h-1.5 bg-[var(--border-interactive)] rounded-full overflow-hidden">
						<div class="h-full bg-[var(--color-accent)] rounded-full transition-all" style="width: {(data.analyzed / data.tracks * 100).toFixed(1)}%"></div>
					</div>
				{/if}
			</Card>
			<Card padding="p-4">
				<h3 class="text-xs text-[var(--text-muted)] font-mono uppercase tracking-wider mb-2">Vibe Embeddings</h3>
				<p class="text-lg font-bold text-[var(--text-primary)]">{data.embedded} <span class="text-sm text-[var(--text-muted)] font-normal">/ {data.tracks}</span></p>
				{#if data.tracks > 0}
					<div class="mt-2 h-1.5 bg-[var(--border-interactive)] rounded-full overflow-hidden">
						<div class="h-full bg-purple-500 rounded-full transition-all" style="width: {(data.embedded / data.tracks * 100).toFixed(1)}%"></div>
					</div>
				{/if}
			</Card>
			<Card padding="p-4">
				<h3 class="text-xs text-[var(--text-muted)] font-mono uppercase tracking-wider mb-2">Playlists</h3>
				<p class="text-lg font-bold text-[var(--text-primary)]">{data.playlists}</p>
			</Card>
		</div>

		<div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
			<!-- Formats -->
			<Card padding="p-4">
				<h2 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)] mb-4">Formats</h2>
				<div class="space-y-2">
					{#each Object.entries(data.formats).sort((a, b) => b[1] - a[1]) as [fmt, count]}
						<div class="flex items-center gap-3 text-sm group">
							<span class="w-16 text-right text-[var(--text-muted)] uppercase font-mono text-xs">{fmt}</span>
							<div class="flex-1 h-5 bg-[var(--bg-hover)] rounded overflow-hidden">
								<div class="h-full {barColors.formats} rounded transition-colors" style="width: {barWidth(count, maxFmt)}"></div>
							</div>
							<span class="w-12 text-right text-[var(--text-muted)] text-xs font-mono">{count}</span>
						</div>
					{/each}
				</div>
			</Card>

			<!-- Top Artists -->
			<Card padding="p-4">
				<h2 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)] mb-4">Top Artists</h2>
				<div class="space-y-2">
					{#each data.top_artists as artist}
						<div class="flex items-center gap-3 text-sm group">
							<span class="w-32 truncate text-right text-[var(--text-body)]" title={artist.name}>{artist.name}</span>
							<div class="flex-1 h-5 bg-[var(--bg-hover)] rounded overflow-hidden">
								<div class="h-full {barColors.artists} rounded transition-colors" style="width: {barWidth(artist.count, maxArt)}"></div>
							</div>
							<span class="w-10 text-right text-[var(--text-muted)] text-xs font-mono">{artist.count}</span>
						</div>
					{/each}
				</div>
			</Card>

			<!-- Genres -->
			<Card padding="p-4">
				<h2 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)] mb-4">Top Genres</h2>
				<div class="space-y-2">
					{#each data.genres as genre}
						<div class="flex items-center gap-3 text-sm group">
							<span class="w-32 truncate text-right text-[var(--text-body)]" title={genre.name}>{genre.name}</span>
							<div class="flex-1 h-5 bg-[var(--bg-hover)] rounded overflow-hidden">
								<div class="h-full {barColors.genres} rounded transition-colors" style="width: {barWidth(genre.count, maxGenre)}"></div>
							</div>
							<span class="w-10 text-right text-[var(--text-muted)] text-xs font-mono">{genre.count}</span>
						</div>
					{/each}
				</div>
			</Card>

			<!-- Bitrate -->
			<Card padding="p-4">
				<h2 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)] mb-4">Bitrate Distribution</h2>
				<div class="space-y-2">
					{#each Object.entries(data.bitrates).sort() as [range, count]}
						<div class="flex items-center gap-3 text-sm group">
							<span class="w-20 text-right text-[var(--text-muted)] text-xs font-mono">{range} kbps</span>
							<div class="flex-1 h-5 bg-[var(--bg-hover)] rounded overflow-hidden">
								<div class="h-full {barColors.bitrates} rounded transition-colors" style="width: {barWidth(count, maxBr)}"></div>
							</div>
							<span class="w-10 text-right text-[var(--text-muted)] text-xs font-mono">{count}</span>
						</div>
					{/each}
				</div>
			</Card>
		</div>

		<!-- Year Distribution -->
		{#if data.years.length}
			<Card padding="p-4" class="mb-8">
				<h2 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)] mb-4">Year Distribution</h2>
				<div class="flex items-end gap-px h-32">
					{#each data.years as yr}
						<div class="flex-1 flex flex-col items-center justify-end h-full group relative">
							<div class="w-full bg-[var(--color-accent)] rounded-t min-h-[2px] transition-colors"
								style="height: {barWidth(yr.count, maxYear)}"></div>
							<div class="hidden group-hover:block absolute bottom-full mb-1 bg-[var(--bg-hover)] text-xs px-2 py-1 rounded whitespace-nowrap z-10 text-[var(--text-body)] border border-[var(--border-subtle)]">
								{yr.year}: {yr.count} tracks
							</div>
						</div>
					{/each}
				</div>
				<div class="flex justify-between text-xs text-[var(--text-muted)] mt-1 font-mono">
					<span>{data.years[0]?.year}</span>
					<span>{data.years[data.years.length - 1]?.year}</span>
				</div>
			</Card>
		{/if}

		<!-- Most Played -->
		{#if data.most_played.length}
			<Card padding="p-4" class="mb-8">
				<h2 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)] mb-4">Most Played</h2>
				<div class="space-y-2">
					{#each data.most_played as track, i}
						<div class="flex items-center gap-3 text-sm">
							<span class="w-6 text-right text-[var(--text-muted)] font-mono text-xs">{i + 1}.</span>
							<span class="flex-1 truncate text-[var(--text-body)]">{track.title}</span>
							<span class="text-[var(--text-secondary)] truncate max-w-48">{track.artist || 'Unknown'}</span>
							<span class="text-[var(--color-accent-light)] text-xs font-mono w-12 text-right">{track.plays}x</span>
						</div>
					{/each}
				</div>
			</Card>
		{/if}

		<!-- Job Stats -->
		{#if data.job_stats.length}
			<Card padding="p-4">
				<h2 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)] mb-4">Job History Summary</h2>
				<div class="grid grid-cols-2 md:grid-cols-4 gap-3">
					{#each data.job_stats as js}
						<div class="bg-[var(--bg-tertiary)] rounded-lg p-3">
							<p class="text-xs text-[var(--text-muted)]">{js.type}</p>
							<p class="text-sm font-medium text-[var(--text-primary)]">{js.completed} <span class="text-[var(--text-muted)]">/ {js.total}</span></p>
						</div>
					{/each}
				</div>
			</Card>
		{/if}
	{/if}
</div>
