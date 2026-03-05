<script>
	import '../app.css';
	import Sidebar from '../components/Sidebar.svelte';
	import Player from '../components/Player.svelte';
	import Toast from '../components/Toast.svelte';
	import { onMount } from 'svelte';

	let { children } = $props();

	onMount(() => {
		// WebSocket connection will be set up when backend supports it
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
