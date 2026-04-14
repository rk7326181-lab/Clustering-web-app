"""
Shared utilities — constants, geometry functions, helpers, session state.
"""
import math
import os
import time
import pandas as pd
import numpy as np
import streamlit as st
from io import BytesIO
from datetime import datetime

# ============================================================
# IMMUTABLE CONSTANTS
# ============================================================

CLUSTER_MAP = {
    "₹0": "C1", "₹1": "C3", "₹2": "C5", "₹3": "C7", "₹4": "C9",
    "₹5": "C11", "₹6": "C12", "₹7": "C13", "₹8": "C14", "₹9": "C15",
    "₹10": "C16", "₹11": "C17", "₹12": "C18", "₹13": "C19", "₹15": "C20",
}

DESCRIPTION_MAPPING = {
    "C1": 0, "C2": 0.5, "C3": 1, "C4": 1.5, "C5": 2, "C6": 2.5,
    "C7": 3, "C8": 3.5, "C9": 4, "C10": 4.5, "C11": 5, "C12": 6,
    "C13": 7, "C14": 8, "C15": 9, "C16": 10, "C17": 11, "C18": 12,
    "C19": 13, "C20": 15,
}

PRICING_SLABS = [
    (0, 5, "₹0"), (5, 10, "₹1"), (10, 15, "₹2"), (15, 20, "₹3"),
    (20, 25, "₹4"), (25, 30, "₹5"), (30, 35, "₹6"), (35, 40, "₹7"),
    (40, 45, "₹8"),
]

FALLBACK_PINCODE_MAP = {
    580011: "C4", 203209: "C8", 282009: "C6",
    584128: "C2", 110074: "C2", 800001: "C0",
}

OUTPUT_DIR = "outputs"
HUB_IMG_DIR = os.path.join(OUTPUT_DIR, "Hub_Payout_Views_Final_All_Hubs")

# Hub color palette — light, semi-transparent, distinct per hub
HUB_COLORS = [
    "#3498db", "#2ecc71", "#e67e22", "#9b59b6", "#e74c3c",
    "#1abc9c", "#f39c12", "#8e44ad", "#2980b9", "#27ae60",
    "#d35400", "#c0392b", "#16a085", "#f1c40f", "#7f8c8d",
    "#2c3e50", "#95a5a6", "#d4a017", "#574b90", "#cf6a87",
]

RATE_COLORS = {
    0: "#2ecc71", 0.5: "#27ae60", 1: "#3498db", 1.5: "#2980b9",
    2: "#9b59b6", 2.5: "#8e44ad", 3: "#e67e22", 3.5: "#d35400",
    4: "#e74c3c", 4.5: "#c0392b", 5: "#f39c12", 6: "#d4a017",
    7: "#ff6b6b", 8: "#ee5a24", 9: "#c44569", 10: "#574b90",
    11: "#303952", 12: "#596275", 13: "#786fa6", 15: "#cf6a87",
}


# ============================================================
# GEOMETRY UTILITIES — IMMUTABLE — DO NOT MODIFY
# ============================================================

def destination_point(lat, lon, bearing, distance_km):
    """Spherical Earth projection. Args: (lat, lon) geographic order."""
    R = 6371
    bearing = math.radians(bearing)
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    lat2 = math.asin(
        math.sin(lat1) * math.cos(distance_km / R)
        + math.cos(lat1) * math.sin(distance_km / R) * math.cos(bearing)
    )
    lon2 = lon1 + math.atan2(
        math.sin(bearing) * math.sin(distance_km / R) * math.cos(lat1),
        math.cos(distance_km / R) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), math.degrees(lon2)


def create_circle_polygon(lat, lon, radius_km, points=15):
    """Create circle polygon. Returns Shapely Polygon with (lon, lat) coords."""
    from shapely.geometry import Polygon as ShapelyPolygon
    coords = []
    # Bearing step = int(410/points) — FIXED, do NOT change to 360
    for bearing in range(0, 360, int(410 / points)):
        lat2, lon2 = destination_point(lat, lon, bearing, radius_km)
        coords.append((lon2, lat2))  # Shapely order: (lon, lat)
    coords.append(coords[0])
    return ShapelyPolygon(coords)


def haversine_km(lat1, lon1, lat2, lon2):
    """Haversine distance in km."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ============================================================
# PRICING LOGIC
# ============================================================

def get_pricing(distance_km):
    if pd.isna(distance_km): return "Nil"
    for lo, hi, label in PRICING_SLABS:
        if distance_km < hi: return label
    return "Nil"


# ============================================================
# PINCODE NORMALIZATION
# ============================================================

def clean_pincode(df, col="Pincode"):
    if col in df.columns:
        df[col] = df[col].astype(str).str.strip().str.replace(".0", "", regex=False)
    return df


# ============================================================
# HUB COLOR ASSIGNMENT
# ============================================================

def get_hub_color_map(hub_names):
    """Return {hub_name: color_hex} mapping."""
    unique = sorted(set(hub_names))
    return {h: HUB_COLORS[i % len(HUB_COLORS)] for i, h in enumerate(unique)}


# ============================================================
# SESSION STATE MANAGEMENT
# ============================================================

ALL_STATE_KEYS = {
    "cluster_df": None, "pincodes_df": None,
    "vol_lat_col": None, "vol_long_col": None,
    "geojson_data": None, "geojson_source": None,
    "geojson_pincode_field": None,
    "upload_status": {"cluster": False, "pincodes": False, "geojson": False},
    "cluster_input_mode": "upload",
    "final_output_df": None, "pin_boundaries_df": None,
    "polygon_records_df": None, "awb_raw_df": None,
    "final_result_df": None, "bq_credentials": None,
    "radius_limit_km": 4.0, "hub_radius_map": {}, "hub_images": {},
    "live_cluster_df": None, "live_hub_df": None,
    "last_refresh_time": None, "groq_api_key": None,
    "ai_chat_history": [], "ai_auto_report": None, "burn_analysis_report": None,
    "bq_client": None, "bq_auth_mode": None, "last_bq_fetch": None,
    "lc_ai_report": None, "edit_undo_stack": [], "edit_redo_stack": [],
    "custom_markers": [], "drawn_shapes": [],
    "sidebar_chat_history": [], "auto_run_requested": False,
}


def init_session_state():
    for k, v in ALL_STATE_KEYS.items():
        if k not in st.session_state:
            st.session_state[k] = v if not isinstance(v, (dict, list)) else v.copy() if isinstance(v, dict) else list(v)


def reload_from_disk():
    """Reload outputs — DuckDB first (fast), CSV fallback (slow)."""
    loaded = []

    # ── Fast path: DuckDB ──
    try:
        from modules.duckdb_store import load_all_to_session
        duck_loaded = load_all_to_session()
        if duck_loaded:
            loaded.extend([f"{k} (DuckDB)" for k in duck_loaded])
    except Exception:
        pass

    # ── Slow fallback: CSV files for anything DuckDB didn't have ──
    csv_mapping = [
        ("final_output_df", "outputs/final_output.csv"),
        ("polygon_records_df", "outputs/Clustering_payout_polygon_latest.csv"),
        ("awb_raw_df", "outputs/Awb_with_polygon_mapping.csv"),
        ("final_result_df", "outputs/Awb_with_cluster_info.csv"),
    ]
    for key, path in csv_mapping:
        if st.session_state.get(key) is None:
            for p in [path, os.path.join("data", os.path.basename(path))]:
                if os.path.exists(p):
                    try:
                        df = pd.read_csv(p)
                        st.session_state[key] = df
                        loaded.append(os.path.basename(p))
                        # Backfill into DuckDB for next time
                        try:
                            from modules.duckdb_store import save_df
                            save_df(key, df)
                        except Exception:
                            pass
                    except Exception:
                        pass
                    break
    return loaded


# ============================================================
# FILE HELPERS
# ============================================================

def ensure_output_dirs():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(HUB_IMG_DIR, exist_ok=True)


def get_download_bytes(df, fmt="csv"):
    if fmt == "csv":
        return df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    buf = BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    return buf.getvalue()


def show_df_download(df, key, title=None):
    """Show dataframe with one CSV download button."""
    if title:
        st.markdown(f'<div class="sfx-section-header">{title}</div>', unsafe_allow_html=True)
    st.caption(f"📊 {len(df):,} rows × {len(df.columns)} columns")
    st.dataframe(df, use_container_width=True, height=350)
    st.download_button(
        "⬇ Download CSV", get_download_bytes(df, "csv"),
        f"{key}.csv", "text/csv", key=f"dl_{key}"
    )


def detect_latlon_cols(df):
    """Auto-detect latitude and longitude columns."""
    lat_candidates = ["Volumetric Lat", "volumetric_lat", "latitude", "lat", "Lat",
                      "delivery_latitude", "vol_lat", "Volumetric_Lat"]
    lon_candidates = ["Volumetric Long", "volumetric_long", "longitude", "long", "Long",
                      "delivery_longitude", "vol_long", "Volumetric_Long", "Volumetric Lon"]
    lat_col = lon_col = None
    for c in lat_candidates:
        if c in df.columns:
            lat_col = c; break
    for c in lon_candidates:
        if c in df.columns:
            lon_col = c; break
    return lat_col, lon_col


def detect_geojson_pincode_field(geojson_data):
    """Auto-detect pincode field in GeoJSON properties."""
    if not geojson_data or "features" not in geojson_data:
        return None
    sample = geojson_data["features"][0].get("properties", {}) if geojson_data["features"] else {}
    for key in ["pincode", "Pincode", "PINCODE", "pin", "PIN", "postalcode", "postal_code"]:
        if key in sample:
            return key
    return None
