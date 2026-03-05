<script>
	import '../app.css';
	import Sidebar from '../components/Sidebar.svelte';
	import Player from '../components/Player.svelte';
	import Toast from '../components/Toast.svelte';
	import { onMount, onDestroy } from 'svelte';
	import { connectWebSocket, disconnectWebSocket } from '$lib/websocket.js';

	let { children } = $props();

	onMount(() => {
		connectWebSocket();
	});

	onDestroy(() => {
		disconnectWebSocket();
	});
</script>

<div class="h-screen flex flex-col bg-[var(--bg-primary)]">
	<div class="flex flex-1 overflow-hidden">
		<Sidebar />
		<main class="flex-1 overflow-y-auto p-6">
			<div class="animate-fade-in">
				{@render children()}
			</div>
		</main>
	</div>
	<Player />
	<Toast />
</div>
