<script>
	let {
		variant = null,
		count = 1,
		class: className = 'h-4 w-full',
	} = $props();
</script>

{#if variant === 'table-row'}
	{#each Array(count) as _}
		<div class="px-4 py-3 flex items-center gap-4 animate-pulse">
			<div class="h-4 w-24 bg-[var(--surface-container)] rounded"></div>
			<div class="h-5 w-16 bg-[var(--surface-container)] rounded-full"></div>
			<div class="h-4 w-12 bg-[var(--surface-container)] rounded"></div>
			<div class="h-4 w-32 bg-[var(--surface-container)] rounded hidden md:block"></div>
			<div class="h-3 w-20 bg-[var(--surface-container)] rounded ml-auto"></div>
		</div>
	{/each}
{:else if variant === 'list-item'}
	{#each Array(count) as _}
		<div class="px-4 py-3 flex items-center gap-3 animate-pulse">
			<div class="w-10 h-10 bg-[var(--surface-container)] rounded flex-shrink-0"></div>
			<div class="flex-1 space-y-1.5">
				<div class="h-3 w-3/4 bg-[var(--surface-container)] rounded"></div>
				<div class="h-2.5 w-1/2 bg-[var(--surface-container)] rounded"></div>
			</div>
		</div>
	{/each}
{:else if variant === 'card'}
	{#each Array(count) as _}
		<div class="animate-pulse bg-[var(--surface-container)] rounded-lg h-24"></div>
	{/each}
{:else if variant === 'cover-tile'}
	{#each Array(count) as _}
		<div class="animate-pulse">
			<div class="aspect-square bg-[var(--surface-container)] rounded-lg mb-2"></div>
			<div class="h-3 w-3/4 bg-[var(--surface-container)] rounded mb-1"></div>
			<div class="h-2.5 w-1/2 bg-[var(--surface-container)] rounded"></div>
		</div>
	{/each}
{:else}
	<div class="animate-pulse bg-[var(--surface-container)] rounded {className}"></div>
{/if}
