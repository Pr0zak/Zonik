<script>
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';
	import { addToast, activeJobs } from '$lib/stores.js';
	import { formatSize } from '$lib/utils.js';
	import { Download, Search, Zap, ShieldBan, Trash2, ListOrdered, ArrowDownToLine, RefreshCw } from 'lucide-svelte';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Button from '../../components/ui/Button.svelte';
	import Badge from '../../components/ui/Badge.svelte';

	let artist = $state('');
	let track = $state('');
	let results = $state([]);
	let searching = $state(false);
	let downloading = $state({});

	let blacklist = $state([]);
	let blArtist = $state('');
	let blTrack = $state('');
	let blReason = $state('');
	let showBlacklist = $state(false);

	let recentDlJobs = $state([]);
	let activeDlJobs = $derived($activeJobs.filter(j => j.type === 'download' || j.type === 'bulk_download'));
	let completedDlJobs = $derived(recentDlJobs.filter(j => j.status !== 'running'));
	let showQueue = $derived(activeDlJobs.length > 0 || completedDlJobs.length > 0);

	// slskd transfer queue
	let slskdTransfers = $state([]);
	let transfersLoading = $state(false);
	let transferPollTimer = $state(null);

	async function loadTransfers() {
		transfersLoading = true;
		try {
			const data = await fetch('/api/download/status').then(r => r.json());
			// Flatten: each user has files array
			const flat = [];
			for (const user of (data.downloads || [])) {
				for (const file of (user.files || [])) {
					flat.push({
						username: user.username,
						filename: file.filename?.split(/[/\\]/).pop() || file.filename,
						state: file.state,
						bytesTransferred: file.bytesTransferred || 0,
						size: file.size || 0,
						averageSpeed: file.averageSpeed || 0,
					});
				}
			}
			slskdTransfers = flat;
		} catch { slskdTransfers = []; }
		finally { transfersLoading = false; }
	}

	onMount(() => {
		loadBlacklist();
		loadRecentJobs();
		loadTransfers();
		// Poll transfers every 5s
		transferPollTimer = setInterval(loadTransfers, 5000);
		return () => { if (transferPollTimer) clearInterval(transferPollTimer); };
	});

	async function loadRecentJobs() {
		try {
			const jobs = await fetch('/api/jobs?limit=10').then(r => r.json());
			recentDlJobs = (jobs || []).filter(j => j.type === 'download' || j.type === 'bulk_download').slice(0, 5);
		} catch (e) { console.error(e); }
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
</script>

<div class="max-w-6xl">
	<PageHeader title="Downloads" color="var(--color-downloads)" />

	<!-- Download Queue -->
	{#if showQueue}
		<Card padding="p-6" class="mb-6">
			<div class="flex items-center gap-2 mb-4">
				<ListOrdered class="w-4 h-4 text-[var(--color-downloads)]" />
				<h2 class="text-base font-semibold text-[var(--text-primary)]">Download Queue</h2>
			</div>

			{#if activeDlJobs.length}
				<div class="space-y-3 mb-4">
					{#each activeDlJobs as job (job.id)}
						<div class="flex items-center gap-3 px-3 py-2.5 bg-[var(--bg-tertiary)] rounded-md animate-fade-slide-in">
							<Badge variant="info">{job.type === 'bulk_download' ? 'bulk' : 'download'}</Badge>
							<div class="flex-1 min-w-0">
								{#if job.total}
									<div class="flex items-center justify-between mb-1">
										<span class="text-xs text-[var(--text-secondary)]">{job.progress || 0} of {job.total} tracks</span>
										<span class="text-xs text-[var(--text-muted)] font-mono">{Math.round(((job.progress || 0) / job.total) * 100)}%</span>
									</div>
								{/if}
								<div class="h-1.5 bg-[var(--border-interactive)] rounded-full overflow-hidden">
									<div class="h-full bg-[var(--color-downloads)] rounded-full transition-all duration-300"
										style="width: {job.total ? ((job.progress || 0) / job.total) * 100 : 50}%"></div>
								</div>
							</div>
							<Badge variant="info">running</Badge>
						</div>
					{/each}
				</div>
			{/if}

			{#if completedDlJobs.length}
				<div class="space-y-2">
					{#each completedDlJobs as job (job.id)}
						<div class="flex items-center gap-3 px-3 py-2 bg-[var(--bg-tertiary)] rounded-md text-sm animate-fade-slide-in">
							<Badge>{job.type === 'bulk_download' ? 'bulk' : 'download'}</Badge>
							<span class="flex-1 text-[var(--text-secondary)] truncate">{job.description || job.type}</span>
							{#if job.total}
								<span class="text-xs text-[var(--text-muted)] font-mono">{job.progress || job.total}/{job.total}</span>
							{/if}
							<Badge variant={job.status === 'completed' ? 'success' : job.status === 'failed' ? 'error' : 'info'}>{job.status}</Badge>
						</div>
					{/each}
				</div>
			{/if}
		</Card>
	{/if}

	<!-- slskd Active Transfers -->
	{#if slskdTransfers.length > 0 || transfersLoading}
		<Card padding="p-6" class="mb-6">
			<div class="flex items-center justify-between mb-4">
				<div class="flex items-center gap-2">
					<ArrowDownToLine class="w-4 h-4 text-[var(--color-downloads)]" />
					<h2 class="text-base font-semibold text-[var(--text-primary)]">Active Transfers</h2>
					<Badge>{slskdTransfers.length}</Badge>
				</div>
				<button onclick={loadTransfers} class="p-1.5 text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors">
					<RefreshCw class="w-3.5 h-3.5 {transfersLoading ? 'animate-spin' : ''}" />
				</button>
			</div>
			{#if slskdTransfers.length}
				<div class="space-y-2">
					{#each slskdTransfers as t}
						<div class="flex items-center gap-3 px-3 py-2 bg-[var(--bg-tertiary)] rounded-md text-sm">
							<div class="flex-1 min-w-0">
								<p class="text-[var(--text-primary)] truncate font-medium">{t.filename}</p>
								<p class="text-xs text-[var(--text-muted)] truncate">from {t.username}</p>
							</div>
							{#if t.size > 0}
								<div class="w-24 flex-shrink-0">
									<div class="h-1.5 bg-[var(--border-interactive)] rounded-full overflow-hidden">
										<div class="h-full bg-[var(--color-downloads)] rounded-full transition-all"
											style="width: {Math.min(100, (t.bytesTransferred / t.size) * 100)}%"></div>
									</div>
									<p class="text-[10px] text-[var(--text-muted)] mt-0.5 text-right">{Math.round((t.bytesTransferred / t.size) * 100)}%</p>
								</div>
							{/if}
							{#if t.averageSpeed > 0}
								<span class="text-xs text-[var(--text-muted)] font-mono flex-shrink-0">{formatSize(t.averageSpeed)}/s</span>
							{/if}
							<Badge variant={
								t.state === 'Completed' || t.state === 'Succeeded' ? 'success' :
								t.state === 'InProgress' || t.state === 'Downloading' ? 'info' :
								t.state === 'Queued' || t.state === 'Requested' ? 'default' : 'error'
							}>{t.state}</Badge>
						</div>
					{/each}
				</div>
			{:else}
				<p class="text-sm text-[var(--text-muted)] text-center py-4">No active transfers</p>
			{/if}
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
									<Button variant="success" size="sm" loading={downloading[key]} onclick={() => downloadFile(r)}>
										<Download class="w-3 h-3" />
									</Button>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
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

			{#if blacklist.length}
				<div class="space-y-1 animate-fade-slide-in">
					{#each blacklist as entry}
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
				<p class="text-[var(--text-muted)] text-sm">No blacklisted artists or tracks.</p>
			{/if}
		{/if}
	</Card>
</div>
