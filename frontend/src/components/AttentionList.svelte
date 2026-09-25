<script>
	/**
	 * "Needs attention" for the admin dashboard: problems ranked by severity from
	 * /api/attention, each with a button that opens the page (already filtered) where
	 * it gets fixed, plus a 24-hour job strip — all in one compact card, one line per
	 * problem, with lower-severity rows folded away past the first few. Collapses to one
	 * "All clear" line when there's nothing to do.
	 */
	import { onMount } from 'svelte';
	import { CheckCircle2, RefreshCw, ChevronRight, ChevronDown, ChevronUp } from 'lucide-svelte';
	import { formatRelativeTime } from '$lib/utils.js';

	let { onsummary = null } = $props();

	let data = $state(null);
	let jobs = $state(null);
	let loading = $state(true);
	let failed = $state(false);

	const dot = { critical: 'bg-red-500', warning: 'bg-amber-400', info: 'bg-cyan-400' };

	// Problems (critical) always show; the rest fold away past this many rows.
	const COLLAPSED_ROWS = 3;
	const EXPANDED_KEY = 'zonik.attention.expanded';
	let expanded = $state(false);
	try { expanded = localStorage.getItem(EXPANDED_KEY) === '1'; } catch {}

	function toggle() {
		expanded = !expanded;
		try { localStorage.setItem(EXPANDED_KEY, expanded ? '1' : '0'); } catch {}
	}

	let shown = $derived.by(() => {
		const items = data?.items ?? [];
		if (expanded) return items;
		const critical = items.filter(i => i.severity === 'critical').length;
		return items.slice(0, Math.max(COLLAPSED_ROWS, critical));
	});
	let hidden = $derived((data?.items.length ?? 0) - shown.length);
	// Same shapes as the shared Button (rounded-md, ghost border). Critical items get the
	// danger tint instead of the bright primary fill, which clashed with the dark cards.
	const button = {
		critical: 'text-red-300 bg-red-500/10 border border-red-500/30 hover:bg-red-500/20',
		warning: 'text-[var(--text-primary)] bg-[var(--surface-container-high)] ghost-border hover:bg-[var(--surface-container-highest)]',
		info: 'text-[var(--text-primary)] bg-[var(--surface-container-high)] ghost-border hover:bg-[var(--surface-container-highest)]',
	};

	async function load() {
		loading = true;
		failed = false;
		try {
			const [a, j] = await Promise.all([
				fetch('/api/attention').then(r => { if (!r.ok) throw new Error(r.status); return r.json(); }),
				fetch('/api/jobs/dashboard').then(r => r.ok ? r.json() : null).catch(() => null),
			]);
			data = a;
			jobs = j;
			onsummary?.(a);
		} catch {
			failed = true;
		} finally {
			loading = false;
		}
	}

	onMount(load);

	let jobs24 = $derived.by(() => {
		if (!jobs?.timeline?.length) return null;
		const counts = jobs.status_counts || {};
		// The API lists only hours that had jobs ("YYYY-MM-DD HH:00", UTC); lay them onto
		// the full 24 hours so quiet hours show as gaps instead of being squeezed out.
		const byHour = new Map(jobs.timeline.map(t => [t.hour, t.count]));
		const bars = [];
		const now = new Date();
		for (let i = 23; i >= 0; i--) {
			const d = new Date(now.getTime() - i * 3600_000);
			const key = `${d.toISOString().slice(0, 10)} ${String(d.getUTCHours()).padStart(2, '0')}:00`;
			bars.push({ hour: key, count: byHour.get(key) || 0 });
		}
		const max = Math.max(...bars.map(b => b.count), 1);
		return { bars, max, run: jobs.total_24h ?? 0, failed: counts.failed ?? 0 };
	});
</script>

<section class="mb-6" aria-label="Needs attention">
	{#if loading && !data}
		<div class="space-y-2">
			{#each [0, 1, 2] as _}
				<div class="h-9 rounded-lg bg-[var(--surface-container)] animate-pulse"></div>
			{/each}
		</div>
	{:else if failed}
		<div class="flex items-center gap-3 rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-container)] px-4 py-3 text-sm text-[var(--text-muted)]">
			Couldn't load what needs attention.
			<button onclick={load} class="ml-auto text-[var(--color-primary)] hover:underline">Try again</button>
		</div>
	{:else if data}
		<!-- One compact card, one line per problem: the list used to be a stack of
		     full-size cards that pushed the library stats below the fold. -->
		<div class="rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-container)] overflow-hidden">
			{#if data.items.length === 0}
				<div class="flex items-center gap-3 px-4 py-2.5">
					<CheckCircle2 class="w-4 h-4 text-emerald-400 flex-shrink-0" />
					<p class="text-sm text-[var(--text-primary)]">All clear — nothing needs you right now.</p>
				</div>
			{:else}
				<ul class="divide-y divide-[var(--border-subtle)]">
					{#each shown as item (item.key)}
						<li class="flex items-center gap-3 px-4 py-2">
							<span class="w-2 h-2 rounded-full flex-shrink-0 {dot[item.severity] || dot.info}" aria-hidden="true"></span>
							<p class="flex-1 min-w-0 truncate text-sm" title={item.detail}>
								<span class="sr-only">{item.severity}: </span>
								<span class="font-medium text-[var(--text-primary)]">{item.title}</span>
								<span class="hidden md:inline text-xs text-[var(--text-muted)] ml-2">{item.detail}</span>
							</p>
							<a href={item.href}
								class="flex-shrink-0 inline-flex items-center gap-0.5 text-xs font-medium pl-2.5 pr-1.5 py-1 rounded-md transition-colors whitespace-nowrap {button[item.severity] || button.info}">
								{item.action}
								<ChevronRight class="w-3.5 h-3.5 opacity-70" />
							</a>
						</li>
					{/each}
				</ul>
				{#if hidden > 0 || expanded}
					<button onclick={toggle}
						class="w-full flex items-center justify-center gap-1 border-t border-[var(--border-subtle)] py-1.5 text-xs text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-container-high)] transition-colors">
						{#if expanded}Show less <ChevronUp class="w-3.5 h-3.5" />{:else}{hidden} more <ChevronDown class="w-3.5 h-3.5" />{/if}
					</button>
				{/if}
			{/if}

			<div class="flex items-center gap-3 border-t border-[var(--border-subtle)] px-4 py-1.5 text-xs text-[var(--text-muted)]">
				{#if jobs24}
					<span class="font-mono uppercase tracking-wider text-[10px] whitespace-nowrap">Jobs 24h</span>
					<div class="flex items-end gap-px h-4 w-24 sm:w-40 flex-shrink-0" role="img"
						aria-label="Jobs started per hour over the last 24 hours">
						{#each jobs24.bars as b}
							<div class="flex-1 rounded-t-[1px] bg-indigo-400/70 min-h-px"
								style="height: {b.count ? Math.max(15, (b.count / jobs24.max) * 100) : 8}%; opacity: {b.count ? 1 : 0.35}"
								title="{b.hour}: {b.count} job{b.count === 1 ? '' : 's'}"></div>
						{/each}
					</div>
					<span class="whitespace-nowrap">
						{jobs24.run} run{#if jobs24.failed} · <span class="text-red-300">{jobs24.failed} failed</span>{/if}
					</span>
				{/if}
				<span class="ml-auto flex items-center gap-1 whitespace-nowrap text-[var(--text-disabled)]">
					Checked {formatRelativeTime(data.generated_at)}
					<button onclick={load} class="p-1 rounded hover:text-[var(--text-primary)] transition-colors" title="Check again" aria-label="Check again">
						<RefreshCw class="w-3.5 h-3.5 {loading ? 'animate-spin' : ''}" />
					</button>
				</span>
			</div>
		</div>
	{/if}
</section>
