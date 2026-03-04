<script>
	import { onMount } from 'svelte';
	import { addToast } from '$lib/stores.js';

	let tasks = $state([]);
	let running = $state({});

	const intervalOptions = [
		{ value: 6, label: '6 hours' },
		{ value: 12, label: '12 hours' },
		{ value: 24, label: '24 hours' },
		{ value: 48, label: '48 hours' },
		{ value: 168, label: '7 days' },
	];

	onMount(async () => {
		try {
			tasks = await fetch('/api/schedule').then(r => r.json());
		} catch (e) {
			console.error('Failed to load schedule:', e);
		}
	});

	async function toggleTask(task) {
		const newEnabled = !task.enabled;
		try {
			await fetch(`/api/schedule/${task.task_name}`, {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ enabled: newEnabled }),
			});
			task.enabled = newEnabled;
			tasks = [...tasks]; // trigger reactivity
		} catch (e) {
			addToast('Failed to update task', 'error');
		}
	}

	async function updateInterval(task, interval) {
		try {
			await fetch(`/api/schedule/${task.task_name}`, {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ interval_hours: parseInt(interval) }),
			});
		} catch (e) {
			addToast('Failed to update interval', 'error');
		}
	}

	async function updateRunAt(task, runAt) {
		try {
			await fetch(`/api/schedule/${task.task_name}`, {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ run_at: runAt }),
			});
		} catch (e) {
			addToast('Failed to update run time', 'error');
		}
	}

	async function runNow(task) {
		running[task.task_name] = true;
		try {
			await fetch(`/api/schedule/${task.task_name}/run`, { method: 'POST' });
			addToast(`${task.label} started`, 'success');
		} catch (e) {
			addToast('Failed to run task', 'error');
		} finally {
			running[task.task_name] = false;
		}
	}
</script>

<div class="max-w-4xl">
	<h1 class="text-2xl font-bold mb-6">Scheduled Tasks</h1>

	<div class="bg-gray-900 rounded-xl border border-gray-800 divide-y divide-gray-800">
		{#each tasks as task}
			<div class="p-4 flex items-center gap-4">
				<button on:click={() => toggleTask(task)}
					class="w-10 h-6 rounded-full transition-colors relative flex-shrink-0
						{task.enabled ? 'bg-accent-600' : 'bg-gray-700'}">
					<span class="absolute top-0.5 w-5 h-5 bg-white rounded-full transition-transform
						{task.enabled ? 'left-[18px]' : 'left-0.5'}"></span>
				</button>

				<div class="flex-1 min-w-0">
					<p class="font-medium text-sm">{task.label}</p>
					{#if task.last_run_at}
						<p class="text-xs text-gray-500">Last: {new Date(task.last_run_at).toLocaleString()}</p>
					{/if}
				</div>

				<select value={task.interval_hours}
					on:change={(e) => updateInterval(task, e.target.value)}
					class="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs">
					{#each intervalOptions as opt}
						<option value={opt.value} selected={opt.value === task.interval_hours}>{opt.label}</option>
					{/each}
				</select>

				<input type="time" value={task.run_at || ''}
					on:change={(e) => updateRunAt(task, e.target.value)}
					class="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs w-24" />

				<button on:click={() => runNow(task)}
					disabled={running[task.task_name]}
					class="px-3 py-1 bg-accent-600 hover:bg-accent-700 rounded text-xs
						disabled:opacity-50 transition whitespace-nowrap">
					{running[task.task_name] ? '...' : 'Run Now'}
				</button>
			</div>
		{/each}
	</div>
</div>
