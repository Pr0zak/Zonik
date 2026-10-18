// Unit tests for pure modules (src/lib/**). Deliberately minimal: no SvelteKit
// plugin, node environment, so tests import plain JS without a browser.
import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';

export default defineConfig({
	resolve: {
		alias: { $lib: fileURLToPath(new URL('./src/lib', import.meta.url)) },
	},
	test: {
		environment: 'node',
		include: ['src/**/*.test.js'],
	},
});
