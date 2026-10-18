<script>
	let {
		title = '',
		description = '',
		compact = false,
		icon,
		action,
	} = $props();
</script>

<div class="flex flex-col items-center justify-center {compact ? 'py-6' : 'py-10'} px-4 text-center">
	{#if icon}
		<div class="text-[var(--text-disabled)] {compact ? 'mb-2 p-2.5' : 'mb-3 p-3.5'} rounded-2xl bg-[var(--surface-container-high)]">
			{@render icon()}
		</div>
	{/if}
	{#if title}
		<h3 class="{compact ? 'text-sm' : 'text-base'} font-semibold text-[var(--text-primary)] mb-1">{title}</h3>
	{/if}
	{#if description}
		<p class="text-xs text-[var(--text-muted)] max-w-sm leading-relaxed">{description}</p>
	{/if}
	{#if action}
		<div class="mt-3">
			{@render action()}
		</div>
	{/if}
</div>
