<script>
	let {
		label = '',
		value = '',
		color = 'var(--text-primary)',
		icon = null,
		class: className = '',
	} = $props();

	let Icon = $derived(icon);
</script>

<div class="bg-[var(--surface-base)] rounded-lg px-3 py-2 text-center {className}">
	{#if Icon}
		<div class="flex items-center justify-center mb-1">
			<Icon class="w-4 h-4" style="color: {color}" />
		</div>
	{/if}
	<p class="text-lg font-bold" style="color: {color}">{value}</p>
	<p class="text-xs text-[var(--text-muted)] uppercase tracking-wider">{label}</p>
</div>
