<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
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
			tasks: ['library_scan', 'upgrade_scan'],
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
			tasks: ['lastfm_top_tracks', 'discover_similar', 'discover_artists', 'recommendation_refresh'],
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

	const DANGER_TASKS = new Set();

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
	<PageHeader
		title="Scheduled Tasks"
		subtitle="Overview of all scheduled tasks. Configure each task on its respective page."
		color="var(--color-schedule)" />

	{#if loading}
		<Skeleton variant="card" count={5} class="space-y-4" />
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
								<div class="space-y-0.5">
									{#each groupTasks as task}
										{@const danger = DANGER_TASKS.has(task.task_name)}
										<div class="flex items-center gap-2 sm:gap-3 py-2 flex-wrap sm:flex-nowrap {danger ? 'opacity-75' : ''}">
											<div class="w-2 h-2 rounded-full flex-shrink-0 {task.enabled ? (danger ? 'bg-amber-400' : 'bg-emerald-400') : 'bg-[var(--border-interactive)]'}"></div>
											<span class="text-sm min-w-0 truncate {danger ? 'text-amber-400/80' : 'text-[var(--text-body)]'}">{task.label}</span>
											{#if danger}
												<AlertTriangle class="w-3.5 h-3.5 text-amber-400/70 flex-shrink-0" />
											{/if}
											<span class="text-xs text-[var(--text-muted)] font-mono flex-shrink-0 hidden sm:inline">{formatLastRun(task.last_run_at)}</span>
											<div class="flex items-center gap-2 ml-auto flex-shrink-0">
												<span class="text-xs text-[var(--text-muted)] font-mono">{formatInterval(task.interval_hours)}</span>
												{#if task.run_at}
													<span class="text-xs text-[var(--text-muted)] font-mono">@ {task.run_at}</span>
												{/if}
												<Badge variant={task.enabled ? (danger ? 'warning' : 'success') : 'default'}>
													{task.enabled ? 'On' : 'Off'}
												</Badge>
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

		<div class="mt-6 flex items-center gap-4 text-xs text-[var(--text-muted)]">
			<span>{tasks.filter(t => t.enabled).length} of {tasks.length} tasks enabled</span>
			<span>&middot;</span>
			<span>{tasks.filter(t => t.last_run_at).length} have run at least once</span>
		</div>
	{:else}
		<EmptyState title="No scheduled tasks" description="No tasks are configured yet.">
			{#snippet icon()}<Clock class="w-10 h-10" />{/snippet}
		</EmptyState>
	{/if}
</div>
