<script>
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';
	import { formatSize } from '$lib/utils.js';
	import { Music, Users, Disc3, HardDrive, Activity } from 'lucide-svelte';
	import PageHeader from '../components/ui/PageHeader.svelte';
	import Card from '../components/ui/Card.svelte';
	import Badge from '../components/ui/Badge.svelte';
	import Skeleton from '../components/ui/Skeleton.svelte';
	import EmptyState from '../components/ui/EmptyState.svelte';

	let stats = $state(null);
	let recent = $state([]);
	let health = $state(null);
	let loading = $state(true);

	const statCards = [
		{ key: 'tracks', label: 'Tracks', icon: Music, color: 'var(--color-library)' },
		{ key: 'artists', label: 'Artists', icon: Users, color: 'var(--color-discover)' },
		{ key: 'albums', label: 'Albums', icon: Disc3, color: 'var(--color-playlists)' },
	];

	onMount(async () => {
		try {
			[stats, recent, health] = await Promise.all([
				api.getStats(),
				api.getRecent(10),
				fetch('/api/config/health').then(r => r.json()).catch(() => null)
			]);
		} catch (e) {
			console.error('Failed to load dashboard:', e);
		} finally {
			loading = false;
		}
	});
</script>

<div class="max-w-6xl">
	<PageHeader title="Dashboard" color="var(--color-dashboard)" />

	{#if loading}
		<div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
			{#each Array(4) as _}
				<Skeleton class="h-24 rounded-lg" />
			{/each}
		</div>
		<Skeleton class="h-64 rounded-lg" />
	{:else if stats}
		<div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
			{#each statCards as card}
				<Card padding="p-4">
					<div class="flex items-center justify-between mb-2">
						{@const Icon = card.icon}
					<Icon class="w-5 h-5" style="color: {card.color}" />
					</div>
					<p class="text-2xl font-bold text-[var(--text-primary)]">{stats[card.key].toLocaleString()}</p>
					<p class="text-xs text-[var(--text-muted)]">{card.label}</p>
				</Card>
			{/each}
			<Card padding="p-4">
				<div class="flex items-center justify-between mb-2">
					<HardDrive class="w-5 h-5" style="color: var(--color-stats)" />
				</div>
				<p class="text-2xl font-bold text-[var(--text-primary)]">{formatSize(stats.total_size_bytes)}</p>
				<p class="text-xs text-[var(--text-muted)]">Total Size</p>
			</Card>
		</div>

		{#if stats.formats && Object.keys(stats.formats).length}
			<Card padding="p-4" class="mb-8">
				<h2 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)] mb-3">Formats</h2>
				<div class="flex flex-wrap gap-2">
					{#each Object.entries(stats.formats) as [fmt, count]}
						<Badge>{fmt.toUpperCase()} <span class="text-[var(--text-muted)] ml-1">{count}</span></Badge>
					{/each}
				</div>
			</Card>
		{/if}

		{#if health}
			<Card padding="p-4" class="mb-8">
				<div class="flex items-center justify-between mb-3">
					<h2 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)]">System Health</h2>
					<Badge variant={health.status === 'ok' ? 'success' : 'warning'}>{health.status}</Badge>
				</div>
				<div class="grid grid-cols-2 md:grid-cols-5 gap-3">
					{#each Object.entries(health.services) as [name, check]}
						<div class="flex items-center gap-2">
							<div class="w-2 h-2 rounded-full {check.status === 'ok' ? 'bg-emerald-400' : check.status === 'warning' ? 'bg-amber-400' : 'bg-red-400'}"></div>
							<span class="text-xs text-[var(--text-body)] capitalize">{name}</span>
						</div>
					{/each}
				</div>
			</Card>
		{/if}
	{/if}

	<Card padding="p-0">
		<h2 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)] px-4 py-3 border-b border-[var(--border-subtle)]">Recent Additions</h2>
		{#if loading}
			<div class="divide-y divide-[var(--border-subtle)]">
				{#each Array(5) as _}
					<div class="px-4 py-3 flex items-center justify-between">
						<Skeleton class="h-4 w-48" />
						<Skeleton class="h-3 w-20" />
					</div>
				{/each}
			</div>
		{:else if recent.length}
			<div class="divide-y divide-[var(--border-subtle)]">
				{#each recent as track}
					<div class="px-4 py-3 flex items-center justify-between text-sm hover:bg-[var(--bg-hover)] transition-colors">
						<span class="text-[var(--text-body)]">{track.title}</span>
						<span class="text-xs text-[var(--text-muted)] font-mono">{track.created_at ? new Date(track.created_at).toLocaleDateString() : ''}</span>
					</div>
				{/each}
			</div>
		{:else}
			<EmptyState
			title="No tracks yet"
			description="Scan your library to get started."
		>
			{#snippet icon()}<Music class="w-10 h-10" />{/snippet}
		</EmptyState>
		{/if}
	</Card>
</div>
