<script>
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';
	import { ScrollText, ChevronDown, ChevronRight } from 'lucide-svelte';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Badge from '../../components/ui/Badge.svelte';
	import Skeleton from '../../components/ui/Skeleton.svelte';
	import EmptyState from '../../components/ui/EmptyState.svelte';

	let jobs = $state([]);
	let loading = $state(true);
	let expandedJob = $state(null);
	let jobDetail = $state(null);

	onMount(async () => {
		try {
			jobs = await api.getJobs();
		} catch (e) {
			console.error('Failed to load jobs:', e);
		} finally {
			loading = false;
		}
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
	<PageHeader title="Job History" color="var(--color-logs)" />

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
						<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider">Progress</th>
						<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider hidden md:table-cell">Duration</th>
						<th class="px-4 py-3 font-medium text-xs uppercase tracking-wider">Started</th>
					</tr>
				</thead>
				<tbody class="divide-y divide-[var(--border-subtle)]">
					{#each jobs as job}
						<!-- svelte-ignore a11y_click_events_have_key_events -->
						<tr class="hover:bg-[var(--bg-hover)] cursor-pointer transition-colors" on:click={() => toggleExpand(job)}>
							<td class="px-4 py-3 font-medium text-[var(--text-body)]">
								<div class="flex items-center gap-2">
									{#if expandedJob === job.id}
										<ChevronDown class="w-3.5 h-3.5 text-[var(--text-muted)]" />
									{:else}
										<ChevronRight class="w-3.5 h-3.5 text-[var(--text-muted)]" />
									{/if}
									{job.type}
								</div>
							</td>
							<td class="px-4 py-3">
								<Badge variant={statusVariant(job.status)}>{job.status}</Badge>
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
										{#if jobDetail.result}
											<div>
												<span class="text-[var(--text-muted)] font-mono uppercase tracking-wider">Result</span>
												<pre class="mt-1 bg-[var(--bg-primary)] text-[var(--text-secondary)] p-3 rounded-md overflow-x-auto font-mono">{jobDetail.result}</pre>
											</div>
										{/if}
										{#if jobDetail.tracks}
											<div>
												<span class="text-[var(--text-muted)] font-mono uppercase tracking-wider">Tracks</span>
												<pre class="mt-1 bg-[var(--bg-primary)] text-[var(--text-secondary)] p-3 rounded-md overflow-x-auto max-h-48 overflow-y-auto font-mono">{jobDetail.tracks}</pre>
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
