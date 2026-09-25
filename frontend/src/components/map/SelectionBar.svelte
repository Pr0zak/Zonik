<script>
	// The action every Music Map view ends in: save the chosen tracks as a
	// playlist (which the phone, watch and TV apps pick up over Subsonic),
	// or play them here.
	import { api } from '$lib/api.js';
	import { addToast, playTrack as storePlayTrack } from '$lib/stores.js';
	import Button from '../ui/Button.svelte';
	import { ListPlus, Play, X, Check } from 'lucide-svelte';

	let {
		tracks = [], // [{ id, title, artist, album_id }]
		name = 'Music Map selection', // suggested playlist name
		onclear = null,
		children = null, // extra controls, rendered before the actions
	} = $props();

	let naming = $state(false);
	let draft = $state('');
	let saving = $state(false);
	let saved = $state(null); // { id, name } of the last playlist made from this selection
	let input = $state();

	// A new selection invalidates the "saved" tick.
	$effect(() => { tracks; saved = null; });

	const sample = $derived(tracks.slice(0, 3).map((t) => t.title).filter(Boolean).join(' · '));

	async function startNaming() {
		draft = name;
		naming = true;
		await Promise.resolve();
		input?.select();
	}

	async function save() {
		const n = draft.trim();
		if (!n || !tracks.length) return;
		saving = true;
		try {
			const r = await api.createPlaylist({ name: n, track_ids: tracks.map((t) => t.id) });
			saved = r;
			naming = false;
			addToast(`Saved “${n}” · ${tracks.length} tracks — it's on your phone now`, 'success');
		} catch (e) {
			addToast(`Couldn't save playlist: ${e.message}`, 'error');
		} finally {
			saving = false;
		}
	}

	function play() {
		if (!tracks.length) return;
		const q = tracks.map((t) => ({ id: t.id, title: t.title, artist: t.artist, album_id: t.album_id }));
		storePlayTrack(q[0], q);
	}
</script>

{#if tracks.length}
	<div class="flex flex-wrap items-center gap-2 rounded-lg border border-[#22d3ee]/30 bg-[#22d3ee]/5 px-3 py-2">
		<div class="min-w-0 flex-1">
			<p class="text-sm text-[var(--text-primary)]"><span class="font-medium">{tracks.length.toLocaleString()}</span> tracks selected</p>
			{#if sample}<p class="text-xs text-[var(--text-muted)] truncate">{sample}{tracks.length > 3 ? ' …' : ''}</p>{/if}
		</div>
		{#if children}{@render children()}{/if}
		{#if naming}
			<form class="flex items-center gap-1.5" onsubmit={(e) => { e.preventDefault(); save(); }}>
				<input bind:this={input} bind:value={draft} aria-label="Playlist name"
					onkeydown={(e) => e.key === 'Escape' && (naming = false)}
					class="w-56 px-2.5 py-1 text-sm rounded-md bg-[var(--surface-lowest)] text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[#22d3ee]/30" />
				<Button type="submit" variant="primary" size="sm" loading={saving}>Save</Button>
				<Button variant="ghost" size="sm" onclick={() => (naming = false)}>Cancel</Button>
			</form>
		{:else if saved}
			<a href="/playlists" class="inline-flex items-center gap-1 text-xs text-emerald-400 hover:underline whitespace-nowrap"><Check class="w-3.5 h-3.5" /> Saved as “{saved.name}”</a>
		{:else}
			<Button variant="primary" size="sm" onclick={startNaming} class="whitespace-nowrap"><ListPlus class="w-3.5 h-3.5" /> Save as playlist</Button>
		{/if}
		<Button variant="secondary" size="sm" onclick={play} title="Play in this browser" class="whitespace-nowrap"><Play class="w-3.5 h-3.5" /> Play here</Button>
		{#if onclear}<Button variant="icon" size="sm" onclick={onclear} title="Clear selection" aria-label="Clear selection"><X class="w-3.5 h-3.5" /></Button>{/if}
	</div>
{/if}
