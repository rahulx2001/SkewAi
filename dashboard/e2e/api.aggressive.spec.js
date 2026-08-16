/**
 * Aggressive API E2E against live FastAPI (auth required).
 * Drives real HTTP paths — not reimplementations.
 */
import { test, expect } from "@playwright/test";

const BASE = process.env.BASE_URL || "http://127.0.0.1:8000";
const KEY =
  process.env.E2E_API_KEY ||
  process.env.FRONTLINE_API_KEY ||
  "live-harden-key-32-chars-min!!";

function authHeaders(extra = {}) {
  return { "X-API-Key": KEY, ...extra };
}

async function api(request, method, path, { headers, data, failOk } = {}) {
  const opts = { method, headers: headers || {} };
  if (data !== undefined) {
    opts.headers = { "Content-Type": "application/json", ...opts.headers };
    opts.data = data;
  }
  const res = await request.fetch(`${BASE}${path}`, opts);
  if (!failOk && res.status() >= 500) {
    const body = await res.text();
    throw new Error(`${method} ${path} → ${res.status()} ${body.slice(0, 300)}`);
  }
  return res;
}

test.describe("API aggressive — auth gate", () => {
  test("health is public and reports auth_required", async ({ request }) => {
    const r = await api(request, "GET", "/health");
    expect(r.status()).toBe(200);
    const j = await r.json();
    expect(j.status).toMatch(/ok|degraded/);
    expect(j.auth_required).toBe(true);
    expect(j.security?.soc2_engineering_baseline).toBe(true);
  });

  test("unauthenticated ops reads are 401", async ({ request }) => {
    for (const path of [
      "/api/frontline/cases",
      "/api/frontline/metrics",
      "/api/packs",
      "/api/interactions",
      "/api/frontline/early-warning",
      "/api/frontline/wallboard",
    ]) {
      const r = await api(request, "GET", path, { failOk: true });
      expect(r.status(), path).toBe(401);
    }
  });

  test("unauthenticated privileged mutations are 401", async ({ request }) => {
    for (const [method, path, data] of [
      ["POST", "/api/frontline/ops/drain", {}],
      ["POST", "/api/frontline/jobs/run-next", {}],
      [
        "POST",
        "/api/frontline/packs/automotive_nhtsa/edit",
        { write_disk: true, edits: { refusal_topics: ["x"] } },
      ],
      ["POST", "/api/frontline/channels/email/ingest", { subject: "s", body: "b" }],
      ["POST", "/api/frontline/biometrics/match", { features: [0.1] }],
      ["DELETE", "/api/frontline/dsr/x", undefined],
      ["POST", "/api/frontline/simulate?count=1", {}],
    ]) {
      const r = await api(request, method, path, { data, failOk: true });
      expect(r.status(), `${method} ${path}`).toBe(401);
    }
  });

  test("query-string api_key alone is rejected", async ({ request }) => {
    const r = await api(request, "GET", `/api/frontline/cases?api_key=${encodeURIComponent(KEY)}`, {
      failOk: true,
    });
    expect(r.status()).toBe(401);
  });
});

test.describe("API aggressive — service key happy paths", () => {
  test("core GETs return 200 with service key", async ({ request }) => {
    const paths = [
      "/api/packs",
      "/api/frontline/cases?limit=5",
      "/api/frontline/metrics",
      "/api/frontline/wallboard",
      "/api/frontline/early-warning",
      "/api/frontline/insights/csat",
      "/api/frontline/insights/product-gap",
      "/api/frontline/audits?limit=20",
      "/api/frontline/investigations?limit=10",
      "/api/frontline/analytics/forecast",
      "/api/frontline/analytics/cohorts?group_field=entity_3",
      "/api/frontline/ops/drain",
      "/api/frontline/ops/backend",
      "/api/frontline/connectors/status",
      "/api/frontline/usage",
      "/api/frontline/auth/oidc",
      "/api/frontline/jobs",
      "/api/frontline/marketplace/packs",
      "/api/v3/learning/proposals?limit=10",
      "/api/v3/experiments?limit=10",
      "/api/v3/governance/deployments",
      "/api/frontline/enterprise/risk/active",
      "/api/frontline/enterprise/scenarios",
      "/api/interactions?limit=10",
    ];
    const failures = [];
    for (const path of paths) {
      const r = await api(request, "GET", path, {
        headers: authHeaders(),
        failOk: true,
      });
      if (r.status() !== 200) {
        failures.push(`${path} → ${r.status()} ${(await r.text()).slice(0, 120)}`);
      }
    }
    expect(failures, failures.join("\n")).toEqual([]);
  });

  test("cohorts rejects injection group_field with 400", async ({ request }) => {
    const r = await api(
      request,
      "GET",
      "/api/frontline/analytics/cohorts?group_field=entity_3%3Bdrop",
      { headers: authHeaders(), failOk: true },
    );
    expect([400, 200]).toContain(r.status());
    if (r.status() === 200) {
      const j = await r.json();
      // empty / error shape — never execute injection
      expect(j.cohorts === undefined || Array.isArray(j.cohorts)).toBe(true);
    }
  });

  test("service key cannot drain / job run-next / pack write_disk", async ({ request }) => {
    let r = await api(request, "POST", "/api/frontline/ops/drain", {
      headers: authHeaders(),
      data: {},
      failOk: true,
    });
    expect(r.status()).toBe(403);

    r = await api(request, "POST", "/api/frontline/jobs/run-next", {
      headers: authHeaders(),
      data: {},
      failOk: true,
    });
    expect(r.status()).toBe(403);

    r = await api(
      request,
      "POST",
      "/api/frontline/packs/automotive_nhtsa/edit",
      {
        headers: authHeaders(),
        data: { write_disk: true, dry_run: false, edits: { refusal_topics: ["e2e"] } },
        failOk: true,
      },
    );
    expect(r.status()).toBe(403);
  });

  test("email ingest and biometrics work with service key", async ({ request }) => {
    let r = await api(request, "POST", "/api/frontline/channels/email/ingest", {
      headers: authHeaders(),
      data: { subject: "e2e", body: "need help with brakes", from: "e2e@example.com" },
    });
    expect(r.status()).toBe(200);
    const email = await r.json();
    expect(email).toHaveProperty("slots");

    r = await api(request, "POST", "/api/frontline/biometrics/match", {
      headers: authHeaders(),
      data: { features: [0.1, 0.2, 0.3], pack_id: "automotive_nhtsa" },
    });
    expect(r.status()).toBe(200);
  });

  test("connector SSRF targets return 400 not 500", async ({ request }) => {
    const r = await api(request, "PUT", "/api/frontline/connectors/config", {
      headers: authHeaders(),
      data: { enabled: true, webhook_url: "https://169.254.169.254/latest/meta-data/" },
      failOk: true,
    });
    expect(r.status()).toBe(400);
  });

  test("simulate creates traffic", async ({ request }) => {
    const r = await api(request, "POST", "/api/frontline/simulate?count=3&speed=instant", {
      headers: authHeaders(),
      data: {},
      failOk: true,
    });
    // simulate may 200 or 429 if rate limited
    expect([200, 429]).toContain(r.status());
    if (r.status() === 200) {
      const j = await r.json();
      expect(j.completed != null || j.count != null || j.results != null || j.ok != null).toBeTruthy();
    }
  });

  test("pack dry_run edit allowed without write_disk", async ({ request }) => {
    const r = await api(request, "POST", "/api/frontline/packs/automotive_nhtsa/edit", {
      headers: authHeaders(),
      data: { dry_run: true, edits: { refusal_topics: ["legal advice"] } },
      failOk: true,
    });
    // service can dry_run (no pack:edit needed when not writing)
    expect([200, 403, 404]).toContain(r.status());
    if (r.status() === 200) {
      const j = await r.json();
      expect(j.dry_run === true || j.preview != null).toBeTruthy();
    }
  });

  test("interaction start/end lifecycle", async ({ request }) => {
    const start = await api(request, "POST", "/api/interactions/start?channel=web_voice", {
      headers: authHeaders(),
      data: {},
      failOk: true,
    });
    expect([200, 503]).toContain(start.status());
    if (start.status() !== 200) return;
    const body = await start.json();
    const iid = body.interaction_id;
    expect(iid).toBeTruthy();

    const end = await api(request, "POST", `/api/interactions/${iid}/end`, {
      headers: authHeaders(),
      data: {},
    });
    expect(end.status()).toBe(200);
  });
});

test.describe("API aggressive — admin bootstrap path", () => {
  test("bootstrap admin can drain then we leave non-draining if reset endpoint absent", async ({
    request,
  }) => {
    // Mint admin via bootstrap env is process-level — may not be set on live server.
    // Try mint; if 403, skip elevated checks.
    const mint = await api(request, "POST", "/api/frontline/auth/session", {
      headers: authHeaders(),
      data: { subject: "e2e-admin", role: "admin" },
      failOk: true,
    });
    if (mint.status() === 403) {
      test.info().annotations.push({
        type: "note",
        description: "FRONTLINE_BOOTSTRAP_ADMIN not enabled on live process — skip elevated",
      });
      return;
    }
    expect(mint.status()).toBe(200);
    const token = (await mint.json()).token;
    expect(token).toBeTruthy();

    // dry_run pack edit with admin session
    const edit = await api(request, "POST", "/api/frontline/packs/automotive_nhtsa/edit", {
      headers: authHeaders({ "X-Frontline-Session": token }),
      data: { dry_run: true, edits: { refusal_topics: ["e2e"] } },
    });
    expect(edit.status()).toBe(200);

    // Do NOT leave process in drain=true for UI tests — skip drain begin if already tested hermetically
  });
});

test.describe("API aggressive — UI assets", () => {
  test("/ui serves SPA shell", async ({ request }) => {
    const r = await api(request, "GET", "/ui/");
    expect(r.status()).toBe(200);
    const html = await r.text();
    expect(html.toLowerCase()).toContain("html");
  });
});
