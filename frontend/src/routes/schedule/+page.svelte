<script>
	import { onMount } from 'svelte';
	import { addToast } from '$lib/stores.js';
	import { Clock, Play } from 'lucide-svelte';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Button from '../../components/ui/Button.svelte';
	import Skeleton from '../../components/ui/Skeleton.svelte';
	import EmptyState from '../../components/ui/EmptyState.svelte';

	let tasks = $state([]);
	let loading = $state(true);
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
		} finally {
			loading = false;
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
			tasks = [...tasks];
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
	<PageHeader title="Scheduled Tasks" color="var(--color-schedule)" />

	<Card padding="p-0">
		{#if loading}
			<div class="divide-y divide-[var(--border-subtle)]">
				{#each Array(5) as _}
					<div class="p-4 flex items-center gap-4">
						<Skeleton class="w-10 h-6 rounded-full" />
						<Skeleton class="h-4 w-32 flex-1" />
						<Skeleton class="h-7 w-24" />
						<Skeleton class="h-7 w-24" />
						<Skeleton class="h-7 w-16" />
					</div>
				{/each}
			</div>
		{:else if tasks.length}
			<div class="divide-y divide-[var(--border-subtle)]">
				{#each tasks as task}
					<div class="p-4 flex items-center gap-4 hover:bg-[var(--bg-hover)] transition-colors">
						<button onclick={() => toggleTask(task)}
							class="w-10 h-6 rounded-full transition-colors relative flex-shrink-0
								{task.enabled ? 'bg-[var(--color-accent)]' : 'bg-[var(--border-interactive)]'}">
							<span class="absolute top-0.5 w-5 h-5 bg-white rounded-full transition-transform shadow-sm
								{task.enabled ? 'left-[18px]' : 'left-0.5'}"></span>
						</button>

						<div class="flex-1 min-w-0">
							<p class="font-medium text-sm text-[var(--text-primary)]">{task.label}</p>
							{#if task.description}
								<p class="text-xs text-[var(--text-secondary)] mt-0.5">{task.description}</p>
							{/if}
							{#if task.last_run_at}
								<p class="text-xs text-[var(--text-muted)] font-mono mt-0.5">Last run: {new Date(task.last_run_at).toLocaleString()}</p>
							{/if}
						</div>

						<select value={task.interval_hours}
							onchange={(e) => updateInterval(task, e.target.value)}
							class="bg-[var(--bg-secondary)] border border-[var(--border-interactive)] rounded-md px-2 py-1 text-xs text-[var(--text-body)] focus:outline-none focus:border-[var(--color-accent)]/50">
							{#each intervalOptions as opt}
								<option value={opt.value} selected={opt.value === task.interval_hours}>{opt.label}</option>
							{/each}
						</select>

						<input type="time" value={task.run_at || ''}
							onchange={(e) => updateRunAt(task, e.target.value)}
							class="bg-[var(--bg-secondary)] border border-[var(--border-interactive)] rounded-md px-2 py-1 text-xs text-[var(--text-body)] w-24 focus:outline-none focus:border-[var(--color-accent)]/50" />

						<Button variant="primary" size="sm"
							loading={running[task.task_name]}
							onclick={() => runNow(task)}>
							<Play class="w-3 h-3" />
							Run
						</Button>
					</div>
				{/each}
			</div>
		{:else}
			<EmptyState
				title="No scheduled tasks"
				description="No tasks are configured yet."
			>
				{#snippet icon()}<Clock class="w-10 h-10" />{/snippet}
			</EmptyState>
		{/if}
	</Card>
</div>
