<script>
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';
	import { createScheduleHelpers } from '$lib/schedule.js';
	import { addToast, playTrack as storePlayTrack } from '$lib/stores.js';
	import { formatDuration, inputClass } from '$lib/utils.js';
	import { ListMusic, Wand2, Plus, Clock, Play, Music, ArrowLeft, Trash2, ChevronLeft, ChevronRight, ChevronDown, ChevronUp, Sparkles, Import, Search, Download, Check, Loader2, ExternalLink } from 'lucide-svelte';
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
	let schedExpanded = $state(false);

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

	// AI generate
	let showAIGen = $state(false);
	let aiPrompt = $state('');
	let aiName = $state('');
	let aiLimit = $state(30);
	let aiGenerating = $state(false);

	// Import
	let showImport = $state(false);
	let importUrl = $state('');
	let importSearchQuery = $state('');
	let importFetching = $state(false);
	let importSearching = $state(false);
	let importPreview = $state(null);  // fetched playlist data
	let importSearchResults = $state([]);
	let importCreating = $state(false);

	async function fetchExternalPlaylist() {
		if (!importUrl.trim()) return;
		importFetching = true;
		importPreview = null;
		try {
			const data = await api.fetchExternalPlaylist(importUrl.trim());
			if (data.error) { addToast(data.error, 'error'); return; }
			importPreview = data;
		} catch (e) { addToast('Failed to fetch playlist: ' + e.message, 'error'); }
		finally { importFetching = false; }
	}

	async function searchExternalPlaylists() {
		if (!importSearchQuery.trim()) return;
		importSearching = true;
		try {
			const data = await api.searchExternalPlaylists(importSearchQuery.trim());
			importSearchResults = data.results || [];
			if (!importSearchResults.length) addToast('No playlists found', 'info');
		} catch (e) { addToast('Search failed: ' + e.message, 'error'); }
		finally { importSearching = false; }
	}

	async function importPlaylist(downloadMissing = false) {
		if (!importPreview) return;
		importCreating = true;
		try {
			const data = await api.importExternalPlaylist(
				importPreview.name,
				importPreview.tracks,
				downloadMissing
			);
			addToast(`Imported "${data.name}" — ${data.matched}/${data.total} matched${data.download_jobs ? `, ${data.download_jobs} downloads queued` : ''}`, 'success');
			playlists = await api.getPlaylists();
			importPreview = null;
			importUrl = '';
			showImport = false;
		} catch (e) { addToast('Import failed: ' + e.message, 'error'); }
		finally { importCreating = false; }
	}

	let aiReview = $state(null);
	let aiReviewLoading = $state(false);

	async function reviewImport() {
		if (!importPreview?.tracks?.length) return;
		aiReviewLoading = true;
		try {
			aiReview = await api.aiReviewImport(importPreview.tracks);
		} catch (e) { addToast('AI review failed', 'error'); }
		finally { aiReviewLoading = false; }
	}

	async function previewSearchResult(result) {
		importFetching = true;
		importPreview = null;
		importSearchResults = [];
		try {
			const data = await api.fetchExternalPlaylist(result.id, result.source);
			if (data.error) { addToast(data.error, 'error'); return; }
			importPreview = data;
		} catch (e) { addToast('Failed to fetch playlist', 'error'); }
		finally { importFetching = false; }
	}

	async function aiGeneratePlaylist() {
		if (!aiPrompt.trim()) return;
		aiGenerating = true;
		try {
			const data = await api.aiGeneratePlaylist(aiPrompt.trim(), aiName.trim() || null, aiLimit);
			if (data.error) {
				addToast(data.error, 'error');
			} else {
				addToast(`Created "${data.name}" with ${data.track_count} tracks`, 'success');
				playlists = await api.getPlaylists();
				showAIGen = false;
				aiPrompt = ''; aiName = '';
			}
		} catch (e) {
			addToast('Failed to generate playlist', 'error');
		} finally {
			aiGenerating = false;
		}
	}

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
		const queue = (playlistDetail || []).map(t => ({ id: t.id, title: t.title, artist: t.artist }));
		storePlayTrack({ id: track.id, title: track.title, artist: track.artist }, queue);
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

	const { toggleSched, updateSched, runSched } = createScheduleHelpers(
		() => schedTasks,
		(name, val) => { schedTasks[name] = val; },
		addToast
	);

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
		<div class="flex items-center gap-2">
			<Button onclick={() => { showImport = !showImport; if (showImport) { showAIGen = false; showGenerator = false; } }} variant="secondary" size="sm">
				{#if showImport}
					<span class="flex items-center gap-1.5">Hide Import</span>
				{:else}
					<span class="flex items-center gap-1.5"><Import class="w-4 h-4" /> Import</span>
				{/if}
			</Button>
			<Button onclick={() => { showAIGen = !showAIGen; if (showAIGen) { showGenerator = false; showImport = false; } }} variant="secondary" size="sm">
				{#if showAIGen}
					<span class="flex items-center gap-1.5">Hide AI</span>
				{:else}
					<span class="flex items-center gap-1.5"><Sparkles class="w-4 h-4 text-amber-400" /> AI Generate</span>
				{/if}
			</Button>
			<Button onclick={() => { showGenerator = !showGenerator; if (showGenerator) { showAIGen = false; showImport = false; } }} variant="secondary" size="sm">
				{#if showGenerator}
					<span class="flex items-center gap-1.5">Hide Generator</span>
				{:else}
					<span class="flex items-center gap-1.5"><Wand2 class="w-4 h-4" /> Smart Playlist</span>
				{/if}
			</Button>
		</div>
	</div>

	<!-- Collapsible Schedule -->
	{#if schedTasks.playlist_weekly_top || schedTasks.playlist_weekly_discover || schedTasks.playlist_favorites || schedTasks.playlist_unfavorites}
		<button onclick={() => schedExpanded = !schedExpanded}
			class="flex items-center gap-2 mb-3 px-3 py-1.5 rounded-md bg-[var(--bg-secondary)] hover:bg-[var(--bg-hover)] transition-colors text-xs text-[var(--text-muted)]">
			<Clock class="w-3.5 h-3.5" />
			<span class="font-mono uppercase tracking-wider">Auto-generate Schedule</span>
			{#if schedExpanded}<ChevronUp class="w-3 h-3" />{:else}<ChevronDown class="w-3 h-3" />{/if}
		</button>
		{#if schedExpanded}
			<Card padding="p-4" class="mb-4">
				{#if schedTasks.playlist_weekly_top}
					<ScheduleControl taskName="playlist_weekly_top" label="Weekly Top" enabled={schedTasks.playlist_weekly_top.enabled} intervalHours={schedTasks.playlist_weekly_top.interval_hours} runAt={schedTasks.playlist_weekly_top.run_at} dayOfWeek={schedTasks.playlist_weekly_top.day_of_week} count={schedTasks.playlist_weekly_top.count} lastRunAt={schedTasks.playlist_weekly_top.last_run_at} running={schedRunning.playlist_weekly_top} onToggle={() => toggleSched('playlist_weekly_top')} onUpdate={(u) => updateSched('playlist_weekly_top', u)} onRun={() => runSched('playlist_weekly_top')} />
				{/if}
				{#if schedTasks.playlist_weekly_discover}
					<ScheduleControl taskName="playlist_weekly_discover" label="Weekly Discover" enabled={schedTasks.playlist_weekly_discover.enabled} intervalHours={schedTasks.playlist_weekly_discover.interval_hours} runAt={schedTasks.playlist_weekly_discover.run_at} dayOfWeek={schedTasks.playlist_weekly_discover.day_of_week} count={schedTasks.playlist_weekly_discover.count} lastRunAt={schedTasks.playlist_weekly_discover.last_run_at} running={schedRunning.playlist_weekly_discover} onToggle={() => toggleSched('playlist_weekly_discover')} onUpdate={(u) => updateSched('playlist_weekly_discover', u)} onRun={() => runSched('playlist_weekly_discover')} />
				{/if}
				{#if schedTasks.playlist_favorites}
					<ScheduleControl taskName="playlist_favorites" label="Favorites Playlist" enabled={schedTasks.playlist_favorites.enabled} intervalHours={schedTasks.playlist_favorites.interval_hours} runAt={schedTasks.playlist_favorites.run_at} lastRunAt={schedTasks.playlist_favorites.last_run_at} running={schedRunning.playlist_favorites} onToggle={() => toggleSched('playlist_favorites')} onUpdate={(u) => updateSched('playlist_favorites', u)} onRun={() => runSched('playlist_favorites')} />
				{/if}
				{#if schedTasks.playlist_unfavorites}
					<ScheduleControl taskName="playlist_unfavorites" label="Unfavorites Playlist" enabled={schedTasks.playlist_unfavorites.enabled} intervalHours={schedTasks.playlist_unfavorites.interval_hours} runAt={schedTasks.playlist_unfavorites.run_at} lastRunAt={schedTasks.playlist_unfavorites.last_run_at} running={schedRunning.playlist_unfavorites} onToggle={() => toggleSched('playlist_unfavorites')} onUpdate={(u) => updateSched('playlist_unfavorites', u)} onRun={() => runSched('playlist_unfavorites')} />
				{/if}
			</Card>
		{/if}
	{/if}

	{#if showImport}
		<Card padding="p-4" class="mb-6">
			<div class="flex items-center gap-2 mb-4">
				<Import class="w-4 h-4 text-blue-400" />
				<h3 class="text-base font-semibold text-[var(--text-primary)]">Import External Playlist</h3>
			</div>

			<!-- URL import -->
			<div class="mb-4">
				<label class="block text-xs text-[var(--text-muted)] mb-1.5">Paste a Spotify, Apple Music, or Deezer playlist URL</label>
				<div class="flex gap-2">
					<input type="text" bind:value={importUrl} placeholder="https://open.spotify.com/playlist/..." class="{inputClass} flex-1"
						onkeydown={(e) => { if (e.key === 'Enter') fetchExternalPlaylist(); }} />
					<Button variant="primary" size="sm" loading={importFetching} onclick={fetchExternalPlaylist} disabled={!importUrl.trim()}>
						Fetch
					</Button>
				</div>
			</div>

			<!-- Or search -->
			<div class="border-t border-[var(--border-subtle)] pt-3">
				<label class="block text-xs text-[var(--text-muted)] mb-1.5">Or search for playlists</label>
				<div class="flex gap-2">
					<input type="text" bind:value={importSearchQuery} placeholder="Search Spotify & Deezer..." class="{inputClass} flex-1"
						onkeydown={(e) => { if (e.key === 'Enter') searchExternalPlaylists(); }} />
					<Button variant="secondary" size="sm" loading={importSearching} onclick={searchExternalPlaylists} disabled={!importSearchQuery.trim()}>
						<Search class="w-3.5 h-3.5" /> Search
					</Button>
				</div>
			</div>

			<!-- Search results -->
			{#if importSearchResults.length}
				<div class="mt-3 space-y-2">
					{#each importSearchResults as result}
						<button class="w-full flex items-center gap-3 p-2 rounded-lg bg-[var(--bg-tertiary)] hover:bg-[var(--bg-hover)] transition-colors text-left"
							onclick={() => previewSearchResult(result)}>
							{#if result.image_url}
								<img src={result.image_url} alt="" class="w-10 h-10 rounded object-cover flex-shrink-0" />
							{:else}
								<div class="w-10 h-10 rounded bg-[var(--bg-secondary)] flex items-center justify-center flex-shrink-0">
									<ListMusic class="w-4 h-4 text-[var(--text-disabled)]" />
								</div>
							{/if}
							<div class="flex-1 min-w-0">
								<p class="text-sm text-[var(--text-primary)] truncate">{result.name}</p>
								<p class="text-xs text-[var(--text-muted)]">{result.owner} &middot; {result.track_count} tracks &middot; <span class="capitalize">{result.source.replace('_', ' ')}</span></p>
							</div>
							<ExternalLink class="w-3.5 h-3.5 text-[var(--text-disabled)] flex-shrink-0" />
						</button>
					{/each}
				</div>
			{/if}

			<!-- Preview -->
			{#if importPreview}
				<div class="mt-4 border-t border-[var(--border-subtle)] pt-4">
					<div class="flex items-center gap-3 mb-3">
						{#if importPreview.image_url}
							<img src={importPreview.image_url} alt="" class="w-14 h-14 rounded-lg object-cover" />
						{/if}
						<div class="flex-1 min-w-0">
							<h4 class="font-semibold text-[var(--text-primary)] truncate">{importPreview.name}</h4>
							<p class="text-xs text-[var(--text-muted)]">
								{importPreview.owner} &middot; {importPreview.track_count} tracks &middot;
								<span class="text-emerald-400">{importPreview.matched_count || 0} in library</span>
							</p>
						</div>
					</div>

					<!-- Track list preview -->
					<div class="max-h-60 overflow-y-auto space-y-1 mb-3">
						{#each importPreview.tracks?.slice(0, 50) || [] as track}
							<div class="flex items-center gap-2 text-xs px-2 py-1 rounded {track.in_library ? 'bg-emerald-500/10' : 'bg-[var(--bg-tertiary)]'}">
								{#if track.in_library}
									<Check class="w-3 h-3 text-emerald-400 flex-shrink-0" />
								{:else}
									<Download class="w-3 h-3 text-[var(--text-disabled)] flex-shrink-0" />
								{/if}
								<span class="text-[var(--text-body)] truncate flex-1">{track.title}</span>
								<span class="text-[var(--text-muted)] truncate max-w-32">{track.artist}</span>
							</div>
						{/each}
						{#if (importPreview.tracks?.length || 0) > 50}
							<p class="text-xs text-[var(--text-muted)] text-center py-1">...and {importPreview.tracks.length - 50} more</p>
						{/if}
					</div>

					<!-- AI Review -->
					{#if aiReview}
						<div class="mb-3 p-3 rounded-lg bg-amber-500/10 border border-amber-500/20">
							<div class="flex items-center gap-2 mb-1">
								<Sparkles class="w-3.5 h-3.5 text-amber-400" />
								<span class="text-xs font-medium text-amber-400">AI Review: {Math.round((aiReview.overall_score || 0) * 100)}% match</span>
							</div>
							{#if aiReview.summary}
								<p class="text-xs text-[var(--text-muted)]">{aiReview.summary}</p>
							{/if}
						</div>
					{/if}

					<div class="flex items-center gap-2 justify-end">
						<Button variant="secondary" size="sm" loading={aiReviewLoading} onclick={reviewImport}>
							<Sparkles class="w-3.5 h-3.5 text-amber-400" /> AI Review
						</Button>
						<Button variant="secondary" size="sm" onclick={() => { importPreview = null; aiReview = null; }}>Cancel</Button>
						<Button variant="primary" size="sm" loading={importCreating} onclick={() => importPlaylist(false)}>
							Import Matched
						</Button>
						<Button variant="success" size="sm" loading={importCreating} onclick={() => importPlaylist(true)}>
							<Download class="w-3.5 h-3.5" /> Import + Download Missing
						</Button>
					</div>
				</div>
			{/if}
		</Card>
	{/if}

	{#if showAIGen}
		<Card padding="p-4" class="mb-6">
			<div class="flex items-center gap-2 mb-4">
				<Sparkles class="w-4 h-4 text-amber-400" />
				<h3 class="text-base font-semibold text-[var(--text-primary)]">AI Playlist Generator</h3>
			</div>
			<p class="text-xs text-[var(--text-muted)] mb-3">Describe the playlist you want in plain English. AI will pick tracks from your library.</p>
			<div class="space-y-3">
				<div>
					<label class="block text-xs text-[var(--text-muted)] mb-1.5">Prompt</label>
					<input type="text" bind:value={aiPrompt} placeholder="e.g. Make a playlist for a late night drive" class={inputClass} />
				</div>
				<div class="grid grid-cols-1 md:grid-cols-2 gap-3">
					<div>
						<label class="block text-xs text-[var(--text-muted)] mb-1.5">Name (optional)</label>
						<input type="text" bind:value={aiName} placeholder="Auto-generated if empty" class={inputClass} />
					</div>
					<div>
						<label class="block text-xs text-[var(--text-muted)] mb-1.5">Max Tracks: {aiLimit}</label>
						<div class="flex items-center gap-3">
							<input type="range" bind:value={aiLimit} min="10" max="100" step="5" class="flex-1 accent-amber-500" />
							<Badge>{aiLimit}</Badge>
						</div>
					</div>
				</div>
			</div>
			<div class="mt-4 flex justify-end">
				<Button onclick={aiGeneratePlaylist} disabled={!aiPrompt.trim() || aiGenerating} variant="primary" size="sm">
					<span class="flex items-center gap-1.5">
						<Sparkles class="w-4 h-4" />
						{aiGenerating ? 'Generating...' : 'Generate with AI'}
					</span>
				</Button>
			</div>
		</Card>
	{/if}

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

</div>
