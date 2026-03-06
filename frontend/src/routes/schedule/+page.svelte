<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { addToast } from '$lib/stores.js';
	import { Clock, ExternalLink, Music, AudioWaveform, Compass, ListMusic, Settings, AlertTriangle } from 'lucide-svelte';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Badge from '../../components/ui/Badge.svelte';
	import Skeleton from '../../components/ui/Skeleton.svelte';
	import EmptyState from '../../components/ui/EmptyState.svelte';

	let tasks = $state([]);
	let loading = $state(true);

	const taskGroups = [
		{
			label: 'Library',
			icon: Music,
			href: '/library',
			color: 'var(--color-library)',
			tasks: ['library_scan', 'library_cleanup'],
		},
		{
			label: 'Analysis',
			icon: AudioWaveform,
			href: '/analysis',
			color: 'var(--color-analysis)',
			tasks: ['audio_analysis', 'enrichment'],
		},
		{
			label: 'Discover',
			icon: Compass,
			href: '/discover',
			color: 'var(--color-discover)',
			tasks: ['lastfm_top_tracks', 'discover_similar', 'discover_artists'],
		},
		{
			label: 'Playlists',
			icon: ListMusic,
			href: '/playlists',
			color: 'var(--color-playlists)',
			tasks: ['playlist_weekly_top', 'playlist_weekly_discover', 'playlist_favorites', 'playlist_unfavorites'],
		},
		{
			label: 'Settings',
			icon: Settings,
			href: '/settings',
			color: 'var(--color-settings)',
			tasks: ['lastfm_sync'],
		},
	];

	const DANGER_TASKS = new Set(['library_cleanup']);

	let taskMap = $derived(Object.fromEntries(tasks.map(t => [t.task_name, t])));

	onMount(async () => {
		try {
			tasks = await fetch('/api/schedule').then(r => r.json());
		} catch (e) {
			console.error('Failed to load schedule:', e);
		} finally {
			loading = false;
		}
	});

	function formatInterval(hours) {
		if (hours < 24) return `${hours}h`;
		if (hours === 24) return '24h';
		if (hours === 48) return '2d';
		if (hours === 168) return '7d';
		return `${hours}h`;
	}

	function formatLastRun(dateStr) {
		if (!dateStr) return 'Never';
		const diff = Math.max(0, Date.now() - new Date(dateStr));
		const mins = Math.floor(diff / 60000);
		if (mins < 1) return 'just now';
		if (mins < 60) return `${mins}m ago`;
		const hrs = Math.floor(mins / 60);
		if (hrs < 24) return `${hrs}h ago`;
		const days = Math.floor(hrs / 24);
		return `${days}d ago`;
	}
</script>

<div class="max-w-4xl">
	<PageHeader title="Scheduled Tasks" color="var(--color-schedule)" />

	<p class="text-sm text-[var(--text-secondary)] mb-6">
		Overview of all scheduled tasks. Configure each task on its respective page.
	</p>

	{#if loading}
		<div class="space-y-4">
			{#each Array(5) as _}
				<Skeleton class="h-24 rounded-lg" />
			{/each}
		</div>
	{:else if tasks.length}
		<div class="space-y-4">
			{#each taskGroups as group}
				{@const groupTasks = group.tasks.map(name => taskMap[name]).filter(Boolean)}
				{#if groupTasks.length > 0}
					<Card padding="p-0" hover>
						<!-- svelte-ignore a11y_click_events_have_key_events -->
						<!-- svelte-ignore a11y_no_static_element_interactions -->
						<div onclick={() => goto(group.href)} class="cursor-pointer">
							<div class="flex items-center gap-3 px-4 pt-4 pb-2">
								<div class="w-8 h-8 rounded-lg flex items-center justify-center" style="background: color-mix(in srgb, {group.color} 15%, transparent)">
									<group.icon class="w-4 h-4" style="color: {group.color}" />
								</div>
								<h3 class="text-sm font-semibold text-[var(--text-primary)] flex-1">{group.label}</h3>
								<ExternalLink class="w-3.5 h-3.5 text-[var(--text-disabled)]" />
							</div>

							<div class="px-4 pb-3">
								<div class="divide-y divide-[var(--border-subtle)]">
									{#each groupTasks as task}
										<div class="flex items-center gap-3 py-2 {DANGER_TASKS.has(task.task_name) ? 'opacity-75' : ''}">
											<div class="w-2 h-2 rounded-full flex-shrink-0 {task.enabled ? (DANGER_TASKS.has(task.task_name) ? 'bg-amber-400' : 'bg-emerald-400') : 'bg-[var(--border-interactive)]'}"></div>
											<span class="text-sm min-w-0 truncate {DANGER_TASKS.has(task.task_name) ? 'text-amber-400/80' : 'text-[var(--text-body)]'}">{task.label}</span>
											{#if DANGER_TASKS.has(task.task_name)}
												<AlertTriangle class="w-3.5 h-3.5 text-amber-400/70 flex-shrink-0" />
											{/if}
											<span class="text-[11px] text-[var(--text-muted)] font-mono flex-shrink-0">{formatLastRun(task.last_run_at)}</span>
											<div class="flex items-center gap-2 ml-auto flex-shrink-0">
												<span class="text-xs text-[var(--text-muted)] font-mono">{formatInterval(task.interval_hours)}</span>
												{#if task.run_at}
													<span class="text-xs text-[var(--text-muted)] font-mono">@ {task.run_at}</span>
												{/if}
												{#if DANGER_TASKS.has(task.task_name) && task.enabled}
														<Badge variant="warning">On</Badge>
													{:else}
														<Badge variant={task.enabled ? 'success' : 'default'}>{task.enabled ? 'On' : 'Off'}</Badge>
													{/if}
											</div>
										</div>
									{/each}
								</div>
							</div>
						</div>
					</Card>
				{/if}
			{/each}
		</div>

		<!-- Summary stats -->
		<div class="mt-6 flex items-center gap-4 text-xs text-[var(--text-muted)]">
			<span>{tasks.filter(t => t.enabled).length} of {tasks.length} tasks enabled</span>
			<span class="text-[var(--border-interactive)]">|</span>
			<span>{tasks.filter(t => t.last_run_at).length} have run at least once</span>
		</div>
	{:else}
		<EmptyState
			title="No scheduled tasks"
			description="No tasks are configured yet."
		>
			{#snippet icon()}<Clock class="w-10 h-10" />{/snippet}
		</EmptyState>
	{/if}
</div>
