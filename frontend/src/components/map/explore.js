// Shared helpers for the Music Map "Explore" layouts (wheel, tempo, atlas).

export const ACCENT = '#22d3ee';

// Fixed colour per genre family (see backend/services/genres.py) so a family
// keeps its colour across layouts and reloads.
export const FAMILY_COLORS = {
	'Pop': '#f28e2b',
	'Rock': '#e15759',
	'Alternative': '#59a14f',
	'Electronic': '#b07aa1',
	'Dance': '#edc948',
	'Hip Hop': '#9c755f',
	'R&B / Soul': '#ff9da7',
	'Country / Folk': '#76b7b2',
	'Metal': '#bab0ac',
	'Jazz / Blues': '#4e79a7',
	'Latin': '#66c2a5',
	'Classical / Score': '#a6d854',
	'Other': '#7c8594',
	'Unknown': '#3f4654',
};
export const familyColor = (f) => FAMILY_COLORS[f] || FAMILY_COLORS.Other;

// --- Camelot ---
const ENHARM = {
	'C': 'C', 'B#': 'C', 'C#': 'C#', 'Db': 'C#', 'D': 'D', 'D#': 'D#', 'Eb': 'D#',
	'E': 'E', 'Fb': 'E', 'F': 'F', 'E#': 'F', 'F#': 'F#', 'Gb': 'F#', 'G': 'G',
	'G#': 'G#', 'Ab': 'G#', 'A': 'A', 'A#': 'A#', 'Bb': 'A#', 'B': 'B', 'Cb': 'B',
};
const MAJOR = { 'C': 8, 'G': 9, 'D': 10, 'A': 11, 'E': 12, 'B': 1, 'F#': 2, 'C#': 3, 'G#': 4, 'D#': 5, 'A#': 6, 'F': 7 };
const MINOR = { 'C': 5, 'G': 6, 'D': 7, 'A': 8, 'E': 9, 'B': 10, 'F#': 11, 'C#': 12, 'G#': 1, 'D#': 2, 'A#': 3, 'F': 4 };

export function camelot(key, scale) {
	if (!key) return null;
	const s = String(key).trim().replace('♯', '#').replace('♭', 'b');
	if (!s) return null;
	const pc = ENHARM[s[0].toUpperCase() + s.slice(1)];
	if (!pc) return null;
	const minor = String(scale || '').toLowerCase().startsWith('min');
	const num = minor ? MINOR[pc] : MAJOR[pc];
	return num ? { num, letter: minor ? 'A' : 'B' } : null;
}

// Mixable with (snum, sletter): same key, ±1 on the same ring, or the relative major/minor.
export function isCompat(num, letter, snum, sletter) {
	if (num === snum) return true;
	if (letter !== sletter) return false;
	return num === (snum % 12) + 1 || num === ((snum + 10) % 12) + 1;
}

// --- numbers ---
export function percentile(sorted, p) {
	if (!sorted.length) return 0;
	const k = Math.min(sorted.length - 1, Math.max(0, Math.round((sorted.length - 1) * p)));
	return sorted[k];
}

// Deterministic 0..1 noise per index so jittered dots don't move between redraws.
export function rand(seed) {
	const s = Math.sin(seed * 12.9898) * 43758.5453;
	return s - Math.floor(s);
}

// Greedy nearest-neighbour walk so a playlist cut from a 2D region flows
// between neighbouring sounds instead of jumping around. Starts at the
// left-most point.
export function flowOrder(idxs, xOf, yOf) {
	if (idxs.length < 3) return idxs.slice();
	const left = idxs.slice();
	let cur = left.reduce((a, b) => (xOf(b) < xOf(a) ? b : a));
	const out = [cur];
	left.splice(left.indexOf(cur), 1);
	while (left.length) {
		let bi = 0, bd = Infinity;
		const cx = xOf(cur), cy = yOf(cur);
		for (let k = 0; k < left.length; k++) {
			const d = (xOf(left[k]) - cx) ** 2 + (yOf(left[k]) - cy) ** 2;
			if (d < bd) { bd = d; bi = k; }
		}
		cur = left[bi];
		out.push(cur);
		left.splice(bi, 1);
	}
	return out;
}

// --- canvas plumbing ---
// Sizes a canvas to its container at device pixel ratio and keeps it sized.
// Calls onsize(width, height, ctx) after every resize; returns a cleanup fn.
export function fitCanvas(container, canvas, onsize) {
	const resize = () => {
		const rect = container.getBoundingClientRect();
		const w = Math.max(100, rect.width), h = Math.max(100, rect.height);
		const dpr = window.devicePixelRatio || 1;
		canvas.width = w * dpr;
		canvas.height = h * dpr;
		canvas.style.width = w + 'px';
		canvas.style.height = h + 'px';
		const ctx = canvas.getContext('2d');
		ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
		onsize(w, h, ctx);
	};
	resize();
	const ro = new ResizeObserver(resize);
	ro.observe(container);
	return () => ro.disconnect();
}

export function frameScheduler(draw) {
	let id = 0;
	const request = () => { if (!id) id = requestAnimationFrame(() => { id = 0; draw(); }); };
	request.cancel = () => { if (id) cancelAnimationFrame(id); id = 0; };
	return request;
}

export function pointerPos(canvas, ev) {
	const r = canvas.getBoundingClientRect();
	return { x: ev.clientX - r.left, y: ev.clientY - r.top };
}
