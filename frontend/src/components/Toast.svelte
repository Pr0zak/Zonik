<script>
	import { toasts } from '$lib/stores.js';
	import { CheckCircle, AlertCircle, Info, AlertTriangle } from 'lucide-svelte';

	const styles = {
		info: { bg: 'bg-blue-500/10 border-blue-500/30', icon: Info, color: 'text-blue-400' },
		success: { bg: 'bg-emerald-500/10 border-emerald-500/30', icon: CheckCircle, color: 'text-emerald-400' },
		error: { bg: 'bg-red-500/10 border-red-500/30', icon: AlertCircle, color: 'text-red-400' },
		warning: { bg: 'bg-amber-500/10 border-amber-500/30', icon: AlertTriangle, color: 'text-amber-400' },
	};
</script>

<div class="fixed bottom-20 right-4 z-50 space-y-2">
	{#each $toasts as toast (toast.id)}
		{@const s = styles[toast.type] || styles.info}
		{@const Icon = s.icon}
		<div class="flex items-center gap-2.5 px-4 py-2.5 rounded-lg border text-sm shadow-lg backdrop-blur-sm animate-slide-in {s.bg}">
			<Icon class="w-4 h-4 shrink-0 {s.color}" />
			<span class="text-[var(--text-body)]">{toast.message}</span>
		</div>
	{/each}
</div>
