<script>
	import { Star } from 'lucide-svelte';

	let { rating = 0, onrate = null, size = 'sm' } = $props();
	let hovered = $state(-1);

	const sizes = { xs: 'w-3 h-3', sm: 'w-4 h-4', md: 'w-5 h-5' };
	const sizeClass = $derived(sizes[size] || sizes.sm);

	function handleClick(star) {
		if (!onrate) return;
		// Click same rating to clear
		onrate(star === rating ? 0 : star);
	}
</script>

<div class="inline-flex items-center gap-0.5" role="group" aria-label="Rating">
	{#each [1, 2, 3, 4, 5] as star}
		{@const filled = star <= (hovered >= 0 ? hovered : rating)}
		<button
			onclick={() => handleClick(star)}
			onmouseenter={() => { if (onrate) hovered = star; }}
			onmouseleave={() => hovered = -1}
			class="p-0 border-0 bg-transparent transition-colors {onrate ? 'cursor-pointer' : 'cursor-default'}"
			disabled={!onrate}
		>
			<Star class="{sizeClass} transition-colors {filled ? 'text-amber-400 fill-amber-400' : 'text-[var(--text-disabled)]'}" />
		</button>
	{/each}
</div>
