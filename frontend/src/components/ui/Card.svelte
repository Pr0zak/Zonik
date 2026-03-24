<script>
	let {
		variant = 'default',
		hover = false,
		padding = 'p-4',
		class: className = '',
		children,
	} = $props();

	const base = 'bg-[var(--surface-container)] rounded-lg transition-colors duration-200';

	const hoverClass = hover ? 'hover:bg-[var(--surface-container-high)]' : '';
</script>

<div class="{base} {hoverClass} {padding} overflow-x-auto {className}">
	{@render children()}
</div>
