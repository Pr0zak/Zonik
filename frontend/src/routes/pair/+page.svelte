<script>
	import { onMount } from 'svelte';
	import { addToast } from '$lib/stores.js';
	import { Tv, Check } from 'lucide-svelte';
	import Button from '../../components/ui/Button.svelte';
	import FormInput from '../../components/ui/FormInput.svelte';

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

	function pairAnother() {
		submitted = false;
		code = '';
		apiKey = '';
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
				<button onclick={pairAnother} class="text-sm text-[var(--color-primary)] hover:underline">
					Pair another device
				</button>
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
					<label for="pair-code" class="block text-xs text-[var(--text-muted)] mb-1">Pairing Code</label>
					<input
						id="pair-code"
						type="text"
						bind:value={code}
						maxlength="6"
						placeholder="000000"
						class="w-full bg-[var(--surface-lowest)] rounded-lg px-4 py-3 text-2xl font-mono text-center text-[var(--text-primary)] tracking-[0.3em]
							placeholder-[var(--text-disabled)] focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20"
						oninput={(e) => { code = e.target.value.replace(/\D/g, '').slice(0, 6); }} />
				</div>

				<div>
					<label for="pair-url" class="block text-xs text-[var(--text-muted)] mb-1">Server URL</label>
					<FormInput id="pair-url" type="text" bind:value={url} />
				</div>

				<div class="grid grid-cols-2 gap-3">
					<div>
						<label for="pair-user" class="block text-xs text-[var(--text-muted)] mb-1">Username</label>
						<FormInput id="pair-user" type="text" bind:value={username} />
					</div>
					<div>
						<label for="pair-key" class="block text-xs text-[var(--text-muted)] mb-1">API Key</label>
						<FormInput id="pair-key" type="text" bind:value={apiKey} placeholder="Subsonic API key" />
					</div>
				</div>

				<Button
					variant="primary"
					size="lg"
					class="w-full"
					loading={submitting}
					disabled={code.length !== 6}
					onclick={submit}>
					{submitting ? 'Pairing...' : 'Pair Device'}
				</Button>
			</div>
		{/if}
	</div>
</div>
