// Reference proxy (Node / Express) for the CS Demoviewer "proxy mode" (Stage 04).
//
// The viewer points `apiBase` at YOUR backend (e.g. https://customer.com/cs) and sends NO
// secret. This route transparently forwards /cs/v1/** to the owner API, injecting the server
// key + end-user id server-side, and streams the response (status, body, and the
// Cache-Control / ETag / Content-Encoding / X-RateLimit-* headers) straight back.
//
//   CSVIEWER_API_BASE   = https://api.owner.gg
//   CSVIEWER_SERVER_KEY = sk_live_…   (NEVER sent to the browser)
//
// Contract: transparent passthrough of /v1/**. The only additions are the two X- headers and
// TLS. Do not rewrite paths beyond the prefix, do not buffer/transform bodies (binary payloads
// + gzip must pass through), and preserve caching headers so the CDN/browser can cache them.
import express from "express";
import { Readable } from "node:stream";

const app = express();
const BASE = (process.env.CSVIEWER_API_BASE ?? "https://api.owner.gg").replace(/\/$/, "");
const SERVER_KEY = process.env.CSVIEWER_SERVER_KEY ?? "";

app.use("/cs", async (req, res) => {
  const upstreamPath = req.originalUrl.replace(/^\/cs/, ""); // keep path + query intact
  const upstream = await fetch(`${BASE}${upstreamPath}`, {
    method: req.method,
    headers: {
      "X-Server-Key": SERVER_KEY,
      "X-End-User": String(req.user?.id ?? "anon"), // a STABLE per-user id
    },
  });

  // Preserve status + all upstream headers (Cache-Control/ETag/Content-Encoding/X-RateLimit-*).
  upstream.headers.forEach((value, key) => res.setHeader(key, value));
  res.status(upstream.status);
  if (upstream.body) Readable.fromWeb(upstream.body).pipe(res); // stream, no buffering
  else res.end();
});

app.listen(process.env.PORT ?? 3000, () => console.log("csviewer proxy on /cs"));
