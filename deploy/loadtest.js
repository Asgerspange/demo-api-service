// k6 load test for the serving read path (Stage 08 §8.1).
//
//   k6 run -e BASE=https://api.owner.gg -e KEY=pk_live_... -e DEMO=123 -e ORIGIN=https://app.x.com deploy/loadtest.js
//
// Drives GET /v1/demos/{id} (metadata, short-TTL) and GET /v1/demos/{id}/rounds/{i} (immutable
// payload bytes). The round path is what the CDN absorbs once warm; this hits the ORIGIN to
// measure worst-case (cold) latency + limiter/pool overhead. Adjust the p99 thresholds to your
// chosen target. The read path is I/O-only (object store + Redis) — no parsing/pandas.
import http from 'k6/http';
import { check } from 'k6';

const BASE = __ENV.BASE || 'http://localhost:8000';
const KEY = __ENV.KEY || '';
const DEMO = __ENV.DEMO || '1';
const ORIGIN = __ENV.ORIGIN || 'http://localhost:8001';

export const options = {
  scenarios: {
    serving: { executor: 'ramping-vus', startVUs: 0,
      stages: [{ duration: '30s', target: 50 }, { duration: '1m', target: 50 }, { duration: '15s', target: 0 }] },
  },
  thresholds: {
    // CHOOSE your targets. Metadata is a couple indexed reads; rounds is one object fetch.
    'http_req_duration{name:meta}': ['p(99)<150'],
    'http_req_duration{name:round}': ['p(99)<250'],
    http_req_failed: ['rate<0.01'],
  },
};

const headers = { Authorization: `Bearer ${KEY}`, Origin: ORIGIN };

export default function () {
  const meta = http.get(`${BASE}/v1/demos/${DEMO}`, { headers, tags: { name: 'meta' } });
  check(meta, { 'meta 200': (r) => r.status === 200 });

  let rounds = [];
  try { rounds = (meta.json().rounds || []).map((r) => r.round_index); } catch (e) {}
  const i = rounds.length ? rounds[Math.floor(Math.random() * rounds.length)] : 1;

  const round = http.get(`${BASE}/v1/demos/${DEMO}/rounds/${i}`, { headers, tags: { name: 'round' } });
  check(round, {
    'round 200': (r) => r.status === 200,
    'round immutable': (r) => (r.headers['Cache-Control'] || '').includes('immutable'),
    'round has etag': (r) => !!r.headers['Etag'],
  });
}
