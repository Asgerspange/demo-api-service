// Stage 07 — world→radar transform math (calibration comes from the API map_ref).
import { describe, it, expect } from 'vitest';
import { makeWorldToImage, worldLenToImage } from '../src/scales.js';

const INFERNO = { pos_x: -2087, pos_y: 3870, scale: 4.9 }; // de_inferno calibration

describe('makeWorldToImage', () => {
  it('maps the calibration origin to image (0,0)', () => {
    const f = makeWorldToImage(INFERNO);
    expect(f(-2087, 3870)).toEqual({ x: 0, y: 0 });
  });

  it('maps world units to image pixels with a flipped Y axis', () => {
    const f = makeWorldToImage(INFERNO);
    const { x, y } = f(0, 0);
    expect(x).toBeCloseTo(2087 / 4.9, 5);
    expect(y).toBeCloseTo(3870 / 4.9, 5);
    // increasing world-Y moves UP the image (smaller y)
    expect(f(0, 100).y).toBeLessThan(f(0, 0).y);
  });

  it('falls back to identity-ish on missing calibration', () => {
    const f = makeWorldToImage(null);
    expect(f(5, 7)).toEqual({ x: 5, y: -7 });
  });

  it('converts world lengths to image pixels by scale', () => {
    expect(worldLenToImage(INFERNO, 144)).toBeCloseTo(144 / 4.9, 5);
    expect(worldLenToImage(null, 10)).toBe(10);
  });
});
