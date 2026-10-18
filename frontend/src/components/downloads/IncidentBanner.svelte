<script>
	/**
	 * Infra incident banner (DC-17): one amber tonal line for the first
	 * un-dismissed incident (restart, outage, …) with Retry all / Dismiss, and
	 * "+ n more" when there are others. Renders nothing when every incident is
	 * dismissed.
	 *
	 * incidents: GET /api/jobs/incidents `items`
	 * onRetry:   (incident) => void   (not offered for kind 'cancel')
	 * onDismiss: (incident) => void
	 * busy:      true, or the id of the incident an action is running for
	 * now:       ms, for "yesterday" wording
	 */
	import { TriangleAlert, RotateCcw } from 'lucide-svelte';
	import Button from '../ui/Button.svelte';
	import { clockTime, shortDate, sourceLabel } from '$lib/downloads/stage.js';
	import { parseUTC } from '$lib/utils.js';

	let {
		incidents = [],
		onRetry = null,
		onDismiss = null,
		busy = false,
		now = Date.now(),
		class: className = '',
	} = $props();

	let open = $derived((Array.isArray(incidents) ? incidents : []).filter((i) => i && !i.dismissed));
	let incident = $derived(open[0] || null);
	let more = $derived(Math.max(0, open.length - 1));
	let isBusy = $derived(busy === true || (!!incident && busy === incident.id));

	function dayKey(d) {
		return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
	}

	/** "21:43" today, "21:43 yesterday", "Oct 15 21:43" before. */
	function when(iso) {
		const d = parseUTC(iso);
		if (!d || Number.isNaN(d.getTime())) return '';
		const today = new Date(now);
		const yesterday = new Date(now - 86400000);
		if (dayKey(d) === dayKey(today)) return clockTime(iso);
		if (dayKey(d) === dayKey(yesterday)) return `${clockTime(iso)} yesterday`;
		return `${shortDate(iso)} ${clockTime(iso)}`;
	}

	/** "06:10–06:14" (same day) or the two full `when`s. */
	function span(startIso, endIso) {
		const a = when(startIso);
		if (!endIso) return a;
		const s = parseUTC(startIso);
		const e = parseUTC(endIso);
		if (s && e && dayKey(s) === dayKey(e)) {
			const tail = a.endsWith(' yesterday') ? ' yesterday' : '';
			const head = a.replace(/ yesterday$/, '');
			return clockTime(startIso) === clockTime(endIso) ? a : `${head}–${clockTime(endIso)}${tail}`;
		}
		return `${a}–${when(endIso)}`;
	}

	/** "playlist " when one source dominates the incident, else "". */
	function sourceWord(byCard) {
		const entries = Object.entries(byCard || {}).filter(([, c]) => Number(c) > 0);
		if (entries.length !== 1) return '';
		return `${sourceLabel(entries[0][0]).toLowerCase()} `;
	}

	function downloads(count) {
		return Number(count) === 1 ? 'download' : 'downloads';
	}

	const NOT_COUNTED = 'Nothing was counted against the tracks and they are kept out of the failure numbers below.';

	let copy = $derived.by(() => {
		if (!incident) return null;
		const count = Number(incident.count) || 0;
		const src = sourceWord(incident.by_card);
		const at = when(incident.start);
		const range = span(incident.start, incident.end);
		switch (incident.kind) {
			case 'restart':
				return { head: `Restart at ${at} interrupted ${count} ${src}${downloads(count)}.`, tail: NOT_COUNTED };
			case 'outage':
				return { head: `Soulseek was disconnected ${range}`, sep: '; ', tail: `${count} ${src}${downloads(count)} failed while waiting. ${NOT_COUNTED}` };
			case 'cancel':
				return { head: `You cancelled ${count} ${src}${downloads(count)} at ${range}.`, tail: 'They are kept out of the failure numbers below.' };
			case 'internal':
				return { head: `Zonik hit an internal error at ${range}`, sep: '; ', tail: `${count} ${src}${downloads(count)} failed. ${NOT_COUNTED}` };
			case 'unreachable':
				return { head: `The download service was unreachable at ${range}`, sep: '; ', tail: `${count} ${src}${downloads(count)} failed. ${NOT_COUNTED}` };
			case 'orphan':
			default:
				return { head: `${count} ${src}${downloads(count)} stopped with no reason recorded (${range}).`, tail: 'They are kept out of the failure numbers below.' };
		}
	});
</script>

{#if incident && copy}
	<div class="rounded-xl bg-amber-500/[0.08] px-4 py-3 flex items-center gap-3 text-xs flex-wrap {className}" role="status">
		<TriangleAlert class="w-4 h-4 text-amber-400 flex-shrink-0" />
		<p class="flex-1 min-w-0 text-[var(--text-secondary)] leading-relaxed">
			<b class="font-semibold text-[var(--text-primary)]">{copy.head}</b>{copy.sep ?? ' '}{copy.tail}
			{#if more > 0}<span class="text-[var(--text-muted)] whitespace-nowrap">+ {more} more</span>{/if}
		</p>
		<div class="flex items-center gap-1.5 flex-shrink-0 max-md:w-full max-md:justify-end">
			{#if incident.kind !== 'cancel' && onRetry}
				<Button variant="secondary" size="sm" loading={isBusy} disabled={isBusy} onclick={() => onRetry(incident)}>
					{#if !isBusy}<RotateCcw class="w-3.5 h-3.5" />{/if}
					Retry all {Number(incident.count) || 0}
				</Button>
			{/if}
			{#if onDismiss}
				<Button variant="ghost" size="sm" disabled={isBusy} onclick={() => onDismiss(incident)}>Dismiss</Button>
			{/if}
		</div>
	</div>
{/if}
