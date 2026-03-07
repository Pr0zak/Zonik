/**
 * Shared color utilities for quality scores and format badges.
 * Used by dashboard, duplicates, map, and other pages.
 */

/** Tailwind class for quality score text color */
export function qualityColor(score) {
	if (score >= 80) return 'text-emerald-400';
	if (score >= 50) return 'text-yellow-400';
	return 'text-red-400';
}

/** Tailwind class for quality bar background */
export function qualityBarColor(score) {
	if (score >= 80) return 'bg-emerald-500';
	if (score >= 50) return 'bg-yellow-500';
	return 'bg-red-500';
}

/** Hex color for quality (D3/SVG/Canvas contexts) */
export function qualityHex(avgQuality) {
	if (avgQuality >= 120) return '#22c55e'; // green — lossless
	if (avgQuality >= 80) return '#84cc16';  // lime — high
	if (avgQuality >= 50) return '#f59e0b';  // amber — mid
	if (avgQuality >= 30) return '#f97316';  // orange — low
	return '#ef4444';                         // red — very low
}

/** Format badge Tailwind classes (color-coded by format tier) */
const FORMAT_COLORS = {
	flac: 'text-emerald-400 bg-emerald-500/15 border-emerald-500/30',
	wav: 'text-emerald-300 bg-emerald-500/10 border-emerald-500/20',
	alac: 'text-emerald-300 bg-emerald-500/10 border-emerald-500/20',
	aiff: 'text-emerald-300 bg-emerald-500/10 border-emerald-500/20',
	opus: 'text-blue-400 bg-blue-500/15 border-blue-500/30',
	ogg: 'text-blue-300 bg-blue-500/10 border-blue-500/20',
	m4a: 'text-amber-400 bg-amber-500/15 border-amber-500/30',
	mp3: 'text-amber-300 bg-amber-500/10 border-amber-500/20',
	aac: 'text-orange-400 bg-orange-500/15 border-orange-500/30',
	wma: 'text-red-400 bg-red-500/15 border-red-500/30',
};

export function formatBadgeClass(fmt) {
	return FORMAT_COLORS[fmt?.toLowerCase()] || 'text-[var(--text-muted)] bg-[var(--bg-tertiary)] border-[var(--border-subtle)]';
}

/** Hex colors for format pie/bar charts */
export const FORMAT_HEX = {
	flac: '#10b981', wav: '#14b8a6', alac: '#06b6d4', aiff: '#0ea5e9',
	mp3: '#f59e0b', m4a: '#f97316', ogg: '#ef4444', opus: '#ec4899',
	aac: '#a855f7', wma: '#6366f1', unknown: '#6b7280',
};
