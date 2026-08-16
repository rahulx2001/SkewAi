"""NHTSA FLAT line → mapping.yaml CSV row (no network)."""

from scripts.ingest_nhtsa import CSV_HEADERS, _FLAT_FIELDS, flat_line_to_mapping_row


def test_flat_tab_line_maps_to_mapping_headers():
    parts = [""] * len(_FLAT_FIELDS)
    idx = {n: i for i, n in enumerate(_FLAT_FIELDS)}
    parts[idx["CMPLID"]] = "16123456"
    parts[idx["MAKETXT"]] = "HONDA"
    parts[idx["MODELTXT"]] = "CR-V"
    parts[idx["YEARTXT"]] = "2019"
    parts[idx["FAILDATE"]] = "20240110"
    parts[idx["DATEA"]] = "20240115"
    parts[idx["CDESCR"]] = "BRAKES GRIND AT LOW SPEED"
    parts[idx["STATE"]] = "CA"
    parts[idx["NUM_CYLS"]] = "4"
    line = "\t".join(parts)
    row = flat_line_to_mapping_row(line)
    assert row is not None
    assert set(row) == set(CSV_HEADERS)
    assert row["CMPLID"] == "16123456"
    assert row["MODEL_YR"] == "2019"
    assert row["CDESC"] == "BRAKES GRIND AT LOW SPEED"
    assert row["DATEC"] == "20240110"
