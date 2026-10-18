<script module>
	/** Row grid (desktop); pass to GroupedList `grid` so the header row lines up. */
	export const FAILED_GRID = 'grid-cols-[10px_minmax(0,1.05fr)_minmax(0,1.5fr)_76px_132px_120px]';
	export const FAILED_COLUMNS = [
		{ label: '' }, { label: 'Track' }, { label: 'What happened' }, { label: 'History' }, { label: 'Next' }, { label: '' },
	];
</script>

<script>
	/**
	 * One failed download row: TRACK | WHAT HAPPENED (wraps, never truncated) |
	 * HISTORY (times failed in 30 days) | NEXT (retry schedule) | four 28 px actions
	 * (search by hand · retry now · stop trying · remove).
	 * Below md: title / what happened / "history · next" / actions.
	 *
	 * job        list item or failed-tracks item merged with its last job (DC-7, DC-20)
	 * now        ms (NEXT is relative)
	 * stopped    true once this track was blacklisted from the page (NEXT reads "blacklisted")
	 * onSearch / onRetry / onStopTrying / onRemove: (job) => void (a missing handler hides its button)
	 * onOpen     (jobId) => void, row click
	 *
	 * Stop trying is hidden for manual / phone cards and for rows that were not the
	 * track's fault (cancelled, restart/outage, orphan); search by hand is hidden for
	 * the latter too.
	 */
	import { Search, RotateCcw, Ban, X } from 'lucide-svelte';
	import Button from '../ui/Button.svelte';
	import { failureClass, failureSentence, nextSentence, firstTrack, ordinal, sourceLabel } from '$lib/downloads/stage.js';

	let {
		job,
		now = Date.now(),
		selected = false,
		stopped = false,
		onSearch = null,
		onRetry = null,
		onStopTrying = null,
		onRemove = null,
		onOpen = null,
	} = $props();

	const NOT_TRACKS_FAULT = new Set(['cancelled', 'infra', 'orphan']);
	const NO_STOP_CARDS = new Set(['dl:manual', 'dl']);
	const DOT = {
		not_found: 'bg-[var(--text-disabled)]',
		no_better: 'bg-[var(--text-disabled)]',
		peer: 'bg-rose-400',
		rejected: 'bg-rose-400',
		cancelled: 'bg-amber-400',
		infra: 'bg-amber-400',
		orphan: 'bg-amber-400',
	};
	const TONE = { rose: 'text-rose-400', muted: 'text-[var(--text-muted)]', default: 'text-[var(--text-secondary)]' };

	/**
	 * A failed-tracks item (DC-20: no `status`, the job facts under `last_job`) is
	 * reshaped into the list-item shape stage.js reads; a list item passes through.
	 */
	function asJob(j) {
		if (!j || j.status || !j.last_job) return j;
		const lj = j.last_job || {};
		return {
			...j,
			id: lj.id ?? j.id ?? j.attempt_key,
			status: 'failed',
			failure_class: j.failure_class ?? j.class ?? null,
			finished_at: lj.finished_at ?? null,
			source_errors: lj.source_errors ?? null,
			search: lj.search ?? null,
			result: JSON.stringify({ message: lj.message ?? '', source_errors: lj.source_errors ?? [], search: lj.search ?? null }),
			tracks: JSON.stringify([{ artist: j.artist, track: j.track }]),
		};
	}

	let row = $derived(asJob(job));
	let t0 = $derived(firstTrack(row));
	let cls = $derived(failureClass(row) || row?.class || 'peer');
	let notFault = $derived(NOT_TRACKS_FAULT.has(cls));
	let title = $derived.by(() => {
		if (t0.artist && t0.track) return `${t0.artist} — ${t0.track}`;
		const d = (row?.description || '').replace(/^Queued( for slot)?:\s*/i, '').replace(/\s*\(attempt\s+\d+.*?\)/i, '');
		const parts = d.split(' — ').filter(Boolean);
		if (parts.length >= 2) return `${parts[0]} — ${parts[1]}`;
		return d.trim() || 'Unknown track';
	});
	let sentence = $derived(failureSentence(row) || 'Failed');
	// Not-found sentences read "4 queries, 0 files kept · 42 seen, 42 wrong title": the funnel tail is muted.
	let parts = $derived.by(() => {
		if (cls !== 'not_found') return [sentence, ''];
		const i = sentence.indexOf(' · ');
		return i > 0 ? [sentence.slice(0, i), sentence.slice(i)] : [sentence, ''];
	});
	let history = $derived.by(() => {
		if (notFault) return '—';
		const n = Number(row?.times_failed_30d);
		if (!Number.isFinite(n) || n <= 0) return '—';
		return n === 1 ? '1st try' : `${ordinal(n)} time`;
	});
	let next = $derived(stopped ? { text: 'blacklisted', tone: 'rose' } : nextSentence(row, now));
	let canSearch = $derived(!!onSearch && !notFault);
	let canStop = $derived(!!onStopTrying && !notFault && !NO_STOP_CARDS.has(row?.card || ''));

	function open() {
		if (row?.id) onOpen?.(row.id);
	}
	function onKey(e) {
		if ((e.key === 'Enter' || e.key === ' ') && e.target === e.currentTarget) {
			e.preventDefault();
			open();
		}
	}
	function act(fn) {
		return (e) => { e.stopPropagation(); fn?.(job); };
	}
</script>

<!-- role/tabindex are set only when the row opens the drawer -->
<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
<div
	class="grid {FAILED_GRID} max-md:grid-cols-[10px_minmax(0,1fr)] items-center gap-x-2.5 gap-y-1 px-3 py-1.5 max-md:px-2 max-md:py-2.5 text-xs leading-4 rounded-lg transition-colors
		{onOpen ? 'cursor-pointer' : ''} {selected ? 'bg-[var(--surface-container-high)]' : 'hover:bg-[var(--surface-container-high)]'}"
	role={onOpen ? 'button' : undefined}
	tabindex={onOpen ? 0 : undefined}
	aria-current={selected ? 'true' : undefined}
	onclick={onOpen ? open : undefined}
	onkeydown={onOpen ? onKey : undefined}
>
	<span class="w-2 h-2 rounded-full {DOT[cls] || DOT.peer} max-md:row-span-4 max-md:self-start max-md:mt-[3px]" title={sentence}></span>

	<div class="min-w-0 flex items-center gap-2 max-md:col-start-2 max-md:row-start-1 max-md:flex-wrap max-md:gap-y-1">
		<span class="font-medium truncate min-w-0 max-md:whitespace-normal {selected ? 'text-sky-400' : 'text-[var(--text-primary)]'}" title={title}>{title}</span>
		<span class="px-1.5 py-0.5 rounded bg-[var(--surface-container-high)] text-[var(--text-muted)] text-[10px] font-medium flex-shrink-0 whitespace-nowrap">{sourceLabel(row?.card)}</span>
	</div>

	<p class="min-w-0 whitespace-normal text-[11px] leading-4 text-[var(--text-secondary)] max-md:col-start-2 max-md:row-start-2">
		{parts[0]}{#if parts[1]}<span class="text-[var(--text-muted)]">{parts[1]}</span>{/if}
	</p>

	<!-- HISTORY + NEXT: two columns from md up, one "history · next" line below md -->
	<div class="md:contents max-md:col-start-2 max-md:row-start-3 max-md:flex max-md:flex-wrap max-md:gap-x-1.5 text-[11px]">
		<span class="font-mono text-[var(--text-muted)] whitespace-nowrap truncate">{history}</span>
		<span class="md:hidden text-[var(--text-disabled)]" aria-hidden="true">·</span>
		<span class="min-w-0 truncate max-md:whitespace-normal {TONE[next.tone] || TONE.default}">{next.text}</span>
	</div>

	<div class="flex items-center justify-end gap-0.5 max-md:col-start-2 max-md:row-start-4 max-md:justify-start max-md:-ml-1.5">
		{#if canSearch}
			<Button variant="icon" size="sm" class="hover:!text-sky-400" title="Search the P2P network by hand" aria-label="Search by hand" onclick={act(onSearch)}>
				<Search class="w-3.5 h-3.5" />
			</Button>
		{/if}
		{#if onRetry}
			<Button variant="icon" size="sm" class="hover:!text-emerald-400" title="Retry now (replaces this row)" aria-label="Retry now" onclick={act(onRetry)}>
				<RotateCcw class="w-3.5 h-3.5" />
			</Button>
		{/if}
		{#if canStop}
			<Button variant="icon" size="sm" class="hover:!text-rose-400" title="Stop trying: add to the blacklist" aria-label="Stop trying"
				disabled={stopped} onclick={act(onStopTrying)}>
				<Ban class="w-3.5 h-3.5" />
			</Button>
		{/if}
		{#if onRemove}
			<Button variant="icon" size="sm" class="hover:!text-rose-400" title="Remove: deletes the row on the server" aria-label="Remove" onclick={act(onRemove)}>
				<X class="w-3.5 h-3.5" />
			</Button>
		{/if}
	</div>
</div>
