"""
Hub Explorer: one hub at a time, the per-hub P-mapping workbench of the Apps Script
"Distance Payout Dashboard" built into the portal.

Per hub: profile (Hub Id, location, status), riders with payout structure, every
pincode with its load (orders) and monthly burn under three P-mappings -
  Current P : today's serviceability (analytics_tables.client_pincode_active_data_new)
  SOP P     : distance hub -> pincode centre, priced with the app's 5 km slabs (Step 2)
  Custom P  : edited by the user
- and a comparison of any two (saving vs extra burn), plus a map with optional road
routes (OSRM) from the hub to each pincode's nearest and farthest boundary point.

Burn = Rs per order (PCAT_SOP rate of the P-category) x FWD load.
Load = delivered FWD orders / REV pickups per pincode over the chosen window
(smaug_dataengine.data_engine_orderleveldata).
"""
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

_D = "data-warehousing-391512"
_SVC = f"`{_D}.analytics_tables.client_pincode_active_data_new`"
WINDOWS = {"Last 30 days": "30d", "Last calendar month": "last_month"}


def _q(client, sql, params=None):
    from google.cloud import bigquery
    cfg = bigquery.QueryJobConfig(query_parameters=params or [])
    return client.query(sql, job_config=cfg).to_dataframe()


# ── BigQuery ─────────────────────────────────────────────────────────────────
def serviceability(client):
    """All hubs' delivery pincodes today: hub, pincode, pcat ('P3'), report_date."""
    df = _q(client, f"""
        SELECT hub, CAST(pincode AS STRING) AS pincode, CONCAT('P', CAST(payment_category AS STRING)) AS pcat,
               report_date
        FROM {_SVC}
        WHERE report_date = (SELECT MAX(report_date) FROM {_SVC})
          AND service = 'regular' AND request_type = 'delivery'""")
    return df.drop_duplicates(["hub", "pincode"]).reset_index(drop=True)


def hub_row(client, hub):
    from google.cloud import bigquery
    df = _q(client, f"""SELECT id, name, latitude, longitude, hub_category, hub_status, address
                         FROM `{_D}.ecommerce.ecommerce_hub` WHERE name = @h""",
            [bigquery.ScalarQueryParameter("h", "STRING", hub)])
    return df.iloc[0].to_dict() if len(df) else None


def riders(client, hub_id):
    """Riders registered at the hub with their active payout structure (no phone numbers)."""
    from google.cloud import bigquery
    return _q(client, f"""
        WITH r AS (SELECT rider_id, name FROM `{_D}.ecommerce.ecommerce_rider` WHERE hub_id = @hid),
        ps AS (SELECT rider_id, payout_structure_id FROM `{_D}.smaugdb.payout_engine_riderpayoutstructures`
               WHERE is_active AND rider_id IN (SELECT rider_id FROM r)
               QUALIFY ROW_NUMBER() OVER (PARTITION BY rider_id ORDER BY date_start DESC) = 1)
        SELECT r.rider_id AS `Rider ID`, TRIM(r.name, ' .') AS `Name`, s.structure_name AS `Payout structure`
        FROM r LEFT JOIN ps USING (rider_id)
        LEFT JOIN `{_D}.smaugdb.payout_engine_payoutstructures` s ON s.id = ps.payout_structure_id
        ORDER BY `Name`""", [bigquery.ScalarQueryParameter("hid", "INT64", int(hub_id))])


def load(client, pincodes, window="30d"):
    """Orders per pincode: FWD delivered, REV picked up, over the window."""
    from google.cloud import bigquery
    pins = [int(p) for p in pincodes if str(p).isdigit()]
    if not pins:
        return pd.DataFrame(columns=["pincode", "fwd", "rev"])
    if window == "last_month":
        cond = ("order_date >= DATE_TRUNC(DATE_SUB(CURRENT_DATE(), INTERVAL 1 MONTH), MONTH) "
                "AND order_date < DATE_TRUNC(CURRENT_DATE(), MONTH)")
    else:
        cond = "order_date > DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)"
    return _q(client, f"""
        SELECT CAST(pincode AS STRING) AS pincode,
               COUNTIF(ecom_request_type = 1 AND order_status = 1) AS fwd,
               COUNTIF(ecom_request_type = 5 AND order_status IN (2, 3)) AS rev
        FROM `{_D}.smaug_dataengine.data_engine_orderleveldata`
        WHERE {cond} AND order_category = 1 AND order_tag IN (0, 1, 14) AND pincode IN UNNEST(@pins)
        GROUP BY 1""", [bigquery.ArrayQueryParameter("pins", "INT64", pins)])


# ── Pricing ──────────────────────────────────────────────────────────────────
def pcat_options():
    from utils import PCAT_SOP, RATE_TO_PCAT
    keys = set(PCAT_SOP) | {v for v in RATE_TO_PCAT.values() if v.startswith("P")}
    return sorted(keys, key=lambda k: (len(k), k))


def rate_per_order(pcat):
    from utils import pcat_to_payout
    v = pcat_to_payout(pcat)
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)


def pincode_centres(pincodes, pincodes_ref=None):
    """{pincode: (lat, lon)}: Volumetric Lat/Long from the pincode reference (as Step 2),
    else the centre of the pincode boundary."""
    out = {}
    if pincodes_ref is not None and len(pincodes_ref):
        ref = pincodes_ref.copy()
        ref["Pincode"] = ref["Pincode"].astype(str).str.replace(r"\.0$", "", regex=True)
        lat = next((c for c in ref.columns if c.lower().replace("_", " ") == "volumetric lat"), None)
        lon = next((c for c in ref.columns if c.lower().replace("_", " ") in ("volumetric long", "volumetric lon")), None)
        if lat and lon:
            sub = ref[ref["Pincode"].isin([str(p) for p in pincodes])]
            out = {r["Pincode"]: (float(r[lat]), float(r[lon])) for _, r in sub.iterrows()
                   if pd.notna(r[lat]) and pd.notna(r[lon])}
    missing = [p for p in pincodes if p not in out]
    if missing:
        try:
            from shapely.geometry import shape
            from modules import boundary_store as bs
            for f in bs.features_for(tuple(missing)).get("features", []):
                pin = bs.norm_pin(f["properties"].get("Pincode", f["properties"].get("pincode", "")))
                c = shape(f["geometry"]).centroid
                out.setdefault(pin, (c.y, c.x))
        except Exception:
            pass
    return out


def road_km(hub_lat, hub_lon, centres, timeout=12):
    """{pincode: road km} hub -> pincode centre via OSRM (None where OSRM gave no route)."""
    import requests

    def one(item):
        pin, (lat, lon) = item
        try:
            r = requests.get(f"https://router.project-osrm.org/route/v1/driving/{hub_lon},{hub_lat};{lon},{lat}",
                             params={"overview": "false"}, timeout=timeout).json()
            return pin, round(r["routes"][0]["distance"] / 1000, 1)
        except Exception:
            return pin, None
    with ThreadPoolExecutor(max_workers=4) as pool:
        return dict(pool.map(one, centres.items()))


def sop_categories(hub_lat, hub_lon, centres, road=None):
    """{pincode: (km, 'P3', by_road)}: distance priced with the app's 5 km slabs. Straight line
    (as Step 2) unless `road` gives road km for the pincode."""
    from utils import get_pricing, haversine_km, rate_to_pcat
    out = {}
    for pin, (lat, lon) in centres.items():
        rk = (road or {}).get(pin)
        km = rk if rk is not None else haversine_km(hub_lat, hub_lon, lat, lon)
        out[pin] = (round(km, 1), rate_to_pcat(get_pricing(km)), rk is not None)
    return out


def priced(table, pcat_col, load_col="FWD load"):
    """Add Rs/order and Burn columns for the P-category column."""
    t = table.copy()
    t["₹/order"] = t[pcat_col].map(rate_per_order)
    t["Burn (₹)"] = (t["₹/order"].fillna(0) * t[load_col].fillna(0)).round(0)
    return t


def compare(a, b, label_a, label_b, loads):
    """Per pincode: category and Rs/order in A and B, the change, and the burn effect of B vs A."""
    df = pd.DataFrame({"Pincode": list(loads.index)})
    df[label_a] = df["Pincode"].map(a)
    df[label_b] = df["Pincode"].map(b)
    df["FWD load"] = df["Pincode"].map(loads).fillna(0).astype(int)
    ra, rb = df[label_a].map(rate_per_order), df[label_b].map(rate_per_order)
    df["Δ ₹/order"] = (rb - ra).round(2)
    df["Δ burn (₹)"] = ((rb.fillna(0) - ra.fillna(0)) * df["FWD load"]).round(0)
    return df


# ── Road routes (OSRM) ───────────────────────────────────────────────────────
def road_routes(hub_lat, hub_lon, features, timeout=12):
    """For each pincode boundary: the nearest and farthest boundary point from the hub
    (straight line) and the road route to it. Returns rows {pincode, kind, km, path}."""
    import requests
    from shapely.geometry import Point, shape
    from utils import haversine_km
    hub = Point(hub_lon, hub_lat)
    jobs = []
    for f in features:
        props = f.get("properties", {})
        pin = str(props.get("Pincode", props.get("pincode", ""))).strip()
        g = shape(f["geometry"])
        pts = list(g.exterior.coords) if g.geom_type == "Polygon" else [c for p in g.geoms for c in p.exterior.coords]
        if not pts:
            continue
        if g.contains(hub):
            near = (hub_lon, hub_lat)
        else:
            near = min(pts, key=lambda c: haversine_km(hub_lat, hub_lon, c[1], c[0]))
        far = max(pts, key=lambda c: haversine_km(hub_lat, hub_lon, c[1], c[0]))
        jobs += [(pin, "nearest", near), (pin, "farthest", far)]

    def route(job):
        pin, kind, (lon, lat) = job
        try:
            r = requests.get(f"https://router.project-osrm.org/route/v1/driving/{hub_lon},{hub_lat};{lon},{lat}",
                             params={"overview": "simplified", "geometries": "geojson"}, timeout=timeout).json()
            rt = r["routes"][0]
            return {"pincode": pin, "kind": kind, "km": round(rt["distance"] / 1000, 1),
                    "path": [(y, x) for x, y in rt["geometry"]["coordinates"]], "road": True}
        except Exception:
            return {"pincode": pin, "kind": kind, "km": round(haversine_km(hub_lat, hub_lon, lat, lon), 1),
                    "path": [(hub_lat, hub_lon), (lat, lon)], "road": False}

    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(route, jobs))


def hub_map(hub, hub_lat, hub_lon, features, pcats, routes=None):
    """Folium map: pincode boundaries coloured by the P-category's Rs/order, labelled,
    the hub pin, and road routes when given."""
    import folium
    from modules.visualizer import _base_map
    m = _base_map(hub_lat, hub_lon, zoom=10)
    palette = [(0, "#22c55e"), (1, "#86efac"), (2, "#3b82f6"), (3, "#8b5cf6"), (4, "#a855f7"),
               (5, "#f59e0b"), (6, "#f97316"), (8, "#ef4444"), (10 ** 9, "#991b1b")]
    col = lambda r: "#9ca3af" if r is None else next(c for lim, c in palette if r <= lim)
    fc = []
    for f in features:
        props = f.get("properties", {})
        pin = str(props.get("Pincode", props.get("pincode", ""))).strip()
        pc = pcats.get(pin)
        r = rate_per_order(pc) if pc else None
        fc.append({"type": "Feature", "geometry": f["geometry"],
                   "properties": {"_c": col(r), "_tip": f"{pin} · {pc or '—'} · " + ("—" if r is None else f"₹{r:g}/order")}})
    if fc:
        gj = folium.GeoJson({"type": "FeatureCollection", "features": fc}, name="Pincodes",
                            style_function=lambda f: {"fillColor": f["properties"]["_c"], "color": "#1f2937",
                                                      "weight": 1.5, "fillOpacity": 0.45},
                            tooltip=folium.GeoJsonTooltip(fields=["_tip"], labels=False))
        gj.add_to(m)
        m.fit_bounds(gj.get_bounds())
    for rt in routes or []:
        folium.PolyLine(rt["path"], color="#008a71" if rt["kind"] == "nearest" else "#dc2626", weight=3,
                        opacity=0.85, dash_array=None if rt["road"] else "6 6",
                        tooltip=f"{rt['pincode']} {rt['kind']}: {rt['km']} km" + ("" if rt["road"] else " (straight line)")).add_to(m)
    folium.Marker([hub_lat, hub_lon], tooltip=hub, icon=folium.Icon(color="red", icon="home")).add_to(m)
    folium.LayerControl(position="topright", collapsed=True).add_to(m)
    return m
