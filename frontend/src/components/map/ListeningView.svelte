<script>
	// Listening tab: how your plays move over time (taste river), which genre
	// tends to follow which (genre flow) and what's in or falling out of
	// rotation. Every list ends in Save as playlist, like the rest of the map.
	import { onMount } from 'svelte';
	import * as d3 from 'd3';
	import { api } from '$lib/api.js';
	import { addToast } from '$lib/stores.js';
	import Card from '../ui/Card.svelte';
	import SelectionBar from './SelectionBar.svelte';
	import TrackCard from './TrackCard.svelte';
	import { familyColor, ago } from './explore.js';
	import { Loader2, Waves, GitFork, ListOrdered } from 'lucide-svelte';

	// --- B: taste river ---
	let river = $state(null);
	let riverW = $state(800);
	let riverHover = $state(null); // week index
	let riverFocus = $state(null); // family
	const RH = 220, RPAD = { l: 8, r: 8, t: 10, b: 22 };

	const riverGeo = $derived.by(() => {
		if (!river || !river.weeks.length) return null;
		const n = river.weeks.length, w = Math.max(200, riverW);
		const tot = river.weeks.map((_, k) => river.counts.reduce((a, c) => a + c[k], 0));
		const mx = Math.max(1, ...tot);
		const h = RH - RPAD.t - RPAD.b, mid = RPAD.t + h / 2, sc = h / mx;
		const x = (k) => RPAD.l + (k * (w - RPAD.l - RPAD.r)) / Math.max(1, n - 1);
		let base = tot.map((t) => mid - (t * sc) / 2);
		const area = d3.area().x((d) => d[0]).y0((d) => d[1]).y1((d) => d[2]).curve(d3.curveMonotoneX);
		const bands = river.families.map((f, fi) => {
			const c = river.counts[fi];
			const pts = base.map((b, k) => [x(k), b, b + c[k] * sc]);
			base = base.map((b, k) => b + c[k] * sc);
			return { family: f, d: area(pts), total: c.reduce((a, b) => a + b, 0) };
		});
		// A label under each new month.
		const months = [];
		let last = '';
		river.weeks.forEach((wk, k) => {
			const m = wk.slice(0, 7);
			if (m !== last) { last = m; months.push({ x: x(k), label: new Date(wk + 'T12:00:00').toLocaleDateString(undefined, { month: 'short' }) }); }
		});
		return { bands, x, w, n, tot, months: months.filter((_, k) => k % (w < 600 ? 2 : 1) === 0) };
	});

	function riverMove(ev) {
		if (!riverGeo) return;
		const r = ev.currentTarget.getBoundingClientRect();
		const t = (ev.clientX - r.left - RPAD.l) / (riverGeo.w - RPAD.l - RPAD.r);
		riverHover = Math.min(riverGeo.n - 1, Math.max(0, Math.round(t * (riverGeo.n - 1))));
	}
	const riverTip = $derived.by(() => {
		if (riverHover == null || !river) return null;
		const k = riverHover;
		const rows = river.families.map((f, fi) => [f, river.counts[fi][k]]).filter(([, n]) => n).sort((a, b) => b[1] - a[1]);
		const wk = new Date(river.weeks[k] + 'T12:00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
		return { wk, total: riverGeo.tot[k], rows: rows.slice(0, 5) };
	});

	// --- G: genre flow ---
	let flowDays = $state(90);
	let flow = $state(null);
	let flowHover = $state(null); // { a, b, n }
	let flowUntagged = $state(false); // include Unknown / Other
	const FH = 340, FL = 130, FR = 130, MIN_SHARE = 0.02;

	// Families under 2% of transitions fold into one "Other" row so the
	// diagram stays readable.
	const flowData = $derived.by(() => {
		if (!flow || !flow.transitions) return null;
		const drop = (f) => !flowUntagged && (f === 'Unknown' || f === 'Other');
		const fams = flow.families;
		const M = flow.matrix.map((row, i) => row.map((n, j) => (drop(fams[i]) || drop(fams[j]) ? 0 : n)));
		const total = M.flat().reduce((a, b) => a + b, 0);
		if (!total) return null;
		const weight = fams.map((_, i) => M[i].reduce((a, b) => a + b, 0) + M.reduce((a, r) => a + r[i], 0));
		const keep = fams.map((f, i) => weight[i] / (2 * total) >= MIN_SHARE && f !== 'Other');
		if (!flowUntagged) fams.forEach((f, i) => { if (drop(f)) keep[i] = true; });
		const names = fams.filter((_, i) => keep[i]);
		const hasOther = keep.some((k) => !k);
		if (hasOther && !names.includes('Other')) names.push('Other');
		const idx = fams.map((f, i) => (keep[i] ? names.indexOf(f) : names.indexOf('Other')));
		const m = names.map(() => names.map(() => 0));
		M.forEach((row, i) => row.forEach((n, j) => { m[idx[i]][idx[j]] += n; }));
		// Families left with no transitions (untagged, when hidden) drop out.
		const live = names.map((_, i) => m[i].some(Boolean) || m.some((r) => r[i]));
		const keepIdx = names.map((_, i) => i).filter((i) => live[i]);
		return { names: keepIdx.map((i) => names[i]), m: keepIdx.map((i) => keepIdx.map((j) => m[i][j])), total };
	});
	let flowW = $state(800);
	const flowGeo = $derived.by(() => {
		if (!flowData) return null;
		const { names, m, total } = flowData;
		const gap = 6, h = FH - 30 - gap * (names.length - 1), sc = h / total;
		const L = FL, R = Math.max(L + 120, flowW - FR);
		const outT = m.map((r) => r.reduce((a, b) => a + b, 0));
		const inT = names.map((_, j) => m.reduce((a, r) => a + r[j], 0));
		const ly = [], ry = [];
		let y = 20; outT.forEach((v) => { ly.push(y); y += v * sc + gap; });
		y = 20; inT.forEach((v) => { ry.push(y); y += v * sc + gap; });
		const lo = [...ly], ro = [...ry], links = [];
		m.forEach((row, i) => row.forEach((n, j) => {
			if (!n) return;
			const hh = n * sc, y0 = lo[i], y1 = ro[j];
			lo[i] += hh; ro[j] += hh;
			const cx = (L + R) / 2;
			links.push({ a: names[i], b: names[j], n, share: n / outT[i],
				d: `M${L},${y0} C${cx},${y0} ${cx},${y1} ${R},${y1} L${R},${y1 + hh} C${cx},${y1 + hh} ${cx},${y0 + hh} ${L},${y0 + hh} Z` });
		}));
		links.sort((p, q) => q.n - p.n);
		return { L, R, sc, ly, ry, outT, inT, links, names };
	});
	// The strongest habit that isn't a family following itself.
	const flowHabit = $derived(flowGeo?.links.find((l) => l.a !== l.b && l.a !== 'Unknown' && l.b !== 'Unknown' && l.a !== 'Other' && l.b !== 'Other'));

	// --- I: rotation ---
	let rotDays = $state(30);
	let rotBy = $state('tracks'); // tracks | artists
	let rotFilter = $state('all');
	let rot = $state(null);
	let focus = $state(null);

	const FLAGS = {
		new: ['New favourite', 'text-emerald-400 bg-emerald-500/10'],
		rising: ['Rising', 'text-emerald-400 bg-emerald-500/10'],
		wearing_out: ['Wearing out', 'text-amber-400 bg-amber-500/10'],
		falling: ['Falling', 'text-[var(--text-secondary)] bg-[var(--surface-container-high)]'],
		dropped: ['Dropped out', 'text-[var(--text-secondary)] bg-[var(--surface-container-high)]'],
	};
	const rotRows = $derived.by(() => {
		if (!rot) return [];
		if (rotBy === 'artists') return rot.artists || [];
		if (rotFilter === 'dropped') return rot.dropped;
		if (rotFilter === 'all') return rot.tracks;
		return rot.tracks.filter((t) => t.flag === rotFilter);
	});
	const flagCounts = $derived.by(() => {
		const c = { all: rot?.tracks.length || 0, dropped: rot?.dropped.length || 0 };
		for (const t of rot?.tracks || []) if (t.flag) c[t.flag] = (c[t.flag] || 0) + 1;
		return c;
	});
	const selTracks = $derived(rotBy === 'tracks' ? rotRows.map((t) => ({ id: t.track_id, title: t.title, artist: t.artist, album_id: t.album_id })) : []);
	const selName = $derived.by(() => {
		const label = rotFilter === 'all' ? 'Top' : FLAGS[rotFilter]?.[0] || '';
		return `${label} · last ${rotDays} days`;
	});

	function sparkPath(v) {
		const mx = Math.max(1, ...v);
		return 'M' + v.map((n, k) => `${(2 + (k * 76) / (v.length - 1)).toFixed(1)},${(18 - (n / mx) * 15).toFixed(1)}`).join(' L');
	}

	async function loadRiver() { try { river = await api.getTasteRiver(52); } catch { addToast('Could not load the taste river', 'error'); } }
	async function loadFlow() { flow = null; try { flow = await api.getGenreFlow(flowDays); } catch { addToast('Could not load the genre flow', 'error'); } }
	async function loadRot() { rot = null; try { rot = await api.getRotation(rotDays); } catch { addToast('Could not load the rotation board', 'error'); } }

	onMount(loadRiver);
	$effect(() => { flowDays; loadFlow(); });
	$effect(() => { rotDays; loadRot(); });

	const seg = (on) => `px-2.5 py-1 ${on ? 'bg-[#22d3ee]/15 text-[#22d3ee] font-medium' : 'bg-[var(--surface-lowest)] text-[var(--text-secondary)] hover:bg-[var(--surface-container-high)]'}`;
</script>

<div class="space-y-4">
	<!-- B: taste river -->
	<Card padding="p-4">
		<div class="flex flex-wrap items-baseline justify-between gap-2">
			<h3 class="flex items-center gap-2 text-sm font-semibold text-[var(--text-primary)]"><Waves class="w-4 h-4 text-[#22d3ee]" /> Taste river</h3>
			<p class="text-xs text-[var(--text-muted)]">Plays per week by genre{#if river}, {river.weeks.length} weeks · {river.total.toLocaleString()} plays{/if}. Click a genre to pick it out.</p>
		</div>
		<div class="relative mt-3" bind:clientWidth={riverW}>
			{#if !riverGeo}
				<div class="h-[220px] flex items-center justify-center gap-2 text-sm text-[var(--text-muted)]"><Loader2 class="w-4 h-4 animate-spin" /> Loading…</div>
			{:else}
				<svg width={riverGeo.w} height={RH} role="img" aria-label="Plays per week by genre family" onmousemove={riverMove} onmouseleave={() => (riverHover = null)} class="block">
					{#each riverGeo.bands as b (b.family)}
						<path d={b.d} fill={familyColor(b.family)} stroke="var(--surface-container)" stroke-width="0.5"
							opacity={riverFocus && riverFocus !== b.family ? 0.15 : 0.9}
							onclick={() => (riverFocus = riverFocus === b.family ? null : b.family)} class="cursor-pointer" role="presentation" />
					{/each}
					{#if riverHover != null}
						<line x1={riverGeo.x(riverHover)} x2={riverGeo.x(riverHover)} y1={RPAD.t} y2={RH - RPAD.b} stroke="var(--text-secondary)" stroke-dasharray="2 3" />
					{/if}
					{#each riverGeo.months as m}
						<text x={m.x} y={RH - 6} font-size="10" fill="var(--text-muted)">{m.label}</text>
					{/each}
				</svg>
				{#if riverTip}
					<div class="absolute top-1 pointer-events-none z-10 px-2 py-1 rounded bg-black/85 text-white text-xs min-w-[150px]"
						style="left:{Math.min(riverGeo.x(riverHover) + 10, riverGeo.w - 170)}px">
						<p class="font-medium">Week of {riverTip.wk} · {riverTip.total} plays</p>
						{#each riverTip.rows as [f, n]}<p class="flex items-center gap-1.5 text-white/75"><span class="w-2 h-2 rounded-full" style="background:{familyColor(f)}"></span>{f} <span class="ml-auto tabular-nums">{n}</span></p>{/each}
					</div>
				{/if}
				<div class="flex flex-wrap gap-1.5 mt-2 text-xs">
					{#each riverGeo.bands.filter((b) => b.total) as b (b.family)}
						<button onclick={() => (riverFocus = riverFocus === b.family ? null : b.family)}
							class="flex items-center gap-1.5 px-2 py-0.5 rounded-md border {riverFocus === b.family ? 'border-[#22d3ee]/50 text-[var(--text-primary)]' : 'border-[var(--border-subtle)] text-[var(--text-secondary)]'} hover:bg-[var(--surface-container-high)]">
							<span class="w-2.5 h-2.5 rounded-full" style="background:{familyColor(b.family)}"></span>{b.family}<span class="text-[var(--text-disabled)] tabular-nums">{b.total}</span>
						</button>
					{/each}
				</div>
			{/if}
		</div>
	</Card>

	<!-- G: genre flow -->
	<Card padding="p-4">
		<div class="flex flex-wrap items-center justify-between gap-2">
			<h3 class="flex items-center gap-2 text-sm font-semibold text-[var(--text-primary)]"><GitFork class="w-4 h-4 text-[#22d3ee]" /> Genre flow</h3>
			<div class="flex flex-wrap items-center gap-3 text-xs">
			<label class="flex items-center gap-1.5 text-[var(--text-secondary)] cursor-pointer">
				<input type="checkbox" bind:checked={flowUntagged} class="accent-[#22d3ee]" /> Include untagged tracks
			</label>
			<div class="flex rounded-md overflow-hidden border border-[var(--border-subtle)]">
				{#each [[30, '30 days'], [90, '90 days'], [365, 'Year']] as [d, label]}
					<button onclick={() => (flowDays = d)} aria-pressed={flowDays === d} class={seg(flowDays === d)}>{label}</button>
				{/each}
			</div>
			</div>
		</div>
		<p class="text-xs text-[var(--text-muted)] mt-1">
			What you play next, by genre. Left is the track you played, right is the one after it in the same session (a gap over {flow?.gap_minutes ?? 30} minutes starts a new one).
			{#if flow}{(flowData?.total ?? 0).toLocaleString()} of {flow.transitions.toLocaleString()} transitions shown, across {flow.sessions.toLocaleString()} sessions.{/if}
			{#if flowHabit}<span class="text-[var(--text-secondary)]">Strongest jump: {flowHabit.a} → {flowHabit.b} ({Math.round(flowHabit.share * 100)}% of the time).</span>{/if}
		</p>
		<div class="relative mt-3" bind:clientWidth={flowW}>
			{#if !flow}
				<div class="h-[340px] flex items-center justify-center gap-2 text-sm text-[var(--text-muted)]"><Loader2 class="w-4 h-4 animate-spin" /> Loading…</div>
			{:else if !flowGeo}
				<p class="text-sm text-[var(--text-muted)] py-8 text-center">No back-to-back plays in this period yet.</p>
			{:else}
				<svg width={Math.max(flowW, 360)} height={FH} role="img" aria-label="Genre transitions" class="block">
					{#each flowGeo.links as l}
						{@const on = flowHover ? flowHover.a === l.a && flowHover.b === l.b : true}
						<path d={l.d} fill={familyColor(l.a)} opacity={flowHover ? (on ? 0.75 : 0.05) : l.share >= 0.2 ? 0.55 : l.share >= 0.1 ? 0.25 : 0.07}
							onmouseenter={() => (flowHover = l)} onmouseleave={() => (flowHover = null)} role="presentation" />
					{/each}
					{#each flowGeo.names as f, i}
						<rect x={flowGeo.L - 8} y={flowGeo.ly[i]} width="8" height={Math.max(1, flowGeo.outT[i] * flowGeo.sc)} fill={familyColor(f)} />
						<text x={flowGeo.L - 14} y={flowGeo.ly[i] + (flowGeo.outT[i] * flowGeo.sc) / 2 + 4} font-size="11" text-anchor="end" fill="var(--text-secondary)">{f}</text>
						<rect x={flowGeo.R} y={flowGeo.ry[i]} width="8" height={Math.max(1, flowGeo.inT[i] * flowGeo.sc)} fill={familyColor(f)} />
						<text x={flowGeo.R + 14} y={flowGeo.ry[i] + (flowGeo.inT[i] * flowGeo.sc) / 2 + 4} font-size="11" fill="var(--text-secondary)">{f}</text>
					{/each}
					<text x={flowGeo.L - 8} y="12" font-size="10" fill="var(--text-muted)">THIS PLAY</text>
					<text x={flowGeo.R + 8} y="12" font-size="10" text-anchor="end" fill="var(--text-muted)">NEXT PLAY</text>
				</svg>
				{#if flowHover}
					<div class="absolute top-0 left-1/2 -translate-x-1/2 pointer-events-none px-2 py-1 rounded bg-black/85 text-white text-xs whitespace-nowrap">
						{flowHover.a} → {flowHover.b}: <span class="tabular-nums">{flowHover.n}</span> times · {Math.round(flowHover.share * 100)}% of what follows {flowHover.a}
					</div>
				{/if}
			{/if}
		</div>
	</Card>

	<!-- I: rotation board -->
	<Card padding="p-4">
		<div class="flex flex-wrap items-center justify-between gap-2">
			<h3 class="flex items-center gap-2 text-sm font-semibold text-[var(--text-primary)]"><ListOrdered class="w-4 h-4 text-[#22d3ee]" /> Rotation</h3>
			<div class="flex flex-wrap gap-2 text-xs">
				<div class="flex rounded-md overflow-hidden border border-[var(--border-subtle)]">
					{#each [['tracks', 'Tracks'], ['artists', 'Artists']] as [v, label]}
						<button onclick={() => (rotBy = v)} aria-pressed={rotBy === v} class={seg(rotBy === v)}>{label}</button>
					{/each}
				</div>
				<div class="flex rounded-md overflow-hidden border border-[var(--border-subtle)]">
					{#each [[30, '30 days'], [90, '90 days']] as [d, label]}
						<button onclick={() => (rotDays = d)} aria-pressed={rotDays === d} class={seg(rotDays === d)}>{label}</button>
					{/each}
				</div>
			</div>
		</div>
		<p class="text-xs text-[var(--text-muted)] mt-1">Plays in the last {rotDays} days against the {rotDays} days before. The line is the last 8 weeks. Click a track for its plays and what you play after it.</p>

		{#if rotBy === 'tracks'}
			<div class="flex flex-wrap gap-1.5 mt-3 text-xs">
				{#each [['all', 'All'], ['new', 'New favourites'], ['rising', 'Rising'], ['wearing_out', 'Wearing out'], ['falling', 'Falling'], ['dropped', 'Dropped out']] as [v, label]}
					<button onclick={() => (rotFilter = v)} aria-pressed={rotFilter === v}
						class="px-2.5 py-1 rounded-md border {rotFilter === v ? 'border-[#22d3ee]/50 bg-[#22d3ee]/15 text-[#22d3ee] font-medium' : 'border-[var(--border-subtle)] text-[var(--text-secondary)] hover:bg-[var(--surface-container-high)]'}">
						{label} <span class="opacity-60 tabular-nums">{flagCounts[v] || 0}</span>
					</button>
				{/each}
			</div>
			{#if selTracks.length}<div class="mt-2"><SelectionBar tracks={selTracks} name={selName} /></div>{/if}
		{/if}

		<div class="grid gap-3 mt-3 {focus && rotBy === 'tracks' ? 'lg:grid-cols-[1fr_380px]' : ''}">
			<div class="overflow-x-auto min-w-0">
				{#if !rot}
					<div class="py-8 flex items-center justify-center gap-2 text-sm text-[var(--text-muted)]"><Loader2 class="w-4 h-4 animate-spin" /> Loading…</div>
				{:else if !rotRows.length}
					<p class="text-sm text-[var(--text-muted)] py-6 text-center">Nothing here for this period.</p>
				{:else}
					<table class="w-full text-sm">
						<thead>
							<tr class="text-[10px] uppercase tracking-wide text-[var(--text-muted)] text-left">
								<th class="font-medium py-1.5 pl-2">{rotBy === 'tracks' ? 'Track' : 'Artist'}</th>
								<th class="font-medium text-right px-2">Plays</th>
								<th class="font-medium px-2">8 weeks</th>
								<th class="font-medium text-right px-2" title="Change from the period before">Change</th>
								{#if rotBy === 'tracks'}
									<th class="font-medium text-right px-2" title="Skips minus full listens">Skips</th>
									<th class="font-medium text-right px-2 whitespace-nowrap">Last played</th>
								{:else}
									<th class="font-medium text-right px-2">Tracks</th>
								{/if}
							</tr>
						</thead>
						<tbody>
							{#each rotRows as r (r.track_id || r.artist)}
								<tr class="border-t border-[var(--border-subtle)] {rotBy === 'tracks' ? 'cursor-pointer hover:bg-[var(--surface-container-high)]' : ''} {focus && focus === r.track_id ? 'bg-[#22d3ee]/5' : ''}"
									onclick={() => rotBy === 'tracks' && (focus = r.track_id)}>
									<td class="py-1.5 pl-2 min-w-0">
										<div class="flex items-center gap-2 min-w-0">
											{#if r.family}<span class="w-1 h-7 rounded-full flex-shrink-0" style="background:{familyColor(r.family)}"></span>{/if}
											<div class="min-w-0">
												<p class="truncate text-[var(--text-primary)] max-w-[320px]">{r.title || r.artist}
													{#if r.flag}<span class="ml-1.5 text-[10px] px-1.5 py-0.5 rounded {FLAGS[r.flag][1]}">{FLAGS[r.flag][0]}</span>{/if}</p>
												{#if r.title}<p class="truncate text-xs text-[var(--text-muted)] max-w-[320px]">{r.artist || 'Unknown'}</p>{/if}
											</div>
										</div>
									</td>
									<td class="text-right px-2 tabular-nums text-[var(--text-primary)]">{r.plays}</td>
									<td class="px-2">
										<svg width="80" height="20" aria-hidden="true"><path d={sparkPath(r.spark)} fill="none" stroke="#22d3ee" stroke-width="1.5" stroke-linejoin="round" /></svg>
									</td>
									<td class="text-right px-2 tabular-nums {r.delta > 0 ? 'text-emerald-400' : r.delta < 0 ? 'text-red-400' : 'text-[var(--text-muted)]'}">{r.delta > 0 ? '+' : r.delta < 0 ? '−' : ''}{Math.abs(r.delta)}</td>
									{#if rotBy === 'tracks'}
										<td class="text-right px-2 tabular-nums {r.skips >= 2 ? 'text-amber-400' : 'text-[var(--text-muted)]'}">{r.skips}</td>
										<td class="text-right px-2 text-xs text-[var(--text-secondary)] whitespace-nowrap">{ago(r.last_played)}</td>
									{:else}
										<td class="text-right px-2 tabular-nums text-[var(--text-muted)]">{r.tracks}</td>
									{/if}
								</tr>
							{/each}
						</tbody>
					</table>
				{/if}
			</div>
			{#if focus && rotBy === 'tracks'}
				<div class="lg:sticky lg:top-4 self-start">
					<TrackCard id={focus} floating={false} onclose={() => (focus = null)} onpick={(id) => (focus = id)} />
				</div>
			{/if}
		</div>
	</Card>
</div>
