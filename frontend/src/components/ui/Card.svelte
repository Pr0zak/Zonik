<script>
	let {
		variant = 'default',
		hover = false,
		padding = 'p-4',
		class: className = '',
		children,
	} = $props();

	const base = 'bg-[var(--bg-secondary)] border border-[var(--border-subtle)] rounded-lg transition-colors duration-200';

	const hoverClass = hover ? 'hover:border-[var(--border-interactive)]' : '';
</script>

<div class="{base} {hoverClass} {padding} {className}">
	{@render children()}
</div>
