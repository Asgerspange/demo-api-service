/**
 * useCanvas
 * Owns everything that touches the two <canvas> elements:
 *   • Context caching (avoids repeated getContext() in hot render loops)
 *   • Map image loading / drawing
 *   • mapPosition (pan + zoom) state
 *   • Pixel cache for wall-collision ray-casting (refreshed only on pan/zoom/resize)
 *   • Coordinate conversion helpers (world ↔ game)
 *   • All DOM input handlers (scroll, drag, resize, touch pan, pinch-to-zoom)
 */
import { ref, shallowRef } from 'vue';
import { MAX_ZOOM, MIN_ZOOM } from '../options';

export function useCanvas({ mapMetadata, demo }) {
  // ─── Canvas context cache ─────────────────────────────────────────────────
  let _mapCanvas = null, _mapCtx = null, _gameCanvas = null, _gameCtx = null;

  function getCanvases() {
    if (!_mapCanvas) {
      _mapCanvas   = document.getElementById('mapCanvas');
      _mapCtx      = _mapCanvas.getContext('2d');
      _gameCanvas  = document.getElementById('gameCanvas');
      _gameCtx     = _gameCanvas.getContext('2d');
    }
    return { mapCanvas: _mapCanvas, mapCtx: _mapCtx, gameCanvas: _gameCanvas, ctx: _gameCtx };
  }

  function invalidateCanvasCache() {
    _mapCanvas = null; _mapCtx = null; _gameCanvas = null; _gameCtx = null;
  }

  // ─── Map image ────────────────────────────────────────────────────────────
  const cachedImage = shallowRef(null);

  // ─── Map position (pan + zoom) ────────────────────────────────────────────
  const mapPosition = shallowRef({ x: 0, y: 0, scale: 0.7 });

  // ─── Pixel cache (wall collision for bullet tracers) ─────────────────────
  // Refreshed only when the map is redrawn (pan / zoom / resize).
  // The original code called getImageData() every frame — huge perf regression.
  let mapPixelCache      = null;
  let mapPixelCacheDirty = true;

  function refreshMapPixelCacheIfNeeded(mapCanvas, mapCtx) {
    if (!mapPixelCacheDirty) return;
    mapPixelCache      = mapCtx.getImageData(0, 0, mapCanvas.width, mapCanvas.height).data;
    mapPixelCacheDirty = false;
  }

  function markPixelCacheDirty() { mapPixelCacheDirty = true; }
  function getPixelCache()       { return mapPixelCache; }

  // ─── Map drawing ──────────────────────────────────────────────────────────
  function drawMap() {
    function _draw() {
      const { mapCanvas, mapCtx, gameCanvas } = getCanvases();
      const container = document.getElementById('canvas-container');
      if (!container || !mapCanvas || !gameCanvas) return;

      mapCanvas.width  = container.clientWidth;
      mapCanvas.height = container.clientHeight;
      gameCanvas.width = container.clientWidth;
      gameCanvas.height = container.clientHeight;

      if (!cachedImage.value?.complete || cachedImage.value.naturalWidth === 0) return;

      const x = Math.floor((container.offsetWidth  - cachedImage.value.width)  / 2);
      const y = Math.floor((container.offsetHeight - cachedImage.value.height) / 2);
      mapPosition.value = { x, y, scale: mapPosition.value.scale || 1 };

      mapCtx.setTransform(1, 0, 0, 1, 0, 0);
      mapCtx.clearRect(0, 0, mapCanvas.width, mapCanvas.height);
      mapCtx.setTransform(1, 0, 0, 1, x, y);
      mapCtx.drawImage(cachedImage.value, 0, 0);
      mapPixelCacheDirty = true;
    }

    if (cachedImage.value instanceof HTMLImageElement && cachedImage.value.complete) {
      _draw();
      return;
    }

    const image = new Image();
    image.crossOrigin = 'anonymous';
    image.src = `/images/demo/${demo.value?.map_metadata.name}.svg`;
    image.onerror = (e) => console.error('Error loading map image:', e);
    image.onload  = () => { cachedImage.value = image; _draw(); };
  }

  // ─── Coordinate helpers ───────────────────────────────────────────────────
  /** Screen pixel → map-image-space (unscaled). */
  function toWorldCoords(screenX, screenY) {
    return {
      x: (screenX - mapPosition.value.x) / mapPosition.value.scale,
      y: (screenY - mapPosition.value.y) / mapPosition.value.scale,
    };
  }

  /** CS:GO world unit → map-image pixel. */
  function toGameCoords(worldX, worldY) {
    const m = mapMetadata.value;
    if (!m) return { x: 0, y: 0 };
    return {
      x: (worldX - m.pos_x) / m.scale,
      y: (m.pos_y - worldY) / m.scale,
    };
  }

  // ─── Input handlers ───────────────────────────────────────────────────────
  const mousedown     = ref(false);
  const resizeTimeout = ref(null);

  /** Callback fired when map position changes — injected by parent to trigger re-render. */
  let _onPositionChange = () => {};
  function onPositionChange(cb) { _onPositionChange = cb; }

  // ─── Mouse handlers ───────────────────────────────────────────────────────

  function handleScroll(event) {
    event.preventDefault();
    const delta    = (event.wheelDelta || -event.detail) > 0 ? 0.1 : -0.1;
    const oldScale = mapPosition.value.scale;
    const newScale = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, oldScale + delta));
    const zoomBy   = newScale / oldScale;
    mapPosition.value = {
      x: event.offsetX - (event.offsetX - mapPosition.value.x) * zoomBy,
      y: event.offsetY - (event.offsetY - mapPosition.value.y) * zoomBy,
      scale: newScale,
    };
    markPixelCacheDirty();
    _onPositionChange();
  }

  function handleMouseMove(event) {
    if (!mousedown.value) return;
    mapPosition.value = {
      x: mapPosition.value.x + event.movementX,
      y: mapPosition.value.y + event.movementY,
      scale: mapPosition.value.scale,
    };
    markPixelCacheDirty();
    _onPositionChange();
  }

  const handleMouseDown = () => { mousedown.value = true;  };
  const handleMouseUp   = () => { mousedown.value = false; };

  // ─── Touch handlers ───────────────────────────────────────────────────────
  // Tracks the previous touch state so we can compute deltas each touchmove.
  let _lastTouches = null;

  /** Returns the midpoint of two Touch objects. */
  function _touchMidpoint(t1, t2) {
    return {
      x: (t1.clientX + t2.clientX) / 2,
      y: (t1.clientY + t2.clientY) / 2,
    };
  }

  /** Returns the pixel distance between two Touch objects. */
  function _touchDistance(t1, t2) {
    const dx = t1.clientX - t2.clientX;
    const dy = t1.clientY - t2.clientY;
    return Math.sqrt(dx * dx + dy * dy);
  }

  /** Converts a client-space coordinate to offset-space relative to the container. */
  function _clientToOffset(clientX, clientY) {
    const container = document.getElementById('canvas-container');
    if (!container) return { x: clientX, y: clientY };
    const rect = container.getBoundingClientRect();
    return { x: clientX - rect.left, y: clientY - rect.top };
  }

  function handleTouchStart(event) {
    event.preventDefault();
    _lastTouches = event.touches;
  }

  function handleTouchEnd(event) {
    event.preventDefault();
    // Keep the remaining touches as the new baseline so lifting one finger
    // during a pinch doesn't cause a sudden position jump on the next move event.
    _lastTouches = event.touches.length > 0 ? event.touches : null;
  }

  function handleTouchMove(event) {
    event.preventDefault();
    if (!_lastTouches) return;

    const curr = event.touches;
    const prev = _lastTouches;

    if (curr.length === 1 && prev.length === 1) {
      // ── Single finger: pan ───────────────────────────────────────────────
      const dx = curr[0].clientX - prev[0].clientX;
      const dy = curr[0].clientY - prev[0].clientY;
      mapPosition.value = {
        x: mapPosition.value.x + dx,
        y: mapPosition.value.y + dy,
        scale: mapPosition.value.scale,
      };
      markPixelCacheDirty();
      _onPositionChange();

    } else if (curr.length === 2 && prev.length === 2) {
      // ── Two fingers: pinch-to-zoom + simultaneous pan ────────────────────
      const prevDist = _touchDistance(prev[0], prev[1]);
      const currDist = _touchDistance(curr[0], curr[1]);

      // Avoid division-by-zero on degenerate pinches.
      if (prevDist === 0) { _lastTouches = curr; return; }

      const oldScale = mapPosition.value.scale;
      const newScale = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, oldScale * (currDist / prevDist)));
      const zoomBy   = newScale / oldScale;

      // Zoom toward the midpoint of the two fingers (converted to offset-space).
      const prevMid = _touchMidpoint(prev[0], prev[1]);
      const currMid = _touchMidpoint(curr[0], curr[1]);
      const origin  = _clientToOffset(prevMid.x, prevMid.y);

      // Pan delta: difference between current and previous midpoints.
      const panDx = currMid.x - prevMid.x;
      const panDy = currMid.y - prevMid.y;

      mapPosition.value = {
        x: origin.x - (origin.x - mapPosition.value.x) * zoomBy + panDx,
        y: origin.y - (origin.y - mapPosition.value.y) * zoomBy + panDy,
        scale: newScale,
      };
      markPixelCacheDirty();
      _onPositionChange();
    }

    _lastTouches = curr;
  }

  // ─── Resize handler ───────────────────────────────────────────────────────

  function handleResize() {
    clearTimeout(resizeTimeout.value);
    resizeTimeout.value = setTimeout(() => {
      const { mapCanvas, gameCanvas } = getCanvases();
      const container = document.getElementById('canvas-container');
      if (!container) return;
      mapCanvas.width  = container.clientWidth;
      mapCanvas.height = container.clientHeight;
      gameCanvas.width = container.clientWidth;
      gameCanvas.height = container.clientHeight;
      markPixelCacheDirty();
      drawMap();
      _onPositionChange();
    }, 10);
  }

  /** Attach / detach all DOM listeners. */
  function attachListeners() {
    const container = document.getElementById('canvas-container');

    // Mouse
    container?.addEventListener('wheel',     handleScroll);
    container?.addEventListener('mousedown', handleMouseDown);
    container?.addEventListener('mouseup',   handleMouseUp);
    container?.addEventListener('mousemove', handleMouseMove);

    // Touch — { passive: false } is required so event.preventDefault() works
    // and the browser doesn't hijack scroll / pinch gestures.
    container?.addEventListener('touchstart', handleTouchStart, { passive: false });
    container?.addEventListener('touchend',   handleTouchEnd,   { passive: false });
    container?.addEventListener('touchmove',  handleTouchMove,  { passive: false });

    window.addEventListener('resize', handleResize);
  }

  function detachListeners() {
    const container = document.getElementById('canvas-container');

    // Mouse
    container?.removeEventListener('wheel',     handleScroll);
    container?.removeEventListener('mousedown', handleMouseDown);
    container?.removeEventListener('mouseup',   handleMouseUp);
    container?.removeEventListener('mousemove', handleMouseMove);

    // Touch
    container?.removeEventListener('touchstart', handleTouchStart);
    container?.removeEventListener('touchend',   handleTouchEnd);
    container?.removeEventListener('touchmove',  handleTouchMove);

    window.removeEventListener('resize', handleResize);
    invalidateCanvasCache();
  }

  return {
    cachedImage,
    mapPosition,
    getCanvases,
    invalidateCanvasCache,
    drawMap,
    toWorldCoords,
    toGameCoords,
    refreshMapPixelCacheIfNeeded,
    getPixelCache,
    markPixelCacheDirty,
    attachListeners,
    detachListeners,
    onPositionChange,
  };
}