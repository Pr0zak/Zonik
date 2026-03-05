<script>
	let {
		title = '',
		description = '',
		icon,
		action,
	} = $props();
</script>

<div class="flex flex-col items-center justify-center py-12 px-4 text-center">
	{#if icon}
		<div class="text-[var(--text-disabled)] mb-4">
			{@render icon()}
		</div>
	{/if}
	{#if title}
		<h3 class="text-lg font-medium text-[var(--text-primary)] mb-1">{title}</h3>
	{/if}
	{#if description}
		<p class="text-sm text-[var(--text-muted)] max-w-sm">{description}</p>
	{/if}
	{#if action}
		<div class="mt-4">
			{@render action()}
		</div>
	{/if}
</div>
