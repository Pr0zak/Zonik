<script>
	/**
	 * Peer reputation chip: "9/0" (good transfers / failed transfers with this peer).
	 * Emerald when the peer never failed us, rose when it never delivered, muted
	 * otherwise; renders nothing when the reputation is unknown (e.g. right after
	 * a restart, reputation lives in memory).
	 */
	let { successes = null, failures = null, class: className = '' } = $props();

	let s = $derived(Number.isFinite(Number(successes)) && successes !== null ? Number(successes) : null);
	let f = $derived(Number.isFinite(Number(failures)) && failures !== null ? Number(failures) : null);
	let known = $derived((s ?? 0) + (f ?? 0) > 0);
	let tone = $derived(
		(s ?? 0) > 0 && !(f ?? 0) ? 'text-emerald-400'
			: (f ?? 0) > 0 && !(s ?? 0) ? 'text-rose-400'
				: 'text-[var(--text-muted)]'
	);
</script>

{#if known}
	<span class="font-mono text-[10px] leading-4 px-1 rounded bg-[var(--surface-container-high)] flex-shrink-0 {tone} {className}"
		title="{s ?? 0} good, {f ?? 0} failed transfers with this peer">{s ?? 0}/{f ?? 0}</span>
{/if}
