/**
 * Deep OpenAPI GET sweep + mutation edge cases (aggressive).
 */
import { test, expect } from "@playwright/test";

const BASE = process.env.BASE_URL || "http://127.0.0.1:8000";
const KEY =
  process.env.E2E_API_KEY ||
  process.env.FRONTLINE_API_KEY ||
  "live-harden-key-32-chars-min!!";

const H = { "X-API-Key": KEY };

test.describe("Deep OpenAPI GET sweep", () => {
  test("production-like docs/openapi not anonymously open (or openapi sweep)", async ({
    request,
  }) => {
    const openapi = await request.get(`${BASE}/openapi.json`);
    const docs = await request.get(`${BASE}/docs`);
    // Hardened servers disable docs (404); open/local keep 200.
    if (openapi.status() === 404 || docs.status() === 404) {
      expect([404, 401, 403]).toContain(openapi.status());
      expect([404, 401, 403]).toContain(docs.status());
      return;
    }
    expect(openapi.status()).toBe(200);
    const spec = await openapi.json();
    const paths = Object.entries(spec.paths || {});
    const failures = [];
    for (const [path, methods] of paths) {
      if (!methods.get) continue;
      if (path.includes("{")) continue;
      if (path === "/docs" || path === "/redoc" || path === "/openapi.json") continue;
      const res = await request.get(`${BASE}${path}`, { headers: H });
      if (res.status() >= 500) {
        failures.push(`GET ${path} → ${res.status()} ${(await res.text()).slice(0, 160)}`);
      }
    }
    expect(failures, failures.join("\n")).toEqual([]);
  });

  test("core /api GETs without auth are 401 (not 500)", async ({ request }) => {
    const sample = [
      "/api/frontline/cases",
      "/api/packs",
      "/api/interactions",
      "/api/frontline/metrics",
      "/api/v3/learning/proposals",
    ];
    for (const path of sample) {
      const res = await request.get(`${BASE}${path}`);
      expect(res.status(), path).not.toBe(500);
      expect([401, 403]).toContain(res.status());
    }
  });
});

test.describe("Deep mutation edges", () => {
  test("usage ignores client tenant spoof", async ({ request }) => {
    const post = await request.post(`${BASE}/api/frontline/usage`, {
      headers: { ...H, "Content-Type": "application/json" },
      data: { metric: "e2e_contacts", quantity: 1, tenant_id: "spoofed_tenant_xyz" },
    });
    expect(post.status()).toBe(200);
    const body = await post.json();
    expect(body.tenant_id).not.toBe("spoofed_tenant_xyz");
  });

  test("case note author cannot be spoofed to CEO", async ({ request }) => {
    // Prefer automotive pack corpus if active pack's fixture is empty/wrong.
    let sim = await request.post(
      `${BASE}/api/frontline/simulate?count=2&speed=instant&pack_id=automotive_nhtsa`,
      { headers: H },
    );
    if (sim.status() !== 200) {
      sim = await request.post(`${BASE}/api/frontline/simulate?count=2&speed=instant`, {
        headers: H,
      });
    }
    expect(sim.status()).toBe(200);
    const simBody = await sim.json();
    expect((simBody.completed || 0) + (simBody.cases_created || 0)).toBeGreaterThan(0);

    const list = await request.get(`${BASE}/api/frontline/cases?limit=5`, { headers: H });
    expect(list.status()).toBe(200);
    const cases = (await list.json()).cases || [];
    expect(cases.length, "simulate should create cases").toBeGreaterThan(0);
    const cid = cases[0].case_id;
    const note = await request.post(`${BASE}/api/frontline/cases/${cid}/notes`, {
      headers: { ...H, "Content-Type": "application/json" },
      data: { body: "e2e note", author: "CEO" },
    });
    expect(note.status()).toBe(200);
    const j = await note.json();
    expect(j.author).not.toBe("CEO");
    expect(j.author).toMatch(/service|operator|e2e|admin/i);
  });

  test("subscriptions create validates channel", async ({ request }) => {
    const bad = await request.post(`${BASE}/api/frontline/subscriptions`, {
      headers: { ...H, "Content-Type": "application/json" },
      data: { channel: "carrier-pigeon", target: "x@y.z" },
    });
    expect([400, 422]).toContain(bad.status());
  });

  test("jobs enqueue unknown type rejected; run-next denied for service", async ({
    request,
  }) => {
    const enq = await request.post(`${BASE}/api/frontline/jobs`, {
      headers: { ...H, "Content-Type": "application/json" },
      data: { job_type: "e2e_unknown_type", payload: { a: 1 } },
    });
    expect(enq.status()).toBe(400);
    const run = await request.post(`${BASE}/api/frontline/jobs/run-next`, {
      headers: H,
    });
    expect(run.status()).toBe(403);
  });

  test("dsr delete with service key is 403", async ({ request }) => {
    const r = await request.delete(`${BASE}/api/frontline/dsr/e2e_missing`, {
      headers: H,
    });
    expect(r.status()).toBe(403);
  });

  test("wrong API key is 401 everywhere critical", async ({ request }) => {
    const bad = { "X-API-Key": "wrong-key-that-is-long-enough!!" };
    for (const path of ["/api/frontline/cases", "/api/packs", "/api/interactions"]) {
      const r = await request.get(`${BASE}${path}`, { headers: bad });
      expect(r.status(), path).toBe(401);
    }
  });
});
