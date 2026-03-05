import defaultTheme from 'tailwindcss/defaultTheme';

/** @type {import('tailwindcss').Config} */
export default {
	content: ['./src/**/*.{html,js,svelte,ts}'],
	darkMode: 'class',
	theme: {
		extend: {
			fontFamily: {
				sans: ['Inter', ...defaultTheme.fontFamily.sans],
			},
			colors: {
				surface: {
					primary: 'var(--bg-primary)',
					secondary: 'var(--bg-secondary)',
					tertiary: 'var(--bg-tertiary)',
					hover: 'var(--bg-hover)',
					active: 'var(--bg-active)',
				},
				border: {
					subtle: 'var(--border-subtle)',
					interactive: 'var(--border-interactive)',
					focus: 'var(--border-focus)',
				},
				accent: {
					DEFAULT: 'var(--color-accent)',
					hover: 'var(--color-accent-hover)',
					light: 'var(--color-accent-light)',
					dark: 'var(--color-accent-dark)',
				},
			},
		},
	},
	plugins: [],
};
