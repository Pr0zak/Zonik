<script>
	import { onMount } from 'svelte';
	import { addToast } from '$lib/stores.js';
	import { api } from '$lib/api.js';
	import { formatBadgeClass } from '$lib/colors.js';
	import { parseUTC } from '$lib/utils.js';
	import {
		ArrowUpCircle, Search, Play, SkipForward, RotateCcw, Trash2, Check, X,
		Loader2, ArrowRight, ChevronDown
	} from 'lucide-svelte';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Button from '../../components/ui/Button.svelte';
	import Badge from '../../components/ui/Badge.svelte';
	import Skeleton from '../../components/ui/Skeleton.svelte';
	import EmptyState from '../../components/ui/EmptyState.svelte';

	// Stats
	let stats = $state(null);

	// Scan controls
	let scanModes = $state({ low_bitrate: true, lossy_to_lossless: false, all_lossy: false, opus_to_flac: false });
	let scanMaxBitrate = $state(256);
	let scanLimit = $state(200);
	let scanning = $state(false);

	// List
	let upgrades = $state([]);
	let total = $state(0);
	let loading = $state(true);
	let activeFilter = $state(null);
	let offset = $state(0);
	let perPage = $state(25);
	let starting = $state(false);
	let selected = $state(new Set());

	const statusFilters = [
		{ value: null, label: 'All' },
		{ value: 'pending', label: 'Pending' },
		{ value: 'queued', label: 'Queued' },
		{ value: 'downloading', label: 'Downloading' },
		{ value: 'completed', label: 'Completed' },
		{ value: 'failed', label: 'Failed' },
		{ value: 'skipped', label: 'Skipped' },
	];

	const statusColors = {
		pending: 'bg-gray-500/20 text-gray-400',
		queued: 'bg-blue-500/20 text-blue-400',
		downloading: 'bg-indigo-500/20 text-indigo-400',
		completed: 'bg-green-500/20 text-green-400',
		failed: 'bg-red-500/20 text-red-400',
		skipped: 'bg-amber-500/20 text-amber-400',
	};

	const reasonLabels = {
		low_bitrate: 'Low Bitrate',
		lossy_to_lossless: 'Lossy',
		opus_to_flac: 'Opus',
		all_lossy: 'Lossy',
	};

	async function loadStats() {
		try {
			stats = await api.getUpgradeStats();
		} catch { /* ignore */ }
	}

	async function loadUpgrades() {
		loading = true;
		try {
			const params = { offset, limit: perPage, order: 'desc' };
			if (activeFilter) params.status = activeFilter;
			const data = await api.getUpgrades(params);
			upgrades = data.items;
			total = data.total;
		} catch (e) {
			addToast('Failed to load upgrades', 'error');
		} finally {
			loading = false;
		}
	}

	async function scanLibrary() {
		scanning = true;
		try {
			const modes = Object.entries(scanModes).filter(([, v]) => v).map(([k]) => k);
			if (!modes.length) {
				addToast('Select at least one scan mode', 'warning');
				scanning = false;
				return;
			}
			const result = await api.scanUpgrades({ modes, max_bitrate: scanMaxBitrate, limit: scanLimit });
			addToast(`Found ${result.created} tracks to upgrade`, 'success');
			await loadStats();
			await loadUpgrades();
		} catch (e) {
			addToast('Scan failed: ' + e.message, 'error');
		} finally {
			scanning = false;
		}
	}

	async function startAll() {
		starting = true;
		try {
			const result = await api.startUpgrades({});
			addToast(`Started ${result.started} upgrades`, 'success');
			await loadStats();
			await loadUpgrades();
		} catch (e) {
			addToast('Start failed: ' + e.message, 'error');
		} finally {
			starting = false;
		}
	}

	async function startSelected() {
		if (!selected.size) return;
		starting = true;
		try {
			const result = await api.startUpgrades({ ids: [...selected] });
			addToast(`Started ${result.started} upgrades`, 'success');
			selected = new Set();
			await loadStats();
			await loadUpgrades();
		} catch (e) {
			addToast('Start failed: ' + e.message, 'error');
		} finally {
			starting = false;
		}
	}

	async function skipUpgrade(id) {
		try {
			await api.skipUpgrade(id);
			await loadStats();
			await loadUpgrades();
		} catch (e) {
			addToast('Skip failed', 'error');
		}
	}

	async function retryUpgrade(id) {
		try {
			await api.retryUpgrade(id);
			await loadStats();
			await loadUpgrades();
		} catch (e) {
			addToast('Retry failed', 'error');
		}
	}

	async function clearByStatus(status) {
		try {
			const result = await api.clearUpgrades(status);
			addToast(`Cleared ${result.deleted} ${status} upgrades`, 'success');
			await loadStats();
			await loadUpgrades();
		} catch (e) {
			addToast('Clear failed', 'error');
		}
	}

	function setFilter(f) {
		activeFilter = f;
		offset = 0;
		selected = new Set();
		loadUpgrades();
	}

	function changePage(newOffset) {
		offset = newOffset;
		selected = new Set();
		loadUpgrades();
	}

	function toggleSelect(id) {
		const s = new Set(selected);
		if (s.has(id)) s.delete(id);
		else s.add(id);
		selected = s;
	}

	function toggleSelectAll() {
		const pending = upgrades.filter(u => u.status === 'pending').map(u => u.id);
		if (pending.every(id => selected.has(id))) {
			const s = new Set(selected);
			pending.forEach(id => s.delete(id));
			selected = s;
		} else {
			selected = new Set([...selected, ...pending]);
		}
	}

	function formatBytes(bytes) {
		if (!bytes) return '—';
		if (bytes > 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
		return (bytes / 1024).toFixed(0) + ' KB';
	}

	function formatBitrate(bps) {
		if (!bps) return '—';
		return Math.round(bps / 1000) + 'k';
	}

	let totalPages = $derived(Math.ceil(total / perPage));
	let currentPage = $derived(Math.floor(offset / perPage) + 1);

	onMount(() => {
		loadStats();
		loadUpgrades();
	});
</script>

<div class="space-y-6">
	<PageHeader title="Upgrades" icon={ArrowUpCircle} color="var(--color-upgrades)" />

	<!-- Stats Bar -->
	{#if stats}
		<div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-7 gap-3">
			{#each [
				{ label: 'Total', value: stats.total, color: 'text-[var(--text-secondary)]' },
				{ label: 'Pending', value: stats.pending, color: 'text-gray-400' },
				{ label: 'Queued', value: stats.queued, color: 'text-blue-400' },
				{ label: 'Downloading', value: stats.downloading, color: 'text-indigo-400' },
				{ label: 'Completed', value: stats.completed, color: 'text-green-400' },
				{ label: 'Failed', value: stats.failed, color: 'text-red-400' },
				{ label: 'Skipped', value: stats.skipped, color: 'text-amber-400' },
			] as stat}
				<div class="bg-[var(--bg-secondary)] border border-[var(--border-subtle)] rounded-lg px-3 py-2 text-center">
					<p class="text-lg font-bold {stat.color}">{stat.value}</p>
					<p class="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">{stat.label}</p>
				</div>
			{/each}
		</div>
		{#if stats.size_delta !== 0}
			<p class="text-xs text-[var(--text-muted)] text-center">
				Size change from completed upgrades: <span class="{stats.size_delta > 0 ? 'text-emerald-400' : 'text-red-400'}">{stats.size_delta > 0 ? '+' : ''}{formatBytes(stats.size_delta)}</span>
			</p>
		{/if}
	{/if}

	<!-- Scan Controls -->
	<Card>
		<div class="p-4 space-y-4">
			<h3 class="text-sm font-semibold text-[var(--text-primary)]">Scan Library for Upgrades</h3>
			<div class="flex flex-wrap gap-4">
				<label class="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
					<input type="checkbox" bind:checked={scanModes.low_bitrate} class="rounded accent-emerald-500" />
					Low Bitrate
				</label>
				<label class="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
					<input type="checkbox" bind:checked={scanModes.lossy_to_lossless} class="rounded accent-emerald-500" />
					Lossy to Lossless
				</label>
				<label class="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
					<input type="checkbox" bind:checked={scanModes.all_lossy} class="rounded accent-emerald-500" />
					All Lossy
				</label>
				<label class="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
					<input type="checkbox" bind:checked={scanModes.opus_to_flac} class="rounded accent-emerald-500" />
					Opus to FLAC
				</label>
			</div>
			<div class="flex flex-wrap items-end gap-4">
				{#if scanModes.low_bitrate}
					<div>
						<label class="text-xs text-[var(--text-muted)] block mb-1">Max Bitrate (kbps)</label>
						<input type="number" bind:value={scanMaxBitrate} min="64" max="512" step="32"
							class="w-24 bg-[var(--bg-tertiary)] border border-[var(--border-interactive)] rounded px-2 py-1 text-sm text-[var(--text-primary)]" />
					</div>
				{/if}
				<div>
					<label class="text-xs text-[var(--text-muted)] block mb-1">Limit</label>
					<input type="number" bind:value={scanLimit} min="10" max="500" step="10"
						class="w-24 bg-[var(--bg-tertiary)] border border-[var(--border-interactive)] rounded px-2 py-1 text-sm text-[var(--text-primary)]" />
				</div>
				<Button variant="primary" onclick={scanLibrary} disabled={scanning}>
					{#if scanning}
						<Loader2 class="w-4 h-4 animate-spin" />
					{:else}
						<Search class="w-4 h-4" />
					{/if}
					Scan Library
				</Button>
			</div>
		</div>
	</Card>

	<!-- Filter Tabs -->
	<div class="flex items-center gap-2 flex-wrap">
		{#each statusFilters as f}
			<button
				onclick={() => setFilter(f.value)}
				class="px-3 py-1.5 text-xs rounded-md transition-colors {activeFilter === f.value ? 'bg-[var(--color-upgrades)]/20 text-emerald-400 border border-emerald-500/30' : 'bg-[var(--bg-secondary)] text-[var(--text-secondary)] border border-[var(--border-subtle)] hover:bg-[var(--bg-hover)]'}"
			>
				{f.label}
				{#if stats}
					{@const count = f.value ? stats[f.value] || 0 : stats.total}
					{#if count > 0}
						<span class="ml-1 text-[10px] opacity-70">({count})</span>
					{/if}
				{/if}
			</button>
		{/each}
	</div>

	<!-- Bulk Actions -->
	<div class="flex items-center gap-2 flex-wrap">
		<Button variant="primary" onclick={startAll} disabled={starting || !stats?.pending}>
			{#if starting}<Loader2 class="w-4 h-4 animate-spin" />{:else}<Play class="w-4 h-4" />{/if}
			Start All Pending
		</Button>
		{#if selected.size > 0}
			<Button variant="default" onclick={startSelected} disabled={starting}>
				<Play class="w-4 h-4" />
				Start Selected ({selected.size})
			</Button>
		{/if}
		{#if stats?.failed}
			<Button variant="ghost" onclick={() => clearByStatus('failed')}>
				<Trash2 class="w-4 h-4" /> Clear Failed
			</Button>
		{/if}
		{#if stats?.completed}
			<Button variant="ghost" onclick={() => clearByStatus('completed')}>
				<Trash2 class="w-4 h-4" /> Clear Completed
			</Button>
		{/if}
		{#if stats?.skipped}
			<Button variant="ghost" onclick={() => clearByStatus('skipped')}>
				<Trash2 class="w-4 h-4" /> Clear Skipped
			</Button>
		{/if}
	</div>

	<!-- Upgrade Queue Table -->
	{#if loading}
		<div class="space-y-2">
			{#each Array(5) as _}
				<Skeleton class="h-12" />
			{/each}
		</div>
	{:else if upgrades.length === 0}
		<EmptyState icon={ArrowUpCircle} title="No upgrades found" description="Scan your library to find tracks that could be upgraded to higher quality." />
	{:else}
		<div class="overflow-x-auto">
			<table class="w-full text-sm">
				<thead>
					<tr class="text-[var(--text-muted)] text-xs uppercase border-b border-[var(--border-subtle)]">
						<th class="px-3 py-2 text-left w-8">
							<input type="checkbox" onchange={toggleSelectAll}
								checked={upgrades.filter(u => u.status === 'pending').length > 0 && upgrades.filter(u => u.status === 'pending').every(u => selected.has(u.id))}
								class="rounded accent-emerald-500" />
						</th>
						<th class="px-3 py-2 text-left">Track</th>
						<th class="px-3 py-2 text-left">Current</th>
						<th class="px-3 py-2 text-left">Result</th>
						<th class="px-3 py-2 text-left">Status</th>
						<th class="px-3 py-2 text-left">Reason</th>
						<th class="px-3 py-2 text-center">Tries</th>
						<th class="px-3 py-2 text-right">Actions</th>
					</tr>
				</thead>
				<tbody class="divide-y divide-[var(--border-subtle)]">
					{#each upgrades as u (u.id)}
						<tr class="hover:bg-[var(--bg-hover)] transition-colors">
							<td class="px-3 py-2">
								{#if u.status === 'pending'}
									<input type="checkbox" checked={selected.has(u.id)} onchange={() => toggleSelect(u.id)}
										class="rounded accent-emerald-500" />
								{/if}
							</td>
							<td class="px-3 py-2">
								<div class="flex items-center gap-3">
									{#if u.album_id}
										<img src="/rest/getCoverArt?id={u.album_id}&size=40" alt=""
											class="w-8 h-8 rounded object-cover flex-shrink-0"
											onerror={(e) => e.target.style.display = 'none'} />
									{/if}
									<div class="min-w-0">
										<p class="text-[var(--text-primary)] truncate">{u.title || 'Unknown'}</p>
										<p class="text-xs text-[var(--text-muted)] truncate">{u.artist || 'Unknown'}</p>
									</div>
								</div>
							</td>
							<td class="px-3 py-2">
								<div class="flex items-center gap-2">
									<span class="px-1.5 py-0.5 rounded text-[10px] font-mono uppercase {formatBadgeClass(u.original_format)}">{u.original_format}</span>
									<span class="text-xs text-[var(--text-muted)]">{formatBitrate(u.original_bitrate)}</span>
								</div>
							</td>
							<td class="px-3 py-2">
								{#if u.status === 'completed' && u.upgraded_format}
									<div class="flex items-center gap-2">
										<ArrowRight class="w-3 h-3 text-emerald-400" />
										<span class="px-1.5 py-0.5 rounded text-[10px] font-mono uppercase {formatBadgeClass(u.upgraded_format)}">{u.upgraded_format}</span>
										<span class="text-xs text-[var(--text-muted)]">{formatBitrate(u.upgraded_bitrate)}</span>
									</div>
								{:else if u.error_message}
									<span class="text-xs text-red-400 truncate max-w-[200px] block" title={u.error_message}>{u.error_message}</span>
								{:else}
									<span class="text-xs text-[var(--text-disabled)]">—</span>
								{/if}
							</td>
							<td class="px-3 py-2">
								<span class="px-2 py-0.5 rounded-full text-[10px] font-medium {statusColors[u.status] || ''}">{u.status}</span>
								{#if u.status === 'downloading'}
									<Loader2 class="w-3 h-3 text-indigo-400 animate-spin inline ml-1" />
								{/if}
							</td>
							<td class="px-3 py-2">
								<span class="text-xs text-[var(--text-muted)]">{reasonLabels[u.reason] || u.reason}</span>
							</td>
							<td class="px-3 py-2 text-center">
								<span class="text-xs text-[var(--text-muted)]">{u.attempts}/{u.max_attempts}</span>
							</td>
							<td class="px-3 py-2 text-right">
								<div class="flex items-center gap-1 justify-end">
									{#if u.status === 'pending'}
										<button onclick={() => skipUpgrade(u.id)} class="p-1 text-[var(--text-muted)] hover:text-amber-400 transition-colors" title="Skip">
											<SkipForward class="w-4 h-4" />
										</button>
									{:else if u.status === 'failed'}
										<button onclick={() => retryUpgrade(u.id)} class="p-1 text-[var(--text-muted)] hover:text-blue-400 transition-colors" title="Retry">
											<RotateCcw class="w-4 h-4" />
										</button>
									{/if}
								</div>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>

		<!-- Pagination -->
		{#if totalPages > 1}
			<div class="flex items-center justify-between pt-2">
				<p class="text-xs text-[var(--text-muted)]">
					Showing {offset + 1}–{Math.min(offset + perPage, total)} of {total}
				</p>
				<div class="flex items-center gap-1">
					<button onclick={() => changePage(offset - perPage)} disabled={offset === 0}
						class="px-2 py-1 text-xs rounded bg-[var(--bg-secondary)] text-[var(--text-secondary)] border border-[var(--border-subtle)] disabled:opacity-30 hover:bg-[var(--bg-hover)]">
						Prev
					</button>
					<span class="text-xs text-[var(--text-muted)] px-2">{currentPage} / {totalPages}</span>
					<button onclick={() => changePage(offset + perPage)} disabled={offset + perPage >= total}
						class="px-2 py-1 text-xs rounded bg-[var(--bg-secondary)] text-[var(--text-secondary)] border border-[var(--border-subtle)] disabled:opacity-30 hover:bg-[var(--bg-hover)]">
						Next
					</button>
					<select bind:value={perPage} onchange={() => { offset = 0; loadUpgrades(); }}
						class="ml-2 bg-[var(--bg-tertiary)] border border-[var(--border-interactive)] rounded px-2 py-1 text-xs text-[var(--text-secondary)]">
						<option value={25}>25</option>
						<option value={50}>50</option>
						<option value={100}>100</option>
						<option value={200}>200</option>
					</select>
				</div>
			</div>
		{/if}
	{/if}
</div>
