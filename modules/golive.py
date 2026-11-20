"""
Go Live: turn cluster polygons into the Saruman "Upload payout cluster" file.

Replaces the manual sheet workflow (payout_cluster_upload_sample):
  1. paste WKT | name (Cluster Code) | category (C1..) into the "Wroking" tab,
  2. formulas fill pincode, hub, Hub Id, "POLYGON Z" boundary and category number,
  3. check the values and the hub name, copy columns M-Q into "Main sheet",
  4. download it and upload it in Saruman -> Geocode -> Upload payout cluster.

Here the same rows are built in Python, every row is checked, and the
"Main sheet" file is produced directly:
  Hub Id | Cluster Code | Description | Boundary | Cluster Category | Pincode | Surge Amount
(Pincode and Surge Amount are left empty, as in the sample.)

Hub Id comes from BigQuery ecommerce.ecommerce_hub (verified: same IDs as the
sheet's "Hub name" tab for 4,878 of 4,887 hubs; the other 9 have ID 0 in the
sheet, i.e. hubs the sheet hasn't caught up with). The hub check uses today's
serviceability (analytics_tables.client_pincode_active_data_new).
"""
import io
import re

import pandas as pd

MAIN_COLUMNS = ["Hub Id", "Cluster Code", "Description", "Boundary", "Cluster Category", "Pincode", "Surge Amount"]
DESC_ACTIVATE = "Clustering as per SOP"
DESC_CRITICAL = "Clustering For Critical area"
DESC_DEACTIVATE = "Deactivated Clustering Payout"
DESCRIPTIONS = [DESC_ACTIVATE, DESC_CRITICAL, DESC_DEACTIVATE]  # values seen in real upload files
_CODE_RE = re.compile(r"^(\d{6})_[A-Z]+$")
_BQ = "data-warehousing-391512"

OK, CHECK, ERROR = "OK", "Check", "Error"


# ── BigQuery lookups ─────────────────────────────────────────────────────────
def hub_info(client, hub_names):
    """{hub name: {"id", "lat", "lon"}} from ecommerce.ecommerce_hub (the registered hub location)."""
    from google.cloud import bigquery
    names = sorted({str(h).strip() for h in hub_names if str(h).strip()})
    if not names:
        return {}
    job = client.query(
        f"SELECT name, id, latitude, longitude FROM `{_BQ}.ecommerce.ecommerce_hub` WHERE name IN UNNEST(@names)",
        job_config=bigquery.QueryJobConfig(query_parameters=[bigquery.ArrayQueryParameter("names", "STRING", names)]))
    return {r["name"]: {"id": int(r["id"]), "lat": r["latitude"], "lon": r["longitude"]} for r in job.result()}


def hub_ids(client, hub_names):
    """{hub name: Hub Id} from ecommerce.ecommerce_hub."""
    return {k: v["id"] for k, v in hub_info(client, hub_names).items()}


def serviceability_hubs(client, pincodes):
    """{pincode: [hubs serving it today]} (service = regular, delivery) from the daily serviceability table."""
    from google.cloud import bigquery
    pins = sorted({str(p).strip() for p in pincodes if re.fullmatch(r"\d{6}", str(p).strip())})
    if not pins:
        return {}
    t = f"`{_BQ}.analytics_tables.client_pincode_active_data_new`"
    job = client.query(
        f"""SELECT CAST(pincode AS STRING) AS pincode, ARRAY_AGG(DISTINCT hub ORDER BY hub) AS hubs
            FROM {t}
            WHERE report_date = (SELECT MAX(report_date) FROM {t})
              AND service = 'regular' AND request_type = 'delivery'
              AND CAST(pincode AS STRING) IN UNNEST(@pins)
            GROUP BY 1""",
        job_config=bigquery.QueryJobConfig(query_parameters=[bigquery.ArrayQueryParameter("pins", "STRING", pins)]))
    return {r["pincode"]: list(r["hubs"]) for r in job.result()}


# ── Input parsing ────────────────────────────────────────────────────────────
def parse_pasted(text):
    """Rows pasted like into the sheet's Wroking tab: WKT <tab> name <tab> category
    [<tab> description <tab> pincode]. A header row is skipped."""
    rows = []
    for line in (text or "").splitlines():
        parts = [p.strip() for p in line.split("\t")]
        if len(parts) < 3 or not parts[0].upper().startswith(("POLYGON", "MULTIPOLYGON")):
            continue
        rows.append({"Polygon WKT": parts[0], "Cluster_Code": parts[1], "Cluster_Category": parts[2],
                     "Pincode": parts[4] if len(parts) > 4 else "", "Hub Name": ""})
    return pd.DataFrame(rows, columns=["Polygon WKT", "Cluster_Code", "Cluster_Category", "Pincode", "Hub Name"])


def normalise_table(df):
    """Map an uploaded CSV/XLSX (app, My Maps, or sheet layout) onto the app's polygon columns."""
    cols = {c.lower().strip(): c for c in df.columns}
    pick = lambda *names: next((cols[n] for n in names if n in cols), None)
    out = pd.DataFrame({
        "Polygon WKT": df[pick("polygon wkt", "wkt", "boundary", "geometry")] if pick("polygon wkt", "wkt", "boundary", "geometry") else "",
        "Cluster_Code": df[pick("cluster_code", "cluster code", "name")] if pick("cluster_code", "cluster code", "name") else "",
        "Cluster_Category": df[pick("cluster_category", "cluster category", "category")] if pick("cluster_category", "cluster category", "category") else "",
        "Pincode": df[pick("pincode", "pin")] if pick("pincode", "pin") else "",
        "Hub Name": df[pick("hub name", "hub_name", "hub")] if pick("hub name", "hub_name", "hub") else "",
    })
    return out.fillna("").astype(str)


# ── Row building + checks ────────────────────────────────────────────────────
def category_number(cat):
    """'C3' -> 3, '3' -> 3, else None (same as the sheet's category column)."""
    m = re.fullmatch(r"[Cc]?\s*(\d{1,2})", str(cat or "").strip())
    return int(m.group(1)) if m else None


def boundary_text(wkt):
    """WKT -> ('POLYGON Z ((lon lat, ...))', problem). Coordinates rounded to 7 decimals
    (~1 cm): real upload files use 6-7, so My Maps coordinates pass through unchanged. Saruman takes one polygon per cluster code, so a
    shape made of several separate parts is an error."""
    import shapely
    from shapely import wkt as _wkt
    from shapely.geometry import MultiPolygon, Polygon
    try:
        g = _wkt.loads(str(wkt).replace("POLYGON Z", "POLYGON").replace("MULTIPOLYGON Z", "MULTIPOLYGON"))
    except Exception:
        return None, (ERROR, "Boundary is not a valid shape")
    if isinstance(g, MultiPolygon):
        if len(g.geoms) != 1:
            return None, (ERROR, f"Shape has {len(g.geoms)} separate parts: split it so each cluster code has one polygon")
        g = g.geoms[0]
    if not isinstance(g, Polygon) or g.is_empty or len(g.exterior.coords) < 4:
        return None, (ERROR, "Boundary needs at least 3 corners")
    text = shapely.to_wkt(g, rounding_precision=7, trim=True)
    text = "POLYGON Z " + text[text.index("("):]
    if not g.is_valid:
        return text, (CHECK, "Boundary crosses itself: check the shape in My Maps")
    return text, None


def build_rows(polys, description, hub_id_map, svc_map):
    """One row per polygon with the upload values and a Status / Problem explaining any issue."""
    recs = []
    seen = polys["Cluster_Code"].astype(str).str.strip().value_counts()
    for _, r in polys.iterrows():
        problems = []
        code = str(r.get("Cluster_Code", "")).strip()
        m = _CODE_RE.match(code)
        if not m:
            problems.append((ERROR, f"Cluster code '{code}' should look like 509375_A"))
        if seen.get(code, 0) > 1:
            problems.append((ERROR, "Cluster code appears more than once"))
        pin = re.sub(r"\.0$", "", str(r.get("Pincode", "")).strip()) or (m.group(1) if m else "")
        if m and pin and pin != m.group(1):
            problems.append((CHECK, f"Pincode {pin} differs from the cluster code's {m.group(1)}"))
        served_by = svc_map.get(pin, [])
        hub = str(r.get("Hub Name", "")).strip()
        if not hub:  # pasted rows: take the hub from today's serviceability, like the sheet's lookup
            hub = served_by[0] if served_by else ""
            if len(served_by) > 1:
                problems.append((CHECK, f"Pincode is served by {len(served_by)} hubs ({', '.join(served_by)}); used {hub}"))
        if not hub:
            problems.append((ERROR, "No hub: pincode not in today's serviceability and no hub given"))
        elif served_by and hub not in served_by:
            problems.append((CHECK, f"Today's serviceability has this pincode on {', '.join(served_by)}, not {hub}"))
        elif pin and not served_by:
            problems.append((CHECK, "Pincode is not in today's serviceability"))
        if re.search(r"test", hub, re.IGNORECASE):
            problems.append((CHECK, f"'{hub}' looks like a test hub"))
        hid = hub_id_map.get(hub)
        if hub and hid is None:
            problems.append((ERROR, f"Hub '{hub}' not found in Shadowfax's hub list"))
        catn = category_number(r.get("Cluster_Category"))
        if catn is None:
            problems.append((ERROR, f"Category '{r.get('Cluster_Category', '')}' should look like C3"))
        boundary, bprob = boundary_text(r.get("Polygon WKT", ""))
        if bprob:
            problems.append(bprob)
        status = ERROR if any(p[0] == ERROR for p in problems) else (CHECK if problems else OK)
        recs.append({"Status": status, "Problem": "; ".join(p[1] for p in problems),
                     "Hub Name": hub, "Hub Id": hid, "Cluster Code": code, "Pincode": pin,
                     "Cluster Category": catn, "Served by (today)": ", ".join(served_by),
                     "Description": description, "Boundary": boundary})
    return pd.DataFrame(recs)


def main_sheet(rows, include_checks=True):
    """The upload rows (columns M-Q of the Wroking tab + the two empty columns), errors left out."""
    keep = rows["Status"].isin([OK, CHECK] if include_checks else [OK])
    out = rows.loc[keep, ["Hub Id", "Cluster Code", "Description", "Boundary", "Cluster Category"]].copy()
    out["Hub Id"] = out["Hub Id"].astype(int)
    out["Cluster Category"] = out["Cluster Category"].astype(int)
    out["Pincode"] = ""
    out["Surge Amount"] = ""
    return out[MAIN_COLUMNS].reset_index(drop=True)


def to_xlsx(df):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        df.to_excel(xw, index=False, sheet_name="Main sheet")
    return buf.getvalue()


def to_csv(df):
    return df.to_csv(index=False).encode("utf-8")


# ── Preview ──────────────────────────────────────────────────────────────────
def category_rate(catn):
    """Cluster Category number -> rate in Rs per order (utils.DESCRIPTION_MAPPING)."""
    from utils import DESCRIPTION_MAPPING
    return DESCRIPTION_MAPPING.get(f"C{catn}") if catn is not None else None


def _fmt_rate(r):
    return "" if r is None else (f"₹{int(r)}" if float(r).is_integer() else f"₹{r:g}")


def preview_frames(rows, info):
    """(polygons, hubs) in the shapes the app's map and photo renderers use, for the rows
    that will be uploaded (errors left out). Hub pins are the registered hub locations."""
    ok = rows[rows["Status"] != ERROR].copy()
    polys = pd.DataFrame({
        "Pincode": ok["Pincode"], "Hub Name": ok["Hub Name"], "Cluster_Code": ok["Cluster Code"],
        "Cluster_Category": ok["Cluster Category"].map(lambda n: f"C{int(n)}"),
        "Description": ok["Cluster Category"].map(lambda n: _fmt_rate(category_rate(int(n)))),
        "Polygon WKT": ok["Boundary"].str.replace("POLYGON Z", "POLYGON", n=1, regex=False),
    }).reset_index(drop=True)
    hubs = pd.DataFrame([{"Hub Name": h, "Hub_Name": h, "Hub_lat": v["lat"], "Hub_long": v["lon"]}
                         for h, v in info.items() if h in set(polys["Hub Name"]) and v.get("lat") is not None],
                        columns=["Hub Name", "Hub_Name", "Hub_lat", "Hub_long"])
    return polys, hubs


def hub_distance_km(polys, hubs, hub):
    """Distance from the registered hub location to its nearest polygon (0 = inside one)."""
    from shapely import wkt as _wkt
    from shapely.geometry import Point
    from shapely.ops import unary_union
    h = hubs[hubs["Hub Name"] == hub]
    sub = polys[polys["Hub Name"] == hub]
    if h.empty or sub.empty:
        return None
    pt = Point(float(h["Hub_long"].iloc[0]), float(h["Hub_lat"].iloc[0]))
    shape = unary_union([_wkt.loads(w) for w in sub["Polygon WKT"]])
    return round(shape.distance(pt) * 111.0, 1)  # degrees -> km (good enough for a sanity check)
