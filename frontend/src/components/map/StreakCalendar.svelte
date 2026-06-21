<script>
	import { onMount, onDestroy } from 'svelte';
	import { api } from '$lib/api.js';
	import { addToast } from '$lib/stores.js';
	import { Flame, CalendarDays } from 'lucide-svelte';

	// --- state ---
	let loading = $state(true);
	let payload = $state(null); // { days, max, total }
	let hover = $state(null); // { label, count, x, y } | null

	// --- wrapper measurement (fill the ~72vh relative container) ---
	let wrap;
	let cellPx = $state(13); // computed square size in px (incl. gap budget)
	let ro;

	const GAP = 3;
	const WEEKS = 53;
	const WD_LABELS = { 1: 'Mon', 3: 'Wed', 5: 'Fri' };
	const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
	const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

	// local-date key helpers (avoid UTC drift from toISOString)
	function keyOf(d) {
		const y = d.getFullYear();
		const m = String(d.getMonth() + 1).padStart(2, '0');
		const day = String(d.getDate()).padStart(2, '0');
		return `${y}-${m}-${day}`;
	}
	function addDays(d, n) {
		const x = new Date(d);
		x.setDate(x.getDate() + n);
		x.setHours(0, 0, 0, 0);
		return x;
	}

	// Build the column-major grid: WEEKS columns, each a Date[7] Sun..Sat.
	// Last column aligned to this week; first cell is the Sunday ~52 weeks back.
	const grid = $derived.by(() => {
		const today = new Date();
		today.setHours(0, 0, 0, 0);
		// start = Sunday of the week (WEEKS-1) weeks ago
		const startSunday = addDays(today, -(WEEKS - 1) * 7 - today.getDay());
		const cols = [];
		for (let w = 0; w < WEEKS; w++) {
			const col = [];
			for (let dow = 0; dow < 7; dow++) {
				const date = addDays(startSunday, w * 7 + dow);
				col.push(date.getTime() > today.getTime() ? null : date);
			}
			cols.push(col);
		}
		return cols;
	});

	const days = $derived(payload?.days ?? {});
	const max = $derived(payload?.max ?? 0);

	function countFor(date) {
		if (!date) return 0;
		return days[keyOf(date)] || 0;
	}

	// 0 → surface-lowest; else 4 buckets of #22d3ee by count/max.
	const RAMP = [
		'rgba(34,211,238,0.22)',
		'rgba(34,211,238,0.42)',
		'rgba(34,211,238,0.65)',
		'rgba(34,211,238,0.95)',
	];
	function colorFor(count) {
		if (count <= 0) return 'var(--surface-lowest)';
		if (max <= 0) return RAMP[0];
		const t = count / max; // (0,1]
		const idx = Math.min(RAMP.length - 1, Math.floor(t * RAMP.length - 1e-9));
		return RAMP[Math.max(0, idx)];
	}

	// Month labels: for each column, the month name if a new month starts in that
	// column's top-visible cell vs the previous column.
	const monthLabels = $derived.by(() => {
		const out = [];
		let prevMonth = -1;
		for (let w = 0; w < grid.length; w++) {
			const firstReal = grid[w].find((d) => d);
			const m = firstReal ? firstReal.getMonth() : -1;
			if (m !== -1 && m !== prevMonth) {
				out.push({ col: w, label: MONTHS[m] });
				prevMonth = m;
			}
		}
		return out;
	});

	// --- summary stats ---
	const stats = $derived.by(() => {
		const today = new Date();
		today.setHours(0, 0, 0, 0);
		const total = payload?.total ?? 0;
		let active = 0;
		for (const k in days) if (days[k] > 0) active++;

		// current streak: consecutive days with >=1 play ending today
		// (a 0-play "today" doesn't break a streak that ran through yesterday)
		let current = 0;
		let cursor = new Date(today);
		if ((days[keyOf(cursor)] || 0) <= 0) cursor = addDays(cursor, -1); // grace for today
		while ((days[keyOf(cursor)] || 0) > 0) {
			current++;
			cursor = addDays(cursor, -1);
		}

		// longest streak over the rendered window
		let longest = 0, run = 0;
		const start = addDays(today, -(WEEKS * 7));
		for (let d = new Date(start); d.getTime() <= today.getTime(); d = addDays(d, 1)) {
			if ((days[keyOf(d)] || 0) > 0) {
				run++;
				if (run > longest) longest = run;
			} else run = 0;
		}
		return { total, active, current, longest };
	});

	function fmtTooltip(date, count) {
		const label = `${DOW[date.getDay()]}, ${date.getDate()} ${MONTHS[date.getMonth()]}`;
		const plays = count === 1 ? '1 play' : `${count} plays`;
		return `${label} · ${plays}`;
	}

	function onEnter(ev, date) {
		if (!date) return;
		const count = countFor(date);
		const rect = wrap.getBoundingClientRect();
		hover = {
			text: fmtTooltip(date, count),
			x: ev.clientX - rect.left,
			y: ev.clientY - rect.top,
		};
	}
	function onLeave() { hover = null; }

	function measure() {
		if (!wrap) return;
		const rect = wrap.getBoundingClientRect();
		// reserve room for left weekday labels (~30px) + top month labels (~18px) + padding
		const usableW = Math.max(120, rect.width - 30 - 16);
		const usableH = Math.max(120, rect.height - 18 - 80 - 16); // top labels + stats header + pad
		const byW = (usableW - GAP) / WEEKS - GAP;
		const byH = (usableH - GAP) / 7 - GAP;
		cellPx = Math.max(8, Math.min(22, Math.floor(Math.min(byW, byH))));
	}

	onMount(async () => {
		measure();
		ro = new ResizeObserver(measure);
		if (wrap) ro.observe(wrap);
		try {
			payload = await api.getStreakCalendar();
		} catch {
			addToast('Failed to load listening streak', 'error');
			payload = { days: {}, max: 0, total: 0 };
		} finally {
			loading = false;
		}
	});
	onDestroy(() => { if (ro) ro.disconnect(); });
</script>

<div bind:this={wrap} class="h-full w-full flex flex-col p-2 sm:p-4 select-none">
	{#if loading}
		<div class="flex-1 flex flex-col items-center justify-center gap-3">
			<div class="w-8 h-8 border-2 border-[#22d3ee] border-t-transparent rounded-full animate-spin"></div>
			<p class="text-sm text-[var(--text-secondary)]">Loading streak…</p>
		</div>
	{:else}
		<!-- summary stats -->
		<div class="flex flex-wrap items-stretch gap-2 sm:gap-3 mb-3">
			<div class="flex items-center gap-2 rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-container)] px-3 py-2">
				<CalendarDays class="w-4 h-4 text-[#22d3ee] flex-shrink-0" />
				<div class="leading-tight">
					<div class="text-base font-semibold text-[var(--text-primary)]">{stats.total.toLocaleString()}</div>
					<div class="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">Total plays</div>
				</div>
			</div>
			<div class="flex items-center gap-2 rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-container)] px-3 py-2">
				<div class="leading-tight">
					<div class="text-base font-semibold text-[var(--text-primary)]">{stats.active.toLocaleString()}</div>
					<div class="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">Active days</div>
				</div>
			</div>
			<div class="flex items-center gap-2 rounded-lg border border-[#22d3ee]/30 bg-[#22d3ee]/5 px-3 py-2">
				<Flame class="w-4 h-4 text-[#22d3ee] flex-shrink-0" />
				<div class="leading-tight">
					<div class="text-base font-semibold text-[var(--text-primary)]">{stats.current}<span class="text-xs text-[var(--text-muted)] font-normal"> d</span></div>
					<div class="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">Current streak</div>
				</div>
			</div>
			<div class="flex items-center gap-2 rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-container)] px-3 py-2">
				<div class="leading-tight">
					<div class="text-base font-semibold text-[var(--text-primary)]">{stats.longest}<span class="text-xs text-[var(--text-muted)] font-normal"> d</span></div>
					<div class="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">Longest streak</div>
				</div>
			</div>
		</div>

		<!-- heatmap -->
		<div class="flex-1 min-h-0 overflow-auto">
			<div class="inline-flex flex-col" style="gap:{GAP}px;">
				<!-- month labels row -->
				<div class="flex" style="margin-left:30px; height:14px; gap:{GAP}px; position:relative;">
					{#each monthLabels as ml}
						<span class="absolute text-[10px] text-[var(--text-muted)]"
							style="left:{ml.col * (cellPx + GAP)}px; top:0;">{ml.label}</span>
					{/each}
				</div>

				<!-- weekday labels + grid -->
				<div class="flex" style="gap:{GAP}px;">
					<!-- weekday labels column -->
					<div class="flex flex-col" style="width:30px; gap:{GAP}px;">
						{#each DOW as _, wd}
							<div class="text-[9px] text-[var(--text-disabled)] flex items-center justify-end pr-1"
								style="height:{cellPx}px;">{WD_LABELS[wd] ?? ''}</div>
						{/each}
					</div>

					<!-- week columns -->
					<div class="flex" style="gap:{GAP}px;">
						{#each grid as col}
							<div class="flex flex-col" style="gap:{GAP}px;">
								{#each col as date}
									{#if date}
										{@const c = countFor(date)}
										<div
											class="rounded-[3px] cursor-pointer transition-transform hover:scale-110"
											style="width:{cellPx}px; height:{cellPx}px; background:{colorFor(c)}; box-shadow: inset 0 0 0 1px rgba(255,255,255,0.03);"
											role="presentation"
											onmouseenter={(e) => onEnter(e, date)}
											onmousemove={(e) => onEnter(e, date)}
											onmouseleave={onLeave}
										></div>
									{:else}
										<div style="width:{cellPx}px; height:{cellPx}px;"></div>
									{/if}
								{/each}
							</div>
						{/each}
					</div>
				</div>
			</div>
		</div>

		<!-- legend -->
		<div class="flex items-center justify-end gap-1.5 mt-3 text-[10px] text-[var(--text-muted)]">
			<span>Less</span>
			<span class="rounded-[3px]" style="width:11px;height:11px;background:var(--surface-lowest);box-shadow: inset 0 0 0 1px rgba(255,255,255,0.04);"></span>
			{#each RAMP as col}
				<span class="rounded-[3px]" style="width:11px;height:11px;background:{col};"></span>
			{/each}
			<span>More</span>
		</div>
	{/if}

	<!-- tooltip -->
	{#if hover}
		<div class="absolute pointer-events-none z-20 px-2 py-1 rounded bg-black/85 text-white text-xs whitespace-nowrap shadow-lg"
			style="left:{Math.min(hover.x + 12, (wrap?.clientWidth ?? 9999) - 160)}px; top:{Math.max(hover.y - 30, 4)}px;">
			{hover.text}
		</div>
	{/if}
</div>
