<script>
	import { currentTrack, isPlaying, addToast, playNext, playPrev, trackQueue, queueIndex } from '$lib/stores.js';
	import { api } from '$lib/api.js';
	import { formatDuration } from '$lib/utils.js';
	import { Play, Pause, Music, Heart, Pencil, SkipBack, SkipForward } from 'lucide-svelte';

	let hasPrev = $derived($trackQueue.length > 0 && $queueIndex > 0);
	let hasNext = $derived($trackQueue.length > 0 && $queueIndex < $trackQueue.length - 1);

	let isFav = $state(false);
	let favIds = $state(new Set());

	// Load favorite IDs
	async function loadFavs() {
		try {
			const data = await api.getFavoriteIds();
			favIds = new Set((data.track_ids || []).map(String));
		} catch {}
	}

	$effect(() => {
		loadFavs();
	});

	$effect(() => {
		if ($currentTrack) {
			isFav = favIds.has($currentTrack.id);
		}
	});

	async function toggleFav() {
		if (!$currentTrack) return;
		try {
			if (isFav) {
				await api.unstar({ id: $currentTrack.id, type: 'track' });
				favIds.delete($currentTrack.id);
				isFav = false;
				addToast('Removed from favorites', 'success');
			} else {
				await api.star({ id: $currentTrack.id, type: 'track' });
				favIds.add($currentTrack.id);
				isFav = true;
				addToast('Added to favorites', 'success');
			}
		} catch (e) { addToast('Failed: ' + e.message, 'error'); }
	}

	let showEditModal = $state(false);
	let editForm = $state({ title: '', genre: '', year: '', track_number: '' });
	let editSaving = $state(false);

	function openEdit() {
		if (!$currentTrack) return;
		editForm = {
			title: $currentTrack.title || '',
			genre: $currentTrack.genre || '',
			year: $currentTrack.year || '',
			track_number: $currentTrack.track_number || '',
		};
		showEditModal = true;
	}

	async function saveEdit() {
		if (!$currentTrack) return;
		editSaving = true;
		try {
			const data = {};
			if (editForm.title) data.title = editForm.title;
			if (editForm.genre) data.genre = editForm.genre;
			if (editForm.year) data.year = parseInt(editForm.year) || null;
			if (editForm.track_number) data.track_number = parseInt(editForm.track_number) || null;
			await api.updateTrack($currentTrack.id, data);
			$currentTrack = { ...$currentTrack, ...data };
			showEditModal = false;
			addToast('Track updated', 'success');
		} catch (e) { addToast('Save failed: ' + e.message, 'error'); }
		finally { editSaving = false; }
	}

	let audio;
	let currentTime = $state(0);
	let duration = $state(0);

	function togglePlay() {
		if (!audio) return;
		if ($isPlaying) {
			audio.pause();
		} else {
			audio.play();
		}
		$isPlaying = !$isPlaying;
	}

	function seek(e) {
		if (!audio || !duration) return;
		const rect = e.currentTarget.getBoundingClientRect();
		const pct = (e.clientX - rect.left) / rect.width;
		audio.currentTime = pct * duration;
	}

	let lastTrackId = $state(null);
	$effect(() => {
		if ($currentTrack && audio && $currentTrack.id !== lastTrackId) {
			lastTrackId = $currentTrack.id;
			audio.src = `/rest/stream?id=${$currentTrack.id}&v=1.16.1&c=zonik-web`;
			audio.play();
			$isPlaying = true;
		}
	});

	// React to external isPlaying changes (e.g. keyboard shortcut)
	$effect(() => {
		if (audio && $currentTrack) {
			if ($isPlaying && audio.paused) {
				audio.play();
			} else if (!$isPlaying && !audio.paused) {
				audio.pause();
			}
		}
	});
</script>

<div class="h-16 bg-[var(--bg-secondary)] border-t border-[var(--border-subtle)] flex items-center px-4 gap-4 shrink-0">
	{#if $currentTrack}
		<div class="flex items-center gap-3 w-72 min-w-0">
			<div class="w-10 h-10 bg-[var(--bg-tertiary)] rounded flex-shrink-0 overflow-hidden">
				{#if $currentTrack.id}
					<img src="/rest/getCoverArt?id={$currentTrack.id}&size=80"
						alt="" class="w-full h-full object-cover"
						onerror={(e) => { e.target.style.display = 'none'; e.target.nextElementSibling.style.display = 'flex'; }} />
					<div class="w-full h-full items-center justify-center hidden">
						<Music class="w-4 h-4 text-[var(--text-disabled)]" />
					</div>
				{:else}
					<div class="w-full h-full flex items-center justify-center">
						<Music class="w-4 h-4 text-[var(--text-disabled)]" />
					</div>
				{/if}
			</div>
			<div class="min-w-0">
				<p class="text-sm font-medium text-[var(--text-primary)] truncate">{$currentTrack.title}</p>
				<p class="text-xs text-[var(--text-secondary)] truncate">{$currentTrack.artist || 'Unknown'}{#if $currentTrack.album} — {$currentTrack.album}{/if}</p>
			</div>
		</div>

		<div class="flex-1 flex flex-col items-center gap-1">
			<div class="flex items-center gap-3">
				<button onclick={playPrev} disabled={!hasPrev}
					class="p-1 text-[var(--text-secondary)] hover:text-white transition-colors disabled:opacity-30 disabled:cursor-default">
					<SkipBack class="w-4 h-4" />
				</button>
				<button onclick={togglePlay}
					class="w-9 h-9 rounded-full bg-white text-black flex items-center justify-center hover:scale-105 transition-transform">
					{#if $isPlaying}
						<Pause class="w-4 h-4" />
					{:else}
						<Play class="w-4 h-4 ml-0.5" />
					{/if}
				</button>
				<button onclick={playNext} disabled={!hasNext}
					class="p-1 text-[var(--text-secondary)] hover:text-white transition-colors disabled:opacity-30 disabled:cursor-default">
					<SkipForward class="w-4 h-4" />
				</button>
			</div>
			<div class="w-full max-w-md flex items-center gap-2 text-xs text-[var(--text-muted)]">
				<span class="font-mono tabular-nums">{formatDuration(currentTime)}</span>
				<!-- svelte-ignore a11y_click_events_have_key_events -->
				<!-- svelte-ignore a11y_no_static_element_interactions -->
				<div class="flex-1 h-1 bg-[var(--border-interactive)] rounded-full cursor-pointer group" onclick={seek}>
					<div class="h-full bg-[var(--color-accent)] rounded-full transition-all"
						style="width: {duration ? (currentTime / duration * 100) : 0}%"></div>
				</div>
				<span class="font-mono tabular-nums">{formatDuration(duration)}</span>
			</div>
		</div>

		<div class="w-32 flex items-center justify-end gap-2">
			<button onclick={toggleFav}
				class="p-1.5 rounded-md transition-colors {isFav ? 'text-red-400 hover:text-red-300' : 'text-[var(--text-muted)] hover:text-white'}"
				title={isFav ? 'Unfavorite' : 'Favorite'}>
				<Heart class="w-4 h-4" fill={isFav ? 'currentColor' : 'none'} />
			</button>
			<button onclick={openEdit}
				class="p-1.5 rounded-md text-[var(--text-muted)] hover:text-white transition-colors"
				title="Edit track info">
				<Pencil class="w-4 h-4" />
			</button>
		</div>
	{:else}
		<p class="text-sm text-[var(--text-disabled)] mx-auto">No track selected</p>
	{/if}
</div>

{#if showEditModal}
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center" onclick={() => showEditModal = false}>
		<!-- svelte-ignore a11y_click_events_have_key_events -->
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div class="bg-[var(--bg-secondary)] border border-[var(--border-subtle)] rounded-xl shadow-2xl p-6 w-full max-w-md mx-4" onclick={(e) => e.stopPropagation()}>
			<h3 class="text-lg font-semibold text-[var(--text-primary)] mb-4">Edit Track</h3>
			<div class="space-y-3">
				<div>
					<label class="block text-xs text-[var(--text-muted)] mb-1">Title</label>
					<input type="text" bind:value={editForm.title}
						class="w-full bg-[var(--bg-primary)] border border-[var(--border-interactive)] rounded-md px-3 py-2 text-sm
							focus:outline-none focus:ring-1 focus:border-[var(--color-accent)]/50 focus:ring-[var(--color-accent)]/20" />
				</div>
				<div class="grid grid-cols-3 gap-3">
					<div>
						<label class="block text-xs text-[var(--text-muted)] mb-1">Genre</label>
						<input type="text" bind:value={editForm.genre}
							class="w-full bg-[var(--bg-primary)] border border-[var(--border-interactive)] rounded-md px-3 py-2 text-sm
								focus:outline-none focus:ring-1 focus:border-[var(--color-accent)]/50 focus:ring-[var(--color-accent)]/20" />
					</div>
					<div>
						<label class="block text-xs text-[var(--text-muted)] mb-1">Year</label>
						<input type="number" bind:value={editForm.year}
							class="w-full bg-[var(--bg-primary)] border border-[var(--border-interactive)] rounded-md px-3 py-2 text-sm
								focus:outline-none focus:ring-1 focus:border-[var(--color-accent)]/50 focus:ring-[var(--color-accent)]/20" />
					</div>
					<div>
						<label class="block text-xs text-[var(--text-muted)] mb-1">Track #</label>
						<input type="number" bind:value={editForm.track_number}
							class="w-full bg-[var(--bg-primary)] border border-[var(--border-interactive)] rounded-md px-3 py-2 text-sm
								focus:outline-none focus:ring-1 focus:border-[var(--color-accent)]/50 focus:ring-[var(--color-accent)]/20" />
					</div>
				</div>
			</div>
			<div class="flex justify-end gap-2 mt-5">
				<button onclick={() => showEditModal = false}
					class="px-4 py-2 text-sm text-[var(--text-secondary)] hover:text-white transition-colors">Cancel</button>
				<button onclick={saveEdit} disabled={editSaving}
					class="px-4 py-2 text-sm bg-[var(--color-accent)] text-white rounded-md hover:opacity-90 transition-opacity disabled:opacity-50">
					{editSaving ? 'Saving...' : 'Save'}
				</button>
			</div>
		</div>
	</div>
{/if}

<audio bind:this={audio}
	ontimeupdate={() => { currentTime = audio.currentTime; }}
	onloadedmetadata={() => { duration = audio.duration; }}
	ondurationchange={() => { duration = audio.duration; }}
	onended={() => { if (hasNext) { playNext(); } else { $isPlaying = false; currentTime = 0; } }}
	onpause={() => { $isPlaying = false; }}
	onplay={() => { $isPlaying = true; }}>
</audio>
