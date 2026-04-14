"""
Point-in-Polygon Cluster Assignment + Financial Calculations.
"""
import pandas as pd
import numpy as np
import streamlit as st
from shapely.wkt import loads as load_wkt
from shapely.geometry import Point
from shapely.prepared import prep
from utils import DESCRIPTION_MAPPING, FALLBACK_PINCODE_MAP


@st.cache_resource(ttl=3600)
def load_clusters(polygon_df):
    df = polygon_df.copy()
    df.columns = df.columns.str.strip()
    clusters = []
    for _, row in df.iterrows():
        try:
            polygon = load_wkt(row["Polygon WKT"])
            clusters.append({
                "prepared": prep(polygon), "polygon": polygon,
                "name": row.get("Cluster_Code", row.get("cluster_code", "")),
                "description": row.get("Cluster_Category", row.get("cluster_category", "")),
                "description_raw": row.get("Description", ""),
            })
        except Exception:
            continue
    return clusters


def get_cluster_for_point(lat, lon, clusters):
    if pd.isna(lat) or pd.isna(lon): return None, None
    try:
        point = Point(float(lon), float(lat))  # Shapely: (lon, lat)
    except (ValueError, TypeError):
        return None, None
    for c in clusters:
        if c["prepared"].contains(point):
            return c["name"], c["description"]
    return None, None


def assign_clusters(awb_df, polygon_df, spa_mapping, progress_cb=None):
    clusters = load_clusters(polygon_df)
    df = awb_df.copy()
    df.columns = df.columns.str.strip().str.lower()
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["long"] = pd.to_numeric(df["long"], errors="coerce")
    df = df.dropna(subset=["lat", "long"])
    df = df[(df["lat"] != 0) & (df["long"] != 0)].copy()

    results = []
    total = len(df)
    for i, (_, row) in enumerate(df.iterrows()):
        lat, lon, pc = row["lat"], row["long"], row.get("pincode", "")
        name, desc = get_cluster_for_point(lat, lon, clusters)
        if not name:
            try:
                pc_int = int(float(str(pc)))
                if pc_int in FALLBACK_PINCODE_MAP:
                    name, desc = "Previous mapping", FALLBACK_PINCODE_MAP[pc_int]
            except (ValueError, TypeError):
                pass
        pc_str = str(pc).strip().replace(".0", "").strip()
        payment = spa_mapping.get(pc_str, spa_mapping.get(
            int(float(pc_str)) if pc_str.replace('.', '', 1).isdigit() else pc_str, None))
        results.append({
            "order_date": row.get("order_date", ""),
            "awb_number": row.get("fwd_del_awb_number", row.get("awb_number", "")),
            "rider_id": row.get("rider_id", ""), "pincode": pc,
            "payment_category": payment, "hub": row.get("hub", ""),
            "lat": lat, "long": lon, "cluster_name": name, "description": desc,
        })
        if progress_cb and (i % 500 == 0 or i == total - 1):
            progress_cb((i + 1) / total)
    return pd.DataFrame(results)


def calculate_financials(df):
    r = df.copy()
    r["Pin_Pay"] = pd.to_numeric(r["payment_category"], errors="coerce")
    r["Clustering_payout"] = r["description"].map(DESCRIPTION_MAPPING).fillna(r["Pin_Pay"])
    r["P & L"] = r["Pin_Pay"] - r["Clustering_payout"]
    r["Saving"] = r["P & L"].apply(lambda x: x if x > 0 else 0)
    r["Burning"] = r["P & L"].apply(lambda x: -x if x < 0 else 0)
    fin_cols = ["Pin_Pay", "Clustering_payout", "Saving", "Burning", "P & L"]
    mask = ~(r[fin_cols].fillna(0) == 0).all(axis=1)
    return r[mask].reset_index(drop=True)


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
