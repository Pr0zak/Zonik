<script>
	import { ChevronLeft, ChevronRight } from 'lucide-svelte';
	import Button from './Button.svelte';

	let {
		total = 0,
		offset = 0,
		limit = 25,
		limitOptions = [25, 50, 100, 200],
		onchange,
		class: className = '',
	} = $props();
</script>

{#if total > 0}
	<div class="flex flex-wrap justify-center items-center gap-2 sm:gap-3 mt-4 {className}">
		{#if total > limit}
			<Button variant="secondary" size="sm" disabled={offset === 0} onclick={() => onchange?.(Math.max(0, offset - limit), limit)}>
				<ChevronLeft class="w-4 h-4" /> <span class="hidden sm:inline">Prev</span>
			</Button>
			<span class="text-xs sm:text-sm text-[var(--text-muted)] font-mono">
				{offset + 1}-{Math.min(offset + limit, total)} of {total}
			</span>
			<Button variant="secondary" size="sm" disabled={offset + limit >= total} onclick={() => onchange?.(offset + limit, limit)}>
				<span class="hidden sm:inline">Next</span> <ChevronRight class="w-4 h-4" />
			</Button>
		{/if}
		{#if limitOptions.length > 0}
			<select value={limit}
				onchange={(e) => onchange?.(0, parseInt(e.target.value))}
				class="bg-[var(--bg-secondary)] border border-[var(--border-interactive)] rounded-md px-2 py-1 text-xs text-[var(--text-body)] focus:outline-none">
				{#each limitOptions as opt}
					<option value={opt} selected={opt === limit}>{opt} / page</option>
				{/each}
			</select>
		{/if}
	</div>
{/if}
