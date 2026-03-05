<script>
	let {
		type = 'text',
		placeholder = '',
		value = $bindable(''),
		error = false,
		class: className = '',
		...rest
	} = $props();

	const base = 'bg-[var(--bg-secondary)] border text-white placeholder-[var(--text-disabled)] rounded-md px-3 py-2 text-sm transition-colors duration-200 focus:outline-none focus:ring-1 w-full';
	const normal = 'border-[var(--border-interactive)] focus:border-[var(--color-accent)]/50 focus:ring-[var(--color-accent)]/20';
	const errorStyle = 'border-red-500/50 focus:border-red-500 focus:ring-red-500/20';
</script>

<input
	{type}
	{placeholder}
	bind:value
	class="{base} {error ? errorStyle : normal} {className}"
	{...rest}
/>
