<script>
	import { KeyRound } from 'lucide-svelte';
	import Button from './ui/Button.svelte';
	import FormInput from './ui/FormInput.svelte';
	import { authApi, loadMe, passwordProblem } from '$lib/auth.js';
	import { addToast } from '$lib/stores.js';

	// Blocking: no close button, no backdrop dismiss, no Escape. Shown while must_change_password.
	let current = $state('admin');
	let next = $state('');
	let confirm = $state('');
	let error = $state('');
	let saving = $state(false);

	async function submit(e) {
		e?.preventDefault();
		error = passwordProblem(next, confirm);
		if (error) return;
		saving = true;
		try {
			await authApi.changePassword(current, next);
			await loadMe();
			addToast('Password changed', 'success');
		} catch (err) {
			error = err.message || 'Could not change password';
		} finally {
			saving = false;
		}
	}
</script>

<div class="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/80" role="dialog" aria-modal="true" aria-labelledby="pw-title">
	<form onsubmit={submit} class="bg-[var(--surface-container)] rounded-xl shadow-float max-w-md w-full max-h-[90vh] overflow-y-auto p-5 space-y-4 animate-slide-up">
		<div class="flex items-center gap-3">
			<div class="w-9 h-9 rounded-lg flex items-center justify-center" style="background: color-mix(in srgb, var(--color-warning) 15%, transparent)">
				<KeyRound class="w-4 h-4" style="color: var(--color-warning)" />
			</div>
			<div>
				<h2 id="pw-title" class="text-lg font-semibold text-[var(--text-primary)] tracking-editorial">Choose a new password</h2>
				<p class="text-xs text-[var(--text-muted)]">Your account still uses the default password. Set a new one to continue.</p>
			</div>
		</div>
		<div class="space-y-3">
			<div>
				<label for="pw-new" class="block text-xs text-[var(--text-muted)] mb-1">New password</label>
				<FormInput id="pw-new" type="password" autocomplete="new-password" bind:value={next} error={!!error} />
			</div>
			<div>
				<label for="pw-confirm" class="block text-xs text-[var(--text-muted)] mb-1">Confirm new password</label>
				<FormInput id="pw-confirm" type="password" autocomplete="new-password" bind:value={confirm} error={!!error} />
			</div>
			{#if error}<p class="text-xs text-red-400" role="alert">{error}</p>{/if}
		</div>
		<Button type="submit" variant="primary" class="w-full" loading={saving}>Change password</Button>
	</form>
</div>
