<script>
	import { Clock, ChevronDown, ChevronUp } from 'lucide-svelte';
	import Card from './Card.svelte';

	let {
		label = 'Schedule & Automation',
		expanded = $bindable(false),
		children,
	} = $props();
</script>

<button onclick={() => expanded = !expanded}
	class="flex items-center gap-2 mb-3 px-3 py-1.5 rounded-md bg-[var(--surface-base)] hover:bg-[var(--surface-container-high)] transition-colors text-xs text-[var(--text-muted)]">
	<Clock class="w-3.5 h-3.5" />
	<span class="font-mono uppercase tracking-wider">{label}</span>
	{#if expanded}<ChevronUp class="w-3 h-3" />{:else}<ChevronDown class="w-3 h-3" />{/if}
</button>
{#if expanded}
	<Card padding="p-4" class="mb-4">
		{@render children()}
	</Card>
{/if}
