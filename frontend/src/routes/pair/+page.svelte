<script>
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/stores';
	import { Tv, Check, TriangleAlert, Loader } from 'lucide-svelte';
	import Button from '../../components/ui/Button.svelte';
	import { currentUser, displayName } from '$lib/auth.js';
	import { normalizeCode, isCompleteCode, secondsLeft, formatCountdown, deviceTitle } from '$lib/pair.js';

	let code = $state('');
	let info = $state(null); // { status, label, platform, created_at, expires }
	let looking = $state(false);
	let lookupError = $state('');
	let approving = $state(false);
	let approveError = $state('');
	let done = $state(null); // { device }
	let left = $state(0);
	let timer;
	let lookupSeq = 0;

	let name = $derived(displayName($currentUser) || 'your account');
	let pending = $derived(info?.status === 'pending' && left > 0);

	async function lookup(c) {
		const seq = ++lookupSeq;
		looking = true;
		lookupError = '';
		approveError = '';
		info = null;
		try {
			const res = await fetch(`/api/pair/${c}/info`, { credentials: 'same-origin' });
			if (seq !== lookupSeq) return;
			if (res.status === 429) {
				lookupError = 'Too many attempts. Wait a minute and try again.';
				return;
			}
			if (!res.ok) throw new Error();
			const data = await res.json();
			if (seq !== lookupSeq) return;
			info = data;
			left = secondsLeft(data.expires);
		} catch {
			if (seq === lookupSeq) lookupError = 'Could not reach the server. Try again.';
		} finally {
			if (seq === lookupSeq) looking = false;
		}
	}

	function onInput(e) {
		const next = normalizeCode(e.target.value);
		e.target.value = next;
		if (next === code) return;
		code = next;
		info = null;
		lookupError = '';
		approveError = '';
		lookupSeq++;
		looking = false;
		if (isCompleteCode(next)) lookup(next);
	}

	async function approve() {
		if (!pending || approving) return;
		approving = true;
		approveError = '';
		try {
			const res = await fetch(`/api/pair/${code}/approve`, {
				method: 'POST',
				credentials: 'same-origin',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({}),
			});
			const data = await res.json().catch(() => ({}));
			if (res.status === 409) {
				approveError = 'This code has already been used.';
				info = { ...info, status: 'expired' };
			} else if (res.status === 404) {
				approveError = 'This code has expired. Ask the TV for a new one.';
				info = { ...info, status: 'expired' };
			} else if (res.status === 401) {
				approveError = 'Your session ended. Sign in again to continue.';
			} else if (!res.ok) {
				approveError = data.detail || 'Pairing failed. Try again.';
			} else {
				done = data.device || {};
			}
		} catch {
			approveError = 'Could not reach the server. Try again.';
		} finally {
			approving = false;
		}
	}

	function reset() {
		done = null;
		code = '';
		info = null;
		approveError = '';
		lookupError = '';
	}

	onMount(() => {
		timer = setInterval(() => {
			if (info?.status === 'pending') left = secondsLeft(info.expires);
		}, 1000);
		const c = normalizeCode($page.url.searchParams.get('code'));
		if (c) {
			code = c;
			if (isCompleteCode(c)) lookup(c);
		}
	});
	onDestroy(() => clearInterval(timer));
</script>

<div class="flex items-center justify-center min-h-[70vh] px-1">
	<div class="w-full max-w-sm text-center">
		{#if done}
			<div class="space-y-4">
				<div class="w-20 h-20 rounded-full bg-emerald-500/15 flex items-center justify-center mx-auto">
					<Check class="w-10 h-10 text-emerald-400" />
				</div>
				<h1 class="text-2xl font-bold text-[var(--text-primary)] tracking-editorial">Done</h1>
				<p class="text-base text-[var(--text-muted)]">
					{done.label || deviceTitle(info)} is signing in as <span class="text-[var(--text-primary)]">{name}</span>.
					You can close this page.
				</p>
				<button onclick={reset} class="text-sm text-[var(--color-primary)] hover:underline py-2">
					Pair another device
				</button>
			</div>
		{:else}
			<div class="mb-6">
				<div class="w-16 h-16 rounded-full bg-[var(--surface-container-high)] flex items-center justify-center mx-auto mb-4">
					<Tv class="w-8 h-8 text-[var(--color-primary)]" />
				</div>
				<h1 class="text-2xl font-bold text-[var(--text-primary)] tracking-editorial">Pair a TV</h1>
				<p class="text-sm text-[var(--text-muted)] mt-1">Enter the 6-digit code shown on your TV</p>
			</div>

			<div class="space-y-5">
				<input
					id="pair-code"
					aria-label="Pairing code"
					type="text"
					inputmode="numeric"
					pattern="[0-9]*"
					autocomplete="one-time-code"
					maxlength="7"
					value={code}
					placeholder="000000"
					oninput={onInput}
					class="w-full bg-[var(--surface-lowest)] rounded-xl px-4 py-4 text-3xl font-mono text-center text-[var(--text-primary)] tracking-[0.3em]
						placeholder-[var(--text-disabled)] focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/30" />

				{#if looking}
					<p class="flex items-center justify-center gap-2 text-sm text-[var(--text-muted)]">
						<Loader class="w-4 h-4 animate-spin" /> Looking up code...
					</p>
				{:else if lookupError}
					<p class="flex items-center justify-center gap-2 text-sm text-red-400" role="alert">
						<TriangleAlert class="w-4 h-4 shrink-0" /> {lookupError}
					</p>
				{:else if info && info.status !== 'pending' || (info && left <= 0)}
					<p class="flex items-center justify-center gap-2 text-sm text-red-400" role="alert">
						<TriangleAlert class="w-4 h-4 shrink-0" /> This code has expired or is not valid. Ask the TV for a new one.
					</p>
				{:else if pending}
					<div class="rounded-xl bg-[var(--surface-container)] px-4 py-4 space-y-1">
						<p class="text-lg font-semibold text-[var(--text-primary)] break-words">{deviceTitle(info)} wants to connect</p>
						<p class="text-sm text-[var(--text-muted)]">
							Code expires in <span class="font-mono tabular-nums">{formatCountdown(left)}</span>
						</p>
					</div>
					<Button variant="primary" size="lg" class="w-full" loading={approving} onclick={approve}>
						{approving ? 'Pairing...' : `Pair as ${name}`}
					</Button>
				{/if}

				{#if approveError}
					<p class="flex items-center justify-center gap-2 text-sm text-red-400" role="alert">
						<TriangleAlert class="w-4 h-4 shrink-0" /> {approveError}
					</p>
				{/if}
			</div>
		{/if}
	</div>
</div>
