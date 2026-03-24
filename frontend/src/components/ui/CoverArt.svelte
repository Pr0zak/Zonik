<script>
	import { Music } from 'lucide-svelte';
	import { coverUrl } from '$lib/utils.js';

	let {
		id = null,
		size = 'md',
		rounded = true,
		class: className = '',
	} = $props();

	const sizes = {
		xs: { box: 'w-8 h-8', icon: 'w-3 h-3', px: 32 },
		sm: { box: 'w-9 h-9', icon: 'w-3.5 h-3.5', px: 36 },
		md: { box: 'w-10 h-10', icon: 'w-4 h-4', px: 40 },
		lg: { box: 'w-12 h-12', icon: 'w-6 h-6', px: 56 },
	};

	let s = $derived(typeof size === 'string' ? sizes[size] || sizes.md : null);
	let src = $derived(coverUrl(id, s?.px));
</script>

<div class="{s?.box || ''} {rounded ? 'rounded-lg' : ''} bg-[var(--surface-container)] overflow-hidden flex-shrink-0 {className}">
	{#if src}
		<img {src} alt="" class="w-full h-full object-cover" loading="lazy"
			onerror={(e) => { e.target.style.display = 'none'; e.target.nextElementSibling.style.display = 'flex'; }} />
		<div class="hidden items-center justify-center w-full h-full">
			<Music class="{s?.icon || 'w-4 h-4'} text-[var(--text-disabled)]" />
		</div>
	{:else}
		<div class="flex items-center justify-center w-full h-full">
			<Music class="{s?.icon || 'w-4 h-4'} text-[var(--text-disabled)]" />
		</div>
	{/if}
</div>
