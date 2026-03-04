<script>
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';

	let jobs = $state([]);
	let expandedJob = $state(null);
	let jobDetail = $state(null);

	onMount(async () => {
		try {
			jobs = await api.getJobs();
		} catch (e) {
			console.error('Failed to load jobs:', e);
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

	function statusColor(status) {
		switch (status) {
			case 'completed': return 'bg-green-900/50 text-green-400';
			case 'failed': return 'bg-red-900/50 text-red-400';
			case 'running': return 'bg-blue-900/50 text-blue-400';
			case 'pending': return 'bg-yellow-900/50 text-yellow-400';
			default: return 'bg-gray-800 text-gray-400';
		}
	}

	function formatDuration(start, end) {
		if (!start || !end) return '-';
		const ms = new Date(end) - new Date(start);
		const s = Math.floor(ms / 1000);
		if (s < 60) return `${s}s`;
		return `${Math.floor(s / 60)}m ${s % 60}s`;
	}
</script>

<div class="max-w-6xl">
	<h1 class="text-2xl font-bold mb-6">Job History</h1>

	<div class="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
		{#if jobs.length}
			<table class="w-full text-sm">
				<thead>
					<tr class="border-b border-gray-800 text-gray-400 text-left">
						<th class="px-4 py-3">Type</th>
						<th class="px-4 py-3">Status</th>
						<th class="px-4 py-3">Progress</th>
						<th class="px-4 py-3 hidden md:table-cell">Duration</th>
						<th class="px-4 py-3">Started</th>
					</tr>
				</thead>
				<tbody class="divide-y divide-gray-800/50">
					{#each jobs as job}
						<tr class="hover:bg-gray-800/50 cursor-pointer" on:click={() => toggleExpand(job)}>
							<td class="px-4 py-3 font-medium">{job.type}</td>
							<td class="px-4 py-3">
								<span class="px-2 py-0.5 rounded text-xs {statusColor(job.status)}">{job.status}</span>
							</td>
							<td class="px-4 py-3 text-gray-400">
								{#if job.total}
									{job.progress}/{job.total}
								{:else}
									-
								{/if}
							</td>
							<td class="px-4 py-3 text-gray-400 hidden md:table-cell">
								{formatDuration(job.started_at, job.finished_at)}
							</td>
							<td class="px-4 py-3 text-gray-400 text-xs">
								{job.started_at ? new Date(job.started_at).toLocaleString() : '-'}
							</td>
						</tr>
						{#if expandedJob === job.id && jobDetail}
							<tr>
								<td colspan="5" class="px-4 py-3 bg-gray-800/30">
									<div class="space-y-2 text-xs">
										{#if jobDetail.result}
											<div>
												<span class="text-gray-400">Result:</span>
												<pre class="mt-1 bg-gray-900 p-2 rounded overflow-x-auto">{jobDetail.result}</pre>
											</div>
										{/if}
										{#if jobDetail.tracks}
											<div>
												<span class="text-gray-400">Tracks:</span>
												<pre class="mt-1 bg-gray-900 p-2 rounded overflow-x-auto max-h-48 overflow-y-auto">{jobDetail.tracks}</pre>
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
			<p class="p-6 text-gray-400">No job history yet.</p>
		{/if}
	</div>
</div>
