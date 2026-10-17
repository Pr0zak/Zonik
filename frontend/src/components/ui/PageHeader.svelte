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
	<div class="flex items-center gap-3.5 min-w-0">
		{#if Icon}
			<div class="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0"
				style="background: color-mix(in srgb, {color} 14%, transparent); box-shadow: inset 0 0 0 1px color-mix(in srgb, {color} 28%, transparent), 0 4px 14px -4px color-mix(in srgb, {color} 25%, transparent);">
				<Icon class="w-5 h-5" style="color: {color}" />
			</div>
		{:else}
			<div class="w-1.5 h-7 rounded-full flex-shrink-0" style="background: {color}; box-shadow: 0 0 10px {color};"></div>
		{/if}
		<div class="min-w-0">
			<h1 class="text-xl md:text-2xl font-bold text-[var(--text-primary)] tracking-editorial truncate leading-tight">{title}</h1>
			{#if subtitle}
				<p class="text-xs text-[var(--text-muted)] truncate mt-0.5">{subtitle}</p>
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
