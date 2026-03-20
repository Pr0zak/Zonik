<script>
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/stores';
	import { api } from '$lib/api.js';
	import { ScrollText, ChevronDown, ChevronRight, RotateCcw, XCircle, Smartphone, Trash2, X } from 'lucide-svelte';
	import { addToast, activeJobs } from '$lib/stores.js';
	import { formatDateTime } from '$lib/utils.js';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Badge from '../../components/ui/Badge.svelte';
	import Button from '../../components/ui/Button.svelte';
	import Skeleton from '../../components/ui/Skeleton.svelte';
	import EmptyState from '../../components/ui/EmptyState.svelte';
	import Pagination from '../../components/ui/Pagination.svelte';
	import FilterPills from '../../components/ui/FilterPills.svelte';

	// --- View mode: 'jobs' or 'app' ---
	let viewMode = $state('jobs');

	// --- Jobs state ---
	let jobs = $state([]);
	let total = $state(0);
	let offset = $state(0);
	let limit = $state(25);
	let loading = $state(true);
	let expandedJob = $state(null);
	let jobDetail = $state(null);
	let retrying = $state(false);
	let categoryFilter = $state('all');
	let unsubJobs;
	let refreshInterval;

	const categories = [
		{ key: 'all', label: 'All' },
		{ key: 'downloads', label: 'Downloads', types: ['download', 'bulk_download'] },
		{ key: 'library', label: 'Library', types: ['library_scan'] },
		{ key: 'analysis', label: 'Analysis', types: ['audio_analysis', 'enrichment'] },
		{ key: 'discovery', label: 'Discovery', types: ['lastfm_top_tracks', 'discover_similar', 'discover_artists', 'lastfm_sync'] },
		{ key: 'playlists', label: 'Playlists', types: ['playlist_weekly_top', 'playlist_weekly_discover', 'playlist_favorites'] },
	];

	// --- App logs state ---
	let appLogs = $state([]);
	let appTotal = $state(0);
	let appOffset = $state(0);
	let appLimit = $state(25);
	let appLoading = $state(false);
	let expandedLog = $state(null);
	let logDetail = $state(null);

	async function loadJobs() {
		loading = true;
		try {
			const params = { limit, offset };
			const cat = categories.find(c => c.key === categoryFilter);
			if (cat?.types) params.type = cat.types.join(',');
			const data = await api.getJobs(params);
			jobs = data.items || data;
			total = data.total ?? jobs.length;
		} catch (e) {
			console.error('Failed to load jobs:', e);
		} finally {
			loading = false;
		}
	}

	async function loadAppLogs() {
		appLoading = true;
		try {
			const data = await api.getAppLogs({ offset: appOffset, limit: appLimit });
			appLogs = data.items || [];
			appTotal = data.total ?? 0;
		} catch (e) {
			console.error('Failed to load app logs:', e);
		} finally {
			appLoading = false;
		}
	}

	onMount(async () => {
		await loadJobs();

		// Auto-expand job from URL param (?job=<id>)
		const jobParam = new URLSearchParams(window.location.search).get('job');
		if (jobParam) {
			expandedJob = jobParam;
			try { jobDetail = await api.getJob(jobParam); } catch {}
			window.history.replaceState({}, '', '/logs');
		}

		unsubJobs = activeJobs.subscribe(active => {
			if (!active.length) return;
			for (const aj of active) {
				const idx = jobs.findIndex(j => j.id === aj.id);
				if (idx >= 0) {
					jobs[idx] = { ...jobs[idx], ...aj };
				} else if (offset === 0) {
					jobs = [{ ...aj, started_at: new Date().toISOString() }, ...jobs];
				}
			}
		});

		refreshInterval = setInterval(async () => {
			if (viewMode === 'jobs' && offset === 0) {
				try {
					const params = { limit, offset: 0 };
					const cat = categories.find(c => c.key === categoryFilter);
					if (cat?.types) params.type = cat.types.join(',');
					const data = await api.getJobs(params);
					const newJobs = data.items || data;
					const newTotal = data.total ?? newJobs.length;
					if (JSON.stringify(newJobs.map(j => j.id + j.status)) !== JSON.stringify(jobs.map(j => j.id + j.status))) {
						jobs = newJobs;
						total = newTotal;
					}
				} catch {}
			}
		}, 30000);
	});

	onDestroy(() => {
		if (unsubJobs) unsubJobs();
		if (refreshInterval) clearInterval(refreshInterval);
	});

	function switchView(mode) {
		viewMode = mode;
		if (mode === 'app' && !appLogs.length) loadAppLogs();
	}

	function changeCategory(key) {
		categoryFilter = key;
		offset = 0;
		loadJobs();
	}

	function handlePageChange(newOffset, newLimit) {
		offset = newOffset;
		limit = newLimit;
		loadJobs();
	}

	function handleAppPageChange(newOffset, newLimit) {
		appOffset = newOffset;
		appLimit = newLimit;
		loadAppLogs();
	}

	async function toggleExpand(job) {
		if (expandedJob === job.id) {
			expandedJob = null;
			jobDetail = null;
			return;
		}
		expandedJob = job.id;
		try {
			jobDetail = await api.getJob(job.id);
		} catch (e) {
			jobDetail = null;
		}
	}

	async function toggleLogExpand(log) {
		if (expandedLog === log.id) {
			expandedLog = null;
			logDetail = null;
			return;
		}
		expandedLog = log.id;
		try {
			logDetail = await api.getAppLog(log.id);
		} catch (e) {
			logDetail = null;
		}
	}

	async function deleteLog(logId) {
		try {
			await api.deleteAppLog(logId);
			addToast('Log deleted', 'success');
			if (expandedLog === logId) { expandedLog = null; logDetail = null; }
			await loadAppLogs();
		} catch (e) { addToast('Failed to delete', 'error'); }
	}

	async function cancelJob(jobId) {
		try {
			const result = await api.cancelJob(jobId);
			if (result.error) {
				addToast(result.error, 'error');
			} else {
				addToast('Job cancelled', 'success');
				await loadJobs();
			}
		} catch (e) { addToast('Failed to cancel', 'error'); }
	}

	async function retryJob(jobId) {
		retrying = true;
		try {
			const result = await api.retryJob(jobId);
			if (result.error) {
				addToast(result.error, 'error');
			} else {
				addToast('Retry job started', 'success');
				expandedJob = null;
				jobDetail = null;
				await loadJobs();
			}
		} catch (e) {
			addToast('Failed to retry job', 'error');
		} finally {
			retrying = false;
		}
	}

	function statusVariant(status) {
		switch (status) {
			case 'completed': return 'success';
			case 'failed': return 'error';
			case 'running': return 'info';
			case 'pending': return 'warning';
			default: return 'default';
		}
	}

	function formatJobDuration(start, end) {
		if (!start || !end) return '-';
		const ms = new Date(end) - new Date(start);
		const s = Math.floor(ms / 1000);
		if (s < 60) return `${s}s`;
		return `${Math.floor(s / 60)}m ${s % 60}s`;
	}

	function formatSize(bytes) {
		if (!bytes || bytes < 1024) return `${bytes ?? 0} B`;
		if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
		return `${(bytes / 1048576).toFixed(1)} MB`;
	}
</script>

<div class="max-w-6xl">
	<PageHeader title={viewMode === 'jobs' ? 'Job History' : 'App Logs'} color="var(--color-logs)">
		{#if viewMode === 'jobs' && $activeJobs.length > 0}
			<Badge variant="info">
				<span class="inline-block w-1.5 h-1.5 rounded-full bg-current animate-pulse mr-1.5"></span>
				Live
			</Badge>
		{/if}
	</PageHeader>

	<!-- View toggle -->
	<div class="flex gap-1 mb-4 bg-[var(--bg-secondary)] rounded-lg p-1 w-fit">
		<button onclick={() => switchView('jobs')}
			class="px-3 py-1.5 rounded-md text-sm font-medium transition-colors {viewMode === 'jobs' ? 'bg-[var(--bg-tertiary)] text-[var(--text-body)]' : 'text-[var(--text-muted)] hover:text-[var(--text-body)]'}">
			<ScrollText class="w-3.5 h-3.5 inline -mt-0.5 mr-1" />Jobs
		</button>
		<button onclick={() => switchView('app')}
			class="px-3 py-1.5 rounded-md text-sm font-medium transition-colors {viewMode === 'app' ? 'bg-[var(--bg-tertiary)] text-[var(--text-body)]' : 'text-[var(--text-muted)] hover:text-[var(--text-body)]'}">
			<Smartphone class="w-3.5 h-3.5 inline -mt-0.5 mr-1" />App Logs
			{#if appTotal > 0}
				<span class="ml-1 text-xs bg-[var(--bg-hover)] px-1.5 py-0.5 rounded-full">{appTotal}</span>
			{/if}
		</button>
	</div>

	{#if viewMode === 'jobs'}
		<!-- Category filters -->
		<FilterPills
			options={categories.map(c => ({ value: c.key, label: c.label, color: 'logs' }))}
			value={categoryFilter}
			onchange={changeCategory}
			class="mb-4 overflow-x-auto pb-1"
		/>

		<Card padding="p-0">
			{#if loading}
				<div class="divide-y divide-[var(--border-subtle)]">
					{#each Array(8) as _}
						<div class="px-4 py-3 flex items-center gap-4">
							<Skeleton class="h-4 w-24" />
							<Skeleton class="h-5 w-16 rounded-full" />
							<Skeleton class="h-4 w-12" />
							<Skeleton class="h-4 w-20 hidden md:block" />
							<Skeleton class="h-3 w-32" />
						</div>
					{/each}
				</div>
			{:else if jobs.length}
				<table class="w-full text-sm">
					<thead>
						<tr class="border-b border-[var(--border-subtle)] text-[var(--text-muted)] text-left">
							<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider">Type</th>
							<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider">Status</th>
							<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider hidden sm:table-cell">Progress</th>
							<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider hidden md:table-cell">Duration</th>
							<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider hidden sm:table-cell">Started</th>
						</tr>
					</thead>
					<tbody class="divide-y divide-[var(--border-subtle)]">
						{#each jobs as job}
							<!-- svelte-ignore a11y_click_events_have_key_events -->
							<tr class="hover:bg-[var(--bg-hover)] cursor-pointer transition-colors min-h-[44px]" onclick={() => toggleExpand(job)}>
								<td class="px-3 sm:px-4 py-3">
									<div class="flex items-center gap-2">
										{#if expandedJob === job.id}
											<ChevronDown class="w-3.5 h-3.5 text-[var(--text-muted)] flex-shrink-0" />
										{:else}
											<ChevronRight class="w-3.5 h-3.5 text-[var(--text-muted)] flex-shrink-0" />
										{/if}
										<div class="min-w-0">
											<p class="font-medium text-[var(--text-body)]">{job.type}</p>
											{#if job.description}
												<p class="text-xs text-[var(--text-muted)] truncate max-w-xs">{job.description}</p>
											{/if}
											<p class="text-xs text-[var(--text-disabled)] sm:hidden">
												{#if job.total}{job.progress}/{job.total} &middot; {/if}{job.started_at ? formatDateTime(job.started_at) : ''}
											</p>
										</div>
									</div>
								</td>
								<td class="px-4 py-3">
									<div class="flex items-center gap-2">
										{#if job.status === 'running'}
											<span class="animate-pulse">
												<Badge variant={statusVariant(job.status)}>{job.status}</Badge>
											</span>
											<button onclick={(e) => { e.stopPropagation(); cancelJob(job.id); }}
												class="text-[var(--text-muted)] hover:text-red-400 transition-colors" title="Cancel job">
												<XCircle class="w-4 h-4" />
											</button>
										{:else}
											<Badge variant={statusVariant(job.status)}>{job.status}</Badge>
										{/if}
									</div>
								</td>
								<td class="px-4 py-3 text-[var(--text-secondary)] font-mono text-xs hidden sm:table-cell">
									{#if job.total}
										{job.progress}/{job.total}
									{:else}
										-
									{/if}
								</td>
								<td class="px-4 py-3 text-[var(--text-muted)] font-mono text-xs hidden md:table-cell">
									{formatJobDuration(job.started_at, job.finished_at)}
								</td>
								<td class="px-4 py-3 text-[var(--text-muted)] text-xs font-mono hidden sm:table-cell">
									{job.started_at ? formatDateTime(job.started_at) : '-'}
								</td>
							</tr>
							{#if expandedJob === job.id && jobDetail}
								<tr>
									<td colspan="5" class="px-4 py-3 bg-[var(--bg-tertiary)]">
										<div class="space-y-2 text-xs animate-fade-slide-in">
											<div class="grid grid-cols-2 sm:grid-cols-4 gap-2">
												<div class="bg-[var(--bg-primary)] p-2 rounded-md">
													<span class="text-[var(--text-muted)] font-mono text-xs uppercase">Job ID</span>
													<p class="text-[var(--text-body)] font-mono text-xs truncate">{jobDetail.id}</p>
												</div>
												<div class="bg-[var(--bg-primary)] p-2 rounded-md">
													<span class="text-[var(--text-muted)] font-mono text-xs uppercase">Progress</span>
													<p class="text-[var(--text-body)] font-mono font-bold">{jobDetail.progress ?? 0} / {jobDetail.total ?? 0}</p>
												</div>
												{#if jobDetail.started_at}
													<div class="bg-[var(--bg-primary)] p-2 rounded-md">
														<span class="text-[var(--text-muted)] font-mono text-xs uppercase">Started</span>
														<p class="text-[var(--text-body)] font-mono text-xs">{formatDateTime(jobDetail.started_at)}</p>
													</div>
												{/if}
												{#if jobDetail.finished_at}
													<div class="bg-[var(--bg-primary)] p-2 rounded-md">
														<span class="text-[var(--text-muted)] font-mono text-xs uppercase">Finished</span>
														<p class="text-[var(--text-body)] font-mono text-xs">{formatDateTime(jobDetail.finished_at)}</p>
													</div>
												{/if}
											</div>

											{#if jobDetail.result}
												{@const parsed = (() => { try { return JSON.parse(jobDetail.result); } catch { return null; } })()}
												<div>
													<span class="text-[var(--text-muted)] font-mono uppercase tracking-wider">Result</span>
													{#if parsed && typeof parsed === 'object' && !parsed.error}
														<div class="mt-1 grid grid-cols-2 sm:grid-cols-4 gap-2">
															{#each Object.entries(parsed) as [key, value]}
																<div class="bg-[var(--bg-primary)] p-2 rounded-md">
																	<span class="text-[var(--text-muted)] font-mono text-xs uppercase">{key}</span>
																	<p class="text-[var(--text-body)] font-mono font-bold">{typeof value === 'number' ? value.toLocaleString() : value}</p>
																</div>
															{/each}
														</div>
													{:else}
														<pre class="mt-1 bg-[var(--bg-primary)] text-[var(--text-secondary)] p-3 rounded-md overflow-x-auto font-mono">{jobDetail.result}</pre>
													{/if}
												</div>
											{:else if !jobDetail.tracks}
												<p class="text-[var(--text-muted)] italic">No result data — job may have been interrupted by a restart.</p>
											{/if}
											{#if jobDetail.tracks}
												{@const trackList = (() => { try { return JSON.parse(jobDetail.tracks); } catch { return null; } })()}
												<div>
													<span class="text-[var(--text-muted)] font-mono uppercase tracking-wider">Tracks</span>
													{#if Array.isArray(trackList)}
														<div class="mt-1 space-y-1 max-h-48 overflow-y-auto">
															{#each trackList as t}
																<div class="flex items-center gap-2 bg-[var(--bg-primary)] px-2 py-1.5 rounded-md flex-wrap">
																	<Badge variant={t.status === 'downloaded' ? 'success' : t.status === 'failed' ? 'error' : t.status === 'skipped' ? 'warning' : 'default'}>{t.status}</Badge>
																	<span class="text-[var(--text-body)] truncate">{t.artist} — {t.track}</span>
																	{#if t.username}
																		<span class="text-[var(--text-muted)] text-xs">from {t.username}</span>
																	{/if}
																	{#if t.error}
																		<span class="text-red-400 text-xs ml-auto" title={t.error}>{t.error}</span>
																	{:else if t.reason}
																		<span class="text-orange-400 text-xs ml-auto">{t.reason}</span>
																	{/if}
																</div>
															{/each}
														</div>
													{:else}
														<pre class="mt-1 bg-[var(--bg-primary)] text-[var(--text-secondary)] p-3 rounded-md overflow-x-auto max-h-48 overflow-y-auto font-mono">{jobDetail.tracks}</pre>
													{/if}
												</div>
											{/if}
											{#if job.status === 'failed' && (job.type === 'download' || job.type === 'bulk_download')}
												<div class="pt-2">
													<Button variant="primary" size="sm" loading={retrying} onclick={() => retryJob(job.id)}>
														<RotateCcw class="w-3.5 h-3.5" />
														Retry Failed Tracks
													</Button>
												</div>
											{/if}
										</div>
									</td>
								</tr>
							{/if}
						{/each}
					</tbody>
				</table>
			{:else}
				<EmptyState
					title="No job history yet"
					description="Jobs will appear here when you scan your library, download tracks, or run analysis."
				>
					{#snippet icon()}<ScrollText class="w-10 h-10" />{/snippet}
				</EmptyState>
			{/if}
		</Card>

		<Pagination {total} {offset} {limit} onchange={handlePageChange} />

	{:else}
		<!-- App Logs view -->
		<Card padding="p-0">
			{#if appLoading}
				<div class="divide-y divide-[var(--border-subtle)]">
					{#each Array(5) as _}
						<div class="px-4 py-3 flex items-center gap-4">
							<Skeleton class="h-4 w-32" />
							<Skeleton class="h-5 w-16 rounded-full" />
							<Skeleton class="h-4 w-20" />
							<Skeleton class="h-3 w-28 hidden md:block" />
						</div>
					{/each}
				</div>
			{:else if appLogs.length}
				<table class="w-full text-sm">
					<thead>
						<tr class="border-b border-[var(--border-subtle)] text-[var(--text-muted)] text-left">
							<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider">Device</th>
							<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider">Version</th>
							<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider hidden sm:table-cell">User</th>
							<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider hidden sm:table-cell">Size</th>
							<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider hidden md:table-cell">Received</th>
							<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider w-10"></th>
						</tr>
					</thead>
					<tbody class="divide-y divide-[var(--border-subtle)]">
						{#each appLogs as log}
							<!-- svelte-ignore a11y_click_events_have_key_events -->
							<tr class="hover:bg-[var(--bg-hover)] cursor-pointer transition-colors" onclick={() => toggleLogExpand(log)}>
								<td class="px-3 sm:px-4 py-3">
									<div class="flex items-center gap-2">
										{#if expandedLog === log.id}
											<ChevronDown class="w-3.5 h-3.5 text-[var(--text-muted)] flex-shrink-0" />
										{:else}
											<ChevronRight class="w-3.5 h-3.5 text-[var(--text-muted)] flex-shrink-0" />
										{/if}
										<div class="min-w-0">
											<p class="font-medium text-[var(--text-body)] truncate">{log.device}</p>
											<p class="text-xs text-[var(--text-disabled)] sm:hidden">
												v{log.app_version} &middot; {log.created_at ? formatDateTime(log.created_at) : ''}
											</p>
										</div>
									</div>
								</td>
								<td class="px-4 py-3">
									<Badge variant="default">{log.app_version}</Badge>
								</td>
								<td class="px-4 py-3 text-[var(--text-secondary)] text-xs hidden sm:table-cell">
									{log.username || '-'}
								</td>
								<td class="px-4 py-3 text-[var(--text-muted)] font-mono text-xs hidden sm:table-cell">
									{formatSize(log.log_size)}
								</td>
								<td class="px-4 py-3 text-[var(--text-muted)] text-xs font-mono hidden md:table-cell">
									{log.created_at ? formatDateTime(log.created_at) : '-'}
								</td>
								<td class="px-4 py-3">
									<button onclick={(e) => { e.stopPropagation(); deleteLog(log.id); }}
										class="text-[var(--text-muted)] hover:text-red-400 transition-colors" title="Delete log">
										<Trash2 class="w-3.5 h-3.5" />
									</button>
								</td>
							</tr>
							{#if expandedLog === log.id && logDetail}
								<tr>
									<td colspan="6" class="px-4 py-3 bg-[var(--bg-tertiary)]">
										<div class="space-y-2 text-xs animate-fade-slide-in">
											<div class="grid grid-cols-2 sm:grid-cols-4 gap-2">
												<div class="bg-[var(--bg-primary)] p-2 rounded-md">
													<span class="text-[var(--text-muted)] font-mono text-xs uppercase">Device</span>
													<p class="text-[var(--text-body)] text-xs">{logDetail.device}</p>
												</div>
												<div class="bg-[var(--bg-primary)] p-2 rounded-md">
													<span class="text-[var(--text-muted)] font-mono text-xs uppercase">App Version</span>
													<p class="text-[var(--text-body)] font-mono font-bold">{logDetail.app_version}</p>
												</div>
												<div class="bg-[var(--bg-primary)] p-2 rounded-md">
													<span class="text-[var(--text-muted)] font-mono text-xs uppercase">Timestamp</span>
													<p class="text-[var(--text-body)] font-mono text-xs">{formatDateTime(logDetail.timestamp)}</p>
												</div>
												{#if logDetail.username}
													<div class="bg-[var(--bg-primary)] p-2 rounded-md">
														<span class="text-[var(--text-muted)] font-mono text-xs uppercase">User</span>
														<p class="text-[var(--text-body)] font-mono">{logDetail.username}</p>
													</div>
												{/if}
											</div>
											<div>
												<span class="text-[var(--text-muted)] font-mono uppercase tracking-wider">Log Output</span>
												<pre class="mt-1 bg-[var(--bg-primary)] text-[var(--text-secondary)] p-3 rounded-md overflow-x-auto max-h-96 overflow-y-auto font-mono text-xs whitespace-pre-wrap break-all">{logDetail.logs}</pre>
											</div>
										</div>
									</td>
								</tr>
							{/if}
						{/each}
					</tbody>
				</table>
			{:else}
				<EmptyState
					title="No app logs yet"
					description="Logs uploaded from Symfonium will appear here."
				>
					{#snippet icon()}<Smartphone class="w-10 h-10" />{/snippet}
				</EmptyState>
			{/if}
		</Card>

		<Pagination total={appTotal} offset={appOffset} limit={appLimit} onchange={handleAppPageChange} />
	{/if}
</div>
