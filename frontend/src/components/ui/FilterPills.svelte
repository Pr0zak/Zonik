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
			inactive: 'bg-[var(--bg-hover)] text-[var(--text-secondary)] hover:text-white hover:bg-[var(--bg-active)]',
		},
		outline: {
			active: (color) => `bg-[var(--color-${color})]/20 text-emerald-400 border border-emerald-500/30`,
			inactive: 'bg-[var(--bg-secondary)] text-[var(--text-secondary)] border border-[var(--border-subtle)] hover:bg-[var(--bg-hover)]',
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
