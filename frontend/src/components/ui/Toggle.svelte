<script>
	let {
		checked = false,
		onchange = null,
		disabled = false,
		size = 'md',
		color = 'var(--color-accent)',
		label = '',
		class: className = '',
	} = $props();

	const sizes = {
		sm: { track: 'w-7 h-4', thumb: 'w-3 h-3', on: 'left-[14px]', off: 'left-0.5' },
		md: { track: 'w-8 h-5', thumb: 'w-4 h-4', on: 'left-[14px]', off: 'left-0.5' },
		lg: { track: 'w-11 h-6', thumb: 'w-5 h-5', on: 'left-[22px]', off: 'left-0.5' },
	};

	let s = $derived(sizes[size] || sizes.md);
</script>

<label class="inline-flex items-center gap-2 {disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'} {className}">
	<button
		type="button"
		onclick={() => !disabled && onchange?.(!checked)}
		{disabled}
		class="{s.track} rounded-full transition-colors relative flex-shrink-0"
		style="background: {checked ? color : 'var(--border-interactive)'}"
		aria-pressed={checked}
	>
		<span class="absolute top-0.5 {s.thumb} bg-white rounded-full transition-transform shadow-sm
			{checked ? s.on : s.off}"></span>
	</button>
	{#if label}
		<span class="text-xs text-[var(--text-secondary)]">{label}</span>
	{/if}
</label>
