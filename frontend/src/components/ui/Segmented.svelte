<script>
	/**
	 * Segmented control: one choice out of a few, shown side by side (e.g. the
	 * Downloads scope Today | 7 days | 30 days). Tonal, no border; the active
	 * segment lifts to surface-container-high. Optional mono counts per option.
	 *
	 * options:  [{ value, label, count? }]
	 * value:    the selected option's value
	 * onchange: (value) => void
	 * size:     'sm' (default, card heads) | 'md'
	 */
	let {
		options = [],
		value = null,
		onchange,
		size = 'sm',
		label = '',
		class: className = '',
	} = $props();

	const sizes = {
		sm: 'px-3 py-1.5 text-xs',
		md: 'px-4 py-2 text-sm',
	};
	let sizeClass = $derived(sizes[size] || sizes.sm);
</script>

<div class="inline-flex max-w-full rounded-lg p-0.5 bg-[var(--surface-container)] {className}" role="group" aria-label={label || undefined}>
	{#each options as opt (opt.value)}
		{@const isActive = value === opt.value}
		<button
			type="button"
			aria-pressed={isActive}
			onclick={() => { if (!isActive) onchange?.(opt.value); }}
			class="{sizeClass} rounded-md font-medium whitespace-nowrap transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500/50
				{isActive ? 'bg-[var(--surface-container-high)] text-[var(--text-primary)] shadow-sm' : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'}"
		>
			{opt.label}{#if opt.count != null}<span class="ml-1 font-mono text-[11px] text-[var(--text-muted)]">{Number(opt.count).toLocaleString()}</span>{/if}
		</button>
	{/each}
</div>
