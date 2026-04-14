"""
GeoJSON Conversion + Cluster Polygon Generation.
"""
import json, ast, math, os
import pandas as pd
import numpy as np
import streamlit as st
from shapely.geometry import Polygon as ShapelyPolygon
from shapely.wkt import loads as wkt_loads

try:
    import simplekml
    HAS_KML = True
except ImportError:
    HAS_KML = False

from utils import (CLUSTER_MAP, destination_point, create_circle_polygon, clean_pincode)


def convert_geojson_to_boundaries(geojson_data, pincode_field=None):
    """Convert GeoJSON to DataFrame with Pincode and polygon_wkt."""
    records = []
    for feature in geojson_data.get("features", []):
        props = feature.get("properties", {})
        geom = feature.get("geometry", {})
        pc = None
        if pincode_field and pincode_field in props:
            pc = str(props[pincode_field]).strip()
        else:
            for k in ["pincode", "Pincode", "PINCODE", "pin", "PIN"]:
                if k in props:
                    pc = str(props[k]).strip(); break
        if pc is None:
            continue
        wkt = _coords_to_wkt(geom.get("type", ""), geom.get("coordinates", []))
        if wkt:
            records.append({"Pincode": pc, "polygon_wkt": wkt})
    df = pd.DataFrame(records)
    return clean_pincode(df)


def _coords_to_wkt(geom_type, coordinates):
    try:
        gt = geom_type.upper()
        if gt == "MULTIPOLYGON":
            polys = []
            for poly in coordinates:
                pc = poly[0] if isinstance(poly[0][0], list) else poly
                polys.append("((" + ", ".join(f"{lon} {lat}" for lon, lat in pc) + "))")
            return "MULTIPOLYGON (" + ", ".join(polys) + ")"
        elif gt == "POLYGON":
            coords = coordinates[0] if isinstance(coordinates[0][0], list) else coordinates
            return "POLYGON ((" + ", ".join(f"{lon} {lat}" for lon, lat in coords) + "))"
        return None
    except Exception:
        return None


def _make_bands(step_km):
    """Generate distance bands for a given step width."""
    bands = []
    i, idx = 0.0, 0
    while i < 100:
        bands.append((i, i + step_km, f"₹{idx}"))
        i += step_km
        idx += 1
    return bands


@st.cache_data(ttl=3600, show_spinner=False)
def _generate_cluster_polygons_core(cluster_df, pin_boundaries_df, radius_limit_km=4, hub_radius_map=None):
    """Core polygon generation logic (cached). Returns (records list, skipped list)."""
    hub_radius_map = hub_radius_map or {}
    live = clean_pincode(cluster_df.copy())
    poly = clean_pincode(pin_boundaries_df.copy())
    df = pd.merge(live, poly, on="Pincode", how="left")

    # Cache bands per unique radius to avoid recomputation
    bands_cache = {}

    added_hubs, pincode_seq, records, skipped = set(), {}, [], []
    total = len(df)

    for ri, (_, row) in enumerate(df.iterrows()):
        try:
            pc = str(row["Pincode"])
            hub_name = str(row.get("Hub_Name", ""))
            hub_lat = float(row.get("Hub_lat", 0))
            hub_lon = float(row.get("Hub_long", 0))
            polygon_wkt = row.get("polygon_wkt")

            # Per-hub radius: use hub-specific override or global default
            hub_radius = hub_radius_map.get(hub_name, float(radius_limit_km))
            if hub_radius not in bands_cache:
                bands_cache[hub_radius] = _make_bands(hub_radius)
            bands = bands_cache[hub_radius]

            if pd.isna(polygon_wkt) or polygon_wkt is None:
                if pc not in skipped: skipped.append(pc)
                continue

            polygon = wkt_loads(polygon_wkt)
            for inner_r, outer_r, description in bands:
                outer_c = create_circle_polygon(hub_lat, hub_lon, outer_r)
                if inner_r == 0:
                    ring = outer_c
                else:
                    inner_c = create_circle_polygon(hub_lat, hub_lon, inner_r)
                    ring = outer_c.difference(inner_c)
                    if ring.is_empty: continue
                    if not ring.is_valid: ring = ring.buffer(0)

                clipped = ring.intersection(polygon)
                if clipped.is_empty: continue

                geoms = [clipped] if clipped.geom_type == "Polygon" else list(clipped.geoms)
                seq = pincode_seq.get(pc, 0)
                for g in geoms:
                    if g.geom_type != "Polygon": continue
                    coords = list(g.exterior.coords)
                    sfx = chr(65 + seq) if seq < 26 else f"Z{seq - 25}"
                    name = f"{pc}_{sfx}"
                    cat = CLUSTER_MAP.get(description.strip(), "Unknown")
                    records.append({
                        "Pincode": pc, "Hub Name": hub_name, "Cluster_Code": name,
                        "Description": description, "Cluster_Category": cat,
                        "Polygon WKT": ShapelyPolygon(coords).wkt,
                    })
                    seq += 1
                pincode_seq[pc] = seq
        except Exception as e:
            print(f"Error: {row.get('Pincode', '?')}: {e}")

    return records, skipped


def generate_cluster_polygons(cluster_df, pin_boundaries_df, radius_limit_km=4, hub_radius_map=None, progress_cb=None):
    """Generate cluster polygons. Returns (records_df, kml, skipped_pincodes).

    Args:
        cluster_df: DataFrame with Hub_Name, Hub_lat, Hub_long, Pincode columns.
        pin_boundaries_df: DataFrame with Pincode and polygon_wkt columns.
        radius_limit_km: Default distance band width in km (used for hubs not in hub_radius_map).
        hub_radius_map: Optional dict mapping Hub_Name -> custom radius_km.
        progress_cb: Optional callback(float) for progress updates.
    """
    # Convert hub_radius_map to a hashable type for caching
    hub_radius_frozen = tuple(sorted((hub_radius_map or {}).items()))

    if progress_cb:
        progress_cb(0.05)

    # Call cached core (hub_radius_map passed as tuple for hashability)
    records, skipped = _generate_cluster_polygons_core(
        cluster_df, pin_boundaries_df, radius_limit_km,
        hub_radius_map=dict(hub_radius_frozen) if hub_radius_frozen else None,
    )

    if progress_cb:
        progress_cb(0.8)

    records_df = pd.DataFrame(records)

    # Build KML (not cached — lightweight post-processing)
    kml = simplekml.Kml() if HAS_KML else None
    if kml and not records_df.empty:
        live = clean_pincode(cluster_df.copy())
        added_hubs = set()
        for _, row in live.iterrows():
            hub_name = str(row.get("Hub_Name", ""))
            hub_lat = float(row.get("Hub_lat", 0))
            hub_lon = float(row.get("Hub_long", 0))
            pc = str(row.get("Pincode", ""))
            hid = (hub_name, hub_lat, hub_lon)
            if hid not in added_hubs:
                desc = f"Hub: {hub_name}\nPincode: {pc}\nLat: {hub_lat}\nLon: {hub_lon}\n"
                pt = kml.newpoint(name=hub_name, description=desc, coords=[(hub_lon, hub_lat)])
                pt.style.iconstyle.icon.href = "http://maps.google.com/mapfiles/kml/paddle/red-circle.png"
                pt.style.iconstyle.scale = 1.3
                added_hubs.add(hid)
        for _, rec in records_df.iterrows():
            try:
                poly_geom = wkt_loads(rec["Polygon WKT"])
                coords = list(poly_geom.exterior.coords)
                pol = kml.newpolygon(name=rec["Cluster_Code"], description=rec["Description"])
                pol.outerboundaryis.coords = coords
                pol.style.polystyle.color = simplekml.Color.changealphaint(100, simplekml.Color.blue)
                pol.style.linestyle.width = 2
                pol.style.linestyle.color = simplekml.Color.blue
            except Exception:
                continue

    if progress_cb:
        progress_cb(1.0)

    return records_df, kml, skipped


def save_polygon_outputs(records_df, kml, radius_km, hub_radius_map=None, out_dir="outputs"):
    os.makedirs(out_dir, exist_ok=True)

    # Build filename
    if hub_radius_map:
        base = "Clustering_payout_polygon_custom"
    else:
        radius_tag = f"{radius_km:.2f}".rstrip('0').rstrip('.')
        base = f"Clustering_payout_polygon_{radius_tag}KM"

    csv_p = os.path.join(out_dir, f"{base}.csv")
    xlsx_p = os.path.join(out_dir, f"{base}.xlsx")
    kml_p = os.path.join(out_dir, f"{base}.kml")

    records_df.to_csv(csv_p, index=False, encoding="utf-8-sig")
    records_df.to_excel(xlsx_p, index=False, engine="openpyxl")
    if kml: kml.save(kml_p)

    # Always save a _latest.csv copy for reload_from_disk()
    latest_csv = os.path.join(out_dir, "Clustering_payout_polygon_latest.csv")
    records_df.to_csv(latest_csv, index=False, encoding="utf-8-sig")

    return csv_p, xlsx_p, kml_p
