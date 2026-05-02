<script>
	import { ChevronUp, ChevronDown, ChevronsUpDown } from 'lucide-svelte';

	let {
		columns = [],
		rows = [],
		sortKey = null,
		sortDir = null,
		onsort = null,
		onrowclick = null,
		rowKey = (r) => r.id,
		rowClass = null,
		minWidth = '',
		viewport = null,
		row,
		header,
		empty,
		class: className = '',
	} = $props();

	function handleSort(col) {
		if (!col.sortable) return;
		if (!onsort) return;
		const key = col.sortKey || col.key;
		if (sortKey === key) {
			if (sortDir === 'asc') onsort(key, 'desc');
			else if (sortDir === 'desc') onsort(null, null);
			else onsort(key, 'asc');
		} else {
			onsort(key, 'asc');
		}
	}

	function indicatorIcon(col) {
		const key = col.sortKey || col.key;
		if (sortKey !== key) return ChevronsUpDown;
		return sortDir === 'asc' ? ChevronUp : ChevronDown;
	}

	function indicatorActive(col) {
		const key = col.sortKey || col.key;
		return sortKey === key;
	}

	let containerStyle = $derived(viewport ? `max-height: ${viewport}; overflow-y: auto;` : '');
</script>

<div class="overflow-x-auto {className}" style={containerStyle}>
	<table class="w-full text-sm" style={minWidth ? `min-width: ${minWidth};` : ''}>
		<thead>
			<tr class="text-[var(--text-muted)] text-left">
				{#if header}
					{@render header()}
				{:else}
					{#each columns as col}
						{@const Indicator = indicatorIcon(col)}
						{@const active = indicatorActive(col)}
						<th class="px-3 py-2.5 font-medium text-xs uppercase tracking-wider whitespace-nowrap {col.align === 'right' ? 'text-right' : col.align === 'center' ? 'text-center' : ''} {col.headerClass || ''}"
							style={col.width ? `width: ${col.width};` : ''}>
							{#if col.sortable && onsort}
								<button onclick={() => handleSort(col)}
									class="inline-flex items-center gap-1 transition-colors hover:text-[var(--text-primary)] {active ? 'text-[var(--text-primary)]' : ''}">
									<span>{col.label}</span>
									<Indicator class="w-3 h-3 {active ? 'opacity-100' : 'opacity-40'}" />
								</button>
							{:else}
								{col.label}
							{/if}
						</th>
					{/each}
				{/if}
			</tr>
		</thead>
		<tbody>
			{#if rows.length === 0 && empty}
				<tr>
					<td colspan={columns.length || 1} class="px-3 py-8 text-center">
						{@render empty()}
					</td>
				</tr>
			{:else}
				{#each rows as r, i (rowKey(r))}
					{@const cls = rowClass ? rowClass(r) : ''}
					<!-- svelte-ignore a11y_click_events_have_key_events -->
					<!-- svelte-ignore a11y_no_static_element_interactions -->
					<tr class="transition-colors hover:bg-[var(--surface-container-high)] {onrowclick ? 'cursor-pointer' : ''} {cls}"
						onclick={onrowclick ? () => onrowclick(r) : null}>
						{#if row}
							{@render row(r, i)}
						{:else}
							{#each columns as col}
								<td class="px-3 py-2 {col.align === 'right' ? 'text-right' : col.align === 'center' ? 'text-center' : ''} {col.cellClass || ''}">
									{r[col.key]}
								</td>
							{/each}
						{/if}
					</tr>
				{/each}
			{/if}
		</tbody>
	</table>
</div>
