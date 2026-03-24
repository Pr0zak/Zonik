<script>
	let {
		variant = 'default',
		class: className = '',
		children,
	} = $props();

	const variants = {
		success: 'bg-emerald-500/10 text-emerald-400 ring-emerald-500/20',
		warning: 'bg-amber-500/10 text-amber-400 ring-amber-500/20',
		error: 'bg-red-500/10 text-red-400 ring-red-500/20',
		info: 'bg-blue-500/10 text-blue-400 ring-blue-500/20',
		default: 'bg-[var(--surface-container-high)] text-[var(--text-secondary)] ring-[var(--outline-variant)]/30',
	};
</script>

<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ring-1 {variants[variant]} {className}">
	{@render children()}
</span>
