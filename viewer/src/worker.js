// Inlined decode worker. The pure `decodeRound` is serialized into a Blob URL so cross-origin
// embeds never hit Worker CORS (Stage 07 §7.1 / gap #10) — we never load the worker from a
// bare cross-origin URL. The worker does the fetch (with the optional client-key Bearer) and
// hands back the decoded columnar buffers zero-copy.

import { decodeRound } from './decode.js';

const BOOTSTRAP = `
onmessage = async (e) => {
  const { url, clientKey } = e.data;
  try {
    const headers = clientKey ? { Authorization: 'Bearer ' + clientKey } : {};
    const resp = await fetch(url, { headers, credentials: 'omit' });
    if (!resp.ok) { postMessage({ error: 'http_' + resp.status }); return; }
    const data = await resp.json();
    const out = decodeRound(data);
    if (!out) { postMessage({ error: 'empty_round' }); return; }
    postMessage({ result: out.result }, out.transferables);
  } catch (err) { postMessage({ error: String((err && err.message) || err) }); }
};
`;

export function createDecodeWorker() {
  const src = `const decodeRound = ${decodeRound.toString()};\n${BOOTSTRAP}`;
  const url = URL.createObjectURL(new Blob([src], { type: 'application/javascript' }));
  const worker = new Worker(url);
  worker.__blobUrl = url; // revoked on destroy()
  return worker;
}
