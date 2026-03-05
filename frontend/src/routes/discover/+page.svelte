<script>
	import { onMount } from 'svelte';
	import { addToast } from '$lib/stores.js';
	import { Compass, Download, TrendingUp, Users, Music } from 'lucide-svelte';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Button from '../../components/ui/Button.svelte';
	import Badge from '../../components/ui/Badge.svelte';
	import Skeleton from '../../components/ui/Skeleton.svelte';
	import EmptyState from '../../components/ui/EmptyState.svelte';

	let activeTab = $state('top');
	let topTracks = $state([]);
	let similarTracks = $state([]);
	let similarArtists = $state([]);
	let loading = $state(false);

	const tabs = [
		{ key: 'top', label: 'Top Tracks', icon: TrendingUp },
		{ key: 'similar', label: 'Similar Tracks', icon: Music },
		{ key: 'artists', label: 'Similar Artists', icon: Users },
	];

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

	async function downloadAllMissing() {
		const items = activeTab === 'top' ? topTracks : similarTracks;
		const missing = items.filter(t => !t.in_library);
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

	function switchTab(tab) {
		activeTab = tab;
		if (tab === 'top' && !topTracks.length) loadTopTracks();
		if (tab === 'similar' && !similarTracks.length) loadSimilarTracks();
		if (tab === 'artists' && !similarArtists.length) loadSimilarArtists();
	}

	onMount(() => loadTopTracks());
</script>

<div class="max-w-6xl">
	<PageHeader title="Discover" color="var(--color-discover)">
		{#if (activeTab === 'top' && topTracks.some(t => !t.in_library)) || (activeTab === 'similar' && similarTracks.some(t => !t.in_library))}
			<Button variant="success" size="sm" onclick={downloadAllMissing}>
				<Download class="w-3.5 h-3.5" />
				Download All Missing
			</Button>
		{/if}
	</PageHeader>

	<div class="flex gap-1.5 mb-6">
		{#each tabs as tab}
			<button on:click={() => switchTab(tab.key)}
				class="flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors
					{activeTab === tab.key
						? 'bg-[var(--color-discover)] text-white'
						: 'bg-[var(--bg-hover)] text-[var(--text-secondary)] hover:text-white hover:bg-[var(--bg-active)]'}">
				<svelte:component this={tab.icon} class="w-3.5 h-3.5" />
				{tab.label}
			</button>
		{/each}
	</div>

	{#if loading}
		<Card padding="p-0">
			<div class="divide-y divide-[var(--border-subtle)]">
				{#each Array(10) as _}
					<div class="px-4 py-3 flex items-center gap-4">
						<Skeleton class="h-4 w-8" />
						<Skeleton class="h-4 w-40" />
						<Skeleton class="h-4 w-28" />
						<Skeleton class="h-5 w-16 rounded-full" />
					</div>
				{/each}
			</div>
		</Card>
	{:else if activeTab === 'top'}
		<Card padding="p-0">
			{#if topTracks.length}
				<table class="w-full text-sm">
					<thead>
						<tr class="border-b border-[var(--border-subtle)] text-[var(--text-muted)] text-left">
							<th class="px-4 py-3 w-8 font-medium text-xs uppercase tracking-wider">#</th>
							<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider">Track</th>
							<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider">Artist</th>
							<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider hidden md:table-cell">Listeners</th>
							<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider">Status</th>
							<th class="px-4 py-3"></th>
						</tr>
					</thead>
					<tbody class="divide-y divide-[var(--border-subtle)]">
						{#each topTracks as t, i}
							<tr class="hover:bg-[var(--bg-hover)] transition-colors">
								<td class="px-4 py-3 text-[var(--text-muted)] font-mono text-xs">{i + 1}</td>
								<td class="px-4 py-3 font-medium text-[var(--text-primary)]">{t.name}</td>
								<td class="px-4 py-3 text-[var(--text-secondary)]">{t.artist}</td>
								<td class="px-4 py-3 text-[var(--text-muted)] font-mono text-xs hidden md:table-cell">{t.listeners?.toLocaleString()}</td>
								<td class="px-4 py-3">
									{#if t.in_library}
										<Badge variant="success">In Library</Badge>
									{:else}
										<Badge variant="warning">Missing</Badge>
									{/if}
								</td>
								<td class="px-4 py-3">
									{#if !t.in_library}
										<Button variant="success" size="sm" onclick={() => downloadTrack(t.artist, t.name)}>
											<Download class="w-3 h-3" />
										</Button>
									{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{:else}
				<EmptyState title="No top tracks" description="Could not load Last.fm top charts." />
			{/if}
		</Card>
	{:else if activeTab === 'similar'}
		<Card padding="p-0">
			{#if similarTracks.length}
				<table class="w-full text-sm">
					<thead>
						<tr class="border-b border-[var(--border-subtle)] text-[var(--text-muted)] text-left">
							<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider">Track</th>
							<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider">Artist</th>
							<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider hidden md:table-cell">Similar to</th>
							<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider">Status</th>
							<th class="px-4 py-3"></th>
						</tr>
					</thead>
					<tbody class="divide-y divide-[var(--border-subtle)]">
						{#each similarTracks as t}
							<tr class="hover:bg-[var(--bg-hover)] transition-colors">
								<td class="px-4 py-3 font-medium text-[var(--text-primary)]">{t.name}</td>
								<td class="px-4 py-3 text-[var(--text-secondary)]">{t.artist}</td>
								<td class="px-4 py-3 text-[var(--text-muted)] text-xs font-mono hidden md:table-cell">
									{t.source_artist} - {t.source_track}
								</td>
								<td class="px-4 py-3">
									{#if t.in_library}
										<Badge variant="success">In Library</Badge>
									{:else}
										<Badge variant="warning">Missing</Badge>
									{/if}
								</td>
								<td class="px-4 py-3">
									{#if !t.in_library}
										<Button variant="success" size="sm" onclick={() => downloadTrack(t.artist, t.name)}>
											<Download class="w-3 h-3" />
										</Button>
									{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{:else}
				<EmptyState title="No similar tracks" description="Star some tracks first to get similar track suggestions." />
			{/if}
		</Card>
	{:else if activeTab === 'artists'}
		<Card padding="p-0">
			{#if similarArtists.length}
				<div class="divide-y divide-[var(--border-subtle)]">
					{#each similarArtists as a}
						<div class="px-4 py-3 flex items-center justify-between hover:bg-[var(--bg-hover)] transition-colors">
							<div>
								<span class="font-medium text-[var(--text-primary)]">{a.name}</span>
								<span class="text-xs text-[var(--text-muted)] ml-2 font-mono">similar to {a.source_artist}</span>
							</div>
							<div class="flex items-center gap-2">
								{#if a.in_library}
									<Badge variant="success">In Library</Badge>
								{:else}
									<Badge variant="warning">New</Badge>
								{/if}
							</div>
						</div>
					{/each}
				</div>
			{:else}
				<EmptyState title="No similar artists" description="Star some tracks first to get artist suggestions." />
			{/if}
		</Card>
	{/if}
</div>
