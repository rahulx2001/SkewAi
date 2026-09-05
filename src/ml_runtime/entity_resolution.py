"""Multi-key entity identity: VIN/serial + make + model.

A pair matches only when the strong key (VIN or serial, namespaced) and make
and model all agree. Sharing make (or make+model without VIN) is not enough.

Scale (item 24): :func:`resolve_matches` blocks by identity key (or
make+model for keyless records) so pairwise comparison is O(block²), not
O(n²). VINs carry an ISO 3779 check digit — :func:`is_valid_vin` validates
it and checksum-invalid 17-character VINs are treated as missing keys (they
never link records).
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

_NON_ALNUM = re.compile(r"[^A-Z0-9]")

# ISO 3779 transliteration (I, O, Q are not allowed in VINs at all).
_VIN_TRANSLITERATION = {
    "A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6, "G": 7, "H": 8,
    "J": 1, "K": 2, "L": 3, "M": 4, "N": 5, "P": 7, "R": 9,
    "S": 2, "T": 3, "U": 4, "V": 5, "W": 6, "X": 7, "Y": 8, "Z": 9,
}
_VIN_WEIGHTS = (8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2)
_VIN_ALLOWED = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")


_SPOKEN_NUMBER_WORDS = {
    "ZERO": "0", "OH": "0", "ONE": "1", "TWO": "2", "THREE": "3", "FOUR": "4",
    "FIVE": "5", "SIX": "6", "SEVEN": "7", "EIGHT": "8", "NINE": "9",
    "DASH": "", "HYPHEN": "", "SPACE": "",
}


def clean_spoken_vin(spoken: Any) -> str:
    """Pre-process ASR-transcribed VINs before ISO 3779 checksum validation.

    Handles common ASR voice transcription errors:
    - Replaces spoken digits ('one' -> '1', 'zero' -> '0', 'oh' -> '0')
    - Maps forbidden ISO 3779 characters 'I' -> '1', 'O' -> '0', 'Q' -> '0'
    - Strips whitespace and punctuation
    """
    if not spoken:
        return ""
    text = str(spoken).upper()
    for word, digit in _SPOKEN_NUMBER_WORDS.items():
        text = re.sub(rf"\b{word}\b", digit, text)
    cleaned = _NON_ALNUM.sub("", text)
    if len(cleaned) == 17:
        # ISO 3779 strictly forbids letters I, O, Q. In voice transcripts, they are ASR misrecognitions.
        repaired = list(cleaned)
        for i, ch in enumerate(repaired):
            if ch == "I":
                repaired[i] = "1"
            elif ch in ("O", "Q"):
                repaired[i] = "0"
        cleaned = "".join(repaired)
    return cleaned


def is_valid_vin(vin: Any) -> bool:
    """ISO 3779 validation: 17 chars, no I/O/Q, check digit (9th) verifies.

    Shorter identifiers (pre-1981 vehicles, serials) are NOT VINs and return
    False — callers must not treat them as checksum failures.
    """
    v = _norm_key(vin)
    if len(v) != 17 or not _VIN_ALLOWED.match(v):
        return False
    total = 0
    for ch, weight in zip(v, _VIN_WEIGHTS):
        if ch.isdigit():
            total += int(ch) * weight
        else:
            total += _VIN_TRANSLITERATION[ch] * weight
    remainder = total % 11
    expected = "X" if remainder == 10 else str(remainder)
    return v[8] == expected


def _norm(val: Any) -> str:
    return str(val or "").strip().upper()


def _norm_key(val: Any) -> str:
    """Alphanumeric-only upper form so '1HG CM82633' == '1HGCM82633'."""
    return _NON_ALNUM.sub("", _norm(val))


def identity_key(record: dict[str, Any]) -> str:
    """Namespaced VIN or serial (vin:XXX / serial:XXX). Empty if missing.

    Namespacing prevents cross-namespace false matches (serial 123 != vin 123).
    A 17-character VIN-shaped value with a bad ISO 3779 check digit is
    treated as MISSING (invalid VINs never link records); shorter values
    pass through for backward compatibility.
    """
    raw_vin = record.get("vin")
    vin = _norm_key(raw_vin)
    if vin:
        if len(vin) == 17 and not is_valid_vin(vin):
            # Attempt ASR spoken repair (e.g. 'O' -> '0', 'I' -> '1')
            repaired = clean_spoken_vin(raw_vin)
            if len(repaired) == 17 and is_valid_vin(repaired):
                return f"vin:{repaired}"
            return ""
        return f"vin:{vin}"
    serial = _norm_key(record.get("serial") or record.get("identity_key"))
    if serial:
        # Heuristic: already-namespaced callers pass through
        if serial.startswith(("VIN", "SERIAL")):
            return serial
        return f"serial:{serial}"
    return ""


def same_entity(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """True iff VIN/serial, make (entity_2), and model (entity_3) all match."""
    vin = identity_key(a)
    if not vin or vin != identity_key(b):
        return False
    make_a = _norm(a.get("entity_2") or a.get("make"))
    make_b = _norm(b.get("entity_2") or b.get("make"))
    model_a = _norm(a.get("entity_3") or a.get("model"))
    model_b = _norm(b.get("entity_3") or b.get("model"))
    if not make_a or make_a != make_b:
        return False
    if not model_a or model_a != model_b:
        return False
    return True


def _block_key(record: dict[str, Any]) -> str:
    """Blocking key: strong identity first, else make+model (item 24).

    Records without any strong key can only match via... nothing (same_entity
    requires a key), so keyless records each land in a make+model block where
    pairwise comparison quickly rules them out — without comparing every
    keyless record against every keyed one.
    """
    key = identity_key(record)
    if key:
        return key
    make = _norm(record.get("entity_2") or record.get("make"))
    model = _norm(record.get("entity_3") or record.get("model"))
    return f"nockey:{make}|{model}"


def resolve_matches(records: list[dict[str, Any]]) -> list[tuple[int, int]]:
    """Index pairs (i, j), i < j, that resolve as the same entity.

    Union-find transitive closure: A=B,B=C implies A=C is also returned.
    Blocking keeps this sub-quadratic: only records sharing a block key are
    ever compared pairwise.
    """
    parent = list(range(len(records)))

    def _find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def _union(a: int, b: int) -> None:
        ra, rb = _find(a), _find(b)
        if ra != rb:
            parent[rb] = ra

    blocks: dict[str, list[int]] = defaultdict(list)
    for i, rec in enumerate(records):
        blocks[_block_key(rec)].append(i)
    for members in blocks.values():
        for a in range(len(members)):
            for b in range(a + 1, len(members)):
                i, j = members[a], members[b]
                if same_entity(records[i], records[j]):
                    _union(i, j)
    # Expand components into all pairs
    comps: dict[int, list[int]] = defaultdict(list)
    for i in range(len(records)):
        comps[_find(i)].append(i)
    pairs: list[tuple[int, int]] = []
    for members in comps.values():
        if len(members) < 2:
            continue
        for a in range(len(members)):
            for b in range(a + 1, len(members)):
                pairs.append((members[a], members[b]))
    return sorted(pairs)


def levenshtein_distance(s1: str, s2: str) -> int:
    """Standard Levenshtein edit distance between two strings."""
    if s1 == s2:
        return 0
    if not s1:
        return len(s2)
    if not s2:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1] * (len(s2) + 1)
        for j, c2 in enumerate(s2):
            cost = 0 if c1 == c2 else 1
            curr[j + 1] = min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost)
        prev = curr
    return prev[len(s2)]


def jaro_winkler_similarity(s1: str, s2: str, prefix_weight: float = 0.1) -> float:
    """Jaro-Winkler string similarity (0.0 to 1.0)."""
    if s1 == s2:
        return 1.0
    len1, len2 = len(s1), len(s2)
    if len1 == 0 or len2 == 0:
        return 0.0

    match_distance = max(len1, len2) // 2 - 1
    if match_distance < 0:
        match_distance = 0

    s1_matches = [False] * len1
    s2_matches = [False] * len2
    matches = 0
    transpositions = 0

    for i in range(len1):
        start = max(0, i - match_distance)
        end = min(i + match_distance + 1, len2)
        for j in range(start, end):
            if s2_matches[j] or s1[i] != s2[j]:
                continue
            s1_matches[i] = True
            s2_matches[j] = True
            matches += 1
            break

    if matches == 0:
        return 0.0

    k = 0
    for i in range(len1):
        if not s1_matches[i]:
            continue
        while not s2_matches[k]:
            k += 1
        if s1[i] != s2[k]:
            transpositions += 1
        k += 1

    jaro = (
        (matches / len1) + (matches / len2) + ((matches - transpositions / 2) / matches)
    ) / 3.0

    prefix_len = 0
    for i in range(min(4, min(len1, len2))):
        if s1[i] == s2[i]:
            prefix_len += 1
        else:
            break

    return jaro + prefix_len * prefix_weight * (1.0 - jaro)


def fuzzy_same_entity(
    a: dict[str, Any],
    b: dict[str, Any],
    min_similarity: float = 0.88,
) -> tuple[bool, float]:
    """Probabilistic / fuzzy entity matching (audit 3.1).

    Returns (is_match, confidence_score [0.0..1.0]).
    Catches OCR/typo variations in VINs, serials, and model strings.
    """
    if same_entity(a, b):
        return True, 1.0

    make_a = _norm(a.get("entity_2") or a.get("make"))
    make_b = _norm(b.get("entity_2") or b.get("make"))
    if not make_a or not make_b:
        return False, 0.0
    make_sim = jaro_winkler_similarity(make_a, make_b)
    if make_sim < 0.80:
        return False, 0.0

    model_a = _norm(a.get("entity_3") or a.get("model"))
    model_b = _norm(b.get("entity_3") or b.get("model"))
    model_sim = jaro_winkler_similarity(model_a, model_b) if (model_a and model_b) else 0.7

    key_a = _norm_key(a.get("vin") or a.get("serial") or a.get("identity_key"))
    key_b = _norm_key(b.get("vin") or b.get("serial") or b.get("identity_key"))

    if key_a and key_b:
        key_sim = jaro_winkler_similarity(key_a, key_b)
        overall = 0.6 * key_sim + 0.2 * make_sim + 0.2 * model_sim
        return overall >= min_similarity, round(overall, 3)

    return False, 0.0


def resolve_fuzzy_matches(
    records: list[dict[str, Any]],
    min_similarity: float = 0.88,
) -> list[tuple[int, int, float]]:
    """Return pairs (i, j, confidence) matching fuzzily above min_similarity."""
    blocks: dict[str, list[int]] = defaultdict(list)
    for i, rec in enumerate(records):
        make = _norm(rec.get("entity_2") or rec.get("make"))[:3]
        blocks[make or "other"].append(i)

    results: list[tuple[int, int, float]] = []
    seen = set()
    for members in blocks.values():
        for a in range(len(members)):
            for b in range(a + 1, len(members)):
                i, j = members[a], members[b]
                pair_key = (min(i, j), max(i, j))
                if pair_key in seen:
                    continue
                seen.add(pair_key)
                matches, score = fuzzy_same_entity(
                    records[i], records[j], min_similarity=min_similarity
                )
                if matches:
                    results.append((pair_key[0], pair_key[1], score))
    return sorted(results, key=lambda x: (x[0], x[1]))


# ── Canonical Identity & Observation Persistence (0-R2) ─────────────────────

from contextlib import nullcontext


def _con_context(con: Any):
    if con is not None:
        return nullcontext(con)
    from src.data.warehouse import ops_con
    return ops_con()


def record_entity_observation(
    *,
    interaction_id: str,
    raw_spoken_text: str,
    extracted_vin: str | None = None,
    confidence: float = 1.0,
    vin_status: str = "observed",
    source_channel: str = "voice",
    con: Any = None,
) -> str:
    """Record a raw or partially resolved entity observation with full provenance."""
    from src.data.timeutil import utc_now
    from src.ids import new_ulid

    obs_id = "obs_" + new_ulid()
    now = utc_now()

    try:
        with _con_context(con) as c:
            c.execute(
                """
                INSERT INTO entity_observations (
                    observation_id, interaction_id, raw_spoken_text,
                    extracted_vin, confidence, vin_status, source_channel, observed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    obs_id,
                    interaction_id,
                    raw_spoken_text[:500] if raw_spoken_text else "",
                    extracted_vin,
                    confidence,
                    vin_status,
                    source_channel,
                    now,
                ],
            )
    except Exception:
        pass
    return obs_id


def get_or_create_canonical_identity(
    *,
    vin: str | None = None,
    make: str | None = None,
    model: str | None = None,
    year: int | str | None = None,
    identity_status: str = "unverified",
    source: str = "voice_intake",
    metadata: dict[str, Any] | None = None,
    con: Any = None,
) -> dict[str, Any]:
    """Retrieve or insert a durable canonical vehicle identity.

    Distinguishes observed/candidate claims from verified cross-source identities.
    """
    import json
    from src.data.timeutil import utc_now
    from src.ids import new_ulid

    key = identity_key({"vin": vin}) if vin else ""
    if not key and make and model:
        # Fallback keyless identity key when VIN is unknown
        key = f"keyless:{_norm(make)}|{_norm(model)}|{year or 'unknown'}"

    if not key:
        return {
            "canonical_id": "",
            "identity_key": "",
            "identity_status": "unverified",
            "vin": vin,
            "make": make,
            "model": model,
            "year": year,
        }

    now = utc_now()
    year_int = int(year) if year and str(year).isdigit() else None
    meta_str = json.dumps(metadata or {})

    try:
        with _con_context(con) as c:
            row = c.execute(
                """
                SELECT canonical_id, identity_key, vin, make, model, year, identity_status,
                       first_observed_at, last_verified_at, source, metadata_json
                FROM canonical_identity
                WHERE identity_key = ?
                """,
                [key],
            ).fetchone()

            if row:
                return {
                    "canonical_id": row[0],
                    "identity_key": row[1],
                    "vin": row[2],
                    "make": row[3],
                    "model": row[4],
                    "year": row[5],
                    "identity_status": row[6],
                    "first_observed_at": row[7],
                    "last_verified_at": row[8],
                    "source": row[9],
                    "metadata": json.loads(row[10] or "{}"),
                }

            cid = "cid_" + new_ulid()
            c.execute(
                """
                INSERT INTO canonical_identity (
                    canonical_id, identity_key, vin, make, model, year,
                    identity_status, first_observed_at, source, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [cid, key, vin, _norm(make), _norm(model), year_int, identity_status, now, source, meta_str],
            )
            return {
                "canonical_id": cid,
                "identity_key": key,
                "vin": vin,
                "make": _norm(make),
                "model": _norm(model),
                "year": year_int,
                "identity_status": identity_status,
                "first_observed_at": now,
                "source": source,
                "metadata": metadata or {},
            }
    except Exception:
        # Graceful fallback if table is unavailable
        from src.ids import new_ulid

        return {
            "canonical_id": "cid_" + new_ulid(),
            "identity_key": key,
            "vin": vin,
            "make": make,
            "model": model,
            "year": year_int,
            "identity_status": identity_status,
        }


def find_canonical_identity(vin: str, *, con: Any = None) -> dict[str, Any] | None:
    """Find an existing canonical identity by VIN."""
    import json

    key = identity_key({"vin": vin})
    if not key:
        return None

    try:
        with _con_context(con) as c:
            row = c.execute(
                """
                SELECT canonical_id, identity_key, vin, make, model, year, identity_status,
                       first_observed_at, last_verified_at, source, metadata_json
                FROM canonical_identity
                WHERE identity_key = ?
                """,
                [key],
            ).fetchone()

            if not row:
                return None
            return {
                "canonical_id": row[0],
                "identity_key": row[1],
                "vin": row[2],
                "make": row[3],
                "model": row[4],
                "year": row[5],
                "identity_status": row[6],
                "first_observed_at": row[7],
                "last_verified_at": row[8],
                "source": row[9],
                "metadata": json.loads(row[10] or "{}"),
            }
    except Exception:
        return None


__all__ = [
    "identity_key",
    "is_valid_vin",
    "clean_spoken_vin",
    "same_entity",
    "resolve_matches",
    "levenshtein_distance",
    "jaro_winkler_similarity",
    "fuzzy_same_entity",
    "resolve_fuzzy_matches",
    "record_entity_observation",
    "get_or_create_canonical_identity",
    "find_canonical_identity",
]

