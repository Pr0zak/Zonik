<script>
	import { toasts } from '$lib/stores.js';

	const colors = {
		info: 'bg-blue-900/80 border-blue-700',
		success: 'bg-green-900/80 border-green-700',
		error: 'bg-red-900/80 border-red-700',
		warning: 'bg-yellow-900/80 border-yellow-700',
	};
</script>

<div class="fixed bottom-20 right-4 z-50 space-y-2">
	{#each $toasts as toast (toast.id)}
		<div class="px-4 py-2 rounded-lg border text-sm {colors[toast.type] || colors.info}
			animate-slide-in shadow-lg">
			{toast.message}
		</div>
	{/each}
</div>

<style>
	@keyframes slide-in {
		from { transform: translateX(100%); opacity: 0; }
		to { transform: translateX(0); opacity: 1; }
	}
	.animate-slide-in {
		animation: slide-in 0.2s ease-out;
	}
</style>
