<script>
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { Loader2 } from 'lucide-svelte';
	import Button from '../../components/ui/Button.svelte';
	import FormInput from '../../components/ui/FormInput.svelte';
	import { authStatus, currentUser, authReady, login, setupAdmin, loadStatus, safeNext, passwordProblem } from '$lib/auth.js';

	let username = $state('');
	let password = $state('');
	let confirm = $state('');
	let displayName = $state('');
	let error = $state('');
	let busy = $state(false);

	let needsSetup = $derived(!!$authStatus?.needs_setup);
	let target = $derived(safeNext($page.url.searchParams.get('next')));

	// Already signed in: skip the form.
	$effect(() => {
		if ($authReady && $currentUser) goto(target, { replaceState: true });
	});

	onMount(() => { if (!$authStatus) loadStatus(); });

	async function submit(e) {
		e.preventDefault();
		error = '';
		if (!username.trim() || !password) { error = 'Enter a username and password'; return; }
		if (needsSetup) {
			error = passwordProblem(password, confirm);
			if (error) return;
		}
		busy = true;
		try {
			if (needsSetup) await setupAdmin(username.trim(), password, displayName.trim());
			else await login(username.trim(), password);
			await goto(target, { replaceState: true });
		} catch (err) {
			error = err.message || 'Sign in failed';
			password = '';
		} finally {
			busy = false;
		}
	}
</script>

<svelte:head><title>{needsSetup ? 'Set up' : 'Sign in'} - Zonik</title></svelte:head>

<div class="min-h-full flex items-center justify-center px-4 py-10">
	<div class="w-full max-w-sm">
		<div class="text-center mb-8">
			<img src="/favicon.svg" alt="" class="w-12 h-12 rounded-xl mx-auto mb-4" />
			<h1 class="text-3xl font-bold tracking-editorial"><span class="bg-gradient-primary bg-clip-text text-transparent">Z</span><span class="text-[var(--text-primary)]">ONIK</span></h1>
			<p class="text-[10px] font-mono text-[var(--text-disabled)] uppercase tracking-wider mt-1">Music Backend</p>
		</div>

		{#if !$authStatus}
			<div class="flex justify-center py-8"><Loader2 class="w-5 h-5 text-[var(--text-disabled)] animate-spin" /></div>
		{:else}
			<form onsubmit={submit} class="bg-[var(--surface-container)] rounded-xl shadow-float p-5 space-y-4">
				<div>
					<h2 class="text-base font-semibold text-[var(--text-primary)]">{needsSetup ? 'Create the admin account' : 'Sign in'}</h2>
					{#if needsSetup}
						<p class="text-xs text-[var(--text-muted)] mt-1">No users exist yet. This account will manage the server.</p>
					{/if}
				</div>

				<div>
					<label for="login-user" class="block text-xs text-[var(--text-muted)] mb-1">Username</label>
					<FormInput id="login-user" bind:value={username} autocomplete="username" autocapitalize="none" spellcheck="false" autofocus />
				</div>
				{#if needsSetup}
					<div>
						<label for="login-name" class="block text-xs text-[var(--text-muted)] mb-1">Display name (optional)</label>
						<FormInput id="login-name" bind:value={displayName} autocomplete="name" />
					</div>
				{/if}
				<div>
					<label for="login-pass" class="block text-xs text-[var(--text-muted)] mb-1">Password</label>
					<FormInput id="login-pass" type="password" bind:value={password} autocomplete={needsSetup ? 'new-password' : 'current-password'} />
				</div>
				{#if needsSetup}
					<div>
						<label for="login-confirm" class="block text-xs text-[var(--text-muted)] mb-1">Confirm password</label>
						<FormInput id="login-confirm" type="password" bind:value={confirm} autocomplete="new-password" />
					</div>
				{/if}

				{#if error}
					<p class="text-sm text-red-400 bg-red-500/10 rounded-md px-3 py-2" role="alert">{error}</p>
				{/if}

				<Button type="submit" variant="primary" size="lg" class="w-full" loading={busy}>
					{needsSetup ? 'Create account' : 'Sign in'}
				</Button>
			</form>
			{#if !needsSetup}
				<p class="text-xs text-center text-[var(--text-disabled)] mt-4">Have an invite? Open the link you were sent.</p>
			{/if}
		{/if}
	</div>
</div>
