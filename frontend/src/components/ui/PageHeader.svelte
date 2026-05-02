<script>
	let {
		title = '',
		subtitle = '',
		icon = null,
		color = 'var(--color-accent)',
		actions,
		children,
	} = $props();

	let Icon = $derived(icon);
</script>

<div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-6">
	<div class="flex items-center gap-3 min-w-0">
		<div class="w-1 h-6 rounded-full flex-shrink-0" style="background: {color}; box-shadow: 0 0 8px {color};"></div>
		{#if Icon}
			<Icon class="w-5 h-5 flex-shrink-0" style="color: {color}" />
		{/if}
		<div class="min-w-0">
			<h1 class="text-xl md:text-2xl font-bold text-[var(--text-primary)] tracking-editorial truncate">{title}</h1>
			{#if subtitle}
				<p class="text-xs text-[var(--text-muted)] truncate">{subtitle}</p>
			{/if}
		</div>
	</div>
	{#if actions || children}
		<div class="flex items-center gap-2 flex-wrap flex-shrink-0">
			{#if actions}
				{@render actions()}
			{:else if children}
				{@render children()}
			{/if}
		</div>
	{/if}
</div>
