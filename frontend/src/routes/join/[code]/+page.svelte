<script>
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { Loader2 } from 'lucide-svelte';
	import Button from '../../../components/ui/Button.svelte';
	import FormInput from '../../../components/ui/FormInput.svelte';
	import { getInvite, joinWithInvite, loadStatus, passwordProblem } from '$lib/auth.js';
	import { usernameProblem } from '$lib/invites.js';

	let code = $derived($page.params.code);
	let invite = $state(null);
	let loading = $state(true);
	let invalid = $state('');
	let username = $state('');
	let displayName = $state('');
	let password = $state('');
	let confirm = $state('');
	let error = $state('');
	let busy = $state(false);

	onMount(async () => {
		try {
			invite = await getInvite(code);
		} catch (e) {
			invalid = e.status === 404 || !e.status ? (e.message || 'This invite link is invalid or has expired') : e.message;
		} finally {
			loading = false;
		}
	});

	async function submit(e) {
		e.preventDefault();
		error = usernameProblem(username) || passwordProblem(password, confirm);
		if (error) return;
		busy = true;
		try {
			await joinWithInvite({ code, username: username.trim(), display_name: displayName.trim(), password });
			await loadStatus();
			await goto('/', { replaceState: true });
		} catch (err) {
			error = err.message || 'Could not create the account';
			if (err.status === 404) { invalid = err.message; invite = null; }
			password = '';
			confirm = '';
		} finally {
			busy = false;
		}
	}
</script>

<svelte:head><title>Join - Zonik</title></svelte:head>

<div class="min-h-full flex items-center justify-center px-4 py-10">
	<div class="w-full max-w-sm">
		<div class="text-center mb-8">
			<img src="/favicon.svg" alt="" class="w-12 h-12 rounded-xl mx-auto mb-4" />
			<h1 class="text-3xl font-bold tracking-editorial"><span class="bg-gradient-primary bg-clip-text text-transparent">Z</span><span class="text-[var(--text-primary)]">ONIK</span></h1>
			<p class="text-[10px] font-mono text-[var(--text-disabled)] uppercase tracking-wider mt-1">Music Backend</p>
		</div>

		{#if loading}
			<div class="flex justify-center py-8"><Loader2 class="w-5 h-5 text-[var(--text-disabled)] animate-spin" /></div>
		{:else if invalid || !invite}
			<div class="bg-[var(--surface-container)] rounded-xl shadow-float p-5 space-y-3 text-center">
				<h2 class="text-base font-semibold text-[var(--text-primary)]">Invite not valid</h2>
				<p class="text-sm text-[var(--text-muted)]">{invalid || 'This invite link is invalid or has expired'}</p>
				<p class="text-xs text-[var(--text-disabled)]">Ask whoever invited you for a new link.</p>
				<a href="/login" class="inline-block text-sm text-[var(--accent,#a78bfa)] hover:underline">Go to sign in</a>
			</div>
		{:else}
			<form onsubmit={submit} class="bg-[var(--surface-container)] rounded-xl shadow-float p-5 space-y-4">
				<div>
					<h2 class="text-base font-semibold text-[var(--text-primary)]">You're invited to Zonik</h2>
					<p class="text-xs text-[var(--text-muted)] mt-1">
						{#if invite.invited_by}Invited by {invite.invited_by.username ?? invite.invited_by}. {/if}{#if invite.role === 'admin'}You'll join as an administrator. {/if}Choose how you'll sign in.
					</p>
				</div>
				<div>
					<label for="join-user" class="block text-xs text-[var(--text-muted)] mb-1">Username</label>
					<FormInput id="join-user" bind:value={username} autocomplete="username" autocapitalize="none" spellcheck="false" />
				</div>
				<div>
					<label for="join-name" class="block text-xs text-[var(--text-muted)] mb-1">Display name (optional)</label>
					<FormInput id="join-name" bind:value={displayName} autocomplete="name" />
				</div>
				<div>
					<label for="join-pass" class="block text-xs text-[var(--text-muted)] mb-1">Password</label>
					<FormInput id="join-pass" type="password" bind:value={password} autocomplete="new-password" />
				</div>
				<div>
					<label for="join-confirm" class="block text-xs text-[var(--text-muted)] mb-1">Confirm password</label>
					<FormInput id="join-confirm" type="password" bind:value={confirm} autocomplete="new-password" />
				</div>

				{#if error}
					<p class="text-sm text-red-400 bg-red-500/10 rounded-md px-3 py-2" role="alert">{error}</p>
				{/if}

				<Button type="submit" variant="primary" size="lg" class="w-full" loading={busy}>Create account</Button>
			</form>
		{/if}
	</div>
</div>
