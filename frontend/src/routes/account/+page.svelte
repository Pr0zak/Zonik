<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { UserRound, KeyRound, MonitorSmartphone, Tv, LogOut } from 'lucide-svelte';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Button from '../../components/ui/Button.svelte';
	import Badge from '../../components/ui/Badge.svelte';
	import FormInput from '../../components/ui/FormInput.svelte';
	import { currentUser, authApi, loadMe, logout, passwordProblem, displayName as nameOf } from '$lib/auth.js';
	import { addToast } from '$lib/stores.js';
	import { formatDateTime, formatRelativeTime } from '$lib/utils.js';

	let displayName = $state('');
	let savingName = $state(false);
	let curPw = $state('');
	let newPw = $state('');
	let confirmPw = $state('');
	let pwError = $state('');
	let savingPw = $state(false);
	let devices = $state([]);
	let devicesLoading = $state(true);

	$effect(() => { displayName = $currentUser?.display_name || ''; });

	async function loadDevices() {
		try { devices = await authApi.getDevices(); }
		catch (e) { addToast(e.message || 'Failed to load sessions', 'error'); }
		finally { devicesLoading = false; }
	}
	onMount(loadDevices);

	async function saveName() {
		savingName = true;
		try {
			await authApi.updateMe(displayName.trim());
			await loadMe();
			addToast('Profile updated', 'success');
		} catch (e) {
			addToast(e.message || 'Failed to save', 'error');
		} finally { savingName = false; }
	}

	async function savePassword(e) {
		e.preventDefault();
		pwError = '';
		if (!curPw) { pwError = 'Enter your current password'; return; }
		pwError = passwordProblem(newPw, confirmPw);
		if (pwError) return;
		savingPw = true;
		try {
			await authApi.changePassword(curPw, newPw);
			curPw = newPw = confirmPw = '';
			addToast('Password changed. Other sessions were signed out.', 'success');
			await Promise.all([loadMe(), loadDevices()]);
		} catch (err) {
			pwError = err.message || 'Could not change password';
		} finally { savingPw = false; }
	}

	async function revoke(d) {
		const msg = d.current ? 'Revoke this session? You will be signed out.' : `Revoke "${d.label || d.kind}"?`;
		if (!confirm(msg)) return;
		try {
			await authApi.revokeDevice(d.id);
			if (d.current) {
				await logout();
				goto('/login');
				return;
			}
			addToast('Revoked', 'success');
			await loadDevices();
		} catch (e) {
			addToast(e.message || 'Failed to revoke', 'error');
		}
	}

	async function signOut() {
		await logout();
		goto('/login');
	}

	const th = 'text-left text-[10px] font-semibold uppercase tracking-widest text-[var(--text-muted)] px-3 py-2 whitespace-nowrap';
	const td = 'px-3 py-2 text-sm text-[var(--text-secondary)] whitespace-nowrap';
</script>

<div class="max-w-3xl mx-auto space-y-6">
	<PageHeader title="Account" subtitle={$currentUser ? `${nameOf($currentUser)} · ${$currentUser.role}` : ''} icon={UserRound} color="var(--color-playlists)">
		{#snippet actions()}
			<Button variant="secondary" size="sm" onclick={signOut}><LogOut class="w-3.5 h-3.5" />Log out</Button>
		{/snippet}
	</PageHeader>

	<Card padding="p-4">
		<h2 class="text-base font-semibold text-[var(--text-primary)] mb-3">Profile</h2>
		<div class="grid grid-cols-1 sm:grid-cols-2 gap-3 items-end">
			<div>
				<label for="acc-user" class="block text-xs text-[var(--text-muted)] mb-1">Username</label>
				<FormInput id="acc-user" value={$currentUser?.username || ''} disabled />
			</div>
			<div>
				<label for="acc-name" class="block text-xs text-[var(--text-muted)] mb-1">Display name</label>
				<FormInput id="acc-name" bind:value={displayName} placeholder={$currentUser?.username || ''} />
			</div>
		</div>
		<div class="mt-3 flex justify-end">
			<Button variant="primary" size="sm" loading={savingName} onclick={saveName}>Save</Button>
		</div>
	</Card>

	<Card padding="p-4">
		<div class="flex items-center gap-2 mb-3">
			<KeyRound class="w-4 h-4 text-[var(--text-muted)]" />
			<h2 class="text-base font-semibold text-[var(--text-primary)]">Change password</h2>
		</div>
		<form onsubmit={savePassword} class="space-y-3">
			<div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
				<div>
					<label for="acc-cur" class="block text-xs text-[var(--text-muted)] mb-1">Current password</label>
					<FormInput id="acc-cur" type="password" autocomplete="current-password" bind:value={curPw} />
				</div>
				<div>
					<label for="acc-new" class="block text-xs text-[var(--text-muted)] mb-1">New password</label>
					<FormInput id="acc-new" type="password" autocomplete="new-password" bind:value={newPw} />
				</div>
				<div>
					<label for="acc-conf" class="block text-xs text-[var(--text-muted)] mb-1">Confirm</label>
					<FormInput id="acc-conf" type="password" autocomplete="new-password" bind:value={confirmPw} />
				</div>
			</div>
			{#if pwError}<p class="text-xs text-red-400" role="alert">{pwError}</p>{/if}
			<div class="flex justify-end">
				<Button type="submit" variant="primary" size="sm" loading={savingPw}>Change password</Button>
			</div>
		</form>
	</Card>

	<Card padding="p-4">
		<div class="flex items-center gap-2 mb-3">
			<MonitorSmartphone class="w-4 h-4 text-[var(--text-muted)]" />
			<h2 class="text-base font-semibold text-[var(--text-primary)]">Devices & sessions</h2>
		</div>
		{#if devicesLoading}
			<p class="text-sm text-[var(--text-muted)]">Loading...</p>
		{:else if !devices.length}
			<p class="text-sm text-[var(--text-muted)]">No active sessions.</p>
		{:else}
			<table class="w-full">
				<thead>
					<tr>
						<th class={th}>Device</th>
						<th class={th}>Type</th>
						<th class={th}>IP</th>
						<th class={th}>Signed in</th>
						<th class={th}>Last seen</th>
						<th class={th}></th>
					</tr>
				</thead>
				<tbody>
					{#each devices as d (d.kind + d.id)}
						<tr class="border-t border-white/[0.04]">
							<td class="{td} max-w-[16rem] truncate">
								<span class="text-[var(--text-primary)]">{d.label || 'Unknown'}</span>
								{#if d.current}<Badge variant="success" size="sm" class="ml-2">This session</Badge>{/if}
							</td>
							<td class={td}><span class="inline-flex items-center gap-1.5">{#if d.platform === 'tv'}<Tv class="w-3.5 h-3.5" />{/if}{d.kind === 'session' ? 'Browser' : (d.platform === 'tv' ? 'TV' : (d.platform || 'device'))}</span></td>
							<td class="{td} font-mono text-xs">{d.ip || '-'}</td>
							<td class={td}>{d.created_at ? formatDateTime(d.created_at) : '-'}</td>
							<td class={td}>{d.last_seen_at ? formatRelativeTime(d.last_seen_at) : '-'}</td>
							<td class="{td} text-right">
								<Button variant="danger" size="sm" onclick={() => revoke(d)}>Revoke</Button>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		{/if}
	</Card>
</div>
