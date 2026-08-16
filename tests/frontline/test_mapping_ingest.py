"""Mapping.yaml is executed as a real CSV → records loader."""

from __future__ import annotations

from pathlib import Path

from src.config import REPO_ROOT
from src.data.warehouse import domain_con
from src.domains.mapping_ingest import (
    ingest_mapped_csv,
    iter_mapped_rows,
    load_mapping,
    map_row,
)
from src.ml_runtime.embeddings import cosine, embed_text


def test_load_automotive_mapping_has_required_keys():
    m = load_mapping(REPO_ROOT / "domains" / "automotive_nhtsa" / "data" / "mapping.yaml")
    rec = m["records"]
    assert rec["record_id"] == "CMPLID"
    assert rec["text"] == "CDESC"
    assert rec["entity_2"] == "MAKETXT"


def test_map_row_uses_source_columns_and_literal_source():
    m = load_mapping(REPO_ROOT / "domains" / "automotive_nhtsa" / "data" / "mapping.yaml")
    row = {
        "CMPLID": "NHTSA-UNIT-1",
        "DATEA": "20240115",
        "DATEC": "20240110",
        "MODEL_YR": "2019",
        "MAKETXT": "HONDA",
        "MODELTXT": "CR-V",
        "CDESC": "grinding noise when braking",
        "NUM_CYLS": "4",
        "STATE": "CA",
    }
    rec = map_row(row, m["records"])
    assert rec is not None
    assert rec["record_id"] == "NHTSA-UNIT-1"
    assert rec["entity_1"] == "2019"
    assert rec["entity_2"] == "HONDA"
    assert rec["entity_3"] == "CR-V"
    assert rec["category"] == "grinding noise when braking"
    assert rec["text"] == "grinding noise when braking"
    assert rec["region"] == "CA"
    assert rec["source"] == "NHTSA"
    assert rec["received_at"] is not None


def test_ingest_mapped_csv_writes_canonical_records(tmp_path, monkeypatch):
    # Live env path: do not fall back to the session fixture warehouse.
    monkeypatch.setenv("DOMAIN_DB_PATH", str(tmp_path))

    csv_path = tmp_path / "nhtsa_sample.csv"
    csv_path.write_text(
        "CMPLID,DATEA,DATEC,MODEL_YR,MAKETXT,MODELTXT,CDESC,NUM_CYLS,STATE\n"
        "NHTSA-A,20260801,20260728,2019,HONDA,CR-V,grinding noise when braking,4,CA\n"
        "NHTSA-B,20260802,20260729,2018,TOYOTA,CAMRY,airbag warning light stays on,4,TX\n",
        encoding="utf-8",
    )
    mapping = REPO_ROOT / "domains" / "automotive_nhtsa" / "data" / "mapping.yaml"
    result = ingest_mapped_csv(
        "automotive_nhtsa",
        csv_path,
        mapping_path=mapping,
    )
    assert result["upserted"] == 2
    assert result["mapped"] == 2

    with domain_con("automotive_nhtsa") as con:
        n = con.execute("SELECT COUNT(*) FROM records").fetchone()[0]
        rows = con.execute(
            "SELECT record_id, entity_2, text, source, embedding FROM records ORDER BY record_id"
        ).fetchall()
    assert n == 2
    by_id = {r[0]: r for r in rows}
    assert by_id["NHTSA-A"][1] == "HONDA"
    assert "grinding" in by_id["NHTSA-A"][2]
    assert by_id["NHTSA-A"][3] == "NHTSA"
    emb = list(by_id["NHTSA-A"][4])
    assert cosine(emb, embed_text("grinding noise when braking")) > 0.999


def test_iter_mapped_rows_skips_empty_text(tmp_path):
    mapping = load_mapping(REPO_ROOT / "domains" / "automotive_nhtsa" / "data" / "mapping.yaml")
    csv_path = tmp_path / "mixed.csv"
    csv_path.write_text(
        "CMPLID,DATEA,DATEC,MODEL_YR,MAKETXT,MODELTXT,CDESC,NUM_CYLS,STATE\n"
        "KEEP,20240115,20240110,2019,HONDA,CR-V,has text,4,CA\n"
        ",20240115,20240110,2019,HONDA,CR-V,no id,4,CA\n"
        "DROP,20240115,20240110,2019,HONDA,CR-V,,4,CA\n",
        encoding="utf-8",
    )
    rows = list(iter_mapped_rows(csv_path, mapping))
    assert [r["record_id"] for r in rows] == ["KEEP"]
