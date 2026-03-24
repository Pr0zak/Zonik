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
					/* New surface hierarchy tokens */
					lowest: 'var(--surface-lowest)',
					base: 'var(--surface-base)',
					'container-low': 'var(--surface-container-low)',
					container: 'var(--surface-container)',
					'container-high': 'var(--surface-container-high)',
					'container-highest': 'var(--surface-container-highest)',
					bright: 'var(--surface-bright)',
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
					primary: 'var(--color-primary)',
					'primary-container': 'var(--color-primary-container)',
				},
				outline: {
					DEFAULT: 'var(--outline)',
					variant: 'var(--outline-variant)',
				},
			},
			boxShadow: {
				ambient: 'var(--shadow-ambient)',
				float: 'var(--shadow-float)',
				glow: 'var(--shadow-glow)',
			},
			borderRadius: {
				sm: '0.125rem',
				DEFAULT: '0.25rem',
				md: '0.75rem',
				lg: '1rem',
				xl: '1.5rem',
			},
			backdropBlur: {
				glass: '20px',
				'glass-subtle': '12px',
			},
			letterSpacing: {
				editorial: '-0.02em',
			},
		},
	},
	plugins: [],
};
