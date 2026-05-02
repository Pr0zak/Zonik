<script>
	import { onMount } from 'svelte';
	import { addToast } from '$lib/stores.js';
	import { api } from '$lib/api.js';
	import FormatBadge from '../../components/ui/FormatBadge.svelte';
	import {
		ArrowUpCircle, Search, Play, SkipForward, RotateCcw, Trash2,
		Loader2, ArrowRight
	} from 'lucide-svelte';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Button from '../../components/ui/Button.svelte';
	import Skeleton from '../../components/ui/Skeleton.svelte';
	import EmptyState from '../../components/ui/EmptyState.svelte';
	import Pagination from '../../components/ui/Pagination.svelte';
	import StatTile from '../../components/ui/StatTile.svelte';
	import FilterPills from '../../components/ui/FilterPills.svelte';
	import DataTable from '../../components/ui/DataTable.svelte';
	import Toolbar from '../../components/ui/Toolbar.svelte';
	import Badge from '../../components/ui/Badge.svelte';

	let stats = $state(null);
	let scanning = $state(false);

	let upgrades = $state([]);
	let total = $state(0);
	let loading = $state(true);
	let activeFilter = $state(null);
	let activeReason = $state(null);
	let sortCol = $state('created_at');
	let sortOrder = $state('desc');
	let offset = $state(0);
	let perPage = $state(25);
	let starting = $state(false);
	let selected = $state(new Set());

	const reasonLabels = {
		low_bitrate: 'Low Bitrate',
		lossy_to_lossless: 'Lossy → Lossless',
		opus_to_flac: 'Opus → FLAC',
		all_lossy: 'All Lossy',
	};

	const statusVariants = {
		pending: 'default',
		queued: 'info',
		downloading: 'info',
		completed: 'success',
		failed: 'error',
		skipped: 'warning',
	};

	const statTiles = $derived([
		{ label: 'Total', value: stats?.total ?? 0, color: 'var(--text-secondary)' },
		{ label: 'Pending', value: stats?.pending ?? 0, color: '#9ca3af' },
		{ label: 'Queued', value: stats?.queued ?? 0, color: '#60a5fa' },
		{ label: 'Downloading', value: stats?.downloading ?? 0, color: '#818cf8' },
		{ label: 'Completed', value: stats?.completed ?? 0, color: '#4ade80' },
		{ label: 'Failed', value: stats?.failed ?? 0, color: '#f87171' },
		{ label: 'Skipped', value: stats?.skipped ?? 0, color: '#fbbf24' },
	]);

	const statusOptions = $derived([
		{ value: null, label: 'All', color: 'upgrades', count: stats?.total },
		{ value: 'pending', label: 'Pending', color: 'upgrades', count: stats?.pending },
		{ value: 'queued', label: 'Queued', color: 'upgrades', count: stats?.queued },
		{ value: 'downloading', label: 'Downloading', color: 'upgrades', count: stats?.downloading },
		{ value: 'completed', label: 'Completed', color: 'upgrades', count: stats?.completed },
		{ value: 'failed', label: 'Failed', color: 'upgrades', count: stats?.failed },
		{ value: 'skipped', label: 'Skipped', color: 'upgrades', count: stats?.skipped },
	]);

	const reasonOptions = [
		{ value: null, label: 'All Reasons', color: 'upgrades' },
		{ value: 'low_bitrate', label: 'Low Bitrate', color: 'upgrades' },
		{ value: 'lossy_to_lossless', label: 'Lossy → Lossless', color: 'upgrades' },
		{ value: 'opus_to_flac', label: 'Opus → FLAC', color: 'upgrades' },
		{ value: 'all_lossy', label: 'All Lossy', color: 'upgrades' },
	];

	let allPendingSelected = $derived.by(() => {
		const pending = upgrades.filter(u => u.status === 'pending');
		return pending.length > 0 && pending.every(u => selected.has(u.id));
	});

	async function loadStats() {
		try { stats = await api.getUpgradeStats(); } catch { /* ignore */ }
	}

	async function loadUpgrades() {
		loading = true;
		try {
			const params = { offset, limit: perPage, sort: sortCol, order: sortOrder };
			if (activeFilter) params.status = activeFilter;
			if (activeReason) params.reason = activeReason;
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
			const result = await api.scanUpgrades({ modes: ['low_bitrate', 'all_lossy'], max_bitrate: 256, limit: 500 });
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

	function setReason(r) {
		activeReason = r;
		offset = 0;
		selected = new Set();
		loadUpgrades();
	}

	function handleSort(key, dir) {
		if (key === null) {
			sortCol = 'created_at';
			sortOrder = 'desc';
		} else {
			sortCol = key;
			sortOrder = dir;
		}
		offset = 0;
		loadUpgrades();
	}

	function handlePageChange(newOffset, newLimit) {
		offset = newOffset;
		perPage = newLimit;
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

	onMount(() => {
		loadStats();
		loadUpgrades();
	});
</script>

<div class="space-y-6">
	<PageHeader title="Upgrades" icon={ArrowUpCircle} color="var(--color-upgrades)" />

	{#if stats}
		<div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-7 gap-3">
			{#each statTiles as tile}
				<StatTile label={tile.label} value={tile.value} color={tile.color} />
			{/each}
		</div>
		{#if stats.size_delta !== 0}
			<p class="text-xs text-[var(--text-muted)] text-center">
				Size change from completed upgrades:
				<span class="{stats.size_delta > 0 ? 'text-emerald-400' : 'text-red-400'}">
					{stats.size_delta > 0 ? '+' : ''}{formatBytes(stats.size_delta)}
				</span>
			</p>
		{/if}
	{/if}

	<Toolbar>
		{#snippet row1Left()}
			<FilterPills options={statusOptions} value={activeFilter} onchange={setFilter} variant="outline" />
		{/snippet}
		{#snippet row1Right()}
			<FilterPills options={reasonOptions} value={activeReason} onchange={setReason} variant="outline" />
		{/snippet}
		{#snippet row2Left()}
			<span class="text-[var(--text-secondary)] font-medium">{selected.size} selected</span>
		{/snippet}
		{#snippet row2Right()}
			<Button variant="secondary" size="sm" onclick={scanLibrary} disabled={scanning} loading={scanning}>
				<Search class="w-3.5 h-3.5" />
				Scan Library
			</Button>
			<Button variant="primary" size="sm" onclick={startAll} disabled={starting || !stats?.pending} loading={starting}>
				<Play class="w-3.5 h-3.5" />
				Start All
			</Button>
			{#if selected.size > 0}
				<Button variant="secondary" size="sm" onclick={startSelected} disabled={starting}>
					<Play class="w-3.5 h-3.5" />
					Start Selected ({selected.size})
				</Button>
			{/if}
			{#if stats?.failed}
				<Button variant="ghost" size="sm" onclick={() => clearByStatus('failed')}>
					<Trash2 class="w-3.5 h-3.5" /> Clear Failed
				</Button>
			{/if}
			{#if stats?.completed}
				<Button variant="ghost" size="sm" onclick={() => clearByStatus('completed')}>
					<Trash2 class="w-3.5 h-3.5" /> Clear Completed
				</Button>
			{/if}
			{#if stats?.skipped}
				<Button variant="ghost" size="sm" onclick={() => clearByStatus('skipped')}>
					<Trash2 class="w-3.5 h-3.5" /> Clear Skipped
				</Button>
			{/if}
		{/snippet}
	</Toolbar>

	{#if loading}
		<Skeleton variant="table-row" count={5} />
	{:else if upgrades.length === 0 && !activeFilter && !activeReason}
		<EmptyState title="No upgrades found" description="Scan your library to find tracks that could be upgraded to higher quality.">
			{#snippet icon()}<ArrowUpCircle class="w-12 h-12" />{/snippet}
		</EmptyState>
	{:else}
		{@const tableColumns = [
			{ key: '__select', label: '', width: '32px' },
			{ key: 'created_at', label: 'Track', sortable: true },
			{ key: 'original_format', label: 'Current', sortable: true },
			{ key: '__result', label: 'Result', headerClass: 'hidden md:table-cell' },
			{ key: 'status', label: 'Status', sortable: true },
			{ key: 'reason', label: 'Reason', sortable: true, headerClass: 'hidden lg:table-cell' },
			{ key: 'attempts', label: 'Tries', sortable: true, align: 'center', headerClass: 'hidden sm:table-cell' },
			{ key: '__actions', label: 'Actions', align: 'right' },
		]}
		<DataTable
			columns={tableColumns}
			rows={upgrades}
			sortKey={sortCol}
			sortDir={sortOrder}
			onsort={handleSort}>
			{#snippet header()}
				<th class="px-3 py-2.5 w-8">
					<input type="checkbox" onchange={toggleSelectAll}
						checked={allPendingSelected}
						class="rounded accent-emerald-500" />
				</th>
				{#each tableColumns.slice(1) as col}
					<th class="px-3 py-2.5 font-medium text-xs uppercase tracking-wider whitespace-nowrap {col.align === 'right' ? 'text-right' : col.align === 'center' ? 'text-center' : 'text-left'} {col.headerClass || ''}">
						{#if col.sortable}
							<button onclick={() => {
								if (sortCol === col.key) {
									if (sortOrder === 'asc') handleSort(col.key, 'desc');
									else if (sortOrder === 'desc') handleSort(null, null);
									else handleSort(col.key, 'asc');
								} else handleSort(col.key, 'asc');
							}} class="hover:text-[var(--text-primary)] transition-colors">
								{col.label}{sortCol === col.key ? (sortOrder === 'asc' ? ' ↑' : ' ↓') : ''}
							</button>
						{:else}
							{col.label}
						{/if}
					</th>
				{/each}
			{/snippet}
			{#snippet row(u)}
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
						<FormatBadge format={u.original_format} />
						<span class="text-xs text-[var(--text-muted)]">{formatBitrate(u.original_bitrate)}</span>
					</div>
				</td>
				<td class="px-3 py-2 hidden md:table-cell">
					{#if u.status === 'completed' && u.upgraded_format}
						<div class="flex items-center gap-2">
							<ArrowRight class="w-3 h-3 text-emerald-400" />
							<FormatBadge format={u.upgraded_format} />
							<span class="text-xs text-[var(--text-muted)]">{formatBitrate(u.upgraded_bitrate)}</span>
						</div>
					{:else if u.error_message}
						<span class="text-xs text-red-400 truncate max-w-[200px] block" title={u.error_message}>{u.error_message}</span>
					{:else}
						<span class="text-xs text-[var(--text-disabled)]">—</span>
					{/if}
				</td>
				<td class="px-3 py-2">
					<Badge variant={statusVariants[u.status] || 'default'}>{u.status}</Badge>
					{#if u.status === 'downloading'}
						<Loader2 class="w-3 h-3 text-indigo-400 animate-spin inline ml-1" />
					{/if}
				</td>
				<td class="px-3 py-2 hidden lg:table-cell">
					<span class="text-xs text-[var(--text-muted)]">{reasonLabels[u.reason] || u.reason}</span>
				</td>
				<td class="px-3 py-2 text-center hidden sm:table-cell">
					<span class="text-xs text-[var(--text-muted)]">{u.attempts}/{u.max_attempts}</span>
				</td>
				<td class="px-3 py-2 text-right">
					<div class="flex items-center gap-1 justify-end">
						{#if u.status === 'pending'}
							<button onclick={() => skipUpgrade(u.id)} class="p-2 min-w-[44px] min-h-[44px] flex items-center justify-center text-[var(--text-muted)] hover:text-amber-400 transition-colors" title="Skip">
								<SkipForward class="w-4 h-4" />
							</button>
						{:else if u.status === 'failed'}
							<button onclick={() => retryUpgrade(u.id)} class="p-2 min-w-[44px] min-h-[44px] flex items-center justify-center text-[var(--text-muted)] hover:text-blue-400 transition-colors" title="Retry">
								<RotateCcw class="w-4 h-4" />
							</button>
						{/if}
					</div>
				</td>
			{/snippet}
		</DataTable>

		<Pagination {total} {offset} limit={perPage} onchange={handlePageChange} />
	{/if}
</div>
