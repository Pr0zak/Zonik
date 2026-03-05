<script>
	import { currentTrack, isPlaying } from '$lib/stores.js';
	import { formatDuration } from '$lib/utils.js';
	import { Play, Pause, Music } from 'lucide-svelte';

	let audio;
	let currentTime = 0;
	let duration = 0;

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

	$: if ($currentTrack && audio) {
		audio.src = `/rest/stream?id=${$currentTrack.id}&u=admin&p=admin&v=1.16.1&c=zonik-web`;
		audio.play();
		$isPlaying = true;
	}

	// React to external isPlaying changes (e.g. keyboard shortcut)
	$: if (audio && $currentTrack) {
		if ($isPlaying && audio.paused) {
			audio.play();
		} else if (!$isPlaying && !audio.paused) {
			audio.pause();
		}
	}
</script>

<div class="h-16 bg-[var(--bg-secondary)] border-t border-[var(--border-subtle)] flex items-center px-4 gap-4 shrink-0">
	{#if $currentTrack}
		<div class="flex items-center gap-3 w-64 min-w-0">
			<div class="w-10 h-10 bg-[var(--bg-tertiary)] rounded flex items-center justify-center flex-shrink-0">
				<Music class="w-4 h-4 text-[var(--text-disabled)]" />
			</div>
			<div class="min-w-0">
				<p class="text-sm font-medium text-[var(--text-primary)] truncate">{$currentTrack.title}</p>
				<p class="text-xs text-[var(--text-secondary)] truncate">{$currentTrack.artist || 'Unknown'}</p>
			</div>
		</div>

		<div class="flex-1 flex flex-col items-center gap-1">
			<div class="flex items-center gap-4">
				<button onclick={togglePlay}
					class="w-9 h-9 rounded-full bg-white text-black flex items-center justify-center hover:scale-105 transition-transform">
					{#if $isPlaying}
						<Pause class="w-4 h-4" />
					{:else}
						<Play class="w-4 h-4 ml-0.5" />
					{/if}
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

		<div class="w-32"></div>
	{:else}
		<p class="text-sm text-[var(--text-disabled)] mx-auto">No track selected</p>
	{/if}
</div>

<audio bind:this={audio}
	bind:currentTime
	bind:duration
	onended={() => { $isPlaying = false; }}
	onpause={() => { $isPlaying = false; }}
	onplay={() => { $isPlaying = true; }}>
</audio>
