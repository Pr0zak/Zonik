<script>
	/**
	 * One collapsible run on the Done tab (DC-20 `runs` item):
	 *   "03:00 · Weekly Radar · 64 tracks · 52 m"  [48 added][9 already had][6 not found][1 peer problem]  ›
	 * Clicking toggles it; when open, `children` (the run's rows) render below.
	 *
	 * run      { id, label, kind, card, start, end, counts, job_ids }
	 * open     expanded?
	 * ontoggle (run) => void
	 * now      ms (a run from another day shows its date)
	 */
	import { ChevronRight, ListMusic, CircleArrowUp, Compass, Radio, Sparkles, Download } from 'lucide-svelte';
	import Badge from '../ui/Badge.svelte';
	import { clockTime, shortDate, sourceLabel, formatDurationWords } from '$lib/downloads/stage.js';
	import { parseUTC } from '$lib/utils.js';

	let {
		run,
		open = false,
		ontoggle = null,
		now = Date.now(),
		children = null,
		class: className = '',
	} = $props();

	const n = (v) => (Number.isFinite(Number(v)) ? Number(v) : 0);
	const plural = (k, one, many = `${one}s`) => `${k} ${k === 1 ? one : many}`;

	function iconFor(r) {
		const card = r?.card || '';
		const kind = r?.kind || '';
		if (kind === 'playlist' || card === 'dl:playlist') return { icon: ListMusic, color: 'var(--color-playlists)' };
		if (card === 'dl:upgrade' || card === 'dl:upgrade_scan') return { icon: CircleArrowUp, color: 'var(--color-upgrades)' };
		if (['dl:weekly-radar', 'dl:radar', 'dl:new-releases'].includes(card)) return { icon: Radio, color: 'var(--color-live)' };
		if (kind === 'recommendation' || card === 'dl:recommendation') return { icon: Sparkles, color: 'var(--color-discover)' };
		if (['dl:similar', 'dl:discovery', 'dl:remix'].includes(card) || kind === 'scheduled') return { icon: Compass, color: 'var(--color-discover)' };
		return { icon: Download, color: 'var(--color-downloads)' };
	}

	let ic = $derived(iconFor(run));
	let Icon = $derived(ic.icon);
	let c = $derived(run?.counts || {});
	let label = $derived(run?.label || sourceLabel(run?.card));
	let time = $derived.by(() => {
		const d = parseUTC(run?.start);
		if (!d || Number.isNaN(d.getTime())) return '';
		const today = new Date(now);
		const same = d.getFullYear() === today.getFullYear() && d.getMonth() === today.getMonth() && d.getDate() === today.getDate();
		return same ? clockTime(run.start) : `${shortDate(run.start)} ${clockTime(run.start)}`;
	});
	let tracks = $derived(n(c.total) || (Array.isArray(run?.job_ids) ? run.job_ids.length : 0));
	let duration = $derived.by(() => {
		if (n(c.live) > 0) return 'running';
		const s = parseUTC(run?.start);
		const e = parseUTC(run?.end);
		if (!s || !e || Number.isNaN(s.getTime()) || Number.isNaN(e.getTime())) return '';
		const secs = Math.max(0, (e.getTime() - s.getTime()) / 1000);
		if (secs < 60) return '';
		// "52 m", "1 h 13 m": minutes are enough for a run
		const words = formatDurationWords(secs);
		return secs < 3600 ? `${Math.round(secs / 60)} m` : words;
	});
	let meta = $derived([plural(tracks, 'track'), duration].filter(Boolean).join(' · '));
	let chips = $derived(
		[
			[n(c.new), (k) => `${k} added`, 'success'],
			[n(c.replaced), (k) => `${k} replaced`, 'info'],
			[n(c.live), (k) => `${k} live`, 'info'],
			[n(c.pending), (k) => `${k} waiting`, 'default'],
			[n(c.already_had), (k) => `${k} already had`, 'default'],
			[n(c.not_found), (k) => `${k} not found`, 'default'],
			[n(c.no_better), (k) => `${k} no better source`, 'default'],
			[n(c.rejected), (k) => `${k} rejected`, 'default'],
			[n(c.peer), (k) => plural(k, 'peer problem'), 'error'],
			[n(c.infra), (k) => `${k} not the track's fault`, 'default'],
		].filter(([k]) => k > 0).map(([k, text, variant]) => ({ text: text(k), variant }))
	);
</script>

<div class={className}>
	<button type="button" aria-expanded={open} onclick={() => ontoggle?.(run)}
		class="w-full flex items-center flex-wrap gap-x-2.5 gap-y-1.5 rounded-lg bg-[var(--surface-container-high)] hover:bg-[var(--surface-container-highest)] transition-colors px-3 py-2 text-xs leading-4 text-left">
		<Icon class="w-3.5 h-3.5 flex-shrink-0" style="color: {ic.color}" />
		{#if time}<span class="font-mono text-[11px] text-[var(--text-muted)] flex-shrink-0">{time}</span>{/if}
		<b class="font-semibold text-[var(--text-primary)] min-w-0 truncate max-md:whitespace-normal">{label}</b>
		<span class="flex-1 min-w-[6rem] text-[var(--text-muted)] truncate">{meta}</span>
		<span class="flex flex-wrap gap-1.5 min-w-0">
			{#each chips as ch (ch.text)}<Badge variant={ch.variant}>{ch.text}</Badge>{/each}
		</span>
		<span class="w-7 h-7 flex items-center justify-center flex-shrink-0 text-[var(--text-muted)]">
			<ChevronRight class="w-3.5 h-3.5 transition-transform {open ? 'rotate-90' : ''}" />
		</span>
	</button>
	{#if open && children}
		<div class="mt-1 mb-2">{@render children()}</div>
	{/if}
</div>
