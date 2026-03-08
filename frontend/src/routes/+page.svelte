<script>
	import { onMount, onDestroy } from 'svelte';
	import { api } from '$lib/api.js';
	import { formatSize, formatRelativeTime, formatDateTime } from '$lib/utils.js';
	import { activeTransfers, addToast } from '$lib/stores.js';
	import { goto } from '$app/navigation';
	import {
		Music, Users, Disc3, HardDrive, Clock, RefreshCw, Wifi, Share2,
		Activity, Heart, Copy, Calendar, Play, Zap,
		Search, AudioWaveform, Sparkles, TrendingUp, ChevronDown, ChevronUp,
		Download, Check, X, Loader2, FileSearch, BarChart3
	} from 'lucide-svelte';
	import PageHeader from '../components/ui/PageHeader.svelte';
	import Card from '../components/ui/Card.svelte';
	import Badge from '../components/ui/Badge.svelte';
	import Skeleton from '../components/ui/Skeleton.svelte';

	let stats = $state(null);
	let health = $state(null);
	let version = $state(null);
	let lastScan = $state(null);
	let slsk = $state(null);
	let dashboard = $state(null);
	let loading = $state(true);
	let transfers = $state([]);

	const unsubTransfers = activeTransfers.subscribe(v => { transfers = v; });
	onDestroy(unsubTransfers);

	const statCards = [
		{ key: 'tracks', label: 'Tracks', icon: Music, color: 'var(--color-library)' },
		{ key: 'artists', label: 'Artists', icon: Users, color: 'var(--color-discover)' },
		{ key: 'albums', label: 'Albums', icon: Disc3, color: 'var(--color-playlists)' },
	];

	const JOB_LABELS = {
		library_scan: 'Library Scan',
		download: 'Download',
		bulk_download: 'Bulk Download',
		audio_analysis: 'Audio Analysis',
		enrichment: 'Enrichment',

		recommendation_refresh: 'AI Recommendations',
		lastfm_top_tracks: 'Top Charts',
		discover_similar: 'Similar Tracks',
		lastfm_sync: 'Last.fm Sync',
		upgrade_scan: 'Upgrade Scan',
	};

	function jobLabel(type) {
		return JOB_LABELS[type] || type;
	}

	function statusColor(status) {
		if (status === 'completed') return 'text-emerald-400';
		if (status === 'failed') return 'text-red-400';
		if (status === 'running') return 'text-blue-400';
		return 'text-[var(--text-muted)]';
	}

	function statusIcon(status) {
		if (status === 'completed') return Check;
		if (status === 'failed') return X;
		if (status === 'running') return Loader2;
		return Clock;
	}

	import { qualityColor, qualityBarColor, FORMAT_HEX } from '$lib/colors.js';

	// Quick actions
	async function quickScan() {
		try {
			await api.scanLibrary();
			addToast('Library scan started', 'success');
		} catch { addToast('Failed to start scan', 'error'); }
	}

	async function quickRefreshRecs() {
		try {
			await fetch('/api/recommendations/refresh', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ limit: 100 }) });
			addToast('Generating recommendations...', 'success');
		} catch { addToast('Failed to start', 'error'); }
	}

	async function quickAnalysis() {
		try {
			await fetch('/api/schedule/audio_analysis/run', { method: 'POST' });
			addToast('Audio analysis started', 'success');
		} catch { addToast('Failed to start', 'error'); }
	}

	async function quickCharts() {
		try {
			await fetch('/api/schedule/lastfm_top_tracks/run', { method: 'POST' });
			addToast('Chart check started', 'success');
		} catch { addToast('Failed to start', 'error'); }
	}

	onMount(async () => {
		try {
			[stats, health, version, lastScan, slsk, dashboard] = await Promise.all([
				api.getStats(),
				fetch('/api/config/health').then(r => r.json()).catch(() => null),
				fetch('/api/config/version').then(r => r.json()).catch(() => null),
				fetch('/api/jobs?limit=50').then(r => r.json()).then(data => (data.items || data).find(j => j.type === 'library_scan' && j.status === 'completed')).catch(() => null),
				fetch('/api/download/soulseek-stats').then(r => r.json()).catch(() => null),
				fetch('/api/library/stats/dashboard').then(r => r.json()).catch(() => null),
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
		<div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
			{#each Array(4) as _}
				<Skeleton class="h-24 rounded-lg" />
			{/each}
		</div>
		<div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
			<Skeleton class="h-48 rounded-lg" />
			<Skeleton class="h-48 rounded-lg" />
		</div>
		<Skeleton class="h-64 rounded-lg" />
	{:else if stats}
		<!-- Row 1: Stat cards -->
		<div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
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

		<!-- Row 2: Quick Actions + Quality Score -->
		<div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
			<!-- Quick Actions -->
			<Card padding="p-4" class="md:col-span-2">
				<h2 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)] mb-3">Quick Actions</h2>
				<div class="grid grid-cols-2 md:grid-cols-4 gap-2">
					<button onclick={quickScan}
						class="flex flex-col items-center gap-1.5 p-3 rounded-lg bg-[var(--bg-hover)] hover:bg-[var(--bg-active)] transition-colors">
						<RefreshCw class="w-5 h-5 text-[var(--color-library)]" />
						<span class="text-xs text-[var(--text-secondary)]">Scan Library</span>
					</button>
					<button onclick={quickRefreshRecs}
						class="flex flex-col items-center gap-1.5 p-3 rounded-lg bg-[var(--bg-hover)] hover:bg-[var(--bg-active)] transition-colors">
						<Sparkles class="w-5 h-5 text-[var(--color-discover)]" />
						<span class="text-xs text-[var(--text-secondary)]">Refresh Recs</span>
					</button>
					<button onclick={quickCharts}
						class="flex flex-col items-center gap-1.5 p-3 rounded-lg bg-[var(--bg-hover)] hover:bg-[var(--bg-active)] transition-colors">
						<TrendingUp class="w-5 h-5 text-[var(--color-downloads)]" />
						<span class="text-xs text-[var(--text-secondary)]">Check Charts</span>
					</button>
					<button onclick={quickAnalysis}
						class="flex flex-col items-center gap-1.5 p-3 rounded-lg bg-[var(--bg-hover)] hover:bg-[var(--bg-active)] transition-colors">
						<AudioWaveform class="w-5 h-5 text-[var(--color-analysis)]" />
						<span class="text-xs text-[var(--text-secondary)]">Run Analysis</span>
					</button>
				</div>
			</Card>

			<!-- Quality Health Score -->
			{#if dashboard?.quality}
				{@const q = dashboard.quality}
				<Card padding="p-4">
					<h2 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)] mb-3">Library Quality</h2>
					<div class="flex items-center gap-4 mb-3">
						<div class="relative w-16 h-16">
							<svg viewBox="0 0 36 36" class="w-16 h-16 -rotate-90">
								<circle cx="18" cy="18" r="15.9" fill="none" stroke="var(--bg-hover)" stroke-width="3" />
								<circle cx="18" cy="18" r="15.9" fill="none" stroke-width="3"
									class="{qualityBarColor(q.score).replace('bg-', 'stroke-')}"
									stroke-dasharray="{q.score}, 100"
									stroke-linecap="round" />
							</svg>
							<span class="absolute inset-0 flex items-center justify-center text-lg font-bold {qualityColor(q.score)}">{Math.round(q.score)}</span>
						</div>
						<div class="space-y-1.5 flex-1">
							<div class="flex justify-between text-xs">
								<span class="text-[var(--text-muted)]">Lossless</span>
								<span class="text-[var(--text-primary)] font-mono">{q.pct_lossless}%</span>
							</div>
							<div class="flex justify-between text-xs">
								<span class="text-[var(--text-muted)]">Analyzed</span>
								<span class="text-[var(--text-primary)] font-mono">{q.pct_analyzed}%</span>
							</div>
							<div class="flex justify-between text-xs">
								<span class="text-[var(--text-muted)]">Avg Bitrate</span>
								<span class="text-[var(--text-primary)] font-mono">{Math.round(q.avg_bitrate / 1000)} kbps</span>
							</div>
							{#if q.low_quality_count > 0}
								<div class="flex justify-between text-xs">
									<span class="text-amber-400">Low Quality</span>
									<span class="text-amber-400 font-mono">{q.low_quality_count}</span>
								</div>
							{/if}
						</div>
					</div>
				</Card>
			{/if}
		</div>

		<!-- Row 3: Library Growth + Storage Usage -->
		<div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
			<!-- Library Growth Chart -->
			{#if dashboard?.growth?.length}
				<Card padding="p-4">
					<h2 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)] mb-3">Library Growth (30 days)</h2>
					{@const maxCount = Math.max(...dashboard.growth.map(d => d.count), 1)}
					<div class="flex items-end gap-0.5 h-24">
						{#each dashboard.growth as day}
							{@const pct = (day.count / maxCount) * 100}
							<div class="flex-1 group relative">
								<div class="bg-indigo-500/70 hover:bg-indigo-400 rounded-t transition-colors cursor-default"
									style="height: {Math.max(pct, 2)}%"
									title="{day.date}: {day.count} tracks"></div>
							</div>
						{/each}
					</div>
					<div class="flex justify-between mt-1.5">
						<span class="text-[10px] text-[var(--text-disabled)]">{dashboard.growth[0]?.date?.slice(5)}</span>
						<span class="text-[10px] text-[var(--text-muted)]">{dashboard.growth.reduce((s, d) => s + d.count, 0)} tracks added</span>
						<span class="text-[10px] text-[var(--text-disabled)]">{dashboard.growth[dashboard.growth.length - 1]?.date?.slice(5)}</span>
					</div>
				</Card>
			{/if}

			<!-- Storage Usage -->
			{#if dashboard?.storage}
				{@const storage = dashboard.storage}
				<Card padding="p-4">
					<div class="flex items-center justify-between mb-3">
						<h2 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)]">Storage Usage</h2>
						<span class="text-sm font-bold text-[var(--text-primary)]">{formatSize(storage.total_size)}</span>
					</div>
					<!-- Stacked bar -->
					{@const fmtColors = FORMAT_HEX}
					<div class="flex h-4 rounded-full overflow-hidden mb-3">
						{#each storage.by_format as fmt}
							{@const pct = (fmt.size / Math.max(storage.total_size, 1)) * 100}
							{#if pct > 0.5}
								<div style="width: {pct}%; background: {fmtColors[fmt.format] || '#6b7280'}"
									title="{fmt.format.toUpperCase()}: {formatSize(fmt.size)} ({fmt.count} tracks)"
									class="transition-all hover:opacity-80"></div>
							{/if}
						{/each}
					</div>
					<div class="flex flex-wrap gap-x-3 gap-y-1">
						{#each storage.by_format.slice(0, 6) as fmt}
							<div class="flex items-center gap-1.5">
								<div class="w-2 h-2 rounded-full" style="background: {fmtColors[fmt.format] || '#6b7280'}"></div>
								<span class="text-[10px] text-[var(--text-secondary)]">{fmt.format.toUpperCase()}</span>
								<span class="text-[10px] text-[var(--text-muted)] font-mono">{formatSize(fmt.size)}</span>
							</div>
						{/each}
					</div>
				</Card>
			{/if}
		</div>

		<!-- Row 4: Active Transfers + Recent Activity -->
		<div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
			<!-- Active Transfers -->
			<Card padding="p-4">
				<div class="flex items-center justify-between mb-3">
					<h2 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)]">Active Transfers</h2>
					{#if transfers.length}
						<Badge variant="info">{transfers.length} active</Badge>
					{/if}
				</div>
				{#if transfers.length}
					<div class="space-y-2">
						{#each transfers.slice(0, 5) as t}
							{@const pct = t.file_size ? Math.round((t.received_bytes / t.file_size) * 100) : 0}
							<div class="p-2 rounded bg-[var(--bg-hover)]">
								<div class="flex items-center justify-between mb-1">
									<span class="text-xs text-[var(--text-primary)] truncate flex-1">{t.filename?.split(/[\\/]/).pop() || 'Unknown'}</span>
									<span class="text-[10px] text-[var(--text-muted)] font-mono ml-2">{pct}%</span>
								</div>
								<div class="h-1.5 bg-[var(--bg-tertiary)] rounded-full overflow-hidden">
									<div class="h-full bg-blue-500 rounded-full transition-all" style="width: {pct}%"></div>
								</div>
								<div class="flex justify-between mt-1">
									<span class="text-[10px] text-[var(--text-disabled)] truncate">{t.username || ''}</span>
									<span class="text-[10px] text-[var(--text-disabled)] font-mono">
										{t.speed ? formatSize(t.speed) + '/s' : ''}
										{t.eta_seconds ? ' · ' + (t.eta_seconds < 60 ? t.eta_seconds + 's' : Math.round(t.eta_seconds / 60) + 'm') : ''}
									</span>
								</div>
							</div>
						{/each}
						{#if transfers.length > 5}
							<button onclick={() => goto('/downloads')} class="text-xs text-blue-400 hover:underline">
								+{transfers.length - 5} more →
							</button>
						{/if}
					</div>
				{:else}
					<div class="flex items-center gap-2 py-4 justify-center">
						<Download class="w-4 h-4 text-[var(--text-disabled)]" />
						<span class="text-xs text-[var(--text-disabled)]">No active transfers</span>
					</div>
				{/if}
			</Card>

			<!-- Recent Activity -->
			{#if dashboard?.recent_activity}
				<Card padding="p-4">
					<div class="flex items-center justify-between mb-3">
						<h2 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)]">Recent Activity</h2>
						<button onclick={() => goto('/logs')} class="text-[10px] text-blue-400 hover:underline">View all →</button>
					</div>
					<div class="space-y-1">
						{#each dashboard.recent_activity.slice(0, 8) as job}
							{@const SIcon = statusIcon(job.status)}
							<button onclick={() => goto(`/logs?job=${job.id}`)}
								class="w-full flex items-center gap-2 py-1.5 px-2 rounded hover:bg-[var(--bg-hover)] transition-colors text-left">
								<SIcon class="w-3 h-3 flex-shrink-0 {statusColor(job.status)} {job.status === 'running' ? 'animate-spin' : ''}" />
								<span class="text-xs text-[var(--text-secondary)] flex-1 truncate">{jobLabel(job.type)}</span>
								<span class="text-[10px] text-[var(--text-disabled)] font-mono">{formatRelativeTime(job.finished_at)}</span>
							</button>
						{/each}
					</div>
				</Card>
			{/if}
		</div>

		<!-- Row 5: Favorites + Duplicates Alert + Scheduled Tasks -->
		<div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
			<!-- Favorites -->
			{#if dashboard?.favorites}
				<Card padding="p-4">
					<div class="flex items-center justify-between mb-3">
						<h2 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)]">Favorites</h2>
						<button onclick={() => goto('/favorites')} class="text-[10px] text-blue-400 hover:underline">View all →</button>
					</div>
					<div class="flex items-center gap-3 mb-3">
						<Heart class="w-5 h-5 text-red-400" fill="currentColor" />
						<span class="text-2xl font-bold text-[var(--text-primary)]">{dashboard.favorites.count}</span>
						<span class="text-xs text-[var(--text-muted)]">starred tracks</span>
					</div>
					{#if dashboard.favorites.recent.length}
						<div class="space-y-1">
							{#each dashboard.favorites.recent as fav}
								<div class="flex items-center gap-2 py-0.5">
									<Heart class="w-3 h-3 text-red-400/50 flex-shrink-0" fill="currentColor" />
									<span class="text-xs text-[var(--text-secondary)] truncate">{fav.title}</span>
									<span class="text-[10px] text-[var(--text-disabled)] truncate">{fav.artist}</span>
								</div>
							{/each}
						</div>
					{/if}
				</Card>
			{/if}

			<!-- Duplicate Alert -->
			{#if dashboard?.duplicates}
				<Card padding="p-4">
					<div class="flex items-center justify-between mb-3">
						<h2 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)]">Duplicates</h2>
						{#if dashboard.duplicates.groups > 0}
							<button onclick={() => goto('/duplicates')} class="text-[10px] text-blue-400 hover:underline">Manage →</button>
						{/if}
					</div>
					{#if dashboard.duplicates.groups > 0}
						<div class="flex items-center gap-3 mb-2">
							<div class="p-2 rounded-lg bg-amber-500/10">
								<Copy class="w-5 h-5 text-amber-400" />
							</div>
							<div>
								<p class="text-lg font-bold text-amber-400">{dashboard.duplicates.groups} groups</p>
								<p class="text-xs text-[var(--text-muted)]">{formatSize(dashboard.duplicates.reclaimable_bytes)} reclaimable</p>
							</div>
						</div>
						<p class="text-[10px] text-[var(--text-disabled)]">Duplicate tracks detected. Review and remove extras to free up space.</p>
					{:else}
						<div class="flex items-center gap-2 py-4 justify-center">
							<Check class="w-4 h-4 text-emerald-400" />
							<span class="text-xs text-emerald-400">No duplicates found</span>
						</div>
					{/if}
				</Card>
			{/if}

			<!-- Scheduled Tasks -->
			{#if dashboard?.upcoming_tasks}
				<Card padding="p-4">
					<div class="flex items-center justify-between mb-3">
						<h2 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)]">Scheduled Tasks</h2>
						<button onclick={() => goto('/schedule')} class="text-[10px] text-blue-400 hover:underline">Manage →</button>
					</div>
					<div class="space-y-1.5">
						{#each dashboard.upcoming_tasks.slice(0, 6) as task}
							<div class="flex items-center gap-2 py-1">
								<div class="w-1.5 h-1.5 rounded-full bg-emerald-400 flex-shrink-0"></div>
								<span class="text-xs text-[var(--text-secondary)] flex-1 truncate">{jobLabel(task.task_name)}</span>
								<span class="text-[10px] text-[var(--text-disabled)] font-mono">
									{#if task.run_at}{task.run_at}{/if}
									{#if task.interval_hours <= 24}daily{:else if task.interval_hours <= 48}2d{:else}weekly{/if}
								</span>
							</div>
						{/each}
					</div>
				</Card>
			{/if}
		</div>

		<!-- Row 6: Soulseek P2P + System Health + Version/Scan -->
		<div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
			{#if slsk}
				<Card padding="p-4">
					<h2 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)] mb-3">Soulseek P2P</h2>
					<div class="grid grid-cols-2 gap-3">
						<div class="flex items-center gap-3">
							<Wifi class="w-4 h-4 flex-shrink-0 {slsk.connected ? 'text-emerald-400' : 'text-red-400'}" />
							<div>
								<p class="text-sm font-semibold text-[var(--text-primary)]">{slsk.connected ? 'Online' : 'Offline'}</p>
								{#if slsk.username}
									<p class="text-[10px] text-[var(--text-muted)] truncate">{slsk.username}</p>
								{/if}
							</div>
						</div>
						<div class="flex items-center gap-3">
							<Users class="w-4 h-4 flex-shrink-0 text-[var(--color-downloads)]" />
							<div>
								<p class="text-sm font-semibold text-[var(--text-primary)]">{slsk.peers} peers</p>
								<p class="text-[10px] text-[var(--text-muted)]">connected</p>
							</div>
						</div>
						<div class="flex items-center gap-3">
							<Share2 class="w-4 h-4 flex-shrink-0 text-[var(--color-discover)]" />
							<div>
								<p class="text-sm font-semibold text-[var(--text-primary)]">{slsk.shared_files.toLocaleString()} files</p>
								<p class="text-[10px] text-[var(--text-muted)]">{slsk.shared_folders} folders</p>
							</div>
						</div>
						<div class="flex items-center gap-3">
							<HardDrive class="w-4 h-4 flex-shrink-0 text-[var(--color-downloads)]" />
							<div>
								<p class="text-sm font-semibold text-[var(--text-primary)]">{slsk.active_transfers} active</p>
								<p class="text-[10px] text-[var(--text-muted)]">{slsk.completed_transfers} done · {slsk.failed_transfers} failed</p>
							</div>
						</div>
					</div>
				</Card>
			{/if}

			<div class="space-y-4">
				{#if health}
					<Card padding="p-4">
						<div class="flex items-center justify-between mb-3">
							<h2 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)]">System Health</h2>
							<Badge variant={health.status === 'ok' ? 'success' : 'warning'}>{health.status}</Badge>
						</div>
						<div class="flex flex-wrap gap-3">
							{#each Object.entries(health.services) as [name, check]}
								<div class="flex items-center gap-1.5">
									<div class="w-2 h-2 rounded-full {check.status === 'ok' ? 'bg-emerald-400' : check.status === 'warning' ? 'bg-amber-400' : 'bg-red-400'}"></div>
									<span class="text-xs text-[var(--text-body)] capitalize">{name}</span>
								</div>
							{/each}
						</div>
					</Card>
				{/if}

				<div class="grid grid-cols-2 gap-4">
					{#if lastScan}
						<Card padding="p-4">
							<div class="flex items-center gap-2 mb-1">
								<RefreshCw class="w-3.5 h-3.5 text-[var(--color-library)]" />
								<span class="text-[10px] font-mono text-[var(--text-muted)] uppercase">Last Scan</span>
							</div>
							<p class="text-sm font-bold text-[var(--text-primary)]">{formatRelativeTime(lastScan.finished_at)}</p>
						</Card>
					{/if}
					{#if version}
						<Card padding="p-4">
							<div class="flex items-center gap-2 mb-1">
								<Clock class="w-3.5 h-3.5 text-[var(--color-settings)]" />
								<span class="text-[10px] font-mono text-[var(--text-muted)] uppercase">Version</span>
							</div>
							<p class="text-sm font-bold text-[var(--text-primary)]">v{version.version}</p>
							{#if version.commit}
								<p class="text-[10px] text-[var(--text-muted)] font-mono">{version.commit.slice(0, 7)}</p>
							{/if}
						</Card>
					{/if}
				</div>
			</div>
		</div>

		<!-- Formats row -->
		{#if stats.formats && Object.keys(stats.formats).length}
			<Card padding="p-4">
				<h2 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)] mb-3">Formats</h2>
				<div class="flex flex-wrap gap-2">
					{#each Object.entries(stats.formats) as [fmt, count]}
						<Badge>{fmt.toUpperCase()} <span class="text-[var(--text-muted)] ml-1">{count}</span></Badge>
					{/each}
				</div>
			</Card>
		{/if}
	{/if}
</div>
