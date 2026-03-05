<script>
	import { X } from 'lucide-svelte';

	let {
		open = $bindable(false),
		title = '',
		maxWidth = 'max-w-2xl',
		children,
		footer,
	} = $props();

	function handleBackdrop(e) {
		if (e.target === e.currentTarget) open = false;
	}

	function handleKeydown(e) {
		if (e.key === 'Escape') open = false;
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
		<div class="bg-gradient-to-br from-[var(--bg-tertiary)] to-[var(--bg-secondary)] border border-[var(--border-interactive)] rounded-lg shadow-2xl {maxWidth} w-full max-h-[85vh] flex flex-col animate-slide-up">
			<div class="flex items-center justify-between p-4 border-b border-[var(--border-subtle)]">
				<h2 class="text-lg font-semibold text-[var(--text-primary)]">{title}</h2>
				<button
					class="w-8 h-8 flex items-center justify-center text-[var(--text-muted)] hover:text-white hover:bg-[var(--bg-hover)] rounded-md transition-colors"
					onclick={() => open = false}
				>
					<X class="w-4 h-4" />
				</button>
			</div>

			<div class="flex-1 overflow-y-auto p-4">
				{@render children()}
			</div>

			{#if footer}
				<div class="p-4 border-t border-[var(--border-subtle)]">
					{@render footer()}
				</div>
			{/if}
		</div>
	</div>
{/if}
