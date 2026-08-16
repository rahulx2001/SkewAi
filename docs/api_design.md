# Frontline v2 API design (optimized)

Date: 2026-07-22  
Spec: [openapi.yaml](./openapi.yaml) · Live docs: `/docs` · Generated OpenAPI: `/openapi.json`

## Goals

Make the pilot HTTP surface consistent, discoverable, and evolvable without
breaking the existing dashboard (`count` + resource arrays stay).

## Resource model

| Resource | Collection | Item | Nested |
|----------|------------|------|--------|
| Interaction | `GET /api/interactions` | `GET /api/interactions/{id}` | start / end / takeover / release |
| Pack | `GET /api/packs` | `GET /api/packs/{id}` | `PUT /api/packs/active` |
| Case | `GET /api/frontline/cases` | `GET/PATCH …/cases/{id}` | notes, export, connector export |
| Investigation | `GET …/investigations` | `GET/PATCH …/investigations/{id}` | — |
| Audit | `GET …/audits` | `GET …/audits/{interaction_id}` | export |
| Enterprise explorers | under `/api/frontline/enterprise/*` | timeline, risk, graph, memory, scenarios | — |

WebSockets remain root-mounted: `/ws/interaction/{id}`, `/ws/console` (not under `/api`).

## Auth

| Mode | Behavior |
|------|----------|
| `FRONTLINE_API_KEY` empty | Open local/dev (tests, `make contact`) |
| Key set | Require `X-API-Key` or `Authorization: Bearer` |

Discovery: `GET /` → `auth.required`, `auth.headers`.

## Versioning

- **Current:** API version **`1`**
- **Signal:** every HTTP response includes header `API-Version: 1`; body fields `api_version` on `/` and `/health`
- **URL:** `/api/...` is the v1 surface (no `/v1` prefix — pilot simplicity)
- **Breaking changes:** introduce `/api/v2/...`, keep v1 until a documented deprecation window ends

## Pagination

All major collections accept:

| Param | Meaning |
|-------|---------|
| `limit` | Page size (clamped; default 50, max 500 unless noted) |
| `offset` | Zero-based offset |
| `cursor` | Opaque token encoding offset (optional) |

Response always keeps the existing array key + `count` (page size returned), and adds:

```json
"pagination": {
  "limit": 50,
  "offset": 0,
  "returned": 50,
  "has_more": true,
  "next_offset": 50,
  "next_cursor": "...",
  "total": null
}
```

`total` is present when known (full page not filled); otherwise `has_more` is inferred by fetching `limit+1`.

## Errors (RFC 7807-shaped)

```json
{
  "type": "about:blank#not-found",
  "title": "Not Found",
  "status": 404,
  "detail": "case not found: case_xyz",
  "instance": "/api/frontline/cases/case_xyz"
}
```

- `detail` remains a **string** (FastAPI / dashboard compatible).
- Validation errors include `errors: [{field, message, type}]`.
- Clients that send `Accept: application/problem+json` receive that media type.

Stable `type` URIs:

| Status | type |
|--------|------|
| 400 | `about:blank#bad-request` |
| 401 | `about:blank#unauthorized` |
| 404 | `about:blank#not-found` |
| 409 | `about:blank#conflict` |
| 422 | `about:blank#validation-error` |
| 429 | `about:blank#rate-limited` |
| 503 | `about:blank#service-unavailable` |

## Rate limiting

`slowapi` remains on write-heavy routes (`/start`, `/simulate`). 429 responses should be retried with backoff; multi-instance limits are process-local (documented residual).

## Naming conventions

- **snake_case** JSON fields (existing pilot contract)
- Plural collection nouns: `cases`, `interactions`, `investigations`
- Actions as subresources or RPC-style POST only when not pure CRUD: `/takeover`, `/replay`, `/copilot`

## Backward compatibility

| Kept | Added |
|------|--------|
| Resource array keys | `pagination` object |
| `count` = page length | `API-Version` header |
| String `detail` on errors | `type`, `title`, `status` on errors |
| `/api/...` paths | Discovery `links` on `/` |

## Enterprise Ops improvements (2026-07-22)

Additive routes (deterministic / offline-honest):

| Path | Purpose |
|------|---------|
| `GET /api/frontline/enterprise/interactions/recent` | Picker catalog for timeline/RCA/decision |
| `GET /api/frontline/enterprise/risk/{id}/history` | Stored risk_snapshots for one contact |
| `GET /api/frontline/enterprise/risk/active?persist=true` | Optionally persist scores while listing |
| `POST /api/frontline/enterprise/scenarios/validate` | Pure step validation before save/run |

Copilot remains an intent router (not a generative LLM).

## Validation

```bash
# Live OpenAPI from FastAPI
curl -s http://127.0.0.1:8000/openapi.json | head

# Optional: lint the hand-maintained contract
# npx @redocly/cli lint docs/openapi.yaml
```

Unit tests: `tests/frontline/test_api_design.py`.
