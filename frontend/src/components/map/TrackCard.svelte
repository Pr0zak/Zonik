<script>
	// One track's listening: plays per month, devices, skips and what you
	// usually play after it. Opens over the map when a track is clicked, and
	// from the Rotation board.
	import { api } from '$lib/api.js';
	import { familyColor, ago, sourceLabel } from './explore.js';
	import { X, Loader2, ListChecks } from 'lucide-svelte';

	let { id, onclose, onpick = null, onselect = null, floating = true } = $props();

	let data = $state(null);
	let error = $state('');

	$effect(() => {
		const want = id;
		data = null; error = '';
		api.getTrackListening(want)
			.then((r) => { if (want === id) data = r; })
			.catch(() => { if (want === id) error = 'Could not load this track’s plays'; });
	});

	const SRC_COLORS = ['#22d3ee', '#76b7b2', '#b07aa1', '#7c8594', '#f28e2b'];
	const sources = $derived(data ? Object.entries(data.sources) : []);
	const srcTotal = $derived(sources.reduce((a, [, n]) => a + n, 0));

	// Sparkline geometry (viewBox 240×56).
	const spark = $derived.by(() => {
		if (!data) return null;
		const v = data.monthly, mx = Math.max(1, ...v);
		const pts = v.map((n, k) => [4 + (k * 232) / (v.length - 1), 48 - (n / mx) * 40]);
		const line = 'M' + pts.map((p) => p.map((c) => c.toFixed(1)).join(',')).join(' L');
		return { line, area: `${line} L${pts.at(-1)[0]},48 L4,48 Z`, end: pts.at(-1), mx };
	});
	const monthLabel = (ym) => new Date(ym + '-01T12:00:00').toLocaleDateString(undefined, { month: 'short' });
</script>

<div class="{floating ? 'absolute bottom-3 right-3 z-20 w-[min(380px,calc(100%-24px))] shadow-xl' : 'w-full'} rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-container)]/95 backdrop-blur p-3 text-xs">
	<div class="flex items-start gap-2">
		<div class="min-w-0 flex-1">
			{#if data}
				<p class="text-sm font-medium text-[var(--text-primary)] truncate">{data.title}</p>
				<p class="text-[var(--text-muted)] truncate">{data.artist || 'Unknown'}{#if data.album} · {data.album}{/if}{#if data.year} · {data.year}{/if}</p>
				<p class="mt-0.5 flex items-center gap-1.5 text-[var(--text-secondary)]">
					<span class="w-2 h-2 rounded-full" style="background:{familyColor(data.family)}"></span>{data.family}
					{#if data.bpm} · {Math.round(data.bpm)} BPM{/if}{#if data.key} · {data.key} {data.scale || ''}{/if}
				</p>
			{:else if error}
				<p class="text-red-400">{error}</p>
			{:else}
				<p class="flex items-center gap-2 text-[var(--text-muted)]"><Loader2 class="w-3.5 h-3.5 animate-spin" /> Loading plays…</p>
			{/if}
		</div>
		<button onclick={onclose} class="p-1 -m-1 rounded text-[var(--text-muted)] hover:text-[var(--text-primary)]" aria-label="Close track card"><X class="w-4 h-4" /></button>
	</div>

	{#if data}
		<div class="grid grid-cols-4 gap-2 mt-3">
			{#each [[data.play_count, 'plays'], [data.skip_count, 'net skips', 'Skips minus full listens since the last reset'], [ago(data.last_played), 'last played'], [data.first_played ? ago(data.first_played) : '—', 'first play']] as [v, l, t]}
				<div title={t || ''}>
					<p class="text-base font-semibold text-[var(--text-primary)] tabular-nums leading-tight">{v}</p>
					<p class="text-[10px] text-[var(--text-muted)]">{l}</p>
				</div>
			{/each}
		</div>

		<p class="mt-3 text-[10px] uppercase tracking-wide text-[var(--text-muted)]">Plays per month</p>
		<svg viewBox="0 0 240 64" class="w-full h-16" role="img" aria-label="Plays per month over the last year">
			<line x1="4" x2="236" y1="48.5" y2="48.5" stroke="var(--border-subtle)" />
			<path d={spark.area} fill="rgba(34,211,238,0.15)" />
			<path d={spark.line} fill="none" stroke="#22d3ee" stroke-width="1.6" stroke-linejoin="round" />
			<circle cx={spark.end[0]} cy={spark.end[1]} r="2.6" fill="#22d3ee" />
			<text x="4" y="62" font-size="8" fill="var(--text-muted)">{monthLabel(data.months[0])}</text>
			<text x="236" y="62" font-size="8" fill="var(--text-muted)" text-anchor="end">{monthLabel(data.months.at(-1))}</text>
			<text x="4" y="8" font-size="8" fill="var(--text-muted)">peak {spark.mx}/mo</text>
		</svg>

		{#if srcTotal}
			<p class="mt-2 text-[10px] uppercase tracking-wide text-[var(--text-muted)]">Played on</p>
			<div class="flex h-2 rounded overflow-hidden mt-1">
				{#each sources as [s, n], k}<span style="width:{(n / srcTotal) * 100}%; background:{SRC_COLORS[k % SRC_COLORS.length]}" title="{sourceLabel(s)}: {n}"></span>{/each}
			</div>
			<div class="flex flex-wrap gap-x-3 mt-1 text-[var(--text-secondary)]">
				{#each sources as [s, n], k}<span class="flex items-center gap-1"><span class="w-2 h-2 rounded-sm" style="background:{SRC_COLORS[k % SRC_COLORS.length]}"></span>{sourceLabel(s)} {n}</span>{/each}
			</div>
		{/if}

		<div class="flex items-center justify-between mt-3">
			<p class="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">After this you usually play</p>
			{#if onselect && data.after.length}
				<button onclick={() => onselect([data.track_id, ...data.after.map((a) => a.track_id)], `After ${data.title}`)}
					class="flex items-center gap-1 text-[#22d3ee] hover:underline"><ListChecks class="w-3.5 h-3.5" /> Select</button>
			{/if}
		</div>
		{#if data.after.length}
			{@const mx = Math.max(...data.after.map((a) => a.count))}
			<ul class="mt-1 space-y-1">
				{#each data.after as a (a.track_id)}
					<li>
						<button onclick={() => onpick?.(a.track_id)} disabled={!onpick}
							class="w-full grid grid-cols-[1fr_72px_24px] items-center gap-2 text-left rounded px-1 py-0.5 hover:bg-[var(--surface-container-high)] disabled:hover:bg-transparent">
							<span class="min-w-0"><span class="block truncate text-[var(--text-primary)]">{a.title}</span><span class="block truncate text-[10px] text-[var(--text-muted)]">{a.artist || 'Unknown'}</span></span>
							<span class="h-1.5 rounded bg-[#22d3ee]/70" style="width:{(a.count / mx) * 100}%"></span>
							<span class="tabular-nums text-[var(--text-muted)] text-right">{a.count}×</span>
						</button>
					</li>
				{/each}
			</ul>
		{:else}
			<p class="mt-1 text-[var(--text-muted)]">Nothing yet — no play of this track has been followed by another in the same session.</p>
		{/if}
	{/if}
</div>
