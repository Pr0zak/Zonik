const BASE_URL = '/api';

async function request(path, options = {}) {
	const res = await fetch(`${BASE_URL}${path}`, {
		headers: { 'Content-Type': 'application/json', ...options.headers },
		...options
	});
	if (!res.ok) throw new Error(`API error: ${res.status}`);
	return res.json();
}

export const api = {
	// Library
	getStats: () => request('/library/stats'),
	scanLibrary: () => request('/library/scan', { method: 'POST' }),
	getRecent: (limit = 20) => request(`/library/recent?limit=${limit}`),
	getGenres: () => request('/library/genres'),

	// Tracks
	getTracks: (params = {}) => {
		const qs = new URLSearchParams(params).toString();
		return request(`/tracks?${qs}`);
	},
	getTrack: (id) => request(`/tracks/${id}`),
	deleteTrack: (id) => request(`/tracks/${id}`, { method: 'DELETE' }),

	// Favorites
	getFavorites: () => request('/favorites'),
	star: (data) => request('/favorites/star', { method: 'POST', body: JSON.stringify(data) }),
	unstar: (data) => request('/favorites/unstar', { method: 'POST', body: JSON.stringify(data) }),

	// Playlists
	getPlaylists: () => request('/playlists'),
	getPlaylist: (id) => request(`/playlists/${id}`),
	createPlaylist: (data) => request('/playlists', { method: 'POST', body: JSON.stringify(data) }),
	updatePlaylist: (id, data) => request(`/playlists/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
	deletePlaylist: (id) => request(`/playlists/${id}`, { method: 'DELETE' }),

	// Jobs
	getJobs: () => request('/jobs'),
	getActiveJobs: () => request('/jobs/active'),
	getJob: (id) => request(`/jobs/${id}`),
};
