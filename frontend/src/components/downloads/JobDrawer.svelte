<script>
	/**
	 * One download's whole story (Release 2, option B drawer): a sticky column at
	 * ≥1280 px, a bottom sheet below. Fetches GET /api/jobs/{id}?detail=1 when it
	 * opens and whenever `version` changes (the page bumps it on a job_update for
	 * this job); every sentence comes from lib/downloads (timeline.js, stage.js).
	 */
	import { untrack } from 'svelte';
	import { goto } from '$app/navigation';
	import { X, Search, RotateCcw, Ban, Trash2, Play, Library } from 'lucide-svelte';
	import { api } from '$lib/api.js';
	import { addToast, playTrack } from '$lib/stores.js';
	import { sourceLabel, clockTime, firstTrack } from '$lib/downloads/stage.js';
	import {
		timelineSentences, candidateLines, peerSentences, stateSentence,
		pickedCandidates, liveQueries, durationPhrase,
	} from '$lib/downloads/timeline.js';
	import { parseUTC } from '$lib/utils.js';
	import Skeleton from '../ui/Skeleton.svelte';
	import Button from '../ui/Button.svelte';
	import FunnelBlock from './FunnelBlock.svelte';

	let {
		jobId = null,
		row = null, // the list item (card / title fallback while the detail loads)
		limits = null, // DC-12 limits from GET /api/download/status
		now = Date.now(), // the page's 1 s tick (ms)
		version = 0, // bump to refetch
		transfer = null, // the job's live transfer_progress entry, when there is one
		onclose = null,
		actions = {}, // {retry, cancel, stopTrying, remove, searchByHand, play, openTrack}
		sheet = false, // true: a bottom sheet at every width (lists too wide to share a row with the column)
	} = $props();

	let detail = $state(null);
	let detailId = $state(null);
	let loading = $state(false);
	let missing = $state(false);
	let loadError = $state('');
	let busy = $state(null); // the action in flight
	let reqSeq = 0;

	async function load(id) {
		const seq = ++reqSeq;
		if (detailId !== id) {
			detail = null;
			missing = false;
			loadError = '';
		}
		loading = true;
		try {
			const d = await api.getJobDetail(id);
			if (seq !== reqSeq) return;
			if (d && d.error) {
				missing = true;
				detail = null;
			} else {
				missing = false;
				loadError = '';
				detail = d;
			}
			detailId = id;
		} catch (e) {
			if (seq !== reqSeq) return;
			loadError = e?.message || 'Could not load this download';
			detailId = id;
		} finally {
			if (seq === reqSeq) loading = false;
		}
	}

	$effect(() => {
		const id = jobId;
		version; // refetch on every bump
		// load() reads and writes detailId/detail: keep them out of this effect's dependencies.
		untrack(() => {
			if (id) load(id);
			else {
				reqSeq += 1;
				detail = null;
				detailId = null;
				missing = false;
				loadError = '';
			}
		});
	});

	function close() {
		onclose?.();
	}

	function onKeydown(e) {
		if (e.key === 'Escape' && jobId) close();
	}

	// The job as the sentences read it: the detail once loaded, else the row.
	let job = $derived(detail && detailId === jobId ? detail : row && row.id === jobId ? row : null);
	let t0 = $derived(firstTrack(job));
	let title = $derived.by(() => {
		const a = t0.artist || '';
		const t = t0.track || '';
		if (a && t) return `${a} — ${t}`;
		return a || t || job?.description || 'Download';
	});
	let isLive = $derived(job?.status === 'running' || job?.status === 'pending');
	let isFailed = $derived(job?.status === 'failed');
	let isDone = $derived(job?.status === 'completed');
	let card = $derived(job?.card ?? row?.card ?? null);
	let batch = $derived(t0.batch && typeof t0.batch === 'object' ? t0.batch : null);

	let meta = $derived.by(() => {
		if (!job) return [];
		const parts = [];
		if (batch?.label && batch.label !== sourceLabel(card)) parts.push(batch.label);
		const startMs = parseUTC(job.started_at)?.getTime();
		const endMs = parseUTC(job.finished_at)?.getTime();
		if (job.started_at) {
			let s = `submitted ${clockTime(job.started_at)}`;
			if (isLive && startMs) s += `, ${durationPhrase(Math.max(0, (now - startMs) / 1000)).replace(/ \d+ s$/, '')} ago`;
			if (!isLive && job.finished_at) {
				s += `, ${isDone ? 'done' : 'gave up'} ${clockTime(job.finished_at)}`;
				if (startMs && endMs && endMs >= startMs) s += ` (${durationPhrase((endMs - startMs) / 1000)})`;
			}
			parts.push(s);
		}
		return parts;
	});

	let sentence = $derived(stateSentence(job, transfer, limits, now));
	let timeline = $derived(detail ? timelineSentences(detail.timeline, detail, now, { transfer, limits }) : []);
	let stage = $derived(job?.stage ?? t0.stage ?? null);
	let showFunnel = $derived(!!detail && (detail.failure_class === 'not_found' || (isLive && stage === 'searching')));
	let funnelSearch = $derived(isLive ? (detail?.search ?? t0.search ?? null) : (detail?.search ?? null));
	let funnelQueries = $derived(isLive && detail ? liveQueries(detail.timeline) : null);

	let peerName = $derived(transfer?.username || job?.username || t0.username || null);
	let attempt = $derived(Number(job?.attempt ?? t0.attempt) || 0);
	let nextCandidates = $derived.by(() => {
		if (!isLive || !detail) return [];
		const list = detail.candidates?.length ? detail.candidates : pickedCandidates(detail.timeline);
		return candidateLines(list, attempt || 1);
	});
	let peers = $derived(detail ? peerSentences(detail.peers) : []);
	let trackId = $derived(job?.track_id || job?.track?.id || null);

	const STATE_TEXT = {
		sky: 'text-sky-400', amber: 'text-amber-400', indigo: 'text-indigo-400',
		muted: 'text-[var(--text-primary)]', emerald: 'text-emerald-400', rose: 'text-rose-400',
	};
	const NOW_TIME = {
		sky: 'text-sky-400', amber: 'text-amber-400', indigo: 'text-indigo-400',
		muted: 'text-[var(--text-secondary)]', emerald: 'text-emerald-400', rose: 'text-rose-400',
	};
	const ROW_TEXT = { rose: 'text-rose-300', emerald: 'text-[var(--text-primary)]', amber: 'text-amber-300' };

	async function run(name, fn) {
		if (!fn || busy) return;
		busy = name;
		try {
			await fn(job);
		} finally {
			busy = null;
		}
	}

	function searchQuery() {
		return [t0.artist, t0.track].filter(Boolean).join(' ');
	}

	async function play() {
		if (actions.play) return run('play', actions.play);
		if (!trackId) return;
		busy = 'play';
		try {
			const track = await api.getTrack(trackId);
			playTrack(track);
		} catch (e) {
			addToast(`Could not play it: ${e.message}`, 'error');
		} finally {
			busy = null;
		}
	}

	function openTrack() {
		if (actions.openTrack) return run('open', actions.openTrack);
		if (trackId) goto(`/library?track=${encodeURIComponent(trackId)}`);
	}

	const LABEL = 'text-[11px] leading-4 font-mono font-bold uppercase tracking-wider text-[var(--text-muted)] mt-4 mb-1';
</script>

<svelte:window onkeydown={onKeydown} />

{#if jobId}
	<!-- below 1280 px the drawer is a bottom sheet over a backdrop -->
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="fixed inset-0 z-30 bg-black/60 {sheet ? '' : 'xl:hidden'}" onclick={close}></div>

	<aside
		class="fixed inset-x-0 bottom-0 z-40 max-h-[82vh] overflow-auto rounded-t-3xl shadow-float animate-slide-up
			{sheet ? 'xl:mx-auto xl:max-w-3xl' : 'xl:sticky xl:inset-auto xl:top-14 xl:z-auto xl:max-h-[calc(100vh-4.5rem)] xl:rounded-3xl xl:shadow-none xl:animate-none'}
			p-5 bg-[var(--surface-container)]"
		aria-label="Download details"
	>
		<div class="w-10 h-1 rounded-full bg-[var(--surface-container-highest)] mx-auto -mt-1 mb-3.5 {sheet ? '' : 'xl:hidden'}" aria-hidden="true"></div>

		<div class="flex justify-between items-start gap-3">
			<h3 class="text-base leading-[1.375rem] font-semibold text-[var(--text-primary)] min-w-0 break-words">{title}</h3>
			<button
				class="w-7 h-7 flex-shrink-0 flex items-center justify-center rounded-xl text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-container-highest)] transition-colors"
				aria-label="Close"
				onclick={close}
			>
				<X class="w-4 h-4" />
			</button>
		</div>

		{#if !job && (loading || !detailId)}
			<div class="mt-3 space-y-2">
				<Skeleton tone="high" class="h-3 w-2/3 rounded" />
				<Skeleton tone="high" class="h-4 w-full rounded" />
				<Skeleton tone="high" class="h-4 w-5/6 rounded" />
				<Skeleton variant="list-item" tone="high" count={3} />
			</div>
		{:else if missing || (!job && loadError)}
			<p class="mt-3 text-sm text-[var(--text-secondary)]">
				{missing ? 'This download is no longer on the server (removed, or retried as a new row).' : loadError}
			</p>
		{:else if job}
			<p class="text-xs leading-[1.125rem] text-[var(--text-muted)] mt-1 mb-4 flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
				<span class="inline-flex items-center rounded-full px-1.5 text-[10px] leading-4 font-medium bg-[var(--surface-container-high)] text-[var(--text-secondary)]">{sourceLabel(card)}</span>
				{#each meta as m}
					<span aria-hidden="true">·</span><span>{m}</span>
				{/each}
			</p>

			{#if sentence.em || sentence.text}
				<p class="text-sm leading-[1.375rem] text-[var(--text-body)] mb-2">
					<em class="not-italic font-semibold {STATE_TEXT[sentence.colour] || STATE_TEXT.muted}">{sentence.em}</em>{sentence.text}
				</p>
			{/if}

			{#if loadError && detail}
				<p class="text-xs text-amber-400">Could not refresh: {loadError}</p>
			{/if}

			<div class={LABEL}>What has happened so far</div>
			{#if !detail}
				<Skeleton variant="list-item" tone="high" count={2} />
			{:else if timeline.length}
				<ul class="divide-y divide-[var(--border-subtle)]">
					{#each timeline as r, i (i)}
						<li class="grid grid-cols-[3.5rem_minmax(0,1fr)] gap-3 py-[7px] text-xs leading-[1.125rem]
							{r.isNow ? 'text-[var(--text-primary)]' : ROW_TEXT[r.colour] || 'text-[var(--text-secondary)]'}">
							<time class="font-mono text-[11px] pt-px {r.isNow ? NOW_TIME[r.colour] || 'text-sky-400' : 'text-[var(--text-muted)]'}">{r.time}</time>
							<span class="min-w-0 break-words">{r.text}</span>
						</li>
					{/each}
				</ul>
			{:else}
				<p class="text-xs text-[var(--text-muted)]">No timeline recorded (job ran before this version).</p>
			{/if}

			{#if showFunnel}
				<div class={LABEL}>Searches</div>
				<FunnelBlock search={funnelSearch} queries={funnelQueries} />
			{/if}

			{#if nextCandidates.length}
				<div class={LABEL}>If {peerName || 'this peer'} doesn't deliver</div>
				<ul class="divide-y divide-[var(--border-subtle)] text-xs leading-[1.125rem] text-[var(--text-secondary)]">
					{#each nextCandidates as c (c.n)}
						<li class="flex gap-2.5 py-[5px]">
							<span class="font-mono text-[11px] text-[var(--text-muted)] w-6 flex-shrink-0">{c.n}</span>
							<span class="min-w-0 break-words">{c.text}</span>
						</li>
					{/each}
				</ul>
			{/if}

			{#if peers.length}
				<div class={LABEL}>Peers</div>
				<p class="text-xs leading-[1.125rem] text-[var(--text-secondary)]">
					{#each peers as p, i (p.user)}
						<b class="font-medium text-[var(--text-primary)]">{p.user}</b> {p.text}.{i < peers.length - 1 ? ' ' : ''}
					{/each}
				</p>
			{/if}

			<div class="flex flex-wrap gap-2 mt-5">
				{#if isLive}
					{#if actions.searchByHand}
						<Button variant="secondary" size="sm" disabled={!!busy} onclick={() => actions.searchByHand(searchQuery(), job)}>
							<Search class="w-3.5 h-3.5" />Search by hand
						</Button>
					{/if}
					{#if actions.cancel}
						<Button variant="danger" size="sm" loading={busy === 'cancel'} disabled={!!busy && busy !== 'cancel'} onclick={() => run('cancel', actions.cancel)}>
							{#if busy !== 'cancel'}<X class="w-3.5 h-3.5" />{/if}Cancel
						</Button>
					{/if}
				{:else if isFailed}
					{#if actions.retry}
						<Button variant="secondary" size="sm" loading={busy === 'retry'} disabled={!!busy && busy !== 'retry'} onclick={() => run('retry', actions.retry)}>
							{#if busy !== 'retry'}<RotateCcw class="w-3.5 h-3.5" />{/if}Retry now
						</Button>
					{/if}
					{#if actions.searchByHand}
						<Button variant="secondary" size="sm" disabled={!!busy} onclick={() => actions.searchByHand(searchQuery(), job)}>
							<Search class="w-3.5 h-3.5" />Search by hand
						</Button>
					{/if}
					{#if actions.stopTrying}
						<Button variant="danger" size="sm" loading={busy === 'stop'} disabled={!!busy && busy !== 'stop'} onclick={() => run('stop', actions.stopTrying)}>
							{#if busy !== 'stop'}<Ban class="w-3.5 h-3.5" />{/if}Stop trying this track
						</Button>
					{/if}
					{#if actions.remove}
						<Button variant="ghost" size="sm" loading={busy === 'remove'} disabled={!!busy && busy !== 'remove'} onclick={() => run('remove', actions.remove)}>
							{#if busy !== 'remove'}<Trash2 class="w-3.5 h-3.5" />{/if}Remove
						</Button>
					{/if}
				{:else if isDone && trackId}
					<Button variant="secondary" size="sm" loading={busy === 'play'} disabled={!!busy && busy !== 'play'} onclick={play}>
						{#if busy !== 'play'}<Play class="w-3.5 h-3.5" />{/if}Play
					</Button>
					<Button variant="secondary" size="sm" disabled={!!busy} onclick={openTrack}>
						<Library class="w-3.5 h-3.5" />Open in library
					</Button>
				{/if}
			</div>
		{/if}
	</aside>
{:else}
	<aside class="hidden xl:flex xl:sticky xl:top-14 items-center justify-center min-h-[12rem] rounded-3xl p-5 bg-[var(--surface-container)] text-sm text-[var(--text-muted)]">
		Pick a row to see its story
	</aside>
{/if}
