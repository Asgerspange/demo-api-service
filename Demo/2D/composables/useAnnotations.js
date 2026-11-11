/**
 * useAnnotations
 *
 * Per-round analyst annotations: text notes, area rectangles/circles,
 * freehand paths lines.
 *
 * Performance fixes vs previous version:
 *  - Freehand points stored in a plain array, mutated in-place (no spread per event)
 *  - Canvas redraws are RAF-throttled (one repaint per frame max)
 *  - Mouse handlers do minimal work; all heavy drawing is deferred to RAF
 */
import { ref, computed, watch } from 'vue';

const API_BASE = '/api';

export const TOOL_NONE     = 'none';
export const TOOL_NOTE     = 'note';
export const TOOL_RECT     = 'area_rect';
export const TOOL_CIRCLE   = 'area_circle';
export const TOOL_FREEHAND = 'freehand';

export function useAnnotations({ demoId, currentRound }) {
  // ─── State ────────────────────────────────────────────────────────────────
  const annotations      = ref([]);
  const activeTool       = ref(TOOL_NONE);
  const activeColor      = ref('#5D3FD3');
  const pendingNote      = ref('');
  const isLoading        = ref(false);

  // Drawing state — plain objects/arrays mutated in-place for perf
  const isDrawing        = ref(false);
  const drawStart        = ref(null);   // { x, y } game coords
  const drawCurrent      = ref(null);   // { x, y } game coords
  const freehandPts      = [];          // plain array, NOT a ref — mutated in place

  // After a shape is drawn, show a popup to attach a comment + optional tick
  const pendingShape     = ref(null);   // { type, shape_data, color } — awaiting user comment
  const pendingComment   = ref('');
  const pendingLabel     = ref('');
  const pendingTick      = ref(null);   // number | null

  // RAF handle for throttled redraws
  let _rafHandle = null;
  let _drawCb    = null;   // callback injected by Viewer to trigger canvas repaint

  // ─── Derived ──────────────────────────────────────────────────────────────
  const roundAnnotations = computed(() =>
    annotations.value.filter(a => a.round_number === currentRound.value)
  );
  const noteAnnotations  = computed(() => roundAnnotations.value.filter(a => a.type === 'note'));
  const shapeAnnotations = computed(() => roundAnnotations.value.filter(a => a.type !== 'note'));
  const isDrawingMode    = computed(() =>
    activeTool.value !== TOOL_NONE && activeTool.value !== TOOL_NOTE
  );

  // ─── RAF-throttled redraw ─────────────────────────────────────────────────
  function requestRedraw() {
    if (_rafHandle) return;
    _rafHandle = requestAnimationFrame(() => {
      _rafHandle = null;
      _drawCb?.();
    });
  }

  function setDrawCallback(cb) { _drawCb = cb; }

  // ─── API ──────────────────────────────────────────────────────────────────
  async function fetchAnnotations() {
    if (!demoId.value || !currentRound.value) return;
    isLoading.value = true;
    try {
      const res  = await fetch(`${API_BASE}/demos/${demoId.value}/rounds/${currentRound.value}/annotations`);
      const data = await res.json();
      annotations.value = [
        ...annotations.value.filter(a => a.round_number !== currentRound.value),
        ...data,
      ];
    } catch (e) {
      console.error('useAnnotations: fetch failed', e);
    } finally {
      isLoading.value = false;
    }
  }

  async function saveAnnotation(payload) {
    const res = await fetch(
      `${API_BASE}/demos/${demoId.value}/rounds/${currentRound.value}/annotations`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-TOKEN': getCsrf() },
        body: JSON.stringify(payload),
      }
    );
    if (!res.ok) throw new Error('Failed to save annotation');
    const saved = await res.json();
    annotations.value = [...annotations.value, saved];
    return saved;
  }

  async function deleteAnnotation(id) {
    await fetch(`${API_BASE}/annotations/${id}`, {
      method: 'DELETE',
      headers: { 'X-CSRF-TOKEN': getCsrf() },
    });
    annotations.value = annotations.value.filter(a => a.id !== id);
  }

  async function updateAnnotation(id, patch) {
    const res = await fetch(`${API_BASE}/annotations/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-TOKEN': getCsrf() },
      body: JSON.stringify(patch),
    });
    const updated = await res.json();
    annotations.value = annotations.value.map(a => a.id === id ? updated : a);
  }

  // ─── Tool control ─────────────────────────────────────────────────────────
  function setTool(tool) {
    activeTool.value = activeTool.value === tool ? TOOL_NONE : tool;
    cancelDraw();
  }

  function cancelDraw() {
    isDrawing.value   = false;
    drawStart.value   = null;
    drawCurrent.value = null;
    freehandPts.length = 0;
  }

  // ─── Note submit ──────────────────────────────────────────────────────────
  async function submitNote() {
    const text = pendingNote.value.trim();
    if (!text) return;
    await saveAnnotation({
      type: 'note',
      content: text,
      color: activeColor.value,
    });
    pendingNote.value = '';
  }

  // ─── Pending shape confirm/discard ────────────────────────────────────────
  async function confirmShape() {
    if (!pendingShape.value) return;
    try {
      await saveAnnotation({
        ...pendingShape.value,
        content: pendingComment.value.trim() || null,
        label:   pendingLabel.value.trim() || null,
        tick:    pendingTick.value || null,
      });
    } catch (e) {
      console.error('useAnnotations: confirmShape failed', e);
    } finally {
      pendingShape.value   = null;
      pendingComment.value = '';
      pendingLabel.value   = '';
      pendingTick.value    = null;
    }
  }

  function discardShape() {
    pendingShape.value   = null;
    pendingComment.value = '';
    pendingLabel.value   = '';
    pendingTick.value    = null;
  }

  // ─── Mouse handlers ───────────────────────────────────────────────────────
  // Caller passes clientToGame(clientX, clientY) → { x, y } in CS world coords

  function onMouseDown(clientX, clientY, clientToGame) {
    const gp = clientToGame(clientX, clientY);

    if (activeTool.value === TOOL_FREEHAND) {
      freehandPts.length = 0;
      freehandPts.push([gp.x, gp.y]);
      isDrawing.value = true;
    } else {
      // RECT or CIRCLE
      drawStart.value   = gp;
      drawCurrent.value = gp;
      isDrawing.value   = true;
    }
  }

  function onMouseMove(clientX, clientY, clientToGame) {
    if (!isDrawing.value) return;
    const gp = clientToGame(clientX, clientY);

    if (activeTool.value === TOOL_FREEHAND) {
      freehandPts.push([gp.x, gp.y]);     // mutate in place — no allocation
    } else {
      drawCurrent.value = gp;
    }
    requestRedraw();
  }

  function onMouseUp(clientX, clientY, clientToGame) {
    if (!isDrawing.value) return;
    const gp = clientToGame(clientX, clientY);
    isDrawing.value = false;

    let shape = null;

    if (activeTool.value === TOOL_RECT && drawStart.value) {
      const w = Math.abs(gp.x - drawStart.value.x);
      const h = Math.abs(gp.y - drawStart.value.y);
      if (w > 5 || h > 5) {
        shape = {
          type: 'area',
          color: activeColor.value,
          shape_data: {
            shape: 'rect',
            x: Math.min(drawStart.value.x, gp.x),
            y: Math.min(drawStart.value.y, gp.y),
            width: w, height: h,
          },
        };
      }
    } else if (activeTool.value === TOOL_CIRCLE && drawStart.value) {
      const r = Math.hypot(gp.x - drawStart.value.x, gp.y - drawStart.value.y);
      if (r > 5) {
        shape = {
          type: 'area',
          color: activeColor.value,
          shape_data: { shape: 'circle', x: drawStart.value.x, y: drawStart.value.y, radius: r },
        };
      }
    } else if (activeTool.value === TOOL_FREEHAND && freehandPts.length > 3) {
      shape = {
        type: 'freehand',
        color: activeColor.value,
        shape_data: { points: [...freehandPts] },  // snapshot here (only once)
      };
    }

    cancelDraw();
    requestRedraw();

    if (shape) {
      pendingShape.value = shape;    // show comment popup
    }
  }

  // ─── Canvas drawing ───────────────────────────────────────────────────────
  /**
   * Draws all persisted shapes + live preview onto ctx.
   * @param {CanvasRenderingContext2D} ctx
   * @param {Function} gameToScreen  — (gameX, gameY) → { x, y } canvas pixels
   */
  function drawAnnotationLayer(ctx, gameToScreen, multiDemoMode = false) {
    if (multiDemoMode) {
      return;
    }
    // ── Persisted shapes ──────────────────────────────────────────────────
    for (const a of shapeAnnotations.value) {
      _drawShape(ctx, a.type, a.shape_data, a.color ?? '#5D3FD3', false, a.label, a.content, gameToScreen);
    }

    // ── Live preview ──────────────────────────────────────────────────────
    if (!isDrawing.value) return;
    const previewColor = activeColor.value;

    if (activeTool.value === TOOL_RECT && drawStart.value && drawCurrent.value) {
      _drawShape(ctx, 'area', {
        shape: 'rect',
        x: Math.min(drawStart.value.x, drawCurrent.value.x),
        y: Math.min(drawStart.value.y, drawCurrent.value.y),
        width:  Math.abs(drawCurrent.value.x - drawStart.value.x),
        height: Math.abs(drawCurrent.value.y - drawStart.value.y),
      }, previewColor, true, null, null, gameToScreen);

    } else if (activeTool.value === TOOL_CIRCLE && drawStart.value && drawCurrent.value) {
      const r = Math.hypot(drawCurrent.value.x - drawStart.value.x, drawCurrent.value.y - drawStart.value.y);
      _drawShape(ctx, 'area', {
        shape: 'circle', x: drawStart.value.x, y: drawStart.value.y, radius: r,
      }, previewColor, true, null, null, gameToScreen);

    } else if (activeTool.value === TOOL_FREEHAND && freehandPts.length > 1) {
      ctx.save();
      ctx.strokeStyle = previewColor;
      ctx.lineWidth   = 2;
      ctx.setLineDash([]);
      ctx.beginPath();
      freehandPts.forEach(([gx, gy], i) => {
        const p = gameToScreen(gx, gy);
        i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y);
      });
      ctx.stroke();
      ctx.restore();

    }
  }

  function _drawShape(ctx, type, sd, color, isPreview, label, content, gameToScreen) {
    if (!sd) return;
    ctx.save();
    ctx.strokeStyle = color;
    ctx.fillStyle   = color + (isPreview ? '18' : '28');
    ctx.lineWidth   = isPreview ? 1.5 : 2;
    ctx.setLineDash(isPreview ? [5, 3] : []);

    if (type === 'area' && sd.shape === 'rect') {
      const tl = gameToScreen(sd.x, sd.y);
      const br = gameToScreen(sd.x + sd.width, sd.y + sd.height);
      ctx.beginPath();
      ctx.rect(tl.x, tl.y, br.x - tl.x, br.y - tl.y);
      ctx.fill(); ctx.stroke();
      if (!isPreview && (label || content)) {
        _drawBubble(ctx, tl.x + 4, tl.y - 4, label || content, color);
      }

    } else if (type === 'area' && sd.shape === 'circle') {
      const c = gameToScreen(sd.x, sd.y);
      const e = gameToScreen(sd.x + sd.radius, sd.y);
      const r = Math.abs(e.x - c.x);
      ctx.beginPath();
      ctx.arc(c.x, c.y, r, 0, Math.PI * 2);
      ctx.fill(); ctx.stroke();
      if (!isPreview && (label || content)) {
        _drawBubble(ctx, c.x, c.y - r - 4, label || content, color);
      }

    } else if (type === 'freehand' && sd.points?.length) {
      ctx.beginPath();
      sd.points.forEach(([gx, gy], i) => {
        const p = gameToScreen(gx, gy);
        i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y);
      });
      ctx.closePath();
      ctx.fill(); ctx.stroke();

    }
    ctx.restore();
  }

  function _drawBubble(ctx, x, y, text, color) {
    ctx.save();
    ctx.font = 'bold 11px "Bai Jamjuree", sans-serif';
    const tw = ctx.measureText(text).width;
    const pad = 4;
    ctx.fillStyle = 'rgba(0,0,0,0.7)';
    ctx.beginPath();
    ctx.roundRect(x - pad, y - 13, tw + pad * 2, 16, 3);
    ctx.fill();
    ctx.fillStyle = color;
    ctx.fillText(text, x, y);
    ctx.restore();
  }

  function _drawArrow(ctx, p0, p1) {
    const angle = Math.atan2(p1.y - p0.y, p1.x - p0.x);
    const len   = 10;
    ctx.save();
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.moveTo(p1.x, p1.y);
    ctx.lineTo(p1.x - len * Math.cos(angle - 0.4), p1.y - len * Math.sin(angle - 0.4));
    ctx.moveTo(p1.x, p1.y);
    ctx.lineTo(p1.x - len * Math.cos(angle + 0.4), p1.y - len * Math.sin(angle + 0.4));
    ctx.stroke();
    ctx.restore();
  }

  function getCsrf() {
    return document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') ?? '';
  }

  watch([demoId, currentRound], () => fetchAnnotations(), { immediate: true });

  return {
    // State
    annotations, roundAnnotations, noteAnnotations, shapeAnnotations,
    activeTool, activeColor, pendingNote, isLoading, isDrawingMode,
    pendingShape, pendingComment, pendingLabel, pendingTick,

    // Constants
    TOOL_NONE, TOOL_NOTE, TOOL_RECT, TOOL_CIRCLE, TOOL_FREEHAND,

    // Actions
    setTool, cancelDraw, submitNote, confirmShape, discardShape,
    deleteAnnotation, updateAnnotation,
    onMouseDown, onMouseMove, onMouseUp,
    drawAnnotationLayer,
    setDrawCallback, requestRedraw,
    fetchAnnotations,
  };
}