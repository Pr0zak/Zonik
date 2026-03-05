<script>
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';
	import { addToast } from '$lib/stores.js';
	import { ListMusic, Wand2, Plus, Clock } from 'lucide-svelte';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import ScheduleControl from '../../components/ui/ScheduleControl.svelte';
	import Button from '../../components/ui/Button.svelte';
	import Badge from '../../components/ui/Badge.svelte';
	import Skeleton from '../../components/ui/Skeleton.svelte';
	import EmptyState from '../../components/ui/EmptyState.svelte';

	let playlists = $state([]);
	let loading = $state(true);
	let schedTasks = $state({});
	let schedRunning = $state({});

	let showGenerator = $state(false);
	let genName = $state('');
	let genRule = $state('genre');
	let genValue = $state('');
	let genLimit = $state(50);
	let generating = $state(false);

	const ruleOptions = [
		{ value: 'genre', label: 'Genre', needsValue: true, placeholder: 'e.g. Electronic' },
		{ value: 'bpm_range', label: 'BPM Range', needsValue: true, placeholder: 'e.g. 120-140' },
		{ value: 'recent', label: 'Recently Added', needsValue: false },
		{ value: 'top_played', label: 'Most Played', needsValue: false },
		{ value: 'random', label: 'Random Mix', needsValue: false },
	];

	let selectedRule = $derived(ruleOptions.find(r => r.value === genRule));

	async function generatePlaylist() {
		if (!genName.trim()) return;
		generating = true;
		try {
			const data = await fetch('/api/playlists/generate', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					name: genName.trim(),
					rule: genRule,
					value: genValue || null,
					limit: genLimit,
				})
			}).then(r => r.json());
			if (data.error) {
				addToast(data.error, 'error');
			} else {
				addToast(`Created "${data.name}" with ${data.track_count} tracks`, 'success');
				playlists = await api.getPlaylists();
				showGenerator = false;
				genName = ''; genValue = '';
			}
		} catch (e) {
			addToast('Failed to generate playlist', 'error');
		} finally {
			generating = false;
		}
	}

	async function toggleSched(name) {
		const t = schedTasks[name];
		if (!t) return;
		const newEnabled = !t.enabled;
		await fetch(`/api/schedule/${name}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled: newEnabled }) });
		schedTasks[name] = { ...t, enabled: newEnabled };
	}
	async function updateSched(name, updates) {
		await fetch(`/api/schedule/${name}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(updates) });
		schedTasks[name] = { ...schedTasks[name], ...updates };
	}
	async function runSched(name) {
		schedRunning[name] = true;
		try {
			await fetch(`/api/schedule/${name}/run`, { method: 'POST' });
			addToast('Task started', 'success');
		} catch { addToast('Failed to run task', 'error'); }
		finally { schedRunning[name] = false; }
	}

	onMount(async () => {
		try {
			playlists = await api.getPlaylists();
		} catch (e) {
			console.error('Failed to load playlists:', e);
		} finally {
			loading = false;
		}
		try {
			const tasks = await fetch('/api/schedule').then(r => r.json());
			for (const t of tasks) schedTasks[t.task_name] = t;
		} catch {}
	});
</script>

<div class="max-w-6xl">
	<div class="flex items-center justify-between mb-6">
		<PageHeader title="Playlists" color="var(--color-playlists)" />
		<Button onclick={() => showGenerator = !showGenerator} variant="secondary" size="sm">
			{#if showGenerator}
				<span class="flex items-center gap-1.5">Hide Generator</span>
			{:else}
				<span class="flex items-center gap-1.5"><Wand2 class="w-4 h-4" /> Smart Playlist</span>
			{/if}
		</Button>
	</div>

	{#if showGenerator}
		<Card padding="p-5" class="mb-6">
			<div class="flex items-center gap-2 mb-4">
				<Wand2 class="w-5 h-5 text-amber-400" />
				<h3 class="font-medium text-[var(--text-primary)]">Generate Smart Playlist</h3>
			</div>

			<div class="grid grid-cols-1 md:grid-cols-2 gap-4">
				<div>
					<label class="block text-xs text-[var(--text-muted)] mb-1.5">Playlist Name</label>
					<input
						type="text"
						bind:value={genName}
						placeholder="My Smart Playlist"
						class="w-full bg-[var(--bg-primary)] border border-[var(--border-interactive)] rounded-md px-3 py-2 text-sm text-[var(--text-body)] placeholder-[var(--text-disabled)] focus:outline-none focus:ring-1 focus:border-[var(--color-accent)]/50 focus:ring-[var(--color-accent)]/20"
					/>
				</div>

				<div>
					<label class="block text-xs text-[var(--text-muted)] mb-1.5">Rule</label>
					<select
						bind:value={genRule}
						class="w-full bg-[var(--bg-primary)] border border-[var(--border-interactive)] rounded-md px-3 py-2 text-sm text-[var(--text-body)] focus:outline-none focus:ring-1 focus:border-[var(--color-accent)]/50 focus:ring-[var(--color-accent)]/20"
					>
						{#each ruleOptions as opt}
							<option value={opt.value}>{opt.label}</option>
						{/each}
					</select>
				</div>

				{#if selectedRule?.needsValue}
					<div>
						<label class="block text-xs text-[var(--text-muted)] mb-1.5">Value</label>
						<input
							type="text"
							bind:value={genValue}
							placeholder={selectedRule.placeholder}
							class="w-full bg-[var(--bg-primary)] border border-[var(--border-interactive)] rounded-md px-3 py-2 text-sm text-[var(--text-body)] placeholder-[var(--text-disabled)] focus:outline-none focus:ring-1 focus:border-[var(--color-accent)]/50 focus:ring-[var(--color-accent)]/20"
						/>
					</div>
				{/if}

				<div>
					<label class="block text-xs text-[var(--text-muted)] mb-1.5">Track Limit: {genLimit}</label>
					<div class="flex items-center gap-3">
						<input
							type="range"
							bind:value={genLimit}
							min="10"
							max="100"
							step="5"
							class="flex-1 accent-amber-500"
						/>
						<Badge>{genLimit}</Badge>
					</div>
				</div>
			</div>

			<div class="mt-4 flex justify-end">
				<Button onclick={generatePlaylist} disabled={!genName.trim() || generating} variant="primary" size="sm">
					<span class="flex items-center gap-1.5">
						<Plus class="w-4 h-4" />
						{generating ? 'Generating...' : 'Generate'}
					</span>
				</Button>
			</div>
		</Card>
	{/if}

	{#if loading}
		<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
			{#each Array(6) as _}
				<Skeleton class="h-20 rounded-lg" />
			{/each}
		</div>
	{:else if playlists.length}
		<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
			{#each playlists as playlist}
				<Card hover padding="p-4" class="cursor-pointer group">
					<div class="flex items-center gap-3">
						<div class="w-10 h-10 rounded-lg bg-[var(--bg-tertiary)] flex items-center justify-center group-hover:bg-amber-500/10 transition-colors">
							<ListMusic class="w-5 h-5 text-[var(--text-disabled)] group-hover:text-amber-400 transition-colors" />
						</div>
						<div>
							<h3 class="font-medium text-[var(--text-primary)]">{playlist.name}</h3>
							<p class="text-xs text-[var(--text-muted)]">{playlist.track_count} tracks</p>
						</div>
					</div>
				</Card>
			{/each}
		</div>
	{:else}
		<Card>
			<EmptyState
				title="No playlists yet"
				description="Create playlists or generate a smart playlist to get started."
			>
				{#snippet icon()}<ListMusic class="w-10 h-10" />{/snippet}
			</EmptyState>
		</Card>
	{/if}

	<!-- Schedule -->
	{#if schedTasks.playlist_weekly_top || schedTasks.playlist_weekly_discover || schedTasks.playlist_favorites}
		<Card padding="p-4" class="mt-6">
			<div class="flex items-center gap-2 mb-2">
				<Clock class="w-4 h-4 text-[var(--text-muted)]" />
				<span class="text-xs text-[var(--text-muted)] font-mono uppercase tracking-wider">Auto-generate Schedule</span>
			</div>
			{#if schedTasks.playlist_weekly_top}
				<ScheduleControl taskName="playlist_weekly_top" label="Weekly Top" enabled={schedTasks.playlist_weekly_top.enabled} intervalHours={schedTasks.playlist_weekly_top.interval_hours} runAt={schedTasks.playlist_weekly_top.run_at} dayOfWeek={schedTasks.playlist_weekly_top.day_of_week} count={schedTasks.playlist_weekly_top.count} lastRunAt={schedTasks.playlist_weekly_top.last_run_at} running={schedRunning.playlist_weekly_top} onToggle={() => toggleSched('playlist_weekly_top')} onUpdate={(u) => updateSched('playlist_weekly_top', u)} onRun={() => runSched('playlist_weekly_top')} />
			{/if}
			{#if schedTasks.playlist_weekly_discover}
				<ScheduleControl taskName="playlist_weekly_discover" label="Weekly Discover" enabled={schedTasks.playlist_weekly_discover.enabled} intervalHours={schedTasks.playlist_weekly_discover.interval_hours} runAt={schedTasks.playlist_weekly_discover.run_at} dayOfWeek={schedTasks.playlist_weekly_discover.day_of_week} count={schedTasks.playlist_weekly_discover.count} lastRunAt={schedTasks.playlist_weekly_discover.last_run_at} running={schedRunning.playlist_weekly_discover} onToggle={() => toggleSched('playlist_weekly_discover')} onUpdate={(u) => updateSched('playlist_weekly_discover', u)} onRun={() => runSched('playlist_weekly_discover')} />
			{/if}
			{#if schedTasks.playlist_favorites}
				<ScheduleControl taskName="playlist_favorites" label="Favorites Playlist" enabled={schedTasks.playlist_favorites.enabled} intervalHours={schedTasks.playlist_favorites.interval_hours} runAt={schedTasks.playlist_favorites.run_at} lastRunAt={schedTasks.playlist_favorites.last_run_at} running={schedRunning.playlist_favorites} onToggle={() => toggleSched('playlist_favorites')} onUpdate={(u) => updateSched('playlist_favorites', u)} onRun={() => runSched('playlist_favorites')} />
			{/if}
		</Card>
	{/if}
</div>
