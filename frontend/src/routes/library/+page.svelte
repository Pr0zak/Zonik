<script>
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';
	import { currentTrack, addToast } from '$lib/stores.js';
	import { formatDuration, formatSize, debounce } from '$lib/utils.js';
	import { Search, ScanLine, ArrowUpDown, Download, X, CheckSquare, Square, Trash2 } from 'lucide-svelte';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Button from '../../components/ui/Button.svelte';
	import Badge from '../../components/ui/Badge.svelte';
	import Skeleton from '../../components/ui/Skeleton.svelte';
	import Modal from '../../components/ui/Modal.svelte';
	import EmptyState from '../../components/ui/EmptyState.svelte';

	let tracks = $state([]);
	let total = $state(0);
	let search = $state('');
	let offset = $state(0);
	let limit = 50;
	let sort = $state('title');
	let order = $state('asc');
	let scanning = $state(false);
	let loading = $state(true);

	let selectMode = $state(false);
	let selected = $state(new Set());

	function toggleSelectMode() {
		selectMode = !selectMode;
		if (!selectMode) selected = new Set();
	}

	function toggleSelect(trackId) {
		const next = new Set(selected);
		if (next.has(trackId)) next.delete(trackId);
		else next.add(trackId);
		selected = next;
	}

	function toggleSelectAll() {
		if (selected.size === tracks.length) {
			selected = new Set();
		} else {
			selected = new Set(tracks.map(t => t.id));
		}
	}

	async function bulkDelete() {
		if (!selected.size) return;
		if (!window.confirm(`Delete ${selected.size} track(s) and their files? This cannot be undone.`)) return;
		try {
			const result = await api.bulkDeleteTracks([...selected]);
			addToast(`Deleted ${result.deleted} track(s)`, 'success');
			selected = new Set();
			await loadTracks();
		} catch (e) {
			addToast('Bulk delete failed: ' + e.message, 'error');
		}
	}

	async function bulkAnalyze() {
		if (!selected.size) return;
		try {
			const result = await api.bulkAnalyzeTracks([...selected]);
			addToast(`Queued ${result.queued} track(s) for analysis`, 'success');
			selected = new Set();
		} catch (e) {
			addToast('Bulk analyze failed: ' + e.message, 'error');
		}
	}

	let showSimilar = $state(false);
	let similarSource = $state(null);
	let similarTracks = $state([]);
	let similarLoading = $state(false);
	let similarTab = $state('lastfm');

	async function loadTracks() {
		try {
			const result = await api.getTracks({ offset, limit, sort, order, search: search || undefined });
			tracks = result.tracks;
			total = result.total;
		} catch (e) {
			console.error('Failed to load tracks:', e);
		} finally {
			loading = false;
		}
	}

	onMount(loadTracks);

	async function scanLibrary() {
		scanning = true;
		try {
			await api.scanLibrary();
			addToast('Library scan started', 'success');
		} catch (e) {
			addToast('Scan failed: ' + e.message, 'error');
		}
	}

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

	function sortIndicator(col) {
		if (sort !== col) return '';
		return order === 'asc' ? ' ^' : ' v';
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
	<PageHeader title="Library" color="var(--color-library)">
		<input type="text" placeholder="Search tracks..."
			bind:value={search} on:input={debouncedSearch}
			class="bg-[var(--bg-primary)] border border-[var(--border-interactive)] rounded-md px-3 py-2 text-sm w-64
				placeholder-[var(--text-disabled)] focus:outline-none focus:ring-1 focus:border-[var(--color-accent)]/50 focus:ring-[var(--color-accent)]/20" />
		<span class="text-sm text-[var(--text-muted)] font-mono">{total.toLocaleString()}</span>
		<Button variant={selectMode ? 'primary' : 'secondary'} size="sm" onclick={toggleSelectMode}>
			<CheckSquare class="w-3.5 h-3.5" />
			{selectMode ? 'Cancel' : 'Select'}
		</Button>
		{#if !selectMode}
			<Button variant="primary" size="sm" loading={scanning} onclick={scanLibrary}>
				<ScanLine class="w-3.5 h-3.5" />
				{scanning ? 'Scanning...' : 'Scan Library'}
			</Button>
		{/if}
	</PageHeader>

	{#if selectMode}
		<div class="flex items-center gap-3 mb-3 px-1">
			<span class="text-sm text-[var(--text-secondary)] font-medium">{selected.size} selected</span>
			<Button variant="secondary" size="sm" onclick={toggleSelectAll}>
				{selected.size === tracks.length ? 'Deselect All' : 'Select All'}
			</Button>
			{#if selected.size > 0}
				<Button variant="danger" size="sm" onclick={bulkDelete}>
					<Trash2 class="w-3.5 h-3.5" />
					Delete Selected
				</Button>
				<Button variant="primary" size="sm" onclick={bulkAnalyze}>
					<ScanLine class="w-3.5 h-3.5" />
					Analyze Selected
				</Button>
			{/if}
		</div>
	{/if}

	<Card padding="p-0">
		{#if loading}
			<div class="divide-y divide-[var(--border-subtle)]">
				{#each Array(10) as _}
					<div class="px-4 py-3 flex items-center gap-4">
						<Skeleton class="h-4 w-48" />
						<Skeleton class="h-4 w-28" />
						<Skeleton class="h-4 w-28 hidden md:block" />
						<Skeleton class="h-4 w-12 hidden lg:block" />
					</div>
				{/each}
			</div>
		{:else if tracks.length}
			<table class="w-full text-sm">
				<thead>
					<tr class="border-b border-[var(--border-subtle)] text-[var(--text-muted)] text-left">
						{#if selectMode}
							<th class="px-4 py-3 w-10">
								<input type="checkbox" checked={selected.size === tracks.length && tracks.length > 0}
									on:change={toggleSelectAll}
									class="rounded border-[var(--border-interactive)] bg-[var(--bg-primary)] text-[var(--color-accent)] cursor-pointer" />
							</th>
						{/if}
						<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider cursor-pointer hover:text-[var(--text-body)] transition-colors" on:click={() => toggleSort('title')}>Title{sortIndicator('title')}</th>
						<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider cursor-pointer hover:text-[var(--text-body)] transition-colors" on:click={() => toggleSort('artist')}>Artist{sortIndicator('artist')}</th>
						<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider cursor-pointer hover:text-[var(--text-body)] transition-colors hidden md:table-cell" on:click={() => toggleSort('album')}>Album{sortIndicator('album')}</th>
						<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider hidden lg:table-cell">Duration</th>
						<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider hidden lg:table-cell">Format</th>
						<th class="px-4 py-3 w-10"></th>
					</tr>
				</thead>
				<tbody class="divide-y divide-[var(--border-subtle)]">
					{#each tracks as track}
						<tr class="hover:bg-[var(--bg-hover)] cursor-pointer transition-colors group {selectMode && selected.has(track.id) ? 'bg-[var(--color-accent)]/10' : ''}"
							on:click={() => selectMode ? toggleSelect(track.id) : playTrack(track)}>
							{#if selectMode}
								<td class="px-4 py-3 w-10">
									<input type="checkbox" checked={selected.has(track.id)}
										on:click|stopPropagation={() => toggleSelect(track.id)}
										class="rounded border-[var(--border-interactive)] bg-[var(--bg-primary)] text-[var(--color-accent)] cursor-pointer" />
								</td>
							{/if}
							<td class="px-4 py-3 font-medium text-[var(--text-primary)]">{track.title}</td>
							<td class="px-4 py-3 text-[var(--text-secondary)]">{track.artist || '-'}</td>
							<td class="px-4 py-3 text-[var(--text-secondary)] hidden md:table-cell">{track.album || '-'}</td>
							<td class="px-4 py-3 text-[var(--text-muted)] font-mono text-xs hidden lg:table-cell">{formatDuration(track.duration)}</td>
							<td class="px-4 py-3 hidden lg:table-cell">
								<Badge>{(track.format || '-').toUpperCase()}</Badge>
							</td>
							<td class="px-4 py-3">
								<button on:click={(e) => findSimilar(track, e)}
									title="Find similar tracks"
									class="opacity-0 group-hover:opacity-100 px-2 py-1 bg-[var(--color-accent)]/20 hover:bg-[var(--color-accent)]/30 text-[var(--color-accent-light)]
										rounded text-xs transition-all">
									Similar
								</button>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		{:else}
			<EmptyState
				title="No tracks found"
				description={search ? 'Try a different search term.' : 'Scan your library to import tracks.'}
			>
				{#snippet icon()}<Search class="w-10 h-10" />{/snippet}
			</EmptyState>
		{/if}
	</Card>

	{#if total > limit}
		<div class="flex justify-center items-center gap-3 mt-4">
			<Button variant="secondary" size="sm"
				disabled={offset === 0}
				onclick={() => { offset = Math.max(0, offset - limit); loadTracks(); }}>
				Prev
			</Button>
			<span class="text-sm text-[var(--text-muted)] font-mono">
				{offset + 1}-{Math.min(offset + limit, total)} of {total}
			</span>
			<Button variant="secondary" size="sm"
				disabled={offset + limit >= total}
				onclick={() => { offset += limit; loadTracks(); }}>
				Next
			</Button>
		</div>
	{/if}
</div>

<!-- Similar Tracks Modal -->
<Modal bind:open={showSimilar} title="Find Similar">
	{#snippet children()}
		{#if similarSource}
			<p class="text-sm text-[var(--text-secondary)] mb-3">
				{similarSource.title} - {similarSource.artist}
			</p>
		{/if}

		<div class="flex gap-1 mb-4">
			<button on:click={() => switchTab('lastfm')}
				class="px-3 py-1 rounded-md text-xs font-medium transition-colors
					{similarTab === 'lastfm' ? 'bg-[var(--color-accent)] text-white' : 'bg-[var(--bg-hover)] text-[var(--text-secondary)] hover:text-white'}">
				Last.fm Similar
			</button>
			<button on:click={() => switchTab('vibe')}
				class="px-3 py-1 rounded-md text-xs font-medium transition-colors
					{similarTab === 'vibe' ? 'bg-purple-600 text-white' : 'bg-[var(--bg-hover)] text-[var(--text-secondary)] hover:text-white'}">
				Vibe Match
			</button>
		</div>

		{#if similarLoading}
			<div class="space-y-2 py-4">
				{#each Array(5) as _}
					<Skeleton class="h-10 rounded" />
				{/each}
			</div>
		{:else if similarTracks.length}
			<div class="space-y-1">
				{#each similarTracks as t}
					<div class="flex items-center justify-between px-3 py-2 rounded-md hover:bg-[var(--bg-hover)] text-sm transition-colors">
						<div class="flex-1 min-w-0">
							<span class="font-medium text-[var(--text-primary)]">{t.name}</span>
							<span class="text-[var(--text-secondary)]"> - {t.artist}</span>
						</div>
						<div class="flex items-center gap-2 ml-3 shrink-0">
							{#if t.match != null}
								<span class="text-xs text-[var(--text-muted)] font-mono">{Math.round((t.match || 0) * 100)}%</span>
							{/if}
							{#if t.in_library}
								<Badge variant="success">In Library</Badge>
							{:else}
								<Button variant="success" size="sm" onclick={() => downloadSimilar(t)}>
									<Download class="w-3 h-3" />
									Download
								</Button>
							{/if}
						</div>
					</div>
				{/each}
			</div>
		{:else}
			<p class="text-[var(--text-muted)] text-center py-8 text-sm">
				{similarTab === 'vibe' ? 'No vibe embeddings for this track yet. Run audio analysis first.' : 'No similar tracks found.'}
			</p>
		{/if}
	{/snippet}

	{#snippet footer()}
		{#if similarTracks.some(t => !t.in_library)}
			<div class="flex items-center justify-between">
				<span class="text-xs text-[var(--text-muted)]">
					{similarTracks.filter(t => !t.in_library).length} not in library
				</span>
				<Button variant="success" size="sm" onclick={downloadAllMissing}>
					<Download class="w-3 h-3" />
					Download All Missing
				</Button>
			</div>
		{/if}
	{/snippet}
</Modal>
