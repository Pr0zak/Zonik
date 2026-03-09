<!--
  SwipeRow: Wrapper with swipe-to-reveal actions.
  Left swipe reveals right actions (e.g., delete).
  Right swipe reveals left actions (e.g., favorite).

  Usage:
  <SwipeRow
    onSwipeLeft={() => deleteTrack(id)}
    onSwipeRight={() => toggleFavorite(id)}
    leftColor="bg-red-500"
    rightColor="bg-emerald-500"
    leftIcon={Trash2}
    rightIcon={Heart}
  >
    <div>Row content</div>
  </SwipeRow>
-->
<script>
	import { swipeRow } from '$lib/swipe.js';

	let {
		onSwipeLeft = null,
		onSwipeRight = null,
		leftColor = 'bg-red-500',
		rightColor = 'bg-emerald-500',
		leftIcon = null,
		rightIcon = null,
		leftLabel = '',
		rightLabel = '',
		children,
	} = $props();

	let swipeDx = $state(0);

	function handleSwipeMove(e) {
		swipeDx = e.detail.dx;
	}
</script>

<div class="relative overflow-hidden">
	<!-- Left action (revealed on right swipe) -->
	{#if onSwipeRight}
		<div class="absolute inset-y-0 left-0 w-24 flex items-center justify-center {rightColor} transition-opacity"
			style="opacity: {Math.min(1, Math.max(0, swipeDx / 80))}">
			{#if rightIcon}
				<svelte:component this={rightIcon} class="w-5 h-5 text-white" />
			{/if}
			{#if rightLabel}
				<span class="text-xs text-white ml-1">{rightLabel}</span>
			{/if}
		</div>
	{/if}

	<!-- Right action (revealed on left swipe) -->
	{#if onSwipeLeft}
		<div class="absolute inset-y-0 right-0 w-24 flex items-center justify-center {leftColor} transition-opacity"
			style="opacity: {Math.min(1, Math.max(0, -swipeDx / 80))}">
			{#if leftIcon}
				<svelte:component this={leftIcon} class="w-5 h-5 text-white" />
			{/if}
			{#if leftLabel}
				<span class="text-xs text-white ml-1">{leftLabel}</span>
			{/if}
		</div>
	{/if}

	<!-- Swipeable content -->
	<div
		use:swipeRow={{ onSwipeLeft, onSwipeRight }}
		onswipemove={handleSwipeMove}
		class="relative bg-[var(--bg-primary)]"
	>
		{@render children()}
	</div>
</div>
