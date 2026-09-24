<script>
	/**
	 * "Needs attention" for the admin dashboard: problems ranked by severity from
	 * /api/attention, each with a button that opens the page (already filtered) where
	 * it gets fixed, plus a 24-hour job strip. Collapses to one "All clear" line when
	 * there's nothing to do.
	 */
	import { onMount } from 'svelte';
	import { CheckCircle2, RefreshCw } from 'lucide-svelte';
	import { formatRelativeTime } from '$lib/utils.js';

	let { onsummary = null } = $props();

	let data = $state(null);
	let jobs = $state(null);
	let loading = $state(true);
	let failed = $state(false);

	const stripe = { critical: 'bg-red-500', warning: 'bg-amber-400', info: 'bg-cyan-400' };
	const button = {
		critical: 'bg-[var(--color-primary)] text-white hover:opacity-90',
		warning: 'bg-[var(--surface-container-high)] text-[var(--text-primary)] hover:bg-[var(--surface-container-highest)]',
		info: 'bg-[var(--surface-container-high)] text-[var(--text-primary)] hover:bg-[var(--surface-container-highest)]',
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
		const bars = jobs.timeline.slice(-24);
		const max = Math.max(...bars.map(b => b.count), 1);
		return { bars, max, run: jobs.total_24h ?? 0, failed: counts.failed ?? 0 };
	});
</script>

<section class="mb-6" aria-label="Needs attention">
	{#if loading && !data}
		<div class="space-y-2">
			{#each [0, 1, 2] as _}
				<div class="h-14 rounded-xl bg-[var(--surface-container)] animate-pulse"></div>
			{/each}
		</div>
	{:else if failed}
		<div class="flex items-center gap-3 rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-container)] px-4 py-3 text-sm text-[var(--text-muted)]">
			Couldn't load what needs attention.
			<button onclick={load} class="ml-auto text-[var(--color-primary)] hover:underline">Try again</button>
		</div>
	{:else if data}
		{#if data.items.length === 0}
			<div class="flex items-center gap-3 rounded-xl border border-emerald-500/30 bg-emerald-500/5 px-4 py-3">
				<CheckCircle2 class="w-5 h-5 text-emerald-400 flex-shrink-0" />
				<p class="text-sm text-[var(--text-primary)]">All clear — nothing needs you right now.</p>
			</div>
		{:else}
			<ul class="space-y-2">
				{#each data.items as item (item.key)}
					<li class="flex items-stretch rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-container)] overflow-hidden">
						<span class="w-1 flex-shrink-0 {stripe[item.severity] || stripe.info}" aria-hidden="true"></span>
						<div class="flex-1 min-w-0 flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-4 px-4 py-3">
							<div class="flex-1 min-w-0">
								<p class="text-sm font-semibold text-[var(--text-primary)]">
									<span class="sr-only">{item.severity}: </span>{item.title}
								</p>
								<p class="text-xs text-[var(--text-muted)] mt-0.5">{item.detail}</p>
							</div>
							<a href={item.href}
								class="self-start sm:self-center flex-shrink-0 text-xs font-medium px-3 py-1.5 rounded-lg transition-colors whitespace-nowrap {button[item.severity] || button.info}">
								{item.action}
							</a>
						</div>
					</li>
				{/each}
			</ul>
		{/if}

		<div class="mt-3 flex flex-col sm:flex-row gap-3">
			{#if jobs24}
				<div class="flex-1 rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-container)] px-4 py-3">
					<div class="flex items-baseline justify-between gap-2">
						<span class="text-[10px] font-mono uppercase tracking-wider text-[var(--text-muted)]">Jobs · last 24h</span>
						<span class="text-xs text-[var(--text-muted)]">
							{jobs24.run} run{#if jobs24.failed} · <span class="text-red-300">{jobs24.failed} failed</span>{/if}
						</span>
					</div>
					<div class="mt-2 flex items-end gap-[3px] h-10" role="img"
						aria-label="Jobs started per hour over the last 24 hours">
						{#each jobs24.bars as b}
							<div class="flex-1 rounded-t-sm bg-indigo-400/70 min-h-[2px]"
								style="height: {Math.max(4, (b.count / jobs24.max) * 100)}%"
								title="{b.hour}: {b.count} job{b.count === 1 ? '' : 's'}"></div>
						{/each}
					</div>
				</div>
			{/if}
			<div class="flex items-center gap-2 text-xs text-[var(--text-disabled)] sm:self-end">
				Checked {formatRelativeTime(data.generated_at)}
				<button onclick={load} class="p-1 rounded hover:text-[var(--text-primary)] transition-colors" title="Check again" aria-label="Check again">
					<RefreshCw class="w-3.5 h-3.5 {loading ? 'animate-spin' : ''}" />
				</button>
			</div>
		</div>
	{/if}
</section>
