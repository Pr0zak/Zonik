<script>
	import { onMount } from 'svelte';
	import { addToast } from '$lib/stores.js';
	import { Tv, Check, Loader2 } from 'lucide-svelte';

	let code = $state('');
	let url = $state('');
	let username = $state('admin');
	let apiKey = $state('');
	let submitting = $state(false);
	let submitted = $state(false);

	onMount(() => {
		url = window.location.origin;
	});

	async function submit() {
		if (!code.trim() || code.trim().length !== 6) {
			addToast('Enter a 6-digit pairing code', 'error');
			return;
		}
		if (!apiKey.trim()) {
			addToast('API key is required', 'error');
			return;
		}
		submitting = true;
		try {
			const res = await fetch(`/api/pair/${code.trim()}/submit`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ url, username, api_key: apiKey }),
			});
			if (!res.ok) {
				const data = await res.json().catch(() => ({}));
				throw new Error(data.detail || 'Failed');
			}
			submitted = true;
			addToast('Device paired successfully', 'success');
		} catch (e) {
			addToast(e.message || 'Pairing failed — code may be expired', 'error');
		} finally {
			submitting = false;
		}
	}
</script>

<div class="flex items-center justify-center min-h-[70vh]">
	<div class="w-full max-w-sm">
		{#if submitted}
			<div class="text-center space-y-4">
				<div class="w-16 h-16 rounded-full bg-emerald-500/15 flex items-center justify-center mx-auto">
					<Check class="w-8 h-8 text-emerald-400" />
				</div>
				<h1 class="text-xl font-bold text-[var(--text-primary)] tracking-editorial">Paired</h1>
				<p class="text-sm text-[var(--text-muted)]">Your device should connect automatically. You can close this page.</p>
				<button onclick={() => { submitted = false; code = ''; apiKey = ''; }}
					class="text-sm text-[var(--color-primary)] hover:underline">Pair another device</button>
			</div>
		{:else}
			<div class="text-center mb-6">
				<div class="w-12 h-12 rounded-full bg-[var(--surface-container-high)] flex items-center justify-center mx-auto mb-3">
					<Tv class="w-6 h-6 text-[var(--color-primary)]" />
				</div>
				<h1 class="text-xl font-bold text-[var(--text-primary)] tracking-editorial">Pair Device</h1>
				<p class="text-sm text-[var(--text-muted)] mt-1">Enter the code shown on your TV or device</p>
			</div>

			<div class="space-y-4">
				<div>
					<label class="block text-xs text-[var(--text-muted)] mb-1">Pairing Code</label>
					<input type="text" bind:value={code} maxlength="6" placeholder="000000"
						class="w-full bg-[var(--surface-lowest)] ghost-border rounded-lg px-4 py-3 text-2xl font-mono text-center text-[var(--text-primary)] tracking-[0.3em]
							placeholder-[var(--text-disabled)] focus:outline-none focus:border-[var(--border-focus)] focus:ring-1 focus:ring-[var(--color-primary)]/15"
						oninput={(e) => { code = e.target.value.replace(/\D/g, '').slice(0, 6); }} />
				</div>

				<div>
					<label class="block text-xs text-[var(--text-muted)] mb-1">Server URL</label>
					<input type="text" bind:value={url}
						class="w-full bg-[var(--surface-lowest)] ghost-border rounded-lg px-3 py-2 text-sm text-[var(--text-primary)]
							focus:outline-none focus:border-[var(--border-focus)] focus:ring-1 focus:ring-[var(--color-primary)]/15" />
				</div>

				<div class="grid grid-cols-2 gap-3">
					<div>
						<label class="block text-xs text-[var(--text-muted)] mb-1">Username</label>
						<input type="text" bind:value={username}
							class="w-full bg-[var(--surface-lowest)] ghost-border rounded-lg px-3 py-2 text-sm text-[var(--text-primary)]
								focus:outline-none focus:border-[var(--border-focus)] focus:ring-1 focus:ring-[var(--color-primary)]/15" />
					</div>
					<div>
						<label class="block text-xs text-[var(--text-muted)] mb-1">API Key</label>
						<input type="text" bind:value={apiKey} placeholder="Subsonic API key"
							class="w-full bg-[var(--surface-lowest)] ghost-border rounded-lg px-3 py-2 text-sm text-[var(--text-primary)]
								placeholder-[var(--text-disabled)] focus:outline-none focus:border-[var(--border-focus)] focus:ring-1 focus:ring-[var(--color-primary)]/15" />
					</div>
				</div>

				<button onclick={submit} disabled={submitting || code.length !== 6}
					class="w-full bg-gradient-primary text-[var(--color-on-primary)] rounded-lg py-2.5 text-sm font-medium shadow-glow
						hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2">
					{#if submitting}
						<Loader2 class="w-4 h-4 animate-spin" />
						Pairing...
					{:else}
						Pair Device
					{/if}
				</button>
			</div>
		{/if}
	</div>
</div>
