<script module>
	/** Row grid: narrower set from md to 1180 px, the full set above. Pass to GroupedList `grid`. */
	export const DONE_GRID = 'md:grid-cols-[10px_minmax(0,1.3fr)_180px_52px_62px_130px_44px_90px_124px] min-[1181px]:grid-cols-[10px_minmax(0,1.3fr)_196px_52px_62px_150px_44px_100px_124px]';
	export const DONE_COLUMNS = [
		{ label: '' }, { label: 'Track' }, { label: 'Outcome' }, { label: 'Format', align: 'center' }, { label: 'Size', align: 'right' },
		{ label: 'From' }, { label: 'At', align: 'right' }, { label: 'Played' }, { label: '' },
	];
</script>

<script>
	/**
	 * One completed download row: TRACK | OUTCOME badge | FORMAT | SIZE | FROM
	 * (peer + reputation, "2nd peer · X never answered") | AT | PLAYED |
	 * "Open track →" (or "Open existing →") + Remove. Already-had rows are muted.
	 * Below md the cells stack under the title.
	 *
	 * job      completed list item (DC-7: outcome, upgrade, track, …)
	 * now      ms (AT shows a clock for today, a date before)
	 * rep      { successes, failures } for the peer | null
	 * onRemove (job) => void;  onOpen (jobId) => void (row click)
	 */
	import { ArrowRight, X } from 'lucide-svelte';
	import Badge from '../ui/Badge.svelte';
	import Button from '../ui/Button.svelte';
	import FormatBadge from '../ui/FormatBadge.svelte';
	import RepChip from './RepChip.svelte';
	import { formatSize, formatDateTime, parseUTC } from '$lib/utils.js';
	import { doneOutcome, firstTrack, jobResult, sourceLabel, clockTime, shortDate, ordinal, peerErrorClause } from '$lib/downloads/stage.js';

	let {
		job,
		now = Date.now(),
		selected = false,
		rep = null,
		onRemove = null,
		onOpen = null,
	} = $props();

	const KNOWN_EXTENSIONS = new Set(['flac', 'mp3', 'wav', 'alac', 'm4a', 'ogg', 'opus', 'aiff', 'ape']);
	function extOf(name) {
		if (!name || typeof name !== 'string' || !name.includes('.')) return '';
		const ext = name.split('.').pop()?.toLowerCase().trim() || '';
		return KNOWN_EXTENSIONS.has(ext) ? ext : '';
	}
	function baseName(p) {
		return typeof p === 'string' ? p.split(/[/\\]/).pop() : '';
	}
	function parseList(v) {
		if (Array.isArray(v)) return v;
		if (typeof v === 'string') { try { const x = JSON.parse(v); return Array.isArray(x) ? x : []; } catch { return []; } }
		return [];
	}
	function sameDay(a, b) {
		return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
	}
	/** "HH:MM" today, "Oct 17" before. */
	function whenShort(iso) {
		const d = parseUTC(iso);
		if (!d || Number.isNaN(d.getTime())) return '';
		return sameDay(d, new Date(now)) ? clockTime(iso) : shortDate(iso);
	}

	let t0 = $derived(firstTrack(job));
	let result = $derived(jobResult(job) || {});
	let outcome = $derived(doneOutcome(job));
	let muted = $derived(outcome?.kind === 'already_had');
	let title = $derived.by(() => {
		if (t0.artist && t0.track) return `${t0.artist} — ${t0.track}`;
		const d = (job?.description || '').replace(/^Queued( for slot)?:\s*/i, '').replace(/\s*\(attempt\s+\d+.*?\)/i, '');
		const parts = d.split(' — ').filter(Boolean);
		if (parts.length >= 2) return `${parts[0]} — ${parts[1]}`;
		return d.trim() || 'Unknown track';
	});
	let fname = $derived(baseName(t0.filename) || baseName(result.filename) || '');
	let fmt = $derived(job?.track?.format || extOf(fname));
	let size = $derived(Number(job?.track?.file_size) || Number(t0.file_size) || Number(result.file_size) || 0);
	let peer = $derived(t0.username || result.username || '');
	let attempt = $derived(Number(job?.attempt ?? t0.attempt ?? result.attempt) || 0);
	let errors = $derived.by(() => {
		const fromJob = parseList(job?.source_errors);
		if (fromJob.length) return fromJob;
		const fromResult = parseList(result.source_errors);
		return fromResult.length ? fromResult : parseList(t0.source_errors);
	});
	// "2nd peer · NuagistTurtleize never answered in 120 s" when an earlier peer failed.
	let fromNote = $derived.by(() => {
		if (attempt <= 1 && !errors.length) return '';
		const clauses = errors.filter((e) => e && e.user !== peer).map((e) => peerErrorClause(e.user, e.error));
		const head = attempt > 1 ? `${ordinal(attempt)} peer` : '';
		return [head, ...clauses].filter(Boolean).join(' · ');
	});
	let timeIso = $derived(job?.finished_at || job?.started_at || null);
	let trackId = $derived(job?.track_id || job?.track?.id || result.track_id || null);
	let played = $derived.by(() => {
		if (muted) return '—';
		const tr = job?.track;
		if (!tr) return '—';
		const n = Number(tr.play_count) || 0;
		if (!n) return 'not yet';
		const last = parseUTC(tr.last_played_at);
		const fin = parseUTC(job?.finished_at);
		if (last && fin && last < fin) return `${n}× before`;
		return tr.last_played_at ? `${n}× · last ${whenShort(tr.last_played_at)}` : `${n}×`;
	});
	let libraryHref = $derived(
		trackId
			? `/library?track=${encodeURIComponent(trackId)}`
			: t0.artist && t0.track ? `/library?search=${encodeURIComponent(`${t0.artist} ${t0.track}`)}` : null
	);

	function open() {
		if (job?.id) onOpen?.(job.id);
	}
	function onKey(e) {
		if ((e.key === 'Enter' || e.key === ' ') && e.target === e.currentTarget) {
			e.preventDefault();
			open();
		}
	}
</script>

<!-- role/tabindex are set only when the row opens the drawer -->
<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
<div
	class="grid {DONE_GRID} max-md:grid-cols-[10px_minmax(0,1fr)_28px] items-center max-md:items-start gap-x-2.5 gap-y-1 px-3 py-1.5 max-md:px-2 max-md:py-2.5 text-xs leading-4 rounded-lg transition-colors
		{onOpen ? 'cursor-pointer' : ''} {selected ? 'bg-[var(--surface-container-high)]' : 'hover:bg-[var(--surface-container-high)]'}"
	role={onOpen ? 'button' : undefined}
	tabindex={onOpen ? 0 : undefined}
	aria-current={selected ? 'true' : undefined}
	onclick={onOpen ? open : undefined}
	onkeydown={onOpen ? onKey : undefined}
>
	<span class="w-2 h-2 rounded-full {muted ? 'bg-[var(--text-disabled)]' : 'bg-emerald-400'} max-md:row-span-2 max-md:self-start max-md:mt-[3px]" title={outcome?.label || 'Completed'}></span>

	<div class="min-w-0 flex items-center gap-2 max-md:col-start-2 max-md:row-start-1 max-md:flex-wrap max-md:gap-y-1">
		<span class="font-medium truncate min-w-0 max-md:whitespace-normal {selected ? 'text-sky-400' : muted ? 'text-[var(--text-muted)]' : 'text-[var(--text-primary)]'}" title={title}>{title}</span>
		<span class="px-1.5 py-0.5 rounded bg-[var(--surface-container-high)] text-[var(--text-muted)] text-[10px] font-medium flex-shrink-0 whitespace-nowrap">{sourceLabel(job?.card)}</span>
	</div>

	<!-- Metadata cells: grid columns from md up, a wrapped block under the title below md -->
	<div class="md:contents max-md:col-start-2 max-md:row-start-2 max-md:flex max-md:flex-wrap max-md:items-center max-md:gap-x-2.5 max-md:gap-y-1 min-w-0">
		<span class="min-w-0 truncate max-md:basis-full" title={outcome?.label || ''}>
			{#if outcome}<Badge variant={outcome.badgeVariant}>{outcome.label}</Badge>{/if}
		</span>
		<span class="md:text-center">{#if fmt}<FormatBadge format={fmt} class="!text-[10px] !py-0" />{/if}</span>
		<span class="font-mono text-[11px] text-[var(--text-muted)] md:text-right whitespace-nowrap truncate">{size > 0 ? formatSize(size) : '—'}</span>
		<span class="min-w-0 flex flex-col text-[11px] text-[var(--text-muted)] max-md:basis-full">
			<span class="flex items-center gap-1.5 min-w-0 whitespace-nowrap overflow-hidden">
				<span class="truncate">{peer || '—'}</span>
				{#if peer && rep}<RepChip successes={rep.successes} failures={rep.failures} />{/if}
			</span>
			{#if fromNote}<small class="text-[10px] leading-3 text-[var(--text-disabled)] whitespace-normal line-clamp-2" title={fromNote}>{fromNote}</small>{/if}
		</span>
		<span class="font-mono text-[11px] text-[var(--text-muted)] md:text-right whitespace-nowrap" title={timeIso ? formatDateTime(timeIso) : ''}>{timeIso ? whenShort(timeIso) : '—'}</span>
		<span class="text-[11px] text-[var(--text-secondary)] truncate">{played}</span>
	</div>

	<div class="flex items-center justify-end gap-1 min-w-0 max-md:col-start-3 max-md:row-start-1 max-md:row-span-2 max-md:flex-col max-md:items-end max-md:-mt-1.5">
		{#if libraryHref}
			<a href={libraryHref} onclick={(e) => e.stopPropagation()} title={trackId ? '' : 'Search the library'}
				class="text-[11px] font-medium text-sky-400 hover:text-sky-300 transition-colors inline-flex items-center gap-1 whitespace-nowrap max-md:hidden">
				{trackId ? (muted ? 'Open existing' : 'Open track') : 'In library'}<ArrowRight class="w-3 h-3" />
			</a>
			<a href={libraryHref} onclick={(e) => e.stopPropagation()} aria-label={muted ? 'Open existing' : 'Open track'}
				class="md:hidden w-7 h-7 rounded-md inline-flex items-center justify-center text-sky-400 hover:bg-[var(--surface-container-high)]">
				<ArrowRight class="w-3.5 h-3.5" />
			</a>
		{/if}
		{#if onRemove}
			<Button variant="icon" size="sm" class="hover:!text-rose-400 flex-shrink-0" title="Remove: deletes the row on the server" aria-label="Remove"
				onclick={(e) => { e.stopPropagation(); onRemove(job); }}>
				<X class="w-3.5 h-3.5" />
			</Button>
		{/if}
	</div>
</div>
