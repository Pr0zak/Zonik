import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

const apiTarget = process.env.VITE_API_TARGET || 'http://localhost:8000';

export default defineConfig({
	plugins: [sveltekit()],
	server: {
		proxy: {
			'/api': apiTarget,
			'/rest': apiTarget
		}
	}
});
