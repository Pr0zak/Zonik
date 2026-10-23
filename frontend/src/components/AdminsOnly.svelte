<script>
	import { ShieldAlert } from 'lucide-svelte';
</script>

<div class="flex items-center justify-center min-h-[50vh]">
	<div class="bg-[var(--surface-container)] rounded-xl p-8 max-w-sm w-full text-center">
		<div class="w-12 h-12 rounded-xl mx-auto mb-4 flex items-center justify-center"
			style="background: color-mix(in srgb, var(--color-warning) 14%, transparent); box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-warning) 28%, transparent);">
			<ShieldAlert class="w-6 h-6" style="color: var(--color-warning)" />
		</div>
		<h1 class="text-xl font-bold text-[var(--text-primary)] tracking-editorial">Admins only</h1>
		<p class="text-sm text-[var(--text-muted)] mt-2">This page is only available to administrators. Ask an admin if you need access.</p>
		<a href="/" class="inline-block mt-5 text-sm text-sky-400 hover:text-sky-300 font-medium">Back to dashboard</a>
	</div>
</div>
