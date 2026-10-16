// Workload derived from third_party/challenge/bench/load.js.
// Copyright (c) 2026 arjaythedev and the challenge contributors, MIT.
// The complete upstream license is in third_party/challenge/LICENSE.
import http from 'k6/http';
import { check, sleep, randomSeed } from 'k6';
import { SharedArray } from 'k6/data';
import { Counter, Gauge, Rate, Trend } from 'k6/metrics';
import exec from 'k6/execution';

const base = (__ENV.BASE_URL || 'http://127.0.0.1:3000').replace(/\/$/, '');
const mode = __ENV.MODE || 'original';
const vus = Number(__ENV.VUS || 100);
const duration = __ENV.DURATION || '5m';
const ramp = __ENV.RAMP_UP || '60s';
const tokens = new SharedArray('tokens', () => JSON.parse(open(__ENV.TOKENS || '../third_party/challenge/seed/tokens.json')));
if (!['original', 'active', 'open'].includes(mode)) throw new Error(`Unknown MODE ${mode}`);
if (!tokens.length || !Number.isSafeInteger(vus) || vus < 1) throw new Error('Require tokens and positive integer VUS');
const full = new Trend('full_request_ms', true);
const valid = new Rate('semantic_success');
const completed = new Counter('validated_requests');
// Delta events are reconstructed globally from raw output, not the misleading per-VU gauge summary.
const inflight = new Gauge('client_inflight_delta');
const endpoints = ['feed', 'post', 'like', 'create'];
function millis(s) {
  const m = /^(\d+(?:\.\d+)?)(ms|s|m|h)$/.exec(s);
  if (!m) throw new Error(`Use a single-unit duration: ${s}`);
  return Number(m[1]) * {ms: 1, s: 1000, m: 60000, h: 3600000}[m[2]];
}
const rampMs = mode === 'original' ? millis(ramp) : 0;
const holdMs = millis(duration);
const thresholds = {
  semantic_success: ['rate==1'],
  checks: ['rate==1'],
  'http_req_failed{phase:hold}': ['rate<0.01'],
  'validated_requests{phase:hold}': ['count>0'],
};
for (const endpoint of endpoints) {
  thresholds[`full_request_ms{phase:hold,endpoint:${endpoint}}`] = ['p(95)<500', 'p(99)<1000'];
  // Require endpoint coverage; an empty endpoint cannot silently pass.
  thresholds[`validated_requests{phase:hold,endpoint:${endpoint}}`] = ['count>0'];
}
if (mode === 'open') thresholds.dropped_iterations = ['count==0'];
const scenario = mode === 'original' ? {
  executor: 'ramping-vus', startVUs: 0,
  stages: [{duration: ramp, target: vus}, {duration, target: vus}, {duration: __ENV.RAMP_DOWN || '30s', target: 0}],
  gracefulRampDown: '10s', gracefulStop: '10s',
} : mode === 'active' ? {
  executor: 'constant-vus', vus, duration, gracefulStop: '10s',
} : {
  executor: 'constant-arrival-rate', rate: Number(__ENV.RATE || 1000), timeUnit: '1s', duration,
  preAllocatedVUs: vus, maxVUs: Number(__ENV.MAX_VUS || vus), gracefulStop: '10s',
};
export const options = {
  scenarios: {load: scenario}, thresholds,
  systemTags: ['status', 'method', 'name', 'scenario', 'expected_response', 'error_code'],
  summaryTrendStats: ['avg', 'min', 'med', 'p(95)', 'p(99)', 'max'],
  discardResponseBodies: false, noConnectionReuse: false,
};
const between = (a, b) => a + Math.random() * (b - a);
function tags(endpoint) {
  const elapsed = Date.now() - exec.scenario.startTime;
  return {endpoint, phase: elapsed < rampMs ? 'ramp' : elapsed < rampMs + holdMs ? 'hold' : 'drain', name: endpoint};
}
function isPost(p) {
  return p && Number.isSafeInteger(p.id) && p.id > 0 && typeof p.body === 'string' &&
    typeof p.author === 'string' && Number.isSafeInteger(p.like_count) && p.like_count >= 0 &&
    typeof p.created_at === 'string' && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/.test(p.created_at) &&
    Object.keys(p).join(',') === 'id,body,created_at,author,like_count';
}
function request(endpoint, method, path, body, auth, predicate) {
  const t = tags(endpoint);
  const started = Date.now();
  inflight.add(1, t);
  let result = null;
  let okay = false;
  try {
    const r = http.request(method, `${base}${path}`, body, {headers: auth || {}, tags: t, timeout: __ENV.TIMEOUT || '5s'});
    const contentType = String(r.headers['Content-Type'] || '').toLowerCase();
    let data = null;
    // k6 Response.json() converts objects through Go maps and loses wire key
    // order. Native JSON.parse preserves JSON insertion order for SPEC checks.
    try { data = JSON.parse(r.body); } catch (_) { /* A JSON failure is a semantic failure below. */ }
    okay = contentType.startsWith('application/json') && data !== null && predicate(r, data);
    result = okay ? data : null;
    check(r, {[`${endpoint} status, schema and meaning`]: () => okay}, t);
  } finally {
    full.add(Date.now() - started, t);
    valid.add(okay, t);
    completed.add(okay ? 1 : 0, t);
    inflight.add(-1, t);
  }
  return result;
}
function feed() {
  return request('feed', 'GET', '/feed', null, null, (r, d) => {
    if (r.status !== 200 || Object.keys(d).join(',') !== 'posts' || !Array.isArray(d.posts) || d.posts.length !== 20 || !d.posts.every(isPost)) return false;
    return d.posts.every((p, i) => i === 0 || d.posts[i-1].created_at > p.created_at ||
      (d.posts[i-1].created_at === p.created_at && d.posts[i-1].id > p.id));
  });
}
function getPost(id) {
  return request('post', 'GET', `/posts/${id}`, null, null, (r, d) => r.status === 200 && Object.keys(d).join(',') === 'post' && isPost(d.post) && d.post.id === id);
}
function like(id, auth) {
  return request('like', 'POST', `/posts/${id}/like`, null, auth, (r, d) =>
    Object.keys(d).join(',') === 'liked,already_liked,post_id' && d.liked === true && d.post_id === id &&
    ((r.status === 201 && d.already_liked === false) || (r.status === 200 && d.already_liked === true)));
}
function create(user, auth) {
  const body = `${user.username} says hi (VU ${__VU}, iter ${__ITER})`;
  return request('create', 'POST', '/posts', JSON.stringify({body}), auth, (r, d) =>
    r.status === 201 && Object.keys(d).join(',') === 'post' && isPost(d.post) &&
    d.post.body === body && d.post.author === user.username && d.post.like_count === 0);
}
export default function () {
  if (__ITER === 0) randomSeed(Number(__ENV.SEED || 7263) + __VU);
  const user = tokens[(__VU - 1) % tokens.length];
  const auth = {Authorization: `Bearer ${user.token}`, 'Content-Type': 'application/json'};
  if (mode === 'original') {
    if (__ITER === 0) sleep(between(0, 5));
    const data = feed();
    if (!data) { sleep(between(3, 7)); return; }
    const p = data.posts[Math.floor(Math.random() * data.posts.length)];
    sleep(between(3, 7));
    getPost(p.id);
    sleep(between(3, 8));
    if (Math.random() < 0.15) like(p.id, auth);
    if (Math.random() < 0.02) create(user, auth);
    sleep(between(5, 15));
  } else {
    // Each iteration is exactly one HTTP request. Rotation guarantees all four
    // endpoints even in a tiny smoke; the documented active mix is 25% each.
    const action = (__ITER + __VU - 1) % 4;
    const id = 1 + ((__ITER * 17 + __VU) % Number(__ENV.POST_IDS || 10000));
    if (action === 0) feed();
    if (action === 1) getPost(id);
    if (action === 2) like(id, auth);
    if (action === 3) create(user, auth);
  }
}
export function handleSummary(data) {
  return {[__ENV.SUMMARY_PATH || 'summary.json']: JSON.stringify(data, null, 2)};
}
