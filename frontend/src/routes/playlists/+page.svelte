<script>
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';
	import { currentTrack, addToast } from '$lib/stores.js';
	import { formatDuration, inputClass } from '$lib/utils.js';
	import { ListMusic, Wand2, Plus, Clock, Play, Music, ArrowLeft, Trash2, ChevronLeft, ChevronRight } from 'lucide-svelte';
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

	// Detail view
	let selectedPlaylist = $state(null);
	let playlistDetail = $state(null);
	let detailLoading = $state(false);
	let deleting = $state(false);
	let trackOffset = $state(0);
	let trackLimit = $state(25);
	const trackLimitOptions = [25, 50, 100, 200];

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

	let paginatedTracks = $derived(
		playlistDetail?.tracks?.slice(trackOffset, trackOffset + trackLimit) || []
	);
	let totalTracks = $derived(playlistDetail?.tracks?.length || 0);

	async function openPlaylist(playlist) {
		selectedPlaylist = playlist;
		detailLoading = true;
		trackOffset = 0;
		try {
			playlistDetail = await fetch(`/api/playlists/${playlist.id}`).then(r => r.json());
		} catch (e) {
			addToast('Failed to load playlist', 'error');
		} finally {
			detailLoading = false;
		}
	}

	function closeDetail() {
		selectedPlaylist = null;
		playlistDetail = null;
	}

	function playTrack(track) {
		$currentTrack = { id: track.id, title: track.title, artist: track.artist };
	}

	async function deletePlaylist(id) {
		if (!window.confirm('Delete this playlist?')) return;
		deleting = true;
		try {
			await fetch(`/api/playlists/${id}`, { method: 'DELETE' });
			playlists = playlists.filter(p => p.id !== id);
			closeDetail();
			addToast('Playlist deleted', 'success');
		} catch { addToast('Failed to delete playlist', 'error'); }
		finally { deleting = false; }
	}

	function coverUrl(id) {
		if (!id) return null;
		return `/rest/getCoverArt?id=${id}`;
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
		} catch (e) { console.error('Schedule load failed:', e); }
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
		<Card padding="p-4" class="mb-6">
			<div class="flex items-center gap-2 mb-4">
				<Wand2 class="w-4 h-4 text-amber-400" />
				<h3 class="text-base font-semibold text-[var(--text-primary)]">Generate Smart Playlist</h3>
			</div>

			<div class="grid grid-cols-1 md:grid-cols-2 gap-4">
				<div>
					<label class="block text-xs text-[var(--text-muted)] mb-1.5">Playlist Name</label>
					<input type="text" bind:value={genName} placeholder="My Smart Playlist" class={inputClass} />
				</div>

				<div>
					<label class="block text-xs text-[var(--text-muted)] mb-1.5">Rule</label>
					<select bind:value={genRule} class={inputClass}>
						{#each ruleOptions as opt}
							<option value={opt.value}>{opt.label}</option>
						{/each}
					</select>
				</div>

				{#if selectedRule?.needsValue}
					<div>
						<label class="block text-xs text-[var(--text-muted)] mb-1.5">Value</label>
						<input type="text" bind:value={genValue} placeholder={selectedRule.placeholder} class={inputClass} />
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

	{#if selectedPlaylist}
		<!-- Detail View -->
		<div class="mb-4 flex items-center gap-3">
			<Button variant="ghost" size="sm" onclick={closeDetail}>
				<ArrowLeft class="w-4 h-4" />
			</Button>
			<div class="flex-1 min-w-0">
				<h2 class="text-lg font-semibold text-[var(--text-primary)] truncate">{selectedPlaylist.name}</h2>
				{#if playlistDetail?.comment}
					<p class="text-xs text-[var(--text-muted)]">{playlistDetail.comment}</p>
				{/if}
			</div>
			<span class="text-sm text-[var(--text-muted)] font-mono">{selectedPlaylist.track_count} tracks</span>
			<Button variant="ghost" size="sm" loading={deleting} onclick={() => deletePlaylist(selectedPlaylist.id)}>
				<Trash2 class="w-4 h-4 text-red-400" />
			</Button>
		</div>

		{#if detailLoading}
			<div class="space-y-2">
				{#each Array(8) as _}
					<Skeleton class="h-14 rounded-lg" />
				{/each}
			</div>
		{:else if playlistDetail?.tracks?.length}
			<Card padding="p-0">
				<div class="divide-y divide-[var(--border-subtle)]">
					{#each paginatedTracks as track, i}
						<button class="w-full flex items-center gap-3 px-4 py-3 hover:bg-[var(--bg-hover)] transition-colors group text-left"
							onclick={() => playTrack(track)}>
							<span class="text-xs text-[var(--text-disabled)] font-mono w-6 text-right flex-shrink-0">{trackOffset + i + 1}</span>
							<div class="relative w-9 h-9 rounded bg-[var(--bg-secondary)] overflow-hidden flex-shrink-0">
								{#if coverUrl(track.cover_art)}
									<img src={coverUrl(track.cover_art)} alt="" class="w-full h-full object-cover" loading="lazy" />
								{:else}
									<div class="flex items-center justify-center w-full h-full">
										<Music class="w-3.5 h-3.5 text-[var(--text-disabled)]" />
									</div>
								{/if}
								<div class="absolute inset-0 bg-black/0 group-hover:bg-black/40 transition-colors flex items-center justify-center">
									<Play class="w-4 h-4 text-white opacity-0 group-hover:opacity-100 transition-opacity" />
								</div>
							</div>
							<div class="flex-1 min-w-0">
								<p class="text-sm font-medium text-[var(--text-primary)] truncate">{track.title}</p>
								<p class="text-xs text-[var(--text-muted)] truncate">{track.artist || 'Unknown'}{#if track.album}<span class="text-[var(--text-disabled)]"> &middot; {track.album}</span>{/if}</p>
							</div>
							{#if track.duration}
								<span class="text-xs text-[var(--text-muted)] font-mono flex-shrink-0 hidden sm:block">{formatDuration(track.duration)}</span>
							{/if}
						</button>
					{/each}
				</div>
			</Card>

			<div class="flex justify-center items-center gap-3 mt-4">
				{#if totalTracks > trackLimit}
					<Button variant="secondary" size="sm" disabled={trackOffset === 0} onclick={() => { trackOffset = Math.max(0, trackOffset - trackLimit); }}>
						<ChevronLeft class="w-4 h-4" /> Prev
					</Button>
					<span class="text-sm text-[var(--text-muted)] font-mono">
						{trackOffset + 1}-{Math.min(trackOffset + trackLimit, totalTracks)} of {totalTracks}
					</span>
					<Button variant="secondary" size="sm" disabled={trackOffset + trackLimit >= totalTracks} onclick={() => { trackOffset += trackLimit; }}>
						Next <ChevronRight class="w-4 h-4" />
					</Button>
				{/if}
				<select value={trackLimit}
					onchange={(e) => { trackLimit = parseInt(e.target.value); trackOffset = 0; }}
					class="bg-[var(--bg-secondary)] border border-[var(--border-interactive)] rounded-md px-2 py-1 text-xs text-[var(--text-body)] focus:outline-none">
					{#each trackLimitOptions as opt}
						<option value={opt} selected={opt === trackLimit}>{opt} / page</option>
					{/each}
				</select>
			</div>
		{:else}
			<Card>
				<EmptyState title="Empty playlist" description="This playlist has no tracks.">
					{#snippet icon()}<ListMusic class="w-10 h-10" />{/snippet}
				</EmptyState>
			</Card>
		{/if}
	{:else if loading}
		<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
			{#each Array(6) as _}
				<Skeleton class="h-20 rounded-lg" />
			{/each}
		</div>
	{:else if playlists.length}
		<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
			{#each playlists as playlist}
				<!-- svelte-ignore a11y_click_events_have_key_events -->
				<!-- svelte-ignore a11y_no_static_element_interactions -->
				<div onclick={() => openPlaylist(playlist)}>
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
				</div>
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
