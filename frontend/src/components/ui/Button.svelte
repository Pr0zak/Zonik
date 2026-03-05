<script>
	import { Loader2 } from 'lucide-svelte';

	let {
		variant = 'primary',
		size = 'md',
		loading = false,
		disabled = false,
		class: className = '',
		onclick,
		type = 'button',
		children,
		...rest
	} = $props();

	const base = 'inline-flex items-center justify-center font-medium transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)] focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--bg-primary)] disabled:opacity-50 disabled:cursor-not-allowed';

	const variants = {
		primary: 'bg-[var(--color-accent)] hover:bg-[var(--color-accent-hover)] text-white rounded-md',
		secondary: 'bg-[var(--bg-hover)] hover:bg-[#222] text-white border border-[var(--border-interactive)] rounded-md',
		ghost: 'text-[var(--text-secondary)] hover:text-white hover:bg-[var(--bg-hover)] rounded-md',
		danger: 'text-red-400 hover:bg-red-500/10 border border-red-500/20 hover:border-red-500/40 rounded-md',
		success: 'bg-emerald-600 hover:bg-emerald-700 text-white rounded-md',
		icon: 'text-[var(--text-secondary)] hover:text-white hover:bg-[var(--bg-hover)] rounded-md',
	};

	const sizes = {
		sm: variant === 'icon' ? 'w-7 h-7' : 'px-2.5 py-1 text-xs gap-1.5',
		md: variant === 'icon' ? 'w-8 h-8' : 'px-4 py-2 text-sm gap-2',
		lg: variant === 'icon' ? 'w-10 h-10' : 'px-5 py-2.5 text-sm gap-2',
	};
</script>

<button
	{type}
	class="{base} {variants[variant]} {sizes[size]} {className}"
	disabled={disabled || loading}
	{onclick}
	{...rest}
>
	{#if loading}
		<Loader2 class="w-4 h-4 animate-spin" />
	{/if}
	{@render children()}
</button>
