<script>
	import { formatBadgeClass } from '$lib/colors.js';

	let {
		format = '',
		class: className = '',
	} = $props();
</script>

<span class="text-xs font-mono font-semibold uppercase px-1.5 py-0.5 rounded border {formatBadgeClass(format)} {className}">
	{format?.toUpperCase() || '?'}
</span>
