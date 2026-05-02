<script>
	import { X } from 'lucide-svelte';

	let {
		open = $bindable(true),
		title = '',
		maxWidth = 'max-w-2xl',
		onclose = null,
		children,
		footer,
	} = $props();

	function close() {
		open = false;
		onclose?.();
	}

	function handleBackdrop(e) {
		if (e.target === e.currentTarget) close();
	}

	function handleKeydown(e) {
		if (e.key === 'Escape' && open) close();
	}
</script>

<svelte:window onkeydown={handleKeydown} />

{#if open}
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60"
		onclick={handleBackdrop}
	>
		<div class="bg-[var(--surface-container)] rounded-xl shadow-float {maxWidth} w-full max-h-[85vh] flex flex-col animate-slide-up">
			<div class="flex items-center justify-between p-4">
				<h2 class="text-lg font-semibold text-[var(--text-primary)] tracking-editorial">{title}</h2>
				<button
					class="w-8 h-8 flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-container-high)] rounded-md transition-colors"
					onclick={close}
				>
					<X class="w-4 h-4" />
				</button>
			</div>

			<div class="flex-1 overflow-y-auto p-4">
				{@render children()}
			</div>

			{#if footer}
				<div class="p-4">
					{@render footer()}
				</div>
			{/if}
		</div>
	</div>
{/if}
