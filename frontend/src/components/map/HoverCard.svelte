<script>
	// Tooltip for a hovered track in the Explore layouts.
	let { p, x, y, width } = $props();
</script>

<div class="absolute pointer-events-none z-10 px-2 py-1 rounded bg-black/85 text-white text-xs max-w-[260px]"
	style="left:{Math.min(x + 14, width - 270)}px; top:{Math.max(y - 44, 4)}px;">
	<span class="font-medium truncate block">{p.title}</span>
	<span class="text-white/60 truncate block">{p.artist || 'Unknown'} · {p.family}</span>
	<span class="font-mono text-white/50">
		{#if p.cam}<span class="text-[#22d3ee]">{p.cam.num}{p.cam.letter}</span> · {/if}{#if p.bpm}{Math.round(p.bpm)} BPM · {/if}{#if p.loudness != null}{p.loudness.toFixed(1)} dB · {/if}{p.plays ? `${p.plays} plays` : 'never played'}
	</span>
</div>
