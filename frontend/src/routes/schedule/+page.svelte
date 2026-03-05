<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { addToast } from '$lib/stores.js';
	import { Clock, Play, Download, ChevronDown, ChevronRight } from 'lucide-svelte';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Button from '../../components/ui/Button.svelte';
	import Badge from '../../components/ui/Badge.svelte';
	import Skeleton from '../../components/ui/Skeleton.svelte';
	import EmptyState from '../../components/ui/EmptyState.svelte';

	let tasks = $state([]);
	let loading = $state(true);
	let running = $state({});
	let expandedTask = $state(null);
	let taskResults = $state({}); // keyed by task_name
	let downloading = $state(false);

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

	async function updateCount(task, count) {
		const val = parseInt(count);
		if (isNaN(val) || val < 1) return;
		try {
			await fetch(`/api/schedule/${task.task_name}`, {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ count: val }),
			});
		} catch (e) {
			addToast('Failed to update count', 'error');
		}
	}

	async function runNow(task) {
		running[task.task_name] = true;
		expandedTask = task.task_name;
		taskResults[task.task_name] = null; // Clear previous while running
		try {
			const res = await fetch(`/api/schedule/${task.task_name}/run`, { method: 'POST' });
			const data = await res.json();
			if (data.job_id) {
				addToast(`${task.label} started`, 'success');
				await pollJobResult(task.task_name, data.job_id);
			} else {
				addToast(`${task.label} started`, 'success');
			}
		} catch (e) {
			addToast('Failed to run task', 'error');
		} finally {
			running[task.task_name] = false;
		}
	}

	async function pollJobResult(taskName, jobId) {
		for (let i = 0; i < 60; i++) {
			await new Promise(r => setTimeout(r, 2000));
			try {
				const res = await fetch(`/api/jobs/${jobId}`);
				const job = await res.json();
				if (job.status === 'completed' || job.status === 'failed') {
					taskResults[taskName] = job;
					tasks = await fetch('/api/schedule').then(r => r.json());
					return;
				}
			} catch {}
		}
	}

	async function loadLastResult(taskName) {
		// Load the most recent job for this task type
		try {
			const res = await fetch(`/api/jobs?type=${taskName}&limit=1`);
			const jobs = await res.json();
			if (jobs.length > 0) {
				const detail = await fetch(`/api/jobs/${jobs[0].id}`).then(r => r.json());
				taskResults[taskName] = detail;
			}
		} catch {}
	}

	async function toggleExpand(taskName) {
		if (expandedTask === taskName) {
			expandedTask = null;
		} else {
			expandedTask = taskName;
			// Load last result if we don't have one cached
			if (!taskResults[taskName]) {
				await loadLastResult(taskName);
			}
		}
	}

	async function downloadMissing(tracks) {
		if (!tracks.length) return;
		downloading = true;
		try {
			const res = await fetch('/api/download/bulk', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					tracks: tracks.map(t => ({ artist: t.artist, track: t.track }))
				})
			});
			const data = await res.json();
			if (data.job_id) {
				addToast(`Downloading ${tracks.length} missing tracks`, 'success');
				goto('/downloads');
			}
		} catch (e) {
			addToast('Failed to start downloads', 'error');
		} finally {
			downloading = false;
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
					<div>
						<div class="p-4 flex items-center gap-4 hover:bg-[var(--bg-hover)] transition-colors">
							<button onclick={() => toggleTask(task)}
								class="w-10 h-6 rounded-full transition-colors relative flex-shrink-0
									{task.enabled ? 'bg-[var(--color-accent)]' : 'bg-[var(--border-interactive)]'}">
								<span class="absolute top-0.5 w-5 h-5 bg-white rounded-full transition-transform shadow-sm
									{task.enabled ? 'left-[18px]' : 'left-0.5'}"></span>
							</button>

							<!-- svelte-ignore a11y_click_events_have_key_events -->
							<!-- svelte-ignore a11y_no_static_element_interactions -->
							<div onclick={() => toggleExpand(task.task_name)} class="flex-1 min-w-0 cursor-pointer">
								<div class="flex items-center gap-1.5">
									{#if expandedTask === task.task_name}
										<ChevronDown class="w-3.5 h-3.5 text-[var(--text-muted)] flex-shrink-0" />
									{:else}
										<ChevronRight class="w-3.5 h-3.5 text-[var(--text-muted)] flex-shrink-0" />
									{/if}
									<p class="font-medium text-sm text-[var(--text-primary)]">{task.label}</p>
								</div>
								{#if task.description}
									<p class="text-xs text-[var(--text-secondary)] mt-0.5 ml-5">{task.description}</p>
								{/if}
								{#if task.last_run_at}
									<p class="text-xs text-[var(--text-muted)] font-mono mt-0.5 ml-5">Last run: {new Date(task.last_run_at).toLocaleString()}</p>
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

							{#if task.count != null}
								<input type="number" value={task.count} min="1" max="1000"
									onchange={(e) => updateCount(task, e.target.value)}
									class="bg-[var(--bg-secondary)] border border-[var(--border-interactive)] rounded-md px-2 py-1 text-xs text-[var(--text-body)] w-20 focus:outline-none focus:border-[var(--color-accent)]/50"
									title="Items per run" />
							{/if}

							<Button variant="primary" size="sm"
								loading={running[task.task_name]}
								onclick={() => runNow(task)}>
								<Play class="w-3 h-3" />
								Run
							</Button>
						</div>

						<!-- Expanded result panel -->
						{#if expandedTask === task.task_name}
							<div class="px-4 pb-4 animate-fade-slide-in">
								{#if running[task.task_name]}
									<div class="bg-[var(--bg-tertiary)] rounded-md p-4 flex items-center gap-3">
										<div class="w-4 h-4 border-2 border-[var(--color-schedule)] border-t-transparent rounded-full animate-spin"></div>
										<span class="text-sm text-[var(--text-secondary)]">Running {task.label}...</span>
									</div>
								{:else if taskResults[task.task_name]}
									{@const job = taskResults[task.task_name]}
									{@const parsed = (() => { try { return JSON.parse(job.result); } catch { return null; } })()}
									{@const trackList = (() => { try { return JSON.parse(job.tracks); } catch { return null; } })()}
									<div class="bg-[var(--bg-tertiary)] rounded-md p-4 space-y-3">
										<div class="flex items-center justify-between">
											<Badge variant={job.status === 'completed' ? 'success' : 'error'}>{job.status}</Badge>
											{#if job.finished_at}
												<span class="text-xs text-[var(--text-muted)] font-mono">{new Date(job.finished_at).toLocaleString()}</span>
											{/if}
										</div>

										{#if parsed && typeof parsed === 'object'}
											<div class="grid grid-cols-2 sm:grid-cols-4 gap-2">
												{#each Object.entries(parsed) as [key, value]}
													<div class="bg-[var(--bg-primary)] p-2 rounded-md">
														<span class="text-[var(--text-muted)] font-mono text-[10px] uppercase">{key.replace(/_/g, ' ')}</span>
														<p class="text-[var(--text-body)] font-mono font-bold">{typeof value === 'number' ? value.toLocaleString() : value}</p>
													</div>
												{/each}
											</div>
										{/if}

										{#if Array.isArray(trackList) && trackList.length > 0}
											<div>
												<div class="flex items-center justify-between mb-2">
													<span class="text-xs text-[var(--text-muted)] font-medium uppercase tracking-wider">
														Missing Tracks ({trackList.length})
													</span>
													<Button variant="success" size="sm" loading={downloading}
														onclick={() => downloadMissing(trackList)}>
														<Download class="w-3 h-3" />
														Download All
													</Button>
												</div>
												<div class="space-y-1 max-h-64 overflow-y-auto">
													{#each trackList as t}
														<div class="flex items-center justify-between bg-[var(--bg-primary)] px-3 py-2 rounded-md">
															<div class="min-w-0">
																<span class="text-sm text-[var(--text-body)]">{t.artist}</span>
																<span class="text-[var(--text-muted)] mx-1">—</span>
																<span class="text-sm text-[var(--text-primary)] font-medium">{t.track}</span>
															</div>
															<Badge variant="warning">Missing</Badge>
														</div>
													{/each}
												</div>
											</div>
										{:else if Array.isArray(trackList) && trackList.length === 0}
											<p class="text-sm text-green-400">All tracks are already in your library!</p>
										{/if}
									</div>
								{:else}
									<div class="bg-[var(--bg-tertiary)] rounded-md p-4">
										<p class="text-sm text-[var(--text-muted)]">No previous results. Click Run to execute this task.</p>
									</div>
								{/if}
							</div>
						{/if}
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
