<script>
	/**
	 * One live download row (two lines, 44 px pitch):
	 *   line 1  dot · title · source chip · format · "size · peer" · reputation chip
	 *   line 2  stage word in its colour · detail sentence   [+ 4 px byte bar while transferring]
	 *   right   mono cell: big = the number that matters, small = context (amber at 75 % of a limit)
	 *   action  28 px cancel
	 * Below md the right cell becomes a third line and the title wraps.
	 *
	 * Everything the row says comes from stage.js `resolveStage` (DC-18).
	 *
	 * job        list item / WS-merged job (DC-1, DC-7)
	 * transfer   matching transfer_progress entry (DC-4) | null
	 * limits     DC-12 limits; pacer DC-12 pacer; medianSpeed bytes/s
	 * now        the page's 1 s tick (ms)
	 * rep        { successes, failures } for the peer | null
	 * cancelling true between the cancel click and the next job_update
	 * onCancel   (job) => void;  onOpen (jobId) => void (row click)
	 * backlog    renders the "Not yet submitted" placeholder row instead of a job
	 *            (expands to the next titles). Takes the backlog row groups.js emits
	 *            ({backlog: true, title, card, pending, next_titles}) or
	 *            { title, card, count, titles[] }; a groups.js backlog row passed as
	 *            `job` works too, so the page can render every Live row the same way.
	 */
	import { X, ChevronDown } from 'lucide-svelte';
	import Button from '../ui/Button.svelte';
	import FormatBadge from '../ui/FormatBadge.svelte';
	import RepChip from './RepChip.svelte';
	import { formatSize, parseUTC } from '$lib/utils.js';
	import { resolveStage, firstTrack, jobResult, sourceLabel, formatDurationWords } from '$lib/downloads/stage.js';

	let {
		job = null,
		transfer = null,
		limits = null,
		pacer = null,
		medianSpeed = 0,
		now = Date.now(),
		selected = false,
		cancelling = false,
		rep = null,
		onCancel = null,
		onOpen = null,
		backlog = null,
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

	const COLOUR_TEXT = {
		sky: 'text-sky-400', amber: 'text-amber-400', indigo: 'text-indigo-400',
		muted: 'text-[var(--text-secondary)]', emerald: 'text-emerald-400', rose: 'text-rose-400',
	};
	const COLOUR_DOT = {
		sky: 'bg-sky-400', amber: 'bg-amber-400', indigo: 'bg-indigo-400',
		muted: 'bg-[var(--text-disabled)]', emerald: 'bg-emerald-400', rose: 'bg-rose-400',
	};
	// Big line of the right cell: stage colour for the moving/searching stages, primary for waits.
	const BIG_TEXT = {
		sky: 'text-sky-400', indigo: 'text-indigo-400', muted: 'text-[var(--text-secondary)]',
		amber: 'text-[var(--text-primary)]', emerald: 'text-emerald-400', rose: 'text-rose-400',
	};

	let bl = $derived.by(() => {
		const b = backlog ?? (job?.backlog ? job : null);
		if (!b) return null;
		return {
			title: b.title,
			card: b.card,
			count: Number(b.count ?? b.pending) || 0,
			titles: Array.isArray(b.titles) ? b.titles : Array.isArray(b.next_titles) ? b.next_titles : [],
		};
	});
	let t0 = $derived(bl ? {} : firstTrack(job));
	let result = $derived(bl ? null : jobResult(job));
	let st = $derived(job && !bl ? resolveStage(job, transfer, limits, now, { pacer, medianSpeed }) : null);

	let title = $derived.by(() => {
		if (t0.artist && t0.track) return `${t0.artist} — ${t0.track}`;
		const d = (job?.description || '').replace(/^Queued( for slot)?:\s*/i, '').replace(/\s*\(attempt\s+\d+.*?\)/i, '');
		const parts = d.split(' — ').filter(Boolean);
		if (parts.length >= 2) return `${parts[0]} — ${parts[1]}`;
		return d.trim() || 'Unknown track';
	});
	let fname = $derived(baseName(t0.filename) || baseName(result?.filename) || baseName(transfer?.filename) || '');
	let ext = $derived(extOf(fname));
	let size = $derived(Number(t0.file_size) || Number(transfer?.total_bytes) || Number(result?.file_size) || 0);
	let peer = $derived(transfer?.username || t0.username || result?.username || '');
	let active = $derived(!!st && ['transferring', 'searching', 'importing'].includes(st.stage));
	let word = $derived(cancelling ? 'Cancelling…' : st?.word || '');
	let wordColour = $derived(cancelling ? 'muted' : st?.colour || 'muted');
	let bigClass = $derived(st?.amber ? 'text-amber-400' : BIG_TEXT[st?.colour] || BIG_TEXT.amber);

	let ageHint = $derived.by(() => {
		const started = parseUTC(job?.started_at);
		const bits = [];
		if (st?.elapsedS != null) bits.push(`${formatDurationWords(st.elapsedS)} in this stage`);
		if (started && !Number.isNaN(started.getTime())) bits.push(`created ${formatDurationWords((now - started.getTime()) / 1000)} ago`);
		return bits.join(' · ');
	});

	let showTitles = $state(false);

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

{#snippet chip(card)}
	<span class="px-1.5 py-0.5 rounded bg-[var(--surface-container-high)] text-[var(--text-muted)] text-[10px] font-medium flex-shrink-0 whitespace-nowrap">{sourceLabel(card)}</span>
{/snippet}

{#if bl}
	{@const titles = bl.titles}
	<div class="grid grid-cols-[10px_minmax(0,1fr)_224px_28px] max-md:grid-cols-[10px_minmax(0,1fr)_28px] items-center gap-x-2.5 gap-y-1 px-3 py-1.5 max-md:px-2 max-md:py-2.5 text-xs leading-4">
		<span class="w-2 h-2 rounded-full bg-[var(--text-disabled)] max-md:self-start max-md:mt-[3px]"></span>
		<div class="min-w-0">
			<div class="flex items-center gap-2 min-w-0 max-md:flex-wrap max-md:gap-y-1">
				<span class="font-medium text-[var(--text-primary)] truncate max-md:whitespace-normal max-md:basis-full">{bl.title ? `${bl.title} · ` : ''}{bl.count} more {bl.count === 1 ? 'track' : 'tracks'}</span>
				{@render chip(bl.card)}
			</div>
			<p class="text-[11px] text-[var(--text-muted)] truncate max-md:whitespace-normal">
				<span class="font-medium text-[var(--text-secondary)]">Not yet submitted</span>{#if titles.length}{` · next: ${titles.slice(0, 3).join(', ')}${titles.length > 3 || bl.count > 3 ? ', …' : ''}`}{/if}
			</p>
			{#if showTitles && titles.length}
				<ol class="mt-1 space-y-0.5 text-[11px] text-[var(--text-secondary)] list-decimal list-inside">
					{#each titles as tt, i (i)}<li class="truncate">{tt}</li>{/each}
				</ol>
			{/if}
		</div>
		<div class="min-w-0 text-right font-mono text-[11px] leading-4 text-[var(--text-muted)] max-md:col-start-2 max-md:row-start-2 max-md:text-left max-md:flex max-md:gap-x-2.5 max-md:items-baseline">
			<b class="block max-md:inline text-xs font-semibold text-[var(--text-secondary)]">later</b>
			<small class="block max-md:inline text-[11px]">in order</small>
		</div>
		<div class="flex justify-end max-md:col-start-3 max-md:row-start-1">
			{#if titles.length}
				<Button variant="icon" size="sm" title={showTitles ? 'Hide the next titles' : 'Show the next titles'} aria-label="Show the next titles"
					aria-expanded={showTitles} onclick={() => (showTitles = !showTitles)}>
					<ChevronDown class="w-3.5 h-3.5 transition-transform {showTitles ? 'rotate-180' : ''}" />
				</Button>
			{/if}
		</div>
	</div>
{:else if job && st}
	<!-- role/tabindex are set only when the row opens the drawer -->
	<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
	<div
		class="grid grid-cols-[10px_minmax(0,1fr)_224px_28px] max-md:grid-cols-[10px_minmax(0,1fr)_28px] items-center gap-x-2.5 gap-y-1 px-3 py-1.5 max-md:px-2 max-md:py-2.5 text-xs leading-4 rounded-lg transition-colors
			{onOpen ? 'cursor-pointer' : ''} {selected ? 'bg-[var(--surface-container-high)]' : 'hover:bg-[var(--surface-container-high)]'}"
		role={onOpen ? 'button' : undefined}
		tabindex={onOpen ? 0 : undefined}
		aria-current={selected ? 'true' : undefined}
		onclick={onOpen ? open : undefined}
		onkeydown={onOpen ? onKey : undefined}
	>
		<span class="w-2 h-2 rounded-full {COLOUR_DOT[wordColour] || COLOUR_DOT.muted} {active && !cancelling ? 'animate-pulse' : ''} max-md:self-start max-md:mt-[3px]" title={word}></span>

		<div class="min-w-0 max-md:col-start-2 max-md:row-start-1">
			<div class="flex items-center gap-2 min-w-0 overflow-hidden max-md:flex-wrap max-md:gap-y-1">
				<span class="font-medium truncate min-w-[min(320px,100%)] max-md:min-w-0 max-md:whitespace-normal max-md:basis-full {selected ? 'text-sky-400' : 'text-[var(--text-primary)]'}" title={title}>{title}</span>
				{@render chip(job.card)}
				{#if ext}<FormatBadge format={ext} class="!text-[10px] !py-0 flex-shrink-0" />{/if}
				{#if size > 0 || peer}
					<span class="font-mono text-[11px] text-[var(--text-muted)] whitespace-nowrap flex-shrink-0">
						{#if size > 0}{formatSize(size)}{/if}{#if size > 0 && peer}{' · '}{/if}{#if peer}<span title="from {peer}">{peer}</span>{/if}
					</span>
				{/if}
				{#if peer && rep}<RepChip successes={rep.successes} failures={rep.failures} />{/if}
			</div>
			<p class="text-[11px] text-[var(--text-muted)] truncate max-md:whitespace-normal">
				<span class="font-medium {COLOUR_TEXT[wordColour] || COLOUR_TEXT.muted}">{word}</span>{#if st.detail}{` · ${st.detail}`}{/if}
			</p>
			{#if st.stage === 'transferring' && st.progress != null}
				<div class="mt-1 h-1 rounded-full overflow-hidden bg-[var(--border-interactive)]">
					<div class="h-full rounded-full bg-[var(--color-downloads)] transition-all duration-300" style="width: {st.progress}%"></div>
				</div>
			{/if}
		</div>

		<div class="min-w-0 text-right font-mono text-[11px] leading-4 text-[var(--text-muted)] whitespace-nowrap max-md:col-start-2 max-md:row-start-2 max-md:text-left max-md:flex max-md:flex-wrap max-md:gap-x-2.5 max-md:items-baseline"
			title={ageHint}>
			<b class="block max-md:inline text-xs font-semibold truncate max-md:whitespace-normal {bigClass}">{st.big}</b>
			{#if st.small}<small class="block max-md:inline text-[11px] truncate">{st.small}</small>{/if}
		</div>

		<div class="flex justify-end max-md:col-start-3 max-md:row-start-1">
			{#if onCancel}
				<Button variant="icon" size="sm" class="hover:!text-rose-400" title="Cancel" aria-label="Cancel" disabled={cancelling}
					onclick={(e) => { e.stopPropagation(); onCancel(job); }}>
					<X class="w-3.5 h-3.5" />
				</Button>
			{/if}
		</div>
	</div>
{/if}
