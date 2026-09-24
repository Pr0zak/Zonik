<script>
	/**
	 * The one headline-number tile used across pages (Dashboard, Stats, Upgrades,
	 * Duplicates, …): colour dot + label, the number, an optional one-line detail.
	 *
	 * tone: 'default' | 'good' | 'warn' | 'bad' — only warn/bad change the border and number,
	 *       so a tile that needs attention stands out from the rest.
	 * href / onclick: make the whole tile a link or button (e.g. to the filtered list).
	 * active: highlight the tile when it's the current filter.
	 */
	let {
		label = '',
		value = '',
		color = 'var(--text-muted)',
		icon = null,
		detail = '',
		tone = 'default',
		href = null,
		onclick = null,
		active = false,
		title = '',
		class: className = '',
	} = $props();

	let Icon = $derived(icon);
	let tag = $derived(href ? 'a' : onclick ? 'button' : 'div');
	const toneBorder = {
		default: 'border-[var(--border-subtle)]',
		good: 'border-[var(--border-subtle)]',
		warn: 'border-amber-500/35',
		bad: 'border-red-500/35',
	};
	const toneValue = {
		default: 'text-[var(--text-primary)]',
		good: 'text-emerald-400',
		warn: 'text-amber-300',
		bad: 'text-red-300',
	};
</script>

<svelte:element
	this={tag}
	{href}
	onclick={onclick}
	type={tag === 'button' ? 'button' : undefined}
	title={title || undefined}
	class="block w-full text-left rounded-xl border bg-[var(--surface-container)] px-4 py-3 transition-colors
		{toneBorder[tone] || toneBorder.default}
		{active ? 'ring-1 ring-[var(--color-primary)]/50 bg-[var(--surface-container-high)]' : ''}
		{href || onclick ? 'hover:bg-[var(--surface-container-high)] cursor-pointer' : ''}
		{className}"
>
	<div class="flex items-center gap-1.5 min-w-0">
		{#if Icon}
			<Icon class="w-3.5 h-3.5 flex-shrink-0" style="color: {color}" />
		{:else}
			<span class="w-2 h-2 rounded-full flex-shrink-0" style="background: {color}"></span>
		{/if}
		<span class="text-[10px] font-mono uppercase tracking-wider text-[var(--text-muted)] truncate">{label}</span>
	</div>
	<p class="mt-1 text-2xl font-bold tabular-nums tracking-tight truncate {toneValue[tone] || toneValue.default}">{value}</p>
	{#if detail}
		<p class="text-xs text-[var(--text-muted)] truncate">{detail}</p>
	{/if}
</svelte:element>
