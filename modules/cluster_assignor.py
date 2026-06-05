"""
Point-in-Polygon Cluster Assignment + Financial Calculations.
Uses Shapely STRtree spatial index for fast lookups.
"""
import pandas as pd
import numpy as np
import streamlit as st
from shapely.wkt import loads as load_wkt
from shapely.geometry import Point
from shapely.prepared import prep
from shapely import STRtree
from utils import DESCRIPTION_MAPPING, FALLBACK_PINCODE_MAP


@st.cache_resource(ttl=3600)
def load_clusters(polygon_df):
    df = polygon_df.copy()
    df.columns = df.columns.str.strip()
    clusters = []
    polygons = []
    for _, row in df.iterrows():
        try:
            polygon = load_wkt(row["Polygon WKT"])
            clusters.append({
                "prepared": prep(polygon), "polygon": polygon,
                "name": row.get("Cluster_Code", row.get("cluster_code", "")),
                "description": row.get("Cluster_Category", row.get("cluster_category", "")),
                "description_raw": row.get("Description", ""),
            })
            polygons.append(polygon)
        except Exception:
            continue
    # Build spatial index for fast lookups
    tree = STRtree(polygons) if polygons else None
    return clusters, polygons, tree


def get_cluster_for_point(lat, lon, clusters, polygons=None, tree=None):
    if pd.isna(lat) or pd.isna(lon): return None, None
    try:
        point = Point(float(lon), float(lat))  # Shapely: (lon, lat)
    except (ValueError, TypeError):
        return None, None

    # Use spatial index if available — much faster than linear scan
    if tree is not None and polygons:
        candidates = tree.query(point)
        for idx in candidates:
            if clusters[idx]["prepared"].contains(point):
                return clusters[idx]["name"], clusters[idx]["description"]
        return None, None

    # Fallback: linear scan
    for c in clusters:
        if c["prepared"].contains(point):
            return c["name"], c["description"]
    return None, None


def assign_clusters(awb_df, polygon_df, spa_mapping, progress_cb=None):
    """Vectorised point-in-polygon using geopandas sjoin (Shapely 2 + GEOS).
    Replaces the O(n * m) iterrows loop that timed out on large datasets."""
    import geopandas as gpd

    clusters, polygons, tree = load_clusters(polygon_df)

    df = awb_df.copy()
    df.columns = df.columns.str.strip().str.lower()
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["long"] = pd.to_numeric(df["long"], errors="coerce")
    df = df.dropna(subset=["lat", "long"])
    df = df[(df["lat"] != 0) & (df["long"] != 0)].reset_index(drop=True)

    if df.empty:
        return pd.DataFrame(columns=[
            "order_date", "awb_number", "rider_id", "pincode",
            "payment_category", "hub", "lat", "long", "cluster_name", "description",
        ])

    n = len(df)
    lats = df["lat"].to_numpy()
    lons = df["long"].to_numpy()

    def _col(name, *aliases):
        for k in (name,) + aliases:
            if k in df.columns:
                return df[k].to_numpy()
        return np.full(n, "", dtype=object)

    pincodes    = _col("pincode")
    order_dates = _col("order_date")
    awb_numbers = _col("fwd_del_awb_number", "awb_number")
    rider_ids   = _col("rider_id")
    hubs        = _col("hub")

    cluster_name_col = np.full(n, None, dtype=object)
    description_col  = np.full(n, None, dtype=object)

    if progress_cb:
        progress_cb(0.05)

    # ── Spatial join (vectorised) ─────────────────────────────────────────────
    if clusters and polygons:
        # Build pin→hub map from AWB data (most frequent hub per pincode).
        # Used to tag each polygon with its own hub so cross-hub polygon
        # leakage is rejected before accepting a match (fixes inflated burn
        # where neighbouring hubs' overlapping polygons captured wrong AWBs).
        pin2hub: dict = {}
        if len(hubs) > 0:
            _hub_series = pd.Series(hubs, dtype=object)
            _pin_series = pd.Series(pincodes)
            _hub_notnull = _hub_series.notna() & (_hub_series != "")
            if _hub_notnull.any():
                _tmp = pd.DataFrame({"pin": _pin_series, "hub": _hub_series})[_hub_notnull]
                pin2hub = (
                    _tmp.groupby("pin")["hub"]
                    .agg(lambda s: s.mode().iloc[0])
                    .to_dict()
                )

        def _poly_hub(name):
            """Derive hub from cluster name prefix e.g. '277209_B' → hub of pin 277209."""
            parts = str(name).split("_")
            if parts and parts[0].replace(".", "").isdigit():
                try:
                    return pin2hub.get(int(float(parts[0])))
                except (ValueError, TypeError):
                    pass
            return None

        pts_gdf = gpd.GeoDataFrame(
            {"_orig_i": np.arange(n), "awb_hub": hubs},
            geometry=gpd.points_from_xy(lons, lats),
            crs="EPSG:4326",
        )
        polys_gdf = gpd.GeoDataFrame(
            {
                "cluster_name": [c["name"] for c in clusters],
                "description":  [c["description"] for c in clusters],
                "poly_hub":     [_poly_hub(c["name"]) for c in clusters],
            },
            geometry=[c["polygon"] for c in clusters],
            crs="EPSG:4326",
        )

        if progress_cb:
            progress_cb(0.20)

        joined = gpd.sjoin(pts_gdf, polys_gdf, how="left", predicate="within")

        # Drop cross-hub matches BEFORE dedup so a same-hub polygon is never
        # shadowed by an earlier cross-hub match in the CSV row order.
        # Keep a row when: no polygon matched (NaN), AWB hub unknown, or hubs agree.
        keep = (
            joined["cluster_name"].isna()
            | joined["awb_hub"].isna()
            | (joined["awb_hub"].astype(str) == "")
            | (joined["awb_hub"] == joined["poly_hub"])
        )
        joined = joined[keep]
        joined = joined.drop_duplicates(subset=["_orig_i"])
        matched = joined[joined["cluster_name"].notna()]
        if not matched.empty:
            mi = matched["_orig_i"].to_numpy().astype(int)
            cluster_name_col[mi] = matched["cluster_name"].to_numpy()
            description_col[mi]  = matched["description"].to_numpy()

    if progress_cb:
        progress_cb(0.70)

    # ── Pincode fallback for unmatched rows ───────────────────────────────────
    unmatched = pd.isnull(cluster_name_col)
    if unmatched.any():
        for i in np.where(unmatched)[0]:
            try:
                pc_int = int(float(str(pincodes[i])))
                if pc_int in FALLBACK_PINCODE_MAP:
                    cluster_name_col[i] = "Previous mapping"
                    description_col[i]  = FALLBACK_PINCODE_MAP[pc_int]
            except (ValueError, TypeError):
                pass

    # ── Payment mapping ───────────────────────────────────────────────────────
    pc_str_series = (
        pd.Series(pincodes).astype(str).str.strip()
        .str.replace(".0", "", regex=False).str.strip()
    )
    payment_col = pc_str_series.map(spa_mapping)
    need_int = payment_col.isna()
    if need_int.any():
        for idx in payment_col.index[need_int]:
            ps = pc_str_series.iloc[idx]
            if ps.replace(".", "", 1).isdigit():
                try:
                    payment_col.iloc[idx] = spa_mapping.get(int(float(ps)))
                except (ValueError, TypeError):
                    pass

    if progress_cb:
        progress_cb(1.0)

    return pd.DataFrame({
        "order_date":       order_dates,
        "awb_number":       awb_numbers,
        "rider_id":         rider_ids,
        "pincode":          pincodes,
        "payment_category": payment_col.to_numpy(),
        "hub":              hubs,
        "lat":              lats,
        "long":             lons,
        "cluster_name":     cluster_name_col,
        "description":      description_col,
    })


def calculate_financials(df):
    r = df.copy()
    r["Pin_Pay"] = pd.to_numeric(r["payment_category"], errors="coerce")
    r["Clustering_payout"] = r["description"].map(DESCRIPTION_MAPPING).fillna(r["Pin_Pay"])
    r["P & L"] = r["Pin_Pay"] - r["Clustering_payout"]
    r["Saving"] = r["P & L"].apply(lambda x: x if x > 0 else 0)
    r["Burning"] = r["P & L"].apply(lambda x: -x if x < 0 else 0)
    # Flag outside-zone orders (delivery not inside any cluster polygon)
    r["outside_zone"] = r["cluster_name"].isna() | (r["cluster_name"].astype(str).str.strip() == "")
    fin_cols = ["Pin_Pay", "Clustering_payout", "Saving", "Burning", "P & L"]
    # Keep rows with financial data OR valid delivery coordinates (outside-zone visibility)
    has_financial = ~(r[fin_cols].fillna(0) == 0).all(axis=1)
    has_coords = (
        r["lat"].notna() & r["long"].notna()
        & (pd.to_numeric(r["lat"], errors="coerce") != 0)
        & (pd.to_numeric(r["long"], errors="coerce") != 0)
    )
    return r[has_financial | has_coords].reset_index(drop=True)


def build_spa_mapping(final_output_df):
    df = final_output_df.copy()
    df.columns = df.columns.str.strip()
    df["SP&A Aligned P mapping"] = (
        df["SP&A Aligned P mapping"].astype(str)
        .str.replace("₹", "", regex=False).str.replace(",", "", regex=False).str.strip()
        .replace({"Nil": float("nan"), "nan": float("nan"), "": float("nan")})
    )
    df["SP&A Aligned P mapping"] = pd.to_numeric(df["SP&A Aligned P mapping"], errors="coerce")
    mapping = {}
    for _, row in df.iterrows():
        pc = str(row["Pincode"]).strip().replace(".0", "")
        val = row["SP&A Aligned P mapping"]
        mapping[pc] = val
        try: mapping[int(pc)] = val
        except ValueError: pass
    return mapping
