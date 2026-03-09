/**
 * Svelte action for swipe-to-reveal gestures.
 * Usage: <div use:swipeRow={{ onSwipeLeft, onSwipeRight, threshold }}>
 */
export function swipeRow(node, params = {}) {
	let startX = 0;
	let startY = 0;
	let currentX = 0;
	let swiping = false;
	let threshold = params.threshold || 80;

	function handleTouchStart(e) {
		const touch = e.touches[0];
		startX = touch.clientX;
		startY = touch.clientY;
		currentX = 0;
		swiping = false;
	}

	function handleTouchMove(e) {
		const touch = e.touches[0];
		const dx = touch.clientX - startX;
		const dy = touch.clientY - startY;

		// Only start swiping if horizontal movement dominates
		if (!swiping && Math.abs(dx) > 10 && Math.abs(dx) > Math.abs(dy) * 1.5) {
			swiping = true;
		}

		if (swiping) {
			e.preventDefault();
			currentX = dx;
			// Clamp translation
			const clampedX = Math.max(-150, Math.min(150, dx));
			node.style.transform = `translateX(${clampedX}px)`;
			node.style.transition = 'none';

			// Dispatch custom event for action visibility
			node.dispatchEvent(new CustomEvent('swipemove', { detail: { dx: clampedX } }));
		}
	}

	function handleTouchEnd() {
		if (!swiping) return;

		node.style.transition = 'transform 0.3s ease';

		if (currentX < -threshold && params.onSwipeLeft) {
			params.onSwipeLeft();
		} else if (currentX > threshold && params.onSwipeRight) {
			params.onSwipeRight();
		}

		// Reset position
		node.style.transform = 'translateX(0)';
		swiping = false;
		currentX = 0;
	}

	node.addEventListener('touchstart', handleTouchStart, { passive: true });
	node.addEventListener('touchmove', handleTouchMove, { passive: false });
	node.addEventListener('touchend', handleTouchEnd, { passive: true });

	return {
		update(newParams) {
			params = newParams;
			threshold = newParams.threshold || 80;
		},
		destroy() {
			node.removeEventListener('touchstart', handleTouchStart);
			node.removeEventListener('touchmove', handleTouchMove);
			node.removeEventListener('touchend', handleTouchEnd);
		},
	};
}
