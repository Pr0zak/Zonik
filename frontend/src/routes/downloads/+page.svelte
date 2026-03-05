<script>
	import { onMount, onDestroy } from 'svelte';
	import { api } from '$lib/api.js';
	import { addToast, activeTransfers } from '$lib/stores.js';
	import { onJobUpdate } from '$lib/websocket.js';
	import { formatSize, formatSpeed, formatETA } from '$lib/utils.js';
	import { Download, Search, Zap, ShieldBan, Trash2, ArrowDownToLine, X, ChevronLeft, ChevronRight, ChevronDown, ChevronUp, RotateCcw, Eraser } from 'lucide-svelte';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Button from '../../components/ui/Button.svelte';
	import Badge from '../../components/ui/Badge.svelte';

	// Search state
	let artist = $state('');
	let track = $state('');
	let results = $state([]);
	let searching = $state(false);
	let downloading = $state({});

	// Blacklist state
	let blacklist = $state([]);
	let blArtist = $state('');
	let blTrack = $state('');
	let blReason = $state('');
	let showBlacklist = $state(false);
	let blSearch = $state('');
	let blSearching = $state(false);
	let blSearchResults = $state([]);
	let blFilter = $state('');
	let filteredBlacklist = $derived(
		blFilter.trim()
			? blacklist.filter(e =>
				e.artist.toLowerCase().includes(blFilter.toLowerCase()) ||
				(e.track && e.track.toLowerCase().includes(blFilter.toLowerCase())))
			: blacklist
	);

	// History state
	let history = $state([]);
	let historyOffset = $state(0);
	let historyLoading = $state(false);
	let expandedJob = $state(null);
	let jobDetails = $state({});
	const HISTORY_LIMIT = 20;

	function transferStateBadge(state) {
		if (state === 'completed') return 'success';
		if (state === 'transferring' || state === 'connected') return 'info';
		if (state === 'requested' || state === 'queued') return 'default';
		return 'error';
	}

	async function loadHistory() {
		historyLoading = true;
		try {
			history = await api.getDownloadHistory(historyOffset, HISTORY_LIMIT);
		} catch (e) { console.error(e); }
		finally { historyLoading = false; }
	}

	async function toggleJobDetail(jobId) {
		if (expandedJob === jobId) { expandedJob = null; return; }
		expandedJob = jobId;
		if (!jobDetails[jobId]) {
			try {
				const detail = await api.getJob(jobId);
				if (detail?.tracks) {
					jobDetails[jobId] = JSON.parse(detail.tracks);
				}
			} catch {}
		}
	}

	async function retryJob(jobId) {
		try {
			await api.retryJob(jobId);
			addToast('Retry started', 'success');
			await loadHistory();
		} catch { addToast('Retry failed', 'error'); }
	}

	async function cancelTransfer(username, filename) {
		try {
			await api.cancelTransfer(username, filename);
			addToast('Transfer cancelled', 'success');
		} catch { addToast('Cancel failed', 'error'); }
	}

	// Blacklist
	async function searchLibraryForBlacklist() {
		if (!blSearch.trim()) return;
		blSearching = true;
		try {
			const data = await api.getArtists({ search: blSearch.trim(), limit: 20 });
			const artists = (data.artists || data || []).map(a => a.name).filter(Boolean);
			blSearchResults = artists;
			if (!artists.length) addToast('No matching artists found', 'warning');
		} catch (e) { addToast('Search failed', 'error'); }
		finally { blSearching = false; }
	}

	async function loadBlacklist() {
		try {
			blacklist = await fetch('/api/download/blacklist').then(r => r.json());
		} catch (e) { console.error(e); }
	}

	async function addBlacklistEntry() {
		if (!blArtist.trim()) return;
		try {
			await fetch('/api/download/blacklist', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					artist: blArtist.trim(),
					track: blTrack.trim() || null,
					reason: blReason.trim() || null,
				})
			});
			blArtist = ''; blTrack = ''; blReason = '';
			await loadBlacklist();
			addToast('Added to blacklist', 'success');
		} catch (e) { addToast('Failed to add', 'error'); }
	}

	async function removeBlacklistEntry(id) {
		try {
			await fetch(`/api/download/blacklist/${id}`, { method: 'DELETE' });
			await loadBlacklist();
		} catch (e) { addToast('Failed to remove', 'error'); }
	}

	// Soulseek Search
	async function searchSoulseek() {
		if (!artist.trim() || !track.trim()) return;
		searching = true;
		results = [];
		try {
			const data = await fetch('/api/download/search', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ artist: artist.trim(), track: track.trim() })
			}).then(r => r.json());
			results = data.results || [];
			if (!results.length) addToast('No results found', 'warning');
		} catch (e) {
			addToast('Search failed: ' + e.message, 'error');
		} finally {
			searching = false;
		}
	}

	async function downloadFile(result) {
		const key = result.username + result.filename;
		downloading[key] = true;
		try {
			await fetch('/api/download/trigger', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					artist: artist.trim(),
					track: track.trim(),
					username: result.username,
					filename: result.filename,
				})
			}).then(r => r.json());
			addToast('Download started', 'success');
		} catch (e) {
			addToast('Download failed: ' + e.message, 'error');
		} finally {
			downloading[key] = false;
		}
	}

	async function autoDownload() {
		try {
			await fetch('/api/download/trigger', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ artist: artist.trim(), track: track.trim() })
			}).then(r => r.json());
			addToast('Auto-download started (best result)', 'success');
		} catch (e) {
			addToast('Download failed: ' + e.message, 'error');
		}
	}

	function handleKeydown(e) {
		if (e.key === 'Enter') searchSoulseek();
	}

	let unsubJobUpdate;

	onMount(() => {
		loadBlacklist();
		loadHistory();
		// Seed transfers from REST on mount (WebSocket takes over after)
		fetch('/api/download/status').then(r => r.json()).then(data => {
			if (data.downloads?.length) activeTransfers.set(data.downloads);
		}).catch(() => {});
		// Auto-refresh when any download job updates
		unsubJobUpdate = onJobUpdate((job) => {
			if (job.type === 'download' || job.type === 'bulk_download') {
				loadHistory();
			}
		});
	});

	onDestroy(() => {
		if (unsubJobUpdate) unsubJobUpdate();
	});
</script>

<div class="max-w-6xl">
	<PageHeader title="Downloads" color="var(--color-downloads)" />

	<!-- Active Transfers (WebSocket-driven) -->
	{#if $activeTransfers.length > 0}
		<Card padding="p-6" class="mb-6">
			<div class="flex items-center gap-2 mb-4">
				<ArrowDownToLine class="w-4 h-4 text-[var(--color-downloads)]" />
				<h2 class="text-base font-semibold text-[var(--text-primary)]">Active Transfers</h2>
				<Badge>{$activeTransfers.length}</Badge>
			</div>
			<div class="space-y-2">
				{#each $activeTransfers.slice(0, 10) as t}
					{@const shortName = t.filename?.split(/[/\\]/).pop() || t.filename}
					<div class="bg-[var(--bg-tertiary)] rounded-lg overflow-hidden animate-fade-slide-in">
						<div class="flex items-center gap-3 px-4 py-2.5">
							<div class="flex-1 min-w-0">
								<p class="text-sm text-[var(--text-primary)] font-medium truncate" title={t.filename}>{shortName}</p>
								<p class="text-xs text-[var(--text-muted)] truncate">from {t.username}</p>
							</div>
							{#if t.speed > 0}
								<span class="text-xs text-[var(--text-muted)] font-mono flex-shrink-0">{formatSpeed(t.speed)}</span>
							{/if}
							{#if t.eta_seconds != null && t.eta_seconds > 0}
								<span class="text-xs text-[var(--text-disabled)] font-mono flex-shrink-0">{formatETA(t.eta_seconds)}</span>
							{/if}
							{#if t.total_bytes > 0}
								<span class="text-xs text-[var(--text-disabled)] font-mono flex-shrink-0 hidden sm:inline">
									{formatSize(t.received_bytes)} / {formatSize(t.total_bytes)}
								</span>
							{/if}
							<Badge variant={transferStateBadge(t.state)}>{t.state}</Badge>
							{#if t.state !== 'completed' && t.state !== 'failed' && t.state !== 'denied'}
								<button onclick={() => cancelTransfer(t.username, t.filename)}
									class="text-[var(--text-muted)] hover:text-red-400 transition-colors flex-shrink-0" title="Cancel">
									<X class="w-3.5 h-3.5" />
								</button>
							{/if}
						</div>
						{#if t.total_bytes > 0 && t.state === 'transferring'}
							<div class="h-1 bg-[var(--border-interactive)]">
								<div class="h-full bg-[var(--color-downloads)] transition-all duration-300"
									style="width: {t.progress}%"></div>
							</div>
						{/if}
					</div>
				{/each}
			</div>
		</Card>
	{/if}

	<!-- Soulseek Search -->
	<Card padding="p-6" class="mb-6">
		<div class="flex items-center gap-2 mb-4">
			<Search class="w-4 h-4 text-[var(--color-downloads)]" />
			<h2 class="text-base font-semibold text-[var(--text-primary)]">Soulseek Search</h2>
		</div>
		<div class="flex flex-col sm:flex-row gap-3 mb-4">
			<input type="text" placeholder="Artist" bind:value={artist} onkeydown={handleKeydown}
				class="flex-1 bg-[var(--bg-primary)] border border-[var(--border-interactive)] rounded-md px-3 py-2 text-sm text-[var(--text-body)]
					placeholder-[var(--text-disabled)] focus:outline-none focus:ring-1 focus:border-[var(--color-accent)]/50 focus:ring-[var(--color-accent)]/20" />
			<input type="text" placeholder="Track" bind:value={track} onkeydown={handleKeydown}
				class="flex-1 bg-[var(--bg-primary)] border border-[var(--border-interactive)] rounded-md px-3 py-2 text-sm text-[var(--text-body)]
					placeholder-[var(--text-disabled)] focus:outline-none focus:ring-1 focus:border-[var(--color-accent)]/50 focus:ring-[var(--color-accent)]/20" />
			<div class="flex gap-2">
				<Button variant="primary" loading={searching} disabled={!artist || !track} onclick={searchSoulseek}>
					<Search class="w-3.5 h-3.5" />
					Search
				</Button>
				<Button variant="success" disabled={!artist || !track} onclick={autoDownload}>
					<Zap class="w-3.5 h-3.5" />
					Auto
				</Button>
			</div>
		</div>

		{#if results.length}
			<div class="border border-[var(--border-subtle)] rounded-lg overflow-hidden overflow-x-auto">
				<table class="w-full text-sm min-w-[400px]">
					<thead>
						<tr class="border-b border-[var(--border-subtle)] text-[var(--text-muted)] text-left">
							<th class="px-4 py-2 font-medium text-xs uppercase tracking-wider">File</th>
							<th class="px-4 py-2 font-medium text-xs uppercase tracking-wider hidden md:table-cell">User</th>
							<th class="px-4 py-2 font-medium text-xs uppercase tracking-wider">Format</th>
							<th class="px-4 py-2 font-medium text-xs uppercase tracking-wider hidden sm:table-cell">Size</th>
							<th class="px-4 py-2 font-medium text-xs uppercase tracking-wider hidden lg:table-cell">Bitrate</th>
							<th class="px-4 py-2"></th>
						</tr>
					</thead>
					<tbody class="divide-y divide-[var(--border-subtle)]">
						{#each results as r}
							{@const key = r.username + r.filename}
							<tr class="hover:bg-[var(--bg-hover)] transition-colors">
								<td class="px-4 py-2 max-w-xs truncate text-[var(--text-body)]" title={r.filename}>
									{r.filename.split(/[/\\]/).pop()}
								</td>
								<td class="px-4 py-2 text-[var(--text-secondary)] hidden md:table-cell">{r.username}</td>
								<td class="px-4 py-2">
									<Badge>{(r.extension || '').toUpperCase()}</Badge>
								</td>
								<td class="px-4 py-2 text-[var(--text-muted)] font-mono text-xs hidden sm:table-cell">{formatSize(r.size)}</td>
								<td class="px-4 py-2 text-[var(--text-muted)] font-mono text-xs hidden lg:table-cell">{r.bitRate ? r.bitRate + ' kbps' : '-'}</td>
								<td class="px-4 py-2">
									<div class="flex gap-1">
										<Button variant="success" size="sm" loading={downloading[key]} onclick={() => downloadFile(r)}>
											<Download class="w-3 h-3" />
										</Button>
										<button onclick={async () => {
											if (!window.confirm(`Blacklist artist "${artist.trim()}"?`)) return;
											try {
												await fetch('/api/download/blacklist', {
													method: 'POST',
													headers: { 'Content-Type': 'application/json' },
													body: JSON.stringify({ artist: artist.trim() })
												});
												await loadBlacklist();
												addToast(`Blacklisted: ${artist.trim()}`, 'success');
											} catch { addToast('Failed to blacklist', 'error'); }
										}} class="p-1.5 rounded-md text-[var(--text-muted)] hover:text-orange-400 hover:bg-[var(--bg-hover)] transition-colors"
											title="Blacklist artist">
											<ShieldBan class="w-3.5 h-3.5" />
										</button>
									</div>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</Card>

	<!-- Download Jobs -->
	<Card padding="p-6" class="mb-6">
		<div class="flex items-center justify-between mb-4">
			<div class="flex items-center gap-2">
				<Download class="w-4 h-4 text-[var(--color-downloads)]" />
				<h2 class="text-base font-semibold text-[var(--text-primary)]">Download Jobs</h2>
			</div>
			{#if history.some(j => j.status === 'completed' || j.status === 'failed')}
				<button onclick={async () => {
					if (!window.confirm('Clear completed/failed downloads?')) return;
					try {
						await api.clearDownloadHistory();
						history = [];
						historyOffset = 0;
						jobDetails = {};
						expandedJob = null;
						addToast('History cleared', 'success');
					} catch { addToast('Failed to clear history', 'error'); }
				}} class="flex items-center gap-1.5 text-xs text-[var(--text-muted)] hover:text-red-400 transition-colors">
					<Eraser class="w-3.5 h-3.5" />
					Clear
				</button>
			{/if}
		</div>

		{#if historyLoading && !history.length}
			<p class="text-sm text-[var(--text-muted)] text-center py-6">Loading...</p>
		{:else if history.length}
			<div class="space-y-2">
				{#each history as job (job.id)}
					<div class="bg-[var(--bg-tertiary)] rounded-lg overflow-hidden">
						<!-- Job header -->
						<button onclick={() => toggleJobDetail(job.id)}
							class="w-full flex items-center gap-3 px-4 py-3 hover:bg-[var(--bg-hover)] transition-colors text-left">
							<div class="flex-1 min-w-0">
								<p class="text-sm text-[var(--text-primary)] font-medium truncate">{job.description || job.type}</p>
								<p class="text-xs text-[var(--text-muted)]">
									{#if job.total}{job.progress || 0}/{job.total} tracks &middot; {/if}
									{job.started_at ? new Date(job.started_at).toLocaleString() : ''}
								</p>
							</div>
							{#if job.status === 'failed'}
								<button onclick={(e) => { e.stopPropagation(); retryJob(job.id); }}
									class="p-1.5 text-[var(--text-muted)] hover:text-[var(--color-downloads)] transition-colors" title="Retry failed tracks">
									<RotateCcw class="w-3.5 h-3.5" />
								</button>
							{/if}
							<Badge variant={job.status === 'running' || job.status === 'pending' ? 'info' : job.status === 'completed' ? 'success' : 'error'}>
								{#if job.status === 'running'}
									<span class="inline-block w-1.5 h-1.5 rounded-full bg-current animate-pulse mr-1"></span>
								{/if}
								{job.status}
							</Badge>
							{#if expandedJob === job.id}
								<ChevronUp class="w-3.5 h-3.5 text-[var(--text-muted)]" />
							{:else}
								<ChevronDown class="w-3.5 h-3.5 text-[var(--text-muted)]" />
							{/if}
						</button>
						<!-- Progress bar for running jobs -->
						{#if job.status === 'running' && job.total}
							<div class="h-1 bg-[var(--border-interactive)]">
								<div class="h-full bg-[var(--color-downloads)] transition-all duration-500"
									style="width: {((job.progress || 0) / job.total) * 100}%"></div>
							</div>
						{/if}
						<!-- Expanded track details -->
						{#if expandedJob === job.id && jobDetails[job.id]}
							<div class="px-4 py-2 space-y-1 border-t border-[var(--border-subtle)] animate-fade-slide-in">
								{#each jobDetails[job.id] as t, i}
									<div class="flex items-center gap-2 text-xs py-1">
										<span class="w-4 text-center text-[var(--text-disabled)]">{i + 1}</span>
										<span class="flex-1 min-w-0 truncate text-[var(--text-body)]">
											{t.artist} — {t.track}
										</span>
										{#if t.filename}
											<span class="text-[var(--text-muted)] truncate max-w-[200px] hidden sm:inline" title={t.filename}>{t.filename}</span>
										{/if}
										{#if t.username}
											<span class="text-[var(--text-disabled)] hidden md:inline">from {t.username}</span>
										{/if}
										{#if t.size}
											<span class="text-[var(--text-disabled)] font-mono hidden lg:inline">{formatSize(t.size)}</span>
										{/if}
										<Badge variant={
											t.status === 'downloaded' ? 'success' :
											t.status === 'downloading' || t.status === 'transferring' ? 'info' :
											t.status === 'pending' ? 'default' :
											t.status === 'skipped' ? 'warning' : 'error'
										}>{t.status}</Badge>
									</div>
								{/each}
							</div>
						{/if}
					</div>
				{/each}
			</div>

			<!-- Pagination -->
			<div class="flex items-center justify-between mt-4">
				<Button variant="ghost" size="sm" disabled={historyOffset === 0}
					onclick={() => { historyOffset = Math.max(0, historyOffset - HISTORY_LIMIT); loadHistory(); }}>
					<ChevronLeft class="w-3.5 h-3.5" />
					Prev
				</Button>
				<span class="text-xs text-[var(--text-muted)]">
					{historyOffset + 1}–{historyOffset + history.length}
				</span>
				<Button variant="ghost" size="sm" disabled={history.length < HISTORY_LIMIT}
					onclick={() => { historyOffset += HISTORY_LIMIT; loadHistory(); }}>
					Next
					<ChevronRight class="w-3.5 h-3.5" />
				</Button>
			</div>
		{:else}
			<p class="text-sm text-[var(--text-muted)] text-center py-6">No downloads yet.</p>
		{/if}
	</Card>

	<!-- Blacklist -->
	<Card padding="p-6">
		<div class="flex items-center justify-between mb-4">
			<div class="flex items-center gap-2">
				<ShieldBan class="w-4 h-4 text-red-400" />
				<h2 class="text-base font-semibold text-[var(--text-primary)]">Download Blacklist</h2>
			</div>
			<button onclick={() => showBlacklist = !showBlacklist}
				class="text-xs text-[var(--text-muted)] hover:text-white transition-colors font-mono">
				{showBlacklist ? 'Hide' : 'Show'} ({blacklist.length})
			</button>
		</div>

		{#if showBlacklist}
			<!-- Search library to blacklist -->
			<div class="mb-4 animate-fade-slide-in">
				<div class="flex flex-col sm:flex-row gap-2 mb-2">
					<input type="text" placeholder="Search library to blacklist..." bind:value={blSearch}
						onkeydown={(e) => e.key === 'Enter' && searchLibraryForBlacklist()}
						class="flex-1 bg-[var(--bg-primary)] border border-[var(--border-interactive)] rounded-md px-3 py-1.5 text-sm text-[var(--text-body)]
							placeholder-[var(--text-disabled)] focus:outline-none focus:ring-1 focus:border-[var(--color-accent)]/50 focus:ring-[var(--color-accent)]/20" />
					<Button variant="secondary" size="sm" disabled={!blSearch.trim() || blSearching} onclick={searchLibraryForBlacklist}>
						<Search class="w-3 h-3" />
						Find
					</Button>
				</div>
				{#if blSearchResults.length}
					<div class="space-y-1 mb-3 max-h-48 overflow-y-auto">
						{#each blSearchResults as artist}
							<div class="flex items-center justify-between px-3 py-1.5 bg-[var(--bg-tertiary)] rounded-md text-sm hover:bg-[var(--bg-hover)] transition-colors">
								<span class="text-[var(--text-primary)]">{artist}</span>
								<button onclick={async () => {
									try {
										await fetch('/api/download/blacklist', {
											method: 'POST',
											headers: { 'Content-Type': 'application/json' },
											body: JSON.stringify({ artist })
										});
										await loadBlacklist();
										blSearchResults = blSearchResults.filter(a => a !== artist);
										addToast(`Blacklisted: ${artist}`, 'success');
									} catch { addToast('Failed to blacklist', 'error'); }
								}} class="flex items-center gap-1 text-xs text-orange-400 hover:text-orange-300 transition-colors">
									<ShieldBan class="w-3 h-3" /> Block
								</button>
							</div>
						{/each}
					</div>
				{/if}
			</div>
			<!-- Manual add -->
			<div class="flex flex-col sm:flex-row gap-2 mb-4 animate-fade-slide-in">
				<input type="text" placeholder="Artist *" bind:value={blArtist}
					class="flex-1 bg-[var(--bg-primary)] border border-[var(--border-interactive)] rounded-md px-3 py-1.5 text-sm text-[var(--text-body)]
						placeholder-[var(--text-disabled)] focus:outline-none focus:ring-1 focus:border-[var(--color-accent)]/50 focus:ring-[var(--color-accent)]/20" />
				<input type="text" placeholder="Track (blank = entire artist)" bind:value={blTrack}
					class="flex-1 bg-[var(--bg-primary)] border border-[var(--border-interactive)] rounded-md px-3 py-1.5 text-sm text-[var(--text-body)]
						placeholder-[var(--text-disabled)] focus:outline-none focus:ring-1 focus:border-[var(--color-accent)]/50 focus:ring-[var(--color-accent)]/20" />
				<input type="text" placeholder="Reason" bind:value={blReason}
					class="w-48 bg-[var(--bg-primary)] border border-[var(--border-interactive)] rounded-md px-3 py-1.5 text-sm text-[var(--text-body)]
						placeholder-[var(--text-disabled)] focus:outline-none focus:ring-1 focus:border-[var(--color-accent)]/50 focus:ring-[var(--color-accent)]/20" />
				<Button variant="danger" size="sm" disabled={!blArtist.trim()} onclick={addBlacklistEntry}>
					<ShieldBan class="w-3 h-3" />
					Block
				</Button>
			</div>

			{#if blacklist.length > 3}
				<div class="mb-2">
					<input type="text" placeholder="Filter blacklist..." bind:value={blFilter}
						class="w-full sm:w-64 bg-[var(--bg-primary)] border border-[var(--border-interactive)] rounded-md px-3 py-1.5 text-sm text-[var(--text-body)]
							placeholder-[var(--text-disabled)] focus:outline-none focus:ring-1 focus:border-[var(--color-accent)]/50 focus:ring-[var(--color-accent)]/20" />
				</div>
			{/if}
			{#if filteredBlacklist.length}
				<div class="space-y-1 animate-fade-slide-in">
					{#each filteredBlacklist as entry}
						<div class="flex items-center justify-between px-3 py-2 bg-[var(--bg-tertiary)] rounded-md text-sm hover:bg-[var(--bg-hover)] transition-colors">
							<div>
								<span class="font-medium text-[var(--text-primary)]">{entry.artist}</span>
								{#if entry.track}
									<span class="text-[var(--text-secondary)]"> - {entry.track}</span>
								{:else}
									<Badge variant="error" class="ml-2">all tracks</Badge>
								{/if}
								{#if entry.reason}
									<span class="text-[var(--text-muted)] text-xs ml-2">({entry.reason})</span>
								{/if}
							</div>
							<button onclick={() => removeBlacklistEntry(entry.id)}
								class="text-[var(--text-disabled)] hover:text-red-400 transition-colors">
								<Trash2 class="w-3.5 h-3.5" />
							</button>
						</div>
					{/each}
				</div>
			{:else}
				<p class="text-[var(--text-muted)] text-sm">{blFilter ? 'No matching entries.' : 'No blacklisted artists or tracks.'}</p>
			{/if}
		{/if}
	</Card>
</div>
