/**
 * Feature #48 — k6 load smoke (optional; not run in hermetic CI).
 * Usage: k6 run load/k6_ws_smoke.js
 * Targets 50 VUs hitting /health (WS load requires live server + keys).
 */
import http from "k6/http";
import { check, sleep } from "k6";

export const options = {
  vus: 50,
  duration: "15s",
};

const BASE = __ENV.FRONTLINE_BASE || "http://127.0.0.1:8000";

export default function () {
  const res = http.get(`${BASE}/health`);
  check(res, { "health 200": (r) => r.status === 200 });
  sleep(0.1);
}
