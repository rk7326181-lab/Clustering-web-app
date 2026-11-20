"""
Pincode-indexed store for the bundled All-India pincode boundaries.

data/geojson_boundaries.json.gz holds 19,312 features (~90 MB of JSON). Parsing it
takes ~10 s and ~500 MB of RAM, yet a session only needs the few dozen pincodes in
its cluster sheet. data/geojson_boundaries.parquet keeps one row per feature
(pincode, original position, the feature as JSON), sorted by pincode in small row
groups, so features_for() reads just the requested pincodes in well under a second.

The store records the SHA-1 of the .json.gz it was built from; if the .gz changes and
the store is not rebuilt, the store is ignored (callers fall back to parsing the .gz),
so it can never serve outdated boundaries.

Rebuild after replacing the .json.gz:
    python -m modules.boundary_store
"""
import gzip
import hashlib
import json
import os

import streamlit as st

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_PATH = os.path.join(_REPO_ROOT, "data", "geojson_boundaries.json.gz")
STORE_PATH = os.path.join(_REPO_ROOT, "data", "geojson_boundaries.parquet")
_PIN_FIELDS = ["pincode", "Pincode", "PINCODE", "pin", "PIN"]


def norm_pin(value) -> str:
    """Same normalisation utils._filter_geojson_to_cluster has always used."""
    return str(value).strip().replace(".0", "")


def _sha1(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_store(source=SOURCE_PATH, out=STORE_PATH):
    """Convert the bundled .json.gz into the pincode-indexed Parquet store."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    with gzip.open(source, "rt", encoding="utf-8") as f:
        data = json.load(f)
    feats = data.get("features", [])
    sample = feats[0].get("properties", {}) if feats else {}
    pf = next((k for k in _PIN_FIELDS if k in sample), None)
    rows = sorted(
        ((norm_pin(f.get("properties", {}).get(pf, "")), i, json.dumps(f, ensure_ascii=False, separators=(",", ":")))
         for i, f in enumerate(feats)),
        key=lambda r: (r[0], r[1]))
    table = pa.table({"pincode": [r[0] for r in rows], "idx": [r[1] for r in rows], "feature": [r[2] for r in rows]})
    header = {k: v for k, v in data.items() if k != "features"}
    table = table.replace_schema_metadata({
        "pincode_field": pf or "", "header": json.dumps(header), "source_sha1": _sha1(source),
        "features": str(len(feats))})
    tmp = out + ".tmp"
    pq.write_table(table, tmp, compression="zstd", row_group_size=256)
    os.replace(tmp, out)
    return len(feats)


@st.cache_resource(max_entries=1, show_spinner=False)
def _meta(store_mtime, source_mtime):
    """Store metadata, or None when the store is missing or was built from another .gz."""
    try:
        import pyarrow.parquet as pq
        md = {k.decode(): v.decode() for k, v in (pq.read_schema(STORE_PATH).metadata or {}).items()}
        if os.path.exists(SOURCE_PATH) and md.get("source_sha1") != _sha1(SOURCE_PATH):
            return None
        return {"pincode_field": md.get("pincode_field") or None,
                "header": json.loads(md.get("header") or "{}"),
                "features": int(md.get("features") or 0)}
    except Exception:
        return None


def meta():
    """Metadata of a usable store, else None (missing, unreadable or out of date)."""
    if not os.path.exists(STORE_PATH):
        return None
    src_mtime = os.path.getmtime(SOURCE_PATH) if os.path.exists(SOURCE_PATH) else 0
    return _meta(os.path.getmtime(STORE_PATH), src_mtime)


@st.cache_data(max_entries=16, show_spinner=False)
def features_for(pins: tuple) -> dict:
    """GeoJSON FeatureCollection with only the features whose pincode is in `pins`
    (normalised with norm_pin), in the original file order: exactly what filtering
    the full parsed file gave before."""
    import pyarrow.parquet as pq
    m = meta() or {"header": {"type": "FeatureCollection"}}
    wanted = sorted({norm_pin(p) for p in pins})
    if not wanted:
        return {**m["header"], "features": []}
    t = pq.read_table(STORE_PATH, columns=["idx", "feature"], filters=[("pincode", "in", wanted)])
    order = sorted(range(t.num_rows), key=t.column("idx").to_pylist().__getitem__)
    feats = t.column("feature").to_pylist()
    return {**m["header"], "features": [json.loads(feats[i]) for i in order]}


if __name__ == "__main__":
    n = build_store()
    print(f"Built {STORE_PATH}: {n:,} features, {os.path.getsize(STORE_PATH) / 1e6:.1f} MB")
