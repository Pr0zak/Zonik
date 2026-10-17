<script>
	let {
		options = [],
		value = null,
		onchange,
		variant = 'solid',
		class: className = '',
	} = $props();

	function activeStyle(color = 'accent') {
		const cssVar = color.startsWith('var(') || color.startsWith('#') ? color : `var(--color-${color}, var(--color-accent))`;
		if (variant === 'outline') {
			return `background: color-mix(in srgb, ${cssVar} 18%, transparent); color: ${cssVar}; box-shadow: inset 0 0 0 1px color-mix(in srgb, ${cssVar} 45%, transparent);`;
		}
		return `background: ${cssVar}; color: #ffffff; box-shadow: 0 2px 10px -2px color-mix(in srgb, ${cssVar} 45%, transparent);`;
	}

	const inactiveClasses = {
		solid: 'bg-[var(--surface-container-high)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-container-highest)]',
		outline: 'bg-[var(--surface-container)] text-[var(--text-secondary)] ghost-border hover:text-[var(--text-primary)] hover:bg-[var(--surface-container-high)]',
	};
</script>

<div class="flex gap-1.5 flex-wrap {className}">
	{#each options as opt}
		{@const isActive = value === opt.value}
		<button
			onclick={() => onchange?.(opt.value)}
			style={isActive ? activeStyle(opt.color || 'accent') : ''}
			class="px-3 py-1.5 rounded-lg text-xs font-medium transition-all duration-150 whitespace-nowrap flex items-center gap-1.5
				{isActive ? '' : inactiveClasses[variant]}">
			<span>{opt.label}</span>
			{#if opt.count != null}
				<span class="font-mono text-[11px] {isActive ? 'opacity-90 bg-black/20 px-1.5 py-0.2 rounded-full' : 'opacity-65'}">{opt.count.toLocaleString()}</span>
			{/if}
		</button>
	{/each}
</div>
