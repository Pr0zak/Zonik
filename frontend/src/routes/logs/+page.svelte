<script>
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';

	let jobs = $state([]);

	onMount(async () => {
		try {
			jobs = await api.getJobs();
		} catch (e) {
			console.error('Failed to load jobs:', e);
		}
	});
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
						<th class="px-4 py-3">Started</th>
					</tr>
				</thead>
				<tbody class="divide-y divide-gray-800/50">
					{#each jobs as job}
						<tr class="hover:bg-gray-800/50">
							<td class="px-4 py-3">{job.type}</td>
							<td class="px-4 py-3">
								<span class="px-2 py-0.5 rounded text-xs
									{job.status === 'completed' ? 'bg-green-900/50 text-green-400' :
									 job.status === 'failed' ? 'bg-red-900/50 text-red-400' :
									 job.status === 'running' ? 'bg-blue-900/50 text-blue-400' :
									 'bg-gray-800 text-gray-400'}">
									{job.status}
								</span>
							</td>
							<td class="px-4 py-3 text-gray-400">{job.progress}/{job.total}</td>
							<td class="px-4 py-3 text-gray-400 text-xs">
								{job.started_at ? new Date(job.started_at).toLocaleString() : '-'}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		{:else}
			<p class="p-6 text-gray-400">No job history yet.</p>
		{/if}
	</div>
</div>
