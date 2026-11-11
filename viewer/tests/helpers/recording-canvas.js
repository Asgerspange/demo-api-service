// A headless, deterministic 2D-canvas recorder for viewer *visual* regression (Stage 15 §15.3).
//
// Rendering pixels in CI needs a real browser (Playwright — the heavier on-`main` gate). For the
// fast PR gate we instead record the exact sequence of draw operations the Renderer issues and
// snapshot that transcript: a calibration drift (wrong map_ref → players land at different pixels)
// or a render-logic change moves the transcript, so the snapshot diff catches it deterministically,
// no browser required. Numbers are rounded so meaningless float jitter can't flap the snapshot.

const r = (n) => (typeof n === 'number' ? Math.round(n * 100) / 100 : n);

export function createRecordingCanvas(width = 800, height = 600) {
  const log = [];
  const push = (op) => log.push(op);

  const gradient = { addColorStop() {} }; // gradient *stops* are too noisy to pin; the fill op is enough

  const ctx = {
    // state we don't record but the renderer sets
    globalAlpha: 1, imageSmoothingEnabled: true, lineWidth: 1,
    font: '', textAlign: '', textBaseline: '', shadowBlur: 0, shadowColor: '',
    roundRect(x, y, w, h) { push(`roundRect ${r(x)},${r(y)},${r(w)},${r(h)}`); },

    setTransform(a, b, c, d, e, f) { push(`setTransform ${r(a)},${r(b)},${r(c)},${r(d)},${r(e)},${r(f)}`); },
    fillRect(x, y, w, h) { push(`fillRect ${r(x)},${r(y)},${r(w)},${r(h)}`); },
    drawImage(img, x, y, w, h) {
      const tag = (img && img.src) || 'img';
      push(w === undefined ? `drawImage ${tag} @${r(x)},${r(y)}` : `drawImage ${tag} @${r(x)},${r(y)} ${r(w)}x${r(h)}`);
    },
    beginPath() { push('beginPath'); },
    arc(x, y, rad) { push(`arc ${r(x)},${r(y)} r${r(rad)}`); },
    moveTo(x, y) { push(`moveTo ${r(x)},${r(y)}`); },
    lineTo(x, y) { push(`lineTo ${r(x)},${r(y)}`); },
    stroke() { push('stroke'); },
    fill() { push('fill'); },
    save() { push('save'); },
    restore() { push('restore'); },
    translate(x, y) { push(`translate ${r(x)},${r(y)}`); },
    rotate(a) { push(`rotate ${r(a)}`); },
    scale(x, y) { push(`scale ${r(x)},${r(y)}`); },
    clip() { push('clip'); },
    fillText(t, x, y) { push(`fillText "${t}" @${r(x)},${r(y)}`); },
    createRadialGradient() { return gradient; },
    createLinearGradient() { return gradient; },
    measureText(s) { return { width: String(s).length * 6 }; },
  };

  // Record team/utility colors when set (a tinting regression should move the snapshot too).
  for (const prop of ['fillStyle', 'strokeStyle']) {
    let v = '';
    Object.defineProperty(ctx, prop, {
      get: () => v,
      set: (nv) => { v = nv; push(`${prop}=${typeof nv === 'object' ? '[gradient]' : nv}`); },
    });
  }

  const canvas = {
    width, height,
    getContext: () => ctx,
    getBoundingClientRect: () => ({ width, height, left: 0, top: 0 }),
    style: {},
  };
  return { canvas, ctx, log };
}

// A fake radar image — `naturalWidth/Height` drive the renderer's fit()/drawImage; `src` is the tag.
export function fakeRadar(name, size = 1024) {
  return { src: `radar:${name}`, naturalWidth: size, naturalHeight: size, width: size, height: size, complete: true };
}
