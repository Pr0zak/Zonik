<script>
	let {
		title = '',
		color = 'var(--color-accent)',
		children,
	} = $props();
</script>

<div class="flex items-center justify-between mb-6">
	<div class="flex items-center gap-3">
		<div class="w-1 h-6 rounded-full" style="background: {color}"></div>
		<h1 class="text-2xl font-bold text-[var(--text-primary)]">{title}</h1>
	</div>
	{#if children}
		<div class="flex items-center gap-2">
			{@render children()}
		</div>
	{/if}
</div>
