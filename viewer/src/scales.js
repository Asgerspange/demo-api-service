// World→radar coordinate transform. The calibration (pos_x/pos_y/scale) comes from the API
// (`/v1/maps/{map}` → `map_ref` on the demo), NOT from the old scales.js — the table is
// authoritative (Stage 06 §6.2). This is just the math, ported from useCanvas.toGameCoords:
//   imageX = (worldX - pos_x) / scale ;  imageY = (pos_y - worldY) / scale
// (Y is flipped because radar images have origin top-left while the world Y axis points up.)

export function makeWorldToImage(mapRef) {
  const pos_x = mapRef?.pos_x ?? 0;
  const pos_y = mapRef?.pos_y ?? 0;
  const scale = mapRef?.scale || 1;
  return (worldX, worldY) => ({
    x: (worldX - pos_x) / scale,
    y: (pos_y - worldY) / scale,
  });
}

// World-unit length → image-pixel length (for smoke/inferno radii, etc.).
export function worldLenToImage(mapRef, len) {
  return len / (mapRef?.scale || 1);
}
