<script>
	/**
	 * SEARCHES block of the job drawer: what each query found and where the files
	 * went (wrong title · length off · under 3 MB · kept). Takes the DC-5 `search`
	 * funnel of a finished job, or the live `tracks[0].search` of a searching job
	 * plus the queries finished so far (`queries`, from the timeline).
	 */
	import { funnelSegments } from '$lib/downloads/timeline.js';

	let {
		search = null,
		queries = null, // [{q, kind, files, peers}] — overrides the funnel's list (live jobs)
	} = $props();

	const SEG_BG = {
		rose: 'bg-rose-400',
		amber: 'bg-amber-400',
		muted: 'bg-[var(--text-disabled)]',
		emerald: 'bg-emerald-400',
	};

	let funnel = $derived(funnelSegments(search));
	// A live search ({query_index, query_total, …}) has no rejection counts yet.
	let live = $derived(search && typeof search === 'object' && search.query_index != null && !Array.isArray(search.queries) ? search : null);
	let rows = $derived.by(() => {
		if (Array.isArray(queries) && queries.length) {
			return queries.map((q) => ({
				q: q.q || '', prefix: q.kind === 'album' ? 'album fallback' : '', suffix: '',
				files: Number(q.files) || 0, error: q.error || null,
			}));
		}
		return funnel?.queries || [];
	});
	let barSegments = $derived((funnel?.segments || []).filter((s) => s.count > 0));
	let showBreakdown = $derived(!live && funnel && funnel.total > 0);
</script>

{#if rows.length || live || showBreakdown}
	<div class="text-[11px] leading-[1.125rem] text-[var(--text-secondary)]">
		{#if live}
			<p class="mb-1">
				Query {live.query_index} of {live.query_total || '?'}{#if live.query}
					&nbsp;<q class="text-[var(--text-body)]">{live.query}</q>{/if}
				· {live.files_seen || 0} files seen, {live.kept || 0} kept so far
			</p>
		{/if}

		{#if rows.length}
			<div class="grid grid-cols-[minmax(0,1fr)_3.5rem] gap-x-3 gap-y-0.5">
				{#each rows as r, i}
					<span class="min-w-0 break-words">
						{#if r.prefix}{r.prefix}&nbsp;{/if}<q class="text-[var(--text-body)]">{r.q}</q>{#if r.suffix}, {r.suffix}{/if}
					</span>
					<span class="font-mono text-right {r.error ? 'text-rose-400' : ''}">
						{#if r.error}failed{:else}{r.files}{i === 0 ? ' files' : ''}{/if}
					</span>
				{/each}
			</div>
		{/if}

		{#if showBreakdown}
			<div class="flex gap-[2px] h-1.5 rounded-full overflow-hidden bg-[var(--surface-lowest)] mt-2.5 mb-1.5" aria-hidden="true">
				{#each barSegments as s (s.key)}
					<i class="block h-full min-w-[3px] {SEG_BG[s.colour]}" style="flex: {s.count} 1 0%"></i>
				{/each}
			</div>
			<div class="flex flex-wrap gap-x-3 gap-y-0.5 text-[var(--text-muted)] mb-2">
				{#each funnel.segments as s (s.key)}
					<span class="inline-flex items-center gap-1">
						<i class="inline-block w-2 h-2 rounded-[2px] {SEG_BG[s.colour]}"></i>{s.label}
					</span>
				{/each}
			</div>
			<div class="grid grid-cols-[minmax(0,1fr)_3.5rem] gap-x-3 gap-y-0.5">
				{#each funnel.segments as s (s.key)}
					<span class={s.key === 'kept' ? 'text-[var(--text-primary)] font-semibold' : ''}>{s.detail}</span>
					<span class="font-mono text-right {s.key === 'kept' ? 'text-[var(--text-primary)] font-semibold' : ''}">{s.count}</span>
				{/each}
			</div>
		{/if}
	</div>
{/if}
