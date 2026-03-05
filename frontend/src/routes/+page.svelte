<script>
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';
	import { formatSize } from '$lib/utils.js';
	import { Music, Users, Disc3, HardDrive, Clock, RefreshCw } from 'lucide-svelte';
	import PageHeader from '../components/ui/PageHeader.svelte';
	import Card from '../components/ui/Card.svelte';
	import Badge from '../components/ui/Badge.svelte';
	import Skeleton from '../components/ui/Skeleton.svelte';

	let stats = $state(null);
	let health = $state(null);
	let version = $state(null);
	let lastScan = $state(null);
	let loading = $state(true);

	const statCards = [
		{ key: 'tracks', label: 'Tracks', icon: Music, color: 'var(--color-library)' },
		{ key: 'artists', label: 'Artists', icon: Users, color: 'var(--color-discover)' },
		{ key: 'albums', label: 'Albums', icon: Disc3, color: 'var(--color-playlists)' },
	];

	function timeAgo(iso) {
		if (!iso) return 'Never';
		const diff = Date.now() - new Date(iso).getTime();
		const mins = Math.floor(diff / 60000);
		if (mins < 1) return 'Just now';
		if (mins < 60) return `${mins}m ago`;
		const hrs = Math.floor(mins / 60);
		if (hrs < 24) return `${hrs}h ago`;
		const days = Math.floor(hrs / 24);
		return `${days}d ago`;
	}

	onMount(async () => {
		try {
			[stats, health, version, lastScan] = await Promise.all([
				api.getStats(),
				fetch('/api/config/health').then(r => r.json()).catch(() => null),
				fetch('/api/config/version').then(r => r.json()).catch(() => null),
				fetch('/api/jobs?limit=50').then(r => r.json()).then(data => (data.items || data).find(j => j.type === 'library_scan' && j.status === 'completed')).catch(() => null),
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
				{@const Icon = card.icon}
				<Card padding="p-4">
					<div class="flex items-center justify-between mb-2">
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

		<div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-8">
			{#if lastScan}
				<Card padding="p-4">
					<div class="flex items-center gap-2 mb-2">
						<RefreshCw class="w-4 h-4 text-[var(--color-library)]" />
						<h2 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)]">Last Scan</h2>
					</div>
					<p class="text-lg font-bold text-[var(--text-primary)]">{timeAgo(lastScan.finished_at)}</p>
					<p class="text-xs text-[var(--text-muted)]">
						{lastScan.finished_at ? new Date(lastScan.finished_at).toLocaleString() : ''}
					</p>
				</Card>
			{/if}
			{#if version}
				<Card padding="p-4">
					<div class="flex items-center gap-2 mb-2">
						<Clock class="w-4 h-4 text-[var(--color-settings)]" />
						<h2 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)]">Version</h2>
					</div>
					<p class="text-lg font-bold text-[var(--text-primary)]">v{version.version}</p>
					{#if version.commit}
						<p class="text-xs text-[var(--text-muted)] font-mono">{version.commit.slice(0, 7)}</p>
					{/if}
				</Card>
			{/if}
		</div>

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

</div>
