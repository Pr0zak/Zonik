<script>
	/**
	 * 28 px group header inside a downloads list: dot · name · count · reason clause,
	 * with an optional action on the right.
	 *
	 * dot: a stage colour ('sky' | 'amber' | 'indigo' | 'muted' | 'emerald' | 'rose'),
	 *      a Tailwind `bg-*` class, or any CSS colour.
	 */
	let {
		dot = 'muted',
		name = '',
		count = null,
		reason = '',
		pulse = false,
		action = null,
		class: className = '',
	} = $props();

	const DOT = {
		sky: 'bg-sky-400', amber: 'bg-amber-400', indigo: 'bg-indigo-400',
		muted: 'bg-[var(--text-disabled)]', emerald: 'bg-emerald-400', rose: 'bg-rose-400',
	};
	let dotClass = $derived(DOT[dot] || (typeof dot === 'string' && dot.startsWith('bg-') ? dot : ''));
	let dotStyle = $derived(dotClass ? '' : `background: ${dot}`);
</script>

<div class="flex items-center gap-2 min-h-7 md:h-7 px-3 mt-1.5 text-[11px] leading-4 font-semibold text-[var(--text-secondary)] md:whitespace-nowrap max-md:flex-wrap max-md:py-1 max-md:gap-y-0 overflow-hidden {className}">
	<span class="w-2 h-2 rounded-full flex-shrink-0 {dotClass} {pulse ? 'animate-pulse' : ''}" style={dotStyle}></span>
	<span>{name}</span>
	{#if count != null}<span class="font-mono font-medium text-[var(--text-muted)]">{Number(count).toLocaleString()}</span>{/if}
	{#if reason}<span class="font-normal text-[var(--text-muted)] min-w-0 md:truncate">· {reason}</span>{/if}
	{#if action}<span class="ml-auto flex-shrink-0 font-normal">{@render action()}</span>{/if}
</div>
