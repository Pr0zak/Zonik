<script>
	import { onMount, onDestroy } from 'svelte';
	import { Tv, Check, AlertTriangle, Loader2 } from 'lucide-svelte';
	import PageHeader from '../../components/ui/PageHeader.svelte';
	import Card from '../../components/ui/Card.svelte';
	import Toggle from '../../components/ui/Toggle.svelte';
	import FilterPills from '../../components/ui/FilterPills.svelte';
	import Button from '../../components/ui/Button.svelte';
	import Modal from '../../components/ui/Modal.svelte';
	import Skeleton from '../../components/ui/Skeleton.svelte';
	import { api } from '$lib/api.js';
	import { inputClass } from '$lib/utils.js';
	import { loadTvShaders, TvPreviewEngine } from '$lib/tvPreview.js';

	const COLOR = 'var(--color-visualizer)';

	let shaders = $state(null);
	let engine = null;
	// Cards can mount before the engine exists (they render as soon as the data arrives), so
	// the preview action waits on this rather than reading `engine` once.
	let resolveEngine;
	const engineReady = new Promise((r) => (resolveEngine = r));
	let engineError = $state('');
	let cfg = $state(null); // { config, defaults, options, updated_at, updated_by }
	let stats = $state(null);
	let loadError = $state('');
	let saving = $state(false);
	let savedAt = $state(0);

	let filter = $state('all');
	let sort = $state('group');
	let days = $state(30);
	let enlarged = $state(null); // effect shown large

	let off = $derived(new Set(cfg?.config.effects_off ?? []));
	let effects = $derived(shaders?.effects ?? []);
	let onCount = $derived(effects.filter((e) => !off.has(e.id)).length);

	let visible = $derived.by(() => {
		let list = effects.filter((e) =>
			filter === 'on' ? !off.has(e.id) : filter === 'off' ? off.has(e.id) : true);
		const st = (e) => stats?.effects[e.id];
		if (sort === 'name') list = [...list].sort((a, b) => a.label.localeCompare(b.label));
		else if (sort === 'shown') list = [...list].sort((a, b) => (st(b)?.seconds ?? 0) - (st(a)?.seconds ?? 0));
		else if (sort === 'fps') list = [...list].sort((a, b) => (st(a)?.fps ?? 999) - (st(b)?.fps ?? 999));
		return list;
	});

	// With the "Group" sort the grid is split under group headings; otherwise one flat list.
	let sections = $derived.by(() => {
		if (sort !== 'group' || !shaders) return [{ title: null, items: visible }];
		return shaders.groups
			.map((g) => ({ title: g, items: visible.filter((e) => e.group === g) }))
			.filter((s) => s.items.length);
	});

	async function loadStats() {
		try {
			stats = await api.getTvVisualizerStats(days);
		} catch (e) {
			console.error('TV visualizer stats', e);
		}
	}

	onMount(async () => {
		try {
			[shaders, cfg] = await Promise.all([loadTvShaders(), api.getTvVisualizerConfig()]);
		} catch (e) {
			loadError = e.message;
			return;
		}
		try {
			engine = new TvPreviewEngine(shaders);
			resolveEngine(engine);
		} catch (e) {
			engineError = e.message;
		}
		loadStats();
	});

	onDestroy(() => engine?.destroy());

	async function save(patch) {
		saving = true;
		try {
			cfg = await api.putTvVisualizerConfig({ config: patch, updated_by: 'web' });
			savedAt = Date.now();
		} catch (e) {
			loadError = `Could not save: ${e.message}`;
		} finally {
			saving = false;
		}
	}

	function setEffect(id, on) {
		const next = new Set(off);
		if (on) next.delete(id);
		else next.add(id);
		// The TV refuses to switch every effect off; so does this page.
		if (next.size >= effects.length) return;
		save({ effects_off: [...next] });
	}

	function setGroup(items, on) {
		const next = new Set(off);
		for (const e of items) on ? next.delete(e.id) : next.add(e.id);
		if (next.size >= effects.length) return;
		save({ effects_off: [...next] });
	}

	/** Svelte action: render an effect into this canvas while it is on screen. */
	function preview(canvas, effectId) {
		let handle = null;
		let io = null;
		let gone = false;
		let current = effectId;
		engineReady.then((eng) => {
			if (gone) return;
			handle = eng.register(canvas, current, () => (canvas.dataset.failed = '1'));
			io = new IntersectionObserver(([entry]) => handle.setVisible(entry.isIntersecting), { rootMargin: '100px' });
			io.observe(canvas);
		});
		return {
			update(id) { current = id; handle?.setEffect(id); },
			destroy() { gone = true; io?.disconnect(); handle?.remove(); },
		};
	}

	function fmtDuration(sec) {
		if (!sec) return '0m';
		const h = Math.floor(sec / 3600);
		const m = Math.round((sec % 3600) / 60);
		return h ? `${h}h ${m}m` : `${m}m`;
	}

	function fmtAgo(iso) {
		if (!iso) return '';
		const s = (Date.now() - new Date(iso).getTime()) / 1000;
		if (s < 90) return 'just now';
		if (s < 3600) return `${Math.round(s / 60)} min ago`;
		if (s < 86400) return `${Math.round(s / 3600)} h ago`;
		return `${Math.round(s / 86400)} d ago`;
	}

	// Below this the effect visibly stutters on the TV.
	const LOW_FPS = 30;

	const SETTINGS = [
		{ key: 'delay_sec', label: 'Start after' },
		{ key: 'rotate_sec', label: 'Change effect' },
		{ key: 'transition', label: 'Transition' },
		{ key: 'transition_ms', label: 'Transition speed' },
		{ key: 'colors', label: 'Colours' },
		{ key: 'info', label: 'Track info' },
	];
	const SWITCHES = [
		{ key: 'enabled', label: 'Visualizer on' },
		{ key: 'beat_reactive', label: 'React to music' },
		{ key: 'trails', label: 'Motion trails' },
	];
</script>

<svelte:head><title>TV Visualizer · Zonik</title></svelte:head>

<PageHeader
	title="TV Visualizer"
	subtitle={shaders ? `${onCount} of ${effects.length} effects on · settings shared with every TV` : 'Google TV app'}
	icon={Tv}
	color={COLOR}
/>

{#if loadError}
	<Card class="mb-4"><p class="text-sm text-[var(--color-error)] flex items-center gap-2"><AlertTriangle class="w-4 h-4" />{loadError}</p></Card>
{/if}

{#if !cfg || !shaders}
	{#if !loadError}<Skeleton variant="card" count={2} />{/if}
{:else}
	<Card class="mb-6">
		<div class="flex items-center justify-between mb-3 gap-3">
			<h2 class="text-sm font-semibold text-[var(--text-primary)]">Settings</h2>
			<p class="text-xs text-[var(--text-muted)] flex items-center gap-1.5 whitespace-nowrap">
				{#if saving}<Loader2 class="w-3 h-3 animate-spin" />Saving…
				{:else if savedAt}<Check class="w-3 h-3 text-[var(--color-success)]" />Saved · TVs pick it up within 5 min
				{:else if cfg.updated_at}Last changed {fmtAgo(cfg.updated_at)} from {cfg.updated_by === 'web' ? 'the web' : cfg.updated_by}
				{:else}Using the app's defaults{/if}
			</p>
		</div>
		<div class="flex flex-wrap gap-x-6 gap-y-2 mb-4">
			{#each SWITCHES as s}
				<Toggle label={s.label} checked={cfg.config[s.key]} color={COLOR}
					onchange={(v) => save({ [s.key]: v })} />
			{/each}
		</div>
		<div class="grid grid-cols-2 md:grid-cols-3 gap-3">
			{#each SETTINGS as s}
				<label class="text-xs text-[var(--text-muted)]">
					{s.label}
					<select class="{inputClass} mt-1" value={cfg.config[s.key]}
						onchange={(e) => {
							const raw = e.currentTarget.value;
							save({ [s.key]: typeof cfg.defaults[s.key] === 'number' ? Number(raw) : raw });
						}}>
						{#each cfg.options[s.key] as [value, label]}
							<option {value}>{label}{value === cfg.defaults[s.key] ? ' (default)' : ''}</option>
						{/each}
					</select>
				</label>
			{/each}
		</div>
	</Card>

	<div class="flex flex-wrap items-center justify-between gap-3 mb-4">
		<FilterPills value={filter} onchange={(v) => (filter = v)} options={[
			{ value: 'all', label: 'All', count: effects.length },
			{ value: 'on', label: 'On', count: onCount },
			{ value: 'off', label: 'Off', count: effects.length - onCount },
		]} />
		<div class="flex items-center gap-2 flex-shrink-0">
			<select class="{inputClass} !w-auto" bind:value={sort}>
				<option value="group">By group</option>
				<option value="name">By name</option>
				<option value="shown">Most shown</option>
				<option value="fps">Slowest first</option>
			</select>
			<select class="{inputClass} !w-auto" bind:value={days} onchange={loadStats}>
				<option value={7}>Last 7 days</option>
				<option value={30}>Last 30 days</option>
				<option value={0}>All time</option>
			</select>
		</div>
	</div>

	{#if engineError}
		<p class="text-xs text-[var(--color-warning)] mb-3">Previews unavailable: {engineError}</p>
	{/if}
	{#if stats && !stats.devices.length}
		<p class="text-xs text-[var(--text-muted)] mb-3">No stats yet: TVs report them once they run app 1.48 or later.</p>
	{:else if stats}
		<p class="text-xs text-[var(--text-muted)] mb-3">
			{fmtDuration(stats.total_seconds)} on screen from {stats.devices.map((d) => d.name || 'a TV').join(', ')}.
			Frame rates are measured on the TV; red is below {LOW_FPS} fps.
		</p>
	{/if}

	{#each sections as section (section.title)}
		{#if section.title}
			<div class="flex items-center justify-between mt-6 mb-2">
				<h2 class="text-sm font-semibold text-[var(--text-primary)]">{section.title}
					<span class="text-[var(--text-muted)] font-normal">{section.items.length}</span></h2>
				<div class="flex gap-1.5">
					<Button variant="ghost" size="sm" onclick={() => setGroup(section.items, true)}>All on</Button>
					<Button variant="ghost" size="sm" onclick={() => setGroup(section.items, false)}>All off</Button>
				</div>
			</div>
		{/if}
		<div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 2xl:grid-cols-6 gap-3">
			{#each section.items as e (e.id)}
				{@const st = stats?.effects[e.id]}
				{@const isOn = !off.has(e.id)}
				<div class="bg-[var(--surface-container)] rounded-lg overflow-hidden transition-opacity {isOn ? '' : 'opacity-45'}">
					<button class="block w-full aspect-video bg-black" onclick={() => (enlarged = e)} title="Show larger">
						<canvas width="320" height="180" class="w-full h-full block" use:preview={e.id}></canvas>
					</button>
					<div class="p-2.5">
						<div class="flex items-center justify-between gap-2">
							<span class="text-sm font-medium text-[var(--text-primary)] truncate">{e.label}</span>
							<Toggle size="sm" checked={isOn} color={COLOR} onchange={(v) => setEffect(e.id, v)} />
						</div>
						<p class="text-[11px] text-[var(--text-muted)] mt-0.5 truncate">
							{#if st}
								<span class={st.fps != null && st.fps < LOW_FPS ? 'text-[var(--color-error)]' : ''}>{st.fps ?? '–'} fps</span>
								· {fmtDuration(st.seconds)} · {st.shows}×
								{#if st.kicks_per_min != null}· {Math.round(st.kicks_per_min)} kicks/min{/if}
							{:else}
								Not shown yet
							{/if}
						</p>
					</div>
				</div>
			{/each}
		</div>
	{/each}
{/if}

{#if enlarged}
	<Modal title={enlarged.label} maxWidth="max-w-5xl" onclose={() => (enlarged = null)}>
		<canvas width="960" height="540" class="w-full aspect-video block bg-black rounded" use:preview={enlarged.id}></canvas>
		<p class="text-xs text-[var(--text-muted)] mt-2">
			{enlarged.group}{enlarged.floats ? ' · floats around the screen' : ''}{enlarged.framesCover ? ' · frames the album cover' : ''}{enlarged.feedback ? ' · draws on its previous frame' : ''}.
			Simulated 120 bpm beat and a stand-in cover; on the TV it follows the music and the album art.
		</p>
	</Modal>
{/if}
