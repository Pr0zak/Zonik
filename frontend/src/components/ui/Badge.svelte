<script>
	let {
		variant = 'default',
		size = 'md', // 'md' | 'sm' (compact, for dense rows)
		class: className = '',
		children,
	} = $props();

	const variants = {
		success: 'bg-emerald-500/10 text-emerald-400 ring-emerald-500/20',
		warning: 'bg-amber-500/10 text-amber-400 ring-amber-500/20',
		error: 'bg-red-500/10 text-red-400 ring-red-500/20',
		info: 'bg-blue-500/10 text-blue-400 ring-blue-500/20',
		default: 'bg-[var(--surface-container-high)] text-[var(--text-secondary)] ring-[color-mix(in_srgb,var(--outline-variant)_30%,transparent)]',
	};
	// Size classes are chosen, not appended, so `sm` never fights the `md` padding/text in the CSS cascade.
	const sizes = {
		md: 'px-2 py-0.5 text-xs',
		sm: 'text-[10px] px-1.5 py-0 leading-4',
	};
</script>

<span class="inline-flex items-center rounded-full font-medium ring-1 {sizes[size] || sizes.md} {variants[variant]} {className}">
	{@render children()}
</span>
