<script>
	import { onMount, onDestroy } from 'svelte';
	import { api } from '$lib/api.js';
	import { ScrollText, ChevronDown, ChevronRight, RotateCcw, XCircle } from 'lucide-svelte';
	import { addToast, activeJobs } from '$lib/stores.js';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Badge from '../../components/ui/Badge.svelte';
	import Button from '../../components/ui/Button.svelte';
	import Skeleton from '../../components/ui/Skeleton.svelte';
	import EmptyState from '../../components/ui/EmptyState.svelte';

	let jobs = $state([]);
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
		{ key: 'library', label: 'Library', types: ['library_scan', 'library_cleanup'] },
		{ key: 'analysis', label: 'Analysis', types: ['audio_analysis', 'enrichment'] },
		{ key: 'discovery', label: 'Discovery', types: ['lastfm_top_tracks', 'discover_similar', 'discover_artists', 'lastfm_sync', 'kimahub_favorites_sync'] },
		{ key: 'playlists', label: 'Playlists', types: ['playlist_weekly_top', 'playlist_weekly_discover', 'playlist_favorites'] },
	];

	let filteredJobs = $derived(
		categoryFilter === 'all'
			? jobs
			: jobs.filter(j => {
				const cat = categories.find(c => c.key === categoryFilter);
				return cat?.types?.includes(j.type);
			})
	);

	onMount(async () => {
		try {
			jobs = await api.getJobs();
		} catch (e) {
			console.error('Failed to load jobs:', e);
		} finally {
			loading = false;
		}

		unsubJobs = activeJobs.subscribe(active => {
			if (!active.length) return;
			for (const aj of active) {
				const idx = jobs.findIndex(j => j.id === aj.id);
				if (idx >= 0) {
					jobs[idx] = { ...jobs[idx], ...aj };
				} else {
					jobs = [{ ...aj, started_at: new Date().toISOString() }, ...jobs];
				}
			}
		});

		refreshInterval = setInterval(async () => {
			try {
				const newJobs = await api.getJobs();
				if (JSON.stringify(newJobs.map(j => j.id + j.status)) !== JSON.stringify(jobs.map(j => j.id + j.status))) {
					jobs = newJobs;
				}
			} catch {}
		}, 30000);
	});

	onDestroy(() => {
		if (unsubJobs) unsubJobs();
		if (refreshInterval) clearInterval(refreshInterval);
	});

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

	async function cancelJob(jobId) {
		try {
			const result = await api.cancelJob(jobId);
			if (result.error) {
				addToast(result.error, 'error');
			} else {
				addToast('Job cancelled', 'success');
				jobs = await api.getJobs();
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
				jobs = await api.getJobs();
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
</script>

<div class="max-w-6xl">
	<PageHeader title="Job History" color="var(--color-logs)">
		{#if $activeJobs.length > 0}
			<Badge variant="info">
				<span class="inline-block w-1.5 h-1.5 rounded-full bg-current animate-pulse mr-1.5"></span>
				Live
			</Badge>
		{/if}
	</PageHeader>

	<!-- Category filters -->
	{#if jobs.length}
		<div class="flex gap-1.5 mb-4 overflow-x-auto">
			{#each categories as cat}
				{@const count = cat.key === 'all' ? jobs.length : jobs.filter(j => cat.types?.includes(j.type)).length}
				{#if cat.key === 'all' || count > 0}
					<button onclick={() => categoryFilter = cat.key}
						class="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors whitespace-nowrap
							{categoryFilter === cat.key
								? 'bg-[var(--color-logs)] text-white'
								: 'bg-[var(--bg-hover)] text-[var(--text-secondary)] hover:text-white hover:bg-[var(--bg-active)]'}">
						{cat.label}
						<span class="opacity-60">{count}</span>
					</button>
				{/if}
			{/each}
		</div>
	{/if}

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
		{:else if filteredJobs.length}
			<table class="w-full text-sm">
				<thead>
					<tr class="border-b border-[var(--border-subtle)] text-[var(--text-muted)] text-left">
						<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider">Type</th>
						<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider">Status</th>
						<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider">Progress</th>
						<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider hidden md:table-cell">Duration</th>
						<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider">Started</th>
					</tr>
				</thead>
				<tbody class="divide-y divide-[var(--border-subtle)]">
					{#each filteredJobs as job}
						<!-- svelte-ignore a11y_click_events_have_key_events -->
						<tr class="hover:bg-[var(--bg-hover)] cursor-pointer transition-colors" onclick={() => toggleExpand(job)}>
							<td class="px-4 py-3">
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
							<td class="px-4 py-3 text-[var(--text-secondary)] font-mono text-xs">
								{#if job.total}
									{job.progress}/{job.total}
								{:else}
									-
								{/if}
							</td>
							<td class="px-4 py-3 text-[var(--text-muted)] font-mono text-xs hidden md:table-cell">
								{formatJobDuration(job.started_at, job.finished_at)}
							</td>
							<td class="px-4 py-3 text-[var(--text-muted)] text-xs font-mono">
								{job.started_at ? new Date(job.started_at).toLocaleString() : '-'}
							</td>
						</tr>
						{#if expandedJob === job.id && jobDetail}
							<tr>
								<td colspan="5" class="px-4 py-3 bg-[var(--bg-tertiary)]">
									<div class="space-y-2 text-xs animate-fade-slide-in">
										<!-- Job summary -->
										<div class="grid grid-cols-2 sm:grid-cols-4 gap-2">
											<div class="bg-[var(--bg-primary)] p-2 rounded-md">
												<span class="text-[var(--text-muted)] font-mono text-[10px] uppercase">Job ID</span>
												<p class="text-[var(--text-body)] font-mono text-[10px] truncate">{jobDetail.id}</p>
											</div>
											<div class="bg-[var(--bg-primary)] p-2 rounded-md">
												<span class="text-[var(--text-muted)] font-mono text-[10px] uppercase">Progress</span>
												<p class="text-[var(--text-body)] font-mono font-bold">{jobDetail.progress ?? 0} / {jobDetail.total ?? 0}</p>
											</div>
											{#if jobDetail.started_at}
												<div class="bg-[var(--bg-primary)] p-2 rounded-md">
													<span class="text-[var(--text-muted)] font-mono text-[10px] uppercase">Started</span>
													<p class="text-[var(--text-body)] font-mono text-[10px]">{new Date(jobDetail.started_at).toLocaleString()}</p>
												</div>
											{/if}
											{#if jobDetail.finished_at}
												<div class="bg-[var(--bg-primary)] p-2 rounded-md">
													<span class="text-[var(--text-muted)] font-mono text-[10px] uppercase">Finished</span>
													<p class="text-[var(--text-body)] font-mono text-[10px]">{new Date(jobDetail.finished_at).toLocaleString()}</p>
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
																<span class="text-[var(--text-muted)] font-mono text-[10px] uppercase">{key}</span>
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
															<div class="flex items-center gap-2 bg-[var(--bg-primary)] px-2 py-1.5 rounded-md">
																<Badge variant={t.status === 'downloaded' ? 'success' : t.status === 'failed' ? 'error' : t.status === 'skipped' ? 'warning' : 'default'}>{t.status}</Badge>
																<span class="text-[var(--text-body)] truncate">{t.artist} — {t.track}</span>
																{#if t.reason}
																	<span class="text-[var(--text-muted)] text-[10px] ml-auto">{t.reason}</span>
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
</div>
