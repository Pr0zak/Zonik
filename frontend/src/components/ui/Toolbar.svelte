<script>
	let {
		sticky = true,
		topClass = 'top-0',
		row1Left,
		row1Right,
		row2Left,
		row2Right,
		class: className = '',
	} = $props();

	let stickyClass = $derived(sticky ? `sticky ${topClass} z-10 bg-[var(--bg-primary)]` : '');
	let hasRow2 = $derived(!!(row2Left || row2Right));
</script>

<div class="{stickyClass} pt-3 pb-2 mt-3 mb-3 space-y-2 {className}">
	<div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2 sm:gap-3">
		<div class="flex items-center gap-2 flex-wrap min-w-0">
			{#if row1Left}{@render row1Left()}{/if}
		</div>
		<div class="flex items-center gap-2 flex-shrink-0 flex-wrap">
			{#if row1Right}{@render row1Right()}{/if}
		</div>
	</div>
	{#if hasRow2}
		<div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2 sm:gap-3">
			<div class="flex items-center gap-2 flex-wrap min-w-0 text-xs">
				{#if row2Left}{@render row2Left()}{/if}
			</div>
			<div class="flex items-center gap-2 flex-shrink-0 flex-wrap">
				{#if row2Right}{@render row2Right()}{/if}
			</div>
		</div>
	{/if}
</div>
