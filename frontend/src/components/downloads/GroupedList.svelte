<script>
	/**
	 * One dense list grouped by stage or class: a mono-caps column header row
	 * (hidden below md, not sortable), then per group a GroupHeader and its rows
	 * with hairline dividers. A group without a `name` renders its rows without a
	 * header (the Done feed is one flat group).
	 *
	 * groups:     [{ key, dot, name, count, reason, rows }] (lib/downloads/groups.js)
	 * columns:    [{ label, align?: 'left' | 'right' | 'center', class? }]
	 * grid:       the rows' grid-template classes, reused by the header row so columns line up
	 * row:        snippet (row, group) -> one row
	 * footer:     optional snippet under the list
	 * empty:      optional snippet shown when no group has rows
	 * groupLimit: rows shown per group before "Show N more" (0 = all)
	 * rowKey:     (row) -> key (default row.id ?? row.key)
	 * groupAction: optional snippet (group) for the right side of each group header
	 */
	import GroupHeader from './GroupHeader.svelte';

	let {
		groups = [],
		columns = [],
		grid = '',
		row,
		footer = null,
		empty = null,
		groupLimit = 0,
		rowKey = (r) => r?.id ?? r?.key,
		groupAction = null,
		class: className = '',
	} = $props();

	let expanded = $state({});
	let list = $derived((Array.isArray(groups) ? groups : []).filter((g) => g && Array.isArray(g.rows)));
	let total = $derived(list.reduce((n, g) => n + g.rows.length, 0));

	const ALIGN = { right: 'text-right', center: 'text-center', left: '' };

	function shown(g) {
		if (!groupLimit || expanded[g.key]) return g.rows;
		return g.rows.slice(0, groupLimit);
	}
</script>

<div class="min-w-0 {className}">
	{#if total === 0 && empty}
		{@render empty()}
	{:else}
		{#if columns.length}
			<div class="grid {grid} items-center gap-x-2.5 px-3 pt-2 pb-1.5 text-[10px] font-mono uppercase tracking-wider text-[var(--text-muted)] max-md:hidden" aria-hidden="true">
				{#each columns as col, i (i)}
					<span class="truncate {ALIGN[col.align] || ''} {col.class || ''}">{col.label || ''}</span>
				{/each}
			</div>
		{/if}
		{#each list as g (g.key)}
			{#if g.rows.length || g.name}
				{#if g.name}
					{#snippet action()}{@render groupAction?.(g)}{/snippet}
					<GroupHeader dot={g.dot} name={g.name} count={g.count ?? g.rows.length} reason={g.reason}
						action={groupAction ? action : null} />
				{/if}
				<div class="divide-y divide-[var(--border-subtle)]">
					{#each shown(g) as r (rowKey(r))}
						{@render row(r, g)}
					{/each}
				</div>
				{#if groupLimit && g.rows.length > groupLimit}
					<button type="button" class="ml-3 mt-1 text-[11px] text-sky-400 hover:text-sky-300 transition-colors"
						onclick={() => (expanded = { ...expanded, [g.key]: !expanded[g.key] })}>
						{expanded[g.key] ? 'Show fewer' : `Show ${g.rows.length - groupLimit} more`}
					</button>
				{/if}
			{/if}
		{/each}
	{/if}
	{#if footer}
		<div class="flex items-center justify-between gap-3 flex-wrap px-3 pt-3 mt-2 border-t border-[var(--border-subtle)] text-xs text-[var(--text-muted)]">
			{@render footer()}
		</div>
	{/if}
</div>
