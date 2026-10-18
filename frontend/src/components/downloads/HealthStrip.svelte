<script>
	/**
	 * Downloads health strip: five tonal tiles that answer "is it connected, is
	 * anything moving, what is queued, what did I get" before a row is read.
	 * Each tile is also a filter (click -> onFilter(key)); the active one gets the ring.
	 *
	 * status:       GET /api/download/status (DC-12: limits, stages, aggregate_speed, pacer, soulseek)
	 * summary:      GET /api/jobs/summary (DC-9: outcomes, failed, last_finished)
	 * backlog:      tracks not yet submitted (batches API) | null when not counted
	 * nextRun:      { at: ISO, label } for the quiet Queue tile | null
	 * scopeLabel:   'today' | '7 days' | '30 days' (the Added tile's label)
	 * activeFilter: 'soulseek' | 'transferring' | 'searching' | 'queue' | 'added' | null
	 * now:          the page's 1 s tick (ms), for the disconnected age
	 */
	import { formatSpeed } from '$lib/utils.js';
	import { clockTime, formatDurationWords } from '$lib/downloads/stage.js';

	let {
		status = null,
		summary = null,
		backlog = null,
		nextRun = null,
		scopeLabel = 'today',
		activeFilter = null,
		onFilter = null,
		now = Date.now(),
		class: className = '',
	} = $props();

	const n = (v) => (Number.isFinite(Number(v)) ? Number(v) : 0);

	/** Short age for the disconnected value: "48 s", "4 m", "1 h 05 m". */
	function age(seconds) {
		const s = Math.max(0, Math.floor(seconds));
		if (s < 60) return `${s} s`;
		if (s < 3600) return `${Math.floor(s / 60)} m`;
		return formatDurationWords(s);
	}

	let limits = $derived(status?.limits || {});
	let stages = $derived(status?.stages || {});
	let pacer = $derived(status?.pacer || {});
	let slsk = $derived(status?.soulseek || null);
	let loaded = $derived(!!status);

	let soulseekTile = $derived.by(() => {
		if (!loaded || !slsk) {
			return { value: '—', tone: 'default', dot: 'var(--text-disabled)', detail: loaded ? 'Soulseek client not running' : '' };
		}
		if (slsk.connected) {
			const bits = [formatDurationWords(n(slsk.uptime_seconds)) || '0 s', `${n(slsk.reconnects)} ${n(slsk.reconnects) === 1 ? 'reconnect' : 'reconnects'}`];
			if (slsk.username) bits.push(slsk.username);
			return { value: 'Connected', tone: 'good', dot: '#34d399', detail: bits.join(' · ') };
		}
		const since = Number(slsk.disconnected_since);
		const wait = n(limits.reconnect_wait_s) || 30;
		const bits = [];
		if (since > 0) bits.push(`for ${age(n(now) / 1000 - since)}`);
		if (slsk.reconnecting) bits.push('reconnecting');
		bits.push(`jobs wait ${wait} s then fail`);
		// The age goes in the detail line: "Disconnected 4 m" does not fit a 2xl value on a 5-column strip.
		return { value: 'Disconnected', tone: 'bad', dot: '#f87171', detail: bits.join(' · ') };
	});

	let transferTile = $derived.by(() => {
		const moving = n(stages.transferring);
		const slots = n(limits.transfer_slots);
		const waiting = n(stages.waiting_slot);
		let detail;
		if (moving > 0) {
			const bits = [formatSpeed(n(status?.aggregate_speed)) || 'starting'];
			if (waiting > 0) bits.push(`${waiting} waiting for a slot`);
			detail = bits.join(' · ');
		} else if (waiting > 0) {
			detail = `${waiting} waiting for a slot`;
		} else {
			const last = clockTime(summary?.last_finished?.finished_at);
			detail = last ? `idle since ${last}` : 'idle';
		}
		return { value: loaded ? (slots ? `${moving} / ${slots}` : `${moving}`) : '—', detail: loaded ? detail : '' };
	});

	let searchTile = $derived.by(() => {
		const searching = n(stages.searching);
		const waiting = n(stages.pacer_waiting) + n(stages.queue_search);
		const sent = n(pacer.sent_last_minute);
		const perMin = n(limits.searches_per_minute);
		let detail;
		if (!searching && !waiting && !sent) detail = 'pacer idle';
		else detail = `${waiting} waiting · pacer ${sent}${perMin ? `/${perMin}` : ''} this minute`;
		return { value: loaded ? `${searching}` : '—', detail: loaded ? detail : '' };
	});

	let queueTile = $derived.by(() => {
		const live = n(stages.live);
		const hasBacklog = backlog != null && Number.isFinite(Number(backlog));
		const back = hasBacklog ? n(backlog) : 0;
		let detail;
		if (live > 0 || back > 0) {
			if (back > 0) detail = `${live} live · ${back} not yet submitted`;
			else if (hasBacklog) detail = `${live} live`;
			else detail = `${live} live · backlog not counted`;
		} else if (nextRun?.at) {
			const at = clockTime(nextRun.at);
			detail = nextRun.label ? `next run ${at} · ${nextRun.label}` : `next run ${at}`;
		} else {
			detail = 'nothing queued';
		}
		return { value: loaded ? `${live + back}` : '—', detail: loaded ? detail : '' };
	});

	let addedTile = $derived.by(() => {
		const o = summary?.outcomes || {};
		return {
			value: summary ? `${n(o.new) + n(o.replaced)}` : '—',
			had: n(o.already_had),
			failed: n(summary?.failed?.total),
		};
	});

	const toneValue = {
		default: 'text-[var(--text-primary)]',
		good: 'text-emerald-400',
		bad: 'text-red-300',
	};
	const toneBorder = {
		default: 'border-[var(--border-subtle)]',
		good: 'border-[var(--border-subtle)]',
		bad: 'border-red-500/35',
	};
</script>

{#snippet tile(key, label, dot, value, tone, hint, extra, detail)}
	{@const active = activeFilter === key}
	{@const cls = `flex flex-col justify-start w-full min-w-0 text-left rounded-xl border bg-[var(--surface-container)] px-4 py-3 transition-colors ${toneBorder[tone] || toneBorder.default} ${active ? 'ring-1 ring-sky-500/50 bg-[var(--surface-container-high)]' : ''} ${extra}`}
	{#snippet body()}
		<div class="flex items-center gap-1.5 min-w-0">
			<span class="w-2 h-2 rounded-full flex-shrink-0" style="background: {dot}"></span>
			<span class="text-[10px] font-mono uppercase tracking-wider text-[var(--text-muted)] truncate">{label}</span>
		</div>
		<p class="mt-1 text-2xl font-bold tabular-nums tracking-tight truncate {toneValue[tone] || toneValue.default}">{value}</p>
		<p class="text-xs text-[var(--text-muted)] whitespace-normal line-clamp-2 min-h-4">{@render detail()}</p>
	{/snippet}
	{#if onFilter}
		<button type="button" class="{cls} hover:bg-[var(--surface-container-high)] cursor-pointer" title={hint} aria-pressed={active}
			onclick={() => onFilter(key)}>
			{@render body()}
		</button>
	{:else}
		<div class={cls} title={hint}>{@render body()}</div>
	{/if}
{/snippet}

{#snippet soulseekDetail()}{soulseekTile.detail}{/snippet}
{#snippet transferDetail()}{transferTile.detail}{/snippet}
{#snippet searchDetail()}{searchTile.detail}{/snippet}
{#snippet queueDetail()}{queueTile.detail}{/snippet}
{#snippet addedDetail()}
	{#if summary}
		{addedTile.had} already had · <span class={addedTile.failed ? 'text-rose-400' : ''}>{addedTile.failed} failed</span>
	{/if}
{/snippet}

<div class="grid grid-cols-2 md:grid-cols-5 gap-3 {className}">
	{@render tile('soulseek', 'Soulseek', soulseekTile.dot, soulseekTile.value, soulseekTile.tone,
		'Soulseek connection', 'col-span-2 md:col-span-1', soulseekDetail)}
	{@render tile('transferring', 'Transferring', '#38bdf8', transferTile.value, 'default',
		'Show the transferring rows', '', transferDetail)}
	{@render tile('searching', 'Searching', '#818cf8', searchTile.value, 'default',
		'Show the searching rows', '', searchDetail)}
	{@render tile('queue', 'Queue', '#fbbf24', queueTile.value, 'default',
		'Show the live list', '', queueDetail)}
	{@render tile('added', scopeLabel === 'today' ? 'Added today' : `Added · ${scopeLabel}`, '#34d399', addedTile.value, 'default',
		'Show Done', '', addedDetail)}
</div>
