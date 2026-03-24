<script>
	let {
		options = [],
		value = null,
		onchange,
		variant = 'solid',
		class: className = '',
	} = $props();

	const styles = {
		solid: {
			active: (color) => `bg-[var(--color-${color})] text-white`,
			inactive: 'bg-[var(--surface-container-high)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-container-highest)]',
		},
		outline: {
			active: (color) => `bg-[var(--color-${color})]/20 text-emerald-400 ghost-border`,
			inactive: 'bg-[var(--surface-container)] text-[var(--text-secondary)] ghost-border hover:bg-[var(--surface-container-high)]',
		},
	};
</script>

<div class="flex gap-1.5 flex-wrap {className}">
	{#each options as opt}
		<button
			onclick={() => onchange?.(opt.value)}
			class="px-3 py-2 sm:py-1.5 rounded-md text-xs font-medium transition-colors whitespace-nowrap
				{value === opt.value
					? styles[variant].active(opt.color || 'accent')
					: styles[variant].inactive}">
			{opt.label}
			{#if opt.count != null}
				<span class="ml-1 opacity-70">{opt.count}</span>
			{/if}
		</button>
	{/each}
</div>
