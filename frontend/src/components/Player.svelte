<script>
	import { currentTrack, isPlaying } from '$lib/stores.js';
	import { formatDuration } from '$lib/utils.js';

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
</script>

<div class="h-16 bg-gray-900 border-t border-gray-800 flex items-center px-4 gap-4 shrink-0">
	{#if $currentTrack}
		<div class="flex items-center gap-3 w-64 min-w-0">
			<div class="w-10 h-10 bg-gray-800 rounded flex-shrink-0"></div>
			<div class="min-w-0">
				<p class="text-sm font-medium truncate">{$currentTrack.title}</p>
				<p class="text-xs text-gray-400 truncate">{$currentTrack.artist || 'Unknown'}</p>
			</div>
		</div>

		<div class="flex-1 flex flex-col items-center gap-1">
			<div class="flex items-center gap-4">
				<button on:click={togglePlay}
					class="w-8 h-8 rounded-full bg-white text-black flex items-center justify-center text-sm hover:scale-105 transition">
					{$isPlaying ? '⏸' : '▶'}
				</button>
			</div>
			<div class="w-full max-w-md flex items-center gap-2 text-xs text-gray-400">
				<span>{formatDuration(currentTime)}</span>
				<!-- svelte-ignore a11y_click_events_have_key_events -->
				<!-- svelte-ignore a11y_no_static_element_interactions -->
				<div class="flex-1 h-1 bg-gray-700 rounded-full cursor-pointer" on:click={seek}>
					<div class="h-full bg-accent-500 rounded-full transition-all"
						style="width: {duration ? (currentTime / duration * 100) : 0}%"></div>
				</div>
				<span>{formatDuration(duration)}</span>
			</div>
		</div>

		<div class="w-32"></div>
	{:else}
		<p class="text-sm text-gray-500 mx-auto">No track selected</p>
	{/if}
</div>

<audio bind:this={audio}
	bind:currentTime
	bind:duration
	on:ended={() => { $isPlaying = false; }}
	on:pause={() => { $isPlaying = false; }}
	on:play={() => { $isPlaying = true; }}>
</audio>
