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

	const base = 'inline-flex items-center justify-center font-medium transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)]/40 focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--surface-base)] disabled:opacity-50 disabled:cursor-not-allowed';

	const variants = {
		primary: 'bg-gradient-primary text-[var(--color-on-primary)] hover:opacity-90 rounded-md shadow-glow',
		secondary: 'bg-[var(--surface-container-high)] hover:bg-[var(--surface-container-highest)] text-[var(--text-primary)] ghost-border rounded-md',
		ghost: 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-container-high)] rounded-md',
		danger: 'text-red-400 hover:bg-red-500/10 ghost-border hover:border-red-500/30 rounded-md',
		success: 'bg-emerald-600 hover:bg-emerald-700 text-white rounded-md',
		warning: 'bg-amber-500/10 text-amber-400 hover:bg-amber-500/20 rounded-md',
		default: 'bg-[var(--surface-container-high)] hover:bg-[var(--surface-container-highest)] text-[var(--text-body)] rounded-md',
		icon: 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-container-high)] rounded-md',
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
