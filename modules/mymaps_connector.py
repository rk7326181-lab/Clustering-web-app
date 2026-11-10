"""
Google My Maps connector.

Reads hub polygons and hub locations straight from a Google My Maps map so
the portal can use My Maps as the single source of truth for polygons.

How it works
------------
Every My Maps map has a public KML export endpoint:

    https://www.google.com/maps/d/kml?mid=<MAP_ID>&forcekml=1

No API key or OAuth is needed, but the map's sharing must be set to
"Anyone with the link can view" -- otherwise Google returns a sign-in page
instead of KML and `fetch_kml` raises `MyMapsAccessError`.

The parser understands the formats this team already uses in My Maps:

* Polygon placemark named ``<pincode>_<suffix>`` (the Cluster_Code) with a
  description ``Hub: X | Pincode: N | Category: C1 | Rate: ₹0`` -- this is
  exactly what the app's own "Export for Google My Maps" KML writes.
* Layers imported from a CSV (``ExtendedData`` columns such as ``Hub Name``,
  ``Pincode``, ``Cluster_Category``, ``Rate``) -- read as a fallback.
* Bare descriptions like ``C3`` (category only).
* Hub location point placemarks named ``HUB: <hub name>``.

Output DataFrames use the same columns as the app's ``polygon_records_df``
(``Pincode, Hub Name, Cluster_Code, Description, Cluster_Category,
Polygon WKT``) plus ``Layer``, so downloads open in the same tools as the
app's own polygon CSV/KML. Used only by the standalone "My Maps Polygons"
page; it never writes into the pipeline's session data.

This module has no Streamlit dependency; caching for the UI lives in app.py.
"""

from __future__ import annotations

import os
import re
import tempfile
import time
import zipfile
import xml.etree.ElementTree as ET
from io import BytesIO

import pandas as pd
import requests

# The team's polygon map (Hub_Cluster-Amrutraj). Override with MYMAPS_URL in
# .streamlit/secrets.toml or the environment, or from the Step 3 UI.
DEFAULT_MYMAPS_URL = "https://www.google.com/maps/d/edit?mid=10r8LStC-ZTyrdu_R_oXq1LTdPq5z25Y"

KML_EXPORT_URL = "https://www.google.com/maps/d/kml?mid={mid}&forcekml=1"
POLYGON_COLUMNS = ["Pincode", "Hub Name", "Cluster_Code", "Description",
                   "Cluster_Category", "Polygon WKT", "Layer"]
HUB_COLUMNS = ["Hub Name", "Hub_lat", "Hub_long", "Layer"]

_KML_NS = "{http://www.opengis.net/kml/2.2}"
_MID_RE = re.compile(r"[?&]mid=([A-Za-z0-9_\-]+)")
_BARE_MID_RE = re.compile(r"^[A-Za-z0-9_\-]{15,}$")
_PINCODE_RE = re.compile(r"^(\d{6})(?:_|$)")
_CATEGORY_RE = re.compile(r"^C\d{1,2}$", re.IGNORECASE)
_COORD_NAME_RE = re.compile(r"^\s*-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?\s*$")
_HUB_NAME_RE = re.compile(r"^[A-Za-z]{2,}_[A-Za-z0-9_]+$")

# Category <-> rate, from the app's own tables (utils.DESCRIPTION_MAPPING /
# CLUSTER_MAP), used to fill whichever one a My Maps layer left out.
try:
    from utils import DESCRIPTION_MAPPING as _CAT_TO_RATE, CLUSTER_MAP as _RATE_TO_CAT
except Exception:  # pragma: no cover - utils needs streamlit; keep module standalone
    _CAT_TO_RATE, _RATE_TO_CAT = {}, {}


class MyMapsError(Exception):
    """Base error for the My Maps connector."""


class MyMapsAccessError(MyMapsError):
    """The map is private / not shared, or the ID is wrong."""


# ─────────────────────────────────────────────────────────────
# Map ID / config
# ─────────────────────────────────────────────────────────────
def extract_map_id(url_or_id: str) -> str:
    """Return the My Maps ``mid`` from a share/edit/view/kml URL or a bare ID."""
    s = (url_or_id or "").strip()
    m = _MID_RE.search(s)
    if m:
        return m.group(1)
    if _BARE_MID_RE.match(s):
        return s
    raise MyMapsError(
        "Could not find a map ID in that link. Paste the My Maps URL "
        "(it contains '?mid=...') or the map ID itself."
    )


def resolve_configured_url(secrets=None) -> str:
    """MYMAPS_URL from Streamlit secrets, then environment, then the default."""
    try:
        if secrets is not None and secrets.get("MYMAPS_URL"):
            return str(secrets["MYMAPS_URL"])
    except Exception:
        pass
    return os.environ.get("MYMAPS_URL") or DEFAULT_MYMAPS_URL


def _cache_path(mid: str, cache_dir: str | None) -> str:
    d = cache_dir or os.path.join(tempfile.gettempdir(), "mymaps_cache")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{mid}.kml")


# ─────────────────────────────────────────────────────────────
# Fetch
# ─────────────────────────────────────────────────────────────
def fetch_kml(mid: str, timeout: int = 90, cache_dir: str | None = None) -> tuple[bytes, dict]:
    """Download the map's KML. Returns ``(kml_bytes, info)``.

    On a network failure, falls back to the last successful download kept in
    ``cache_dir`` (``info["stale"] = True``) so the portal keeps working when
    Google is briefly unreachable. Access errors (private map) are never
    masked by the cache -- the user needs to know sharing changed.
    """
    url = KML_EXPORT_URL.format(mid=mid)
    path = _cache_path(mid, cache_dir)
    try:
        resp = requests.get(url, timeout=timeout,
                            headers={"User-Agent": "Mozilla/5.0 (clustering-web-app)"})
    except requests.RequestException as e:
        return _from_disk_cache(path, f"Network error reaching Google My Maps: {e}")

    if resp.status_code in (401, 403, 404):
        raise MyMapsAccessError(
            f"Google returned HTTP {resp.status_code} for map {mid}. Check the map ID and "
            "that the map is shared as 'Anyone with the link can view'."
        )
    if resp.status_code != 200:
        return _from_disk_cache(path, f"Google My Maps returned HTTP {resp.status_code}")

    data = resp.content
    # forcekml=1 should give plain KML, but handle a KMZ (zip) just in case.
    if data[:2] == b"PK":
        with zipfile.ZipFile(BytesIO(data)) as zf:
            kml_name = next((n for n in zf.namelist() if n.lower().endswith(".kml")), None)
            if not kml_name:
                raise MyMapsError("Downloaded KMZ contains no KML file.")
            data = zf.read(kml_name)

    head = data[:2048].lstrip().lower()
    if b"<kml" not in head and b"<?xml" not in head:
        # A private map redirects to an HTML sign-in page.
        raise MyMapsAccessError(
            "Google did not return KML for this map -- it is probably private. In My Maps, "
            "click Share and set 'Anyone with the link' to Viewer, then retry."
        )

    try:
        with open(path, "wb") as f:
            f.write(data)
    except OSError:
        pass  # cache is best-effort
    return data, {"source": "live", "stale": False, "fetched_at": time.time(),
                  "bytes": len(data), "url": url}


def _from_disk_cache(path: str, reason: str) -> tuple[bytes, dict]:
    if os.path.exists(path):
        with open(path, "rb") as f:
            data = f.read()
        return data, {"source": "disk-cache", "stale": True, "reason": reason,
                      "fetched_at": os.path.getmtime(path), "bytes": len(data)}
    raise MyMapsError(reason)


# ─────────────────────────────────────────────────────────────
# Parse
# ─────────────────────────────────────────────────────────────
def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(el, name: str) -> str:
    """Text of a direct child, namespaced or not. (Avoids `find(a) or find(b)`:
    an Element with no children is falsy, which silently drops matches.)"""
    for ch in el:
        if _local(ch.tag) == name:
            return (ch.text or "").strip()
    return ""


def _parse_coords(text: str) -> list[tuple[float, float]]:
    pts = []
    for tok in (text or "").split():
        parts = tok.split(",")
        if len(parts) >= 2:
            try:
                pts.append((float(parts[0]), float(parts[1])))
            except ValueError:
                pass
    return pts


def _ring_coords(boundary_el) -> list[tuple[float, float]]:
    for el in boundary_el.iter():
        if _local(el.tag) == "coordinates":
            return _parse_coords(el.text)
    return []


def _placemark_polygons(pm):
    """All polygons in a placemark (handles MultiGeometry) as shapely Polygons."""
    from shapely.geometry import Polygon
    polys = []
    for el in pm.iter():
        if _local(el.tag) != "Polygon":
            continue
        outer, inners = [], []
        for ch in el:
            n = _local(ch.tag)
            if n == "outerBoundaryIs":
                outer = _ring_coords(ch)
            elif n == "innerBoundaryIs":
                ring = _ring_coords(ch)
                if len(ring) >= 4:
                    inners.append(ring)
        if len(outer) >= 4:
            try:
                polys.append(Polygon(outer, inners))
            except Exception:
                pass
    return polys


def _placemark_point(pm):
    for el in pm.iter():
        if _local(el.tag) == "Point":
            for ch in el.iter():
                if _local(ch.tag) == "coordinates":
                    pts = _parse_coords(ch.text)
                    if pts:
                        return pts[0]
    return None


def _norm_key(k: str) -> str:
    return re.sub(r"[^a-z]", "", (k or "").replace("﻿", "").lower())


_FIELD_ALIASES = {
    "hub": "hub", "hubname": "hub",
    "pincode": "pincode", "pin": "pincode",
    "category": "category", "clustercategory": "category",
    "rate": "rate", "surge": "rate",
    "clustercode": "cluster_code",
}


def _parse_description(desc: str) -> dict:
    """Parse 'Hub: X | Pincode: N | Category: C1 | Rate: ₹0' (or <br>-separated)."""
    out = {}
    if not desc:
        return out
    text = re.sub(r"<br\s*/?>", "|", desc, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    parts = [p.strip() for p in text.split("|") if p.strip()]
    for p in parts:
        if ":" in p:
            k, v = p.split(":", 1)
            k, v = _norm_key(k), v.strip()
            if not v:
                continue
            if k == "description" and _CATEGORY_RE.match(v):
                out.setdefault("category", v.upper())
            elif k in _FIELD_ALIASES:
                out.setdefault(_FIELD_ALIASES[k], v)
        elif _CATEGORY_RE.match(p):
            out.setdefault("category", p.upper())
    return out


def _parse_extended_data(pm) -> dict:
    out = {}
    for el in pm:
        if _local(el.tag) != "ExtendedData":
            continue
        for d in el.iter():
            if _local(d.tag) != "Data":
                continue
            k = _norm_key(d.get("name", ""))
            v = _child_text(d, "value")
            if not v:
                continue
            if k == "description" and _CATEGORY_RE.match(v):
                out.setdefault("category", v.upper())
            elif k in _FIELD_ALIASES:
                out.setdefault(_FIELD_ALIASES[k], v)
    return out


def _format_rate(v: str) -> str:
    v = (v or "").strip()
    if not v:
        return ""
    if v.lower() == "nil":
        return "Nil"
    num = v.replace("₹", "").replace("Rs.", "").replace("Rs", "").strip()
    try:
        f = float(num)
        return f"₹{int(f)}" if f.is_integer() else f"₹{f:g}"
    except ValueError:
        return v


def _iter_placemarks(node, layer: str):
    """Yield (layer_name, placemark), using the nearest enclosing Folder name."""
    for ch in node:
        n = _local(ch.tag)
        if n == "Placemark":
            yield layer, ch
        elif n in ("Folder", "Document"):
            yield from _iter_placemarks(ch, _child_text(ch, "name") or layer)


def parse_kml(kml_bytes: bytes) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    """Parse My Maps KML into ``(polygons_df, hubs_df, map_title)``.

    Polygons whose hub is not written on the polygon itself (e.g. a layer
    whose description is only 'C3') get their hub from another layer that has
    the same Cluster_Code with a hub, or else from the ``HUB:`` point that is
    in the same layer and nearest to the polygon. Such rows have
    ``Hub Source`` = 'inferred-code' / 'inferred-nearest-hub' so they can be
    reviewed; rows read from the map directly have 'mymaps'.
    """
    from shapely.geometry import MultiPolygon

    root = ET.fromstring(kml_bytes)
    doc = next((e for e in root.iter() if _local(e.tag) == "Document"), root)
    title = _child_text(doc, "name")

    poly_rows, hub_rows = [], []
    for layer, pm in _iter_placemarks(doc, title):
        name = _child_text(pm, "name")
        polys = _placemark_polygons(pm)
        if not polys:
            pt = _placemark_point(pm)
            if pt is None or not name or _COORD_NAME_RE.match(name):
                continue
            is_hub_prefixed = name.upper().startswith("HUB:")
            hub = name.split(":", 1)[1].strip() if is_hub_prefixed else name.strip()
            hub_rows.append({"Hub Name": hub, "Hub_lat": pt[1], "Hub_long": pt[0],
                             "Layer": layer, "_prefixed": is_hub_prefixed})
            continue

        fields = _parse_extended_data(pm)
        for k, v in _parse_description(_child_text(pm, "description")).items():
            fields.setdefault(k, v)
        code = fields.get("cluster_code") or name
        pin = fields.get("pincode", "")
        if not pin:
            m = _PINCODE_RE.match(code or "")
            pin = m.group(1) if m else ""
        pin = re.sub(r"\.0$", "", str(pin).strip())
        hub = fields.get("hub", "").strip()
        if not hub and not pin and _HUB_NAME_RE.match(name or ""):
            hub = name.strip()  # a hub-boundary polygon named after its hub
        rate = _format_rate(fields.get("rate", ""))
        cat = fields.get("category", "").upper()
        if not rate and cat in _CAT_TO_RATE:
            rate = _format_rate(str(_CAT_TO_RATE[cat]))
        if not cat and rate in _RATE_TO_CAT:
            cat = _RATE_TO_CAT[rate]
        geom = polys[0] if len(polys) == 1 else MultiPolygon(polys)
        poly_rows.append({
            "Pincode": pin,
            "Hub Name": hub,
            "Cluster_Code": code,
            "Description": rate,
            "Cluster_Category": cat,
            "Polygon WKT": geom.wkt,
            "Layer": layer,
            "Hub Source": "mymaps" if hub else "",
            "_geom": geom,
        })

    pdf = pd.DataFrame(poly_rows)
    hdf = pd.DataFrame(hub_rows)
    if pdf.empty:
        pdf = pd.DataFrame(columns=POLYGON_COLUMNS + ["Hub Source", "_geom"])
    if hdf.empty:
        hdf = pd.DataFrame(columns=HUB_COLUMNS + ["_prefixed"])

    _infer_missing_hubs(pdf, hdf)
    pdf = pdf.drop(columns=["_geom"])

    # Hub points: keep 'HUB:'-prefixed ones, plus un-prefixed names that look
    # like hub codes (e.g. 'PNQ_Kothrud'); one row per hub name.
    if not hdf.empty:
        looks_like_hub = hdf["Hub Name"].str.match(_HUB_NAME_RE)
        hdf = hdf[hdf["_prefixed"] | looks_like_hub]
        hdf = (hdf.sort_values("_prefixed", ascending=False)
                  .drop_duplicates("Hub Name").drop(columns=["_prefixed"])
                  .sort_values("Hub Name").reset_index(drop=True))
    return pdf.reset_index(drop=True), hdf, title


def _infer_missing_hubs(pdf: pd.DataFrame, hdf: pd.DataFrame) -> None:
    missing = pdf["Hub Name"].eq("")
    if not missing.any():
        return
    # 1) Same Cluster_Code has a hub in another layer.
    code_to_hub = (pdf.loc[~missing].drop_duplicates("Cluster_Code")
                      .set_index("Cluster_Code")["Hub Name"])
    by_code = pdf.loc[missing, "Cluster_Code"].map(code_to_hub)
    hit = by_code.notna()
    pdf.loc[by_code[hit].index, "Hub Name"] = by_code[hit]
    pdf.loc[by_code[hit].index, "Hub Source"] = "inferred-code"

    # 2) Nearest hub point in the same layer (polygons of one pincode share it).
    missing = pdf["Hub Name"].eq("")
    if not missing.any() or hdf.empty:
        return
    from shapely.geometry import Point
    for layer, idx in pdf[missing].groupby("Layer").groups.items():
        hubs = hdf[hdf["Layer"] == layer]
        if hubs.empty:
            continue
        hub_pts = [(r["Hub Name"], Point(r["Hub_long"], r["Hub_lat"])) for _, r in hubs.iterrows()]
        # Decide per pincode using the union-ish centroid of all its rings,
        # so the A/B/C rings of one pincode always land on the same hub.
        sub = pdf.loc[idx]
        for _, grp in sub.groupby(sub["Pincode"].where(sub["Pincode"] != "", sub["Cluster_Code"])):
            c = grp["_geom"].iloc[0].centroid
            best = min(hub_pts, key=lambda hp: hp[1].distance(c))[0]
            pdf.loc[grp.index, "Hub Name"] = best
            pdf.loc[grp.index, "Hub Source"] = "inferred-nearest-hub"


def load_map(url_or_id: str, cache_dir: str | None = None, timeout: int = 90) -> dict:
    """Fetch + parse a My Maps map. Returns a dict with polygons, hubs, title, info."""
    mid = extract_map_id(url_or_id)
    data, info = fetch_kml(mid, timeout=timeout, cache_dir=cache_dir)
    polygons, hubs, title = parse_kml(data)
    info["mid"] = mid
    return {"polygons": polygons, "hubs": hubs, "title": title, "info": info}


# ─────────────────────────────────────────────────────────────
# Lookups
# ─────────────────────────────────────────────────────────────
def _norm_hub(s) -> str:
    return re.sub(r"\s+", "", str(s or "")).lower()


def list_hubs(polygons: pd.DataFrame) -> list[str]:
    hubs = polygons["Hub Name"].dropna()
    return sorted(h for h in hubs.unique() if h)


def get_hub_polygons(polygons: pd.DataFrame, hubs, layers=None) -> pd.DataFrame:
    """Polygons for one hub name or a list of them (case/space-insensitive)."""
    if isinstance(hubs, str):
        hubs = [hubs]
    wanted = {_norm_hub(h) for h in hubs}
    out = polygons[polygons["Hub Name"].map(_norm_hub).isin(wanted)]
    if layers:
        out = out[out["Layer"].isin(layers)]
    return out.reset_index(drop=True)


def find_polygons(polygons: pd.DataFrame, query: str) -> pd.DataFrame:
    """Search by Cluster_Code (e.g. '206131_A'), pincode ('206131') or hub name.

    Comma-separated queries are OR-ed. Exact Cluster_Code / pincode matches
    win; otherwise falls back to a case-insensitive substring match.
    """
    terms = [t.strip() for t in str(query or "").split(",") if t.strip()]
    if not terms:
        return polygons.iloc[0:0]
    code = polygons["Cluster_Code"].astype(str).str.lower()
    pin = polygons["Pincode"].astype(str)
    hub = polygons["Hub Name"].map(_norm_hub)
    mask = pd.Series(False, index=polygons.index)
    for t in terms:
        tl = t.lower()
        exact = (code == tl) | (pin == t) | (hub == _norm_hub(t))
        mask |= exact if exact.any() else (code.str.contains(tl, regex=False)
                                           | hub.str.contains(_norm_hub(t), regex=False))
    return polygons[mask].reset_index(drop=True)


def hub_layer_breakdown(polygons: pd.DataFrame, hub: str) -> pd.DataFrame:
    """Per-layer counts for one hub, flagging layers where the hub was written
    explicitly on the polygons (vs inferred)."""
    rows = get_hub_polygons(polygons, hub)
    if rows.empty:
        return pd.DataFrame(columns=["Layer", "Polygons", "Pincodes", "Explicit"])
    g = rows.groupby("Layer", sort=False)
    return pd.DataFrame({
        "Polygons": g.size(),
        "Pincodes": g["Pincode"].nunique(),
        "Explicit": g["Hub Source"].apply(lambda s: bool((s == "mymaps").any())),
    }).reset_index()


def default_layers_for_hub(polygons: pd.DataFrame, hub: str) -> list[str]:
    """Layers to show by default for a hub: those where the hub is explicit,
    else every layer it appears in."""
    b = hub_layer_breakdown(polygons, hub)
    explicit = b.loc[b["Explicit"], "Layer"].tolist()
    return explicit or b["Layer"].tolist()


def hub_summary(polygons: pd.DataFrame) -> pd.DataFrame:
    """One row per hub: polygon/pincode counts, layers, inferred-hub rows."""
    if polygons.empty:
        return pd.DataFrame(columns=["Hub Name", "Polygons", "Pincodes", "Layers", "Inferred rows"])
    p = polygons[polygons["Hub Name"] != ""]
    g = p.groupby("Hub Name")
    return pd.DataFrame({
        "Polygons": g.size(),
        "Pincodes": g["Pincode"].nunique(),
        "Layers": g["Layer"].nunique(),
        "Inferred rows": g["Hub Source"].apply(lambda s: int(s.str.startswith("inferred").sum())),
    }).reset_index().sort_values("Hub Name").reset_index(drop=True)


def _xesc(s) -> str:
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _polygon_kml(pg) -> str:
    ring = lambda coords: " ".join(f"{x},{y},0" for x, y in coords)
    inner = "".join(f"<innerBoundaryIs><LinearRing><coordinates>{ring(r.coords)}"
                    f"</coordinates></LinearRing></innerBoundaryIs>" for r in pg.interiors)
    return (f"<Polygon><outerBoundaryIs><LinearRing><coordinates>{ring(pg.exterior.coords)}"
            f"</coordinates></LinearRing></outerBoundaryIs>{inner}</Polygon>")


def to_kml(polygons: pd.DataFrame, hubs: pd.DataFrame | None = None, title: str = "Polygons") -> str:
    """KML with one Placemark per polygon row (MultiGeometry for multipolygons)
    plus ``HUB:`` points, in the same description format My Maps holds today --
    so the file re-imports into My Maps and round-trips through ``parse_kml``."""
    from shapely.wkt import loads as wkt_loads
    marks = []
    if hubs is not None:
        for _, h in hubs.iterrows():
            if pd.notna(h.get("Hub_lat")) and pd.notna(h.get("Hub_long")):
                marks.append(f"<Placemark><name>HUB: {_xesc(h['Hub Name'])}</name><styleUrl>#hub</styleUrl>"
                             f"<Point><coordinates>{h['Hub_long']},{h['Hub_lat']},0</coordinates></Point></Placemark>")
    for _, r in polygons.iterrows():
        try:
            g = wkt_loads(str(r["Polygon WKT"]))
        except Exception:
            continue
        parts = list(g.geoms) if g.geom_type == "MultiPolygon" else [g]
        geom_kml = "".join(_polygon_kml(pg) for pg in parts)
        if len(parts) > 1:
            geom_kml = f"<MultiGeometry>{geom_kml}</MultiGeometry>"
        desc = " | ".join(f"{lab}: {_xesc(r.get(col))}" for lab, col in
                          [("Hub", "Hub Name"), ("Pincode", "Pincode"),
                           ("Category", "Cluster_Category"), ("Rate", "Description")]
                          if _xesc(r.get(col)))
        marks.append(f"<Placemark><name>{_xesc(r.get('Cluster_Code'))}</name>"
                     f"<description>{desc}</description><styleUrl>#poly</styleUrl>{geom_kml}</Placemark>")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
            f"<name>{_xesc(title)}</name>"
            '<Style id="hub"><IconStyle><color>ff0000ff</color><scale>1.2</scale>'
            '<Icon><href>http://maps.google.com/mapfiles/kml/paddle/red-stars.png</href></Icon></IconStyle></Style>'
            '<Style id="poly"><LineStyle><color>ff984e00</color><width>2</width></LineStyle>'
            '<PolyStyle><color>55984e00</color></PolyStyle></Style>'
            + "".join(marks) + "</Document></kml>")


def to_csv_bytes(polygons: pd.DataFrame) -> bytes:
    """Polygon table as CSV in the app's standard column order (+ Map, Layer, Hub Source)."""
    cols = [c for c in ["Map"] + POLYGON_COLUMNS + ["Hub Source"] if c in polygons.columns]
    return polygons[cols].to_csv(index=False).encode("utf-8-sig")


def to_geojson(polygons: pd.DataFrame) -> str:
    import json
    from shapely.geometry import mapping
    from shapely.wkt import loads as wkt_loads
    feats = []
    for _, r in polygons.iterrows():
        try:
            g = wkt_loads(str(r["Polygon WKT"]))
        except Exception:
            continue
        props = {c: (None if pd.isna(r.get(c)) else str(r.get(c)))
                 for c in POLYGON_COLUMNS if c != "Polygon WKT" and c in r}
        feats.append({"type": "Feature", "geometry": mapping(g), "properties": props})
    return json.dumps({"type": "FeatureCollection", "features": feats})




# ─────────────────────────────────────────────────────────────
# Several My Maps links
# ─────────────────────────────────────────────────────────────
def _link(name, url, source):
    try:
        mid = extract_map_id(url)
    except MyMapsError:
        return None
    return {"name": (str(name or "").strip() or mid), "url": str(url).strip(), "mid": mid, "source": source}


def configured_links(secrets=None) -> list[dict]:
    """Maps set by the admin -- not removable from the UI.

    Read from Streamlit secrets, any of:
        [[mymaps]]                      # one table per map
        name = "North hubs"
        url  = "https://www.google.com/maps/d/edit?mid=..."
        MYMAPS_URLS = ["https://...", "https://..."]
        MYMAPS_URL  = "https://..."
    then env vars MYMAPS_URLS (comma-separated) / MYMAPS_URL, then the default map.
    """
    out = []

    def sget(k):
        try:
            return secrets.get(k) if secrets is not None else None
        except Exception:
            return None

    for t in (sget("mymaps") or []):
        try:
            out.append(_link(t.get("name"), t.get("url"), "secrets"))
        except Exception:
            pass
    for u in (sget("MYMAPS_URLS") or []):
        out.append(_link("", u, "secrets"))
    if sget("MYMAPS_URL"):
        out.append(_link("", sget("MYMAPS_URL"), "secrets"))
    for u in filter(None, (os.environ.get("MYMAPS_URLS") or "").split(",")):
        out.append(_link("", u, "env"))
    if os.environ.get("MYMAPS_URL"):
        out.append(_link("", os.environ["MYMAPS_URL"], "env"))
    if not any(out):
        out.append(_link("Hub_Cluster-Amrutraj", DEFAULT_MYMAPS_URL, "default"))
    return [l for l in out if l]


def load_saved_links(path: str) -> list[dict]:
    """Maps added from the UI (a small JSON file)."""
    import json
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return []
    return [l for l in (_link(r.get("name"), r.get("url"), "saved") for r in raw if isinstance(r, dict)) if l]


def save_links(path: str, links: list[dict]) -> None:
    import json
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump([{"name": l["name"], "url": l["url"]} for l in links], f, indent=2, ensure_ascii=False)


def merge_links(*groups: list[dict]) -> list[dict]:
    """Concatenate link lists, first occurrence of each map ID wins."""
    seen, out = set(), []
    for g in groups:
        for l in g:
            if l["mid"] not in seen:
                seen.add(l["mid"])
                out.append(l)
    return out


# ─────────────────────────────────────────────────────────────
# Photo (PNG) of a set of polygons
# ─────────────────────────────────────────────────────────────
# Same buckets/colours as the app's map legend (modules/visualizer.py).
_RATE_BUCKETS = [
    ("₹0", lambda r: r == 0, "#22c55e"),
    ("₹1–₹2", lambda r: 0 < r <= 2, "#3b82f6"),
    ("₹3–₹4", lambda r: 2 < r <= 4, "#8b5cf6"),
    ("₹5–₹6", lambda r: 4 < r <= 6, "#f59e0b"),
    ("₹7–₹8", lambda r: 6 < r <= 8, "#ef4444"),
    ("₹9+", lambda r: r > 8, "#991b1b"),
]
_NO_RATE = ("Nil / no rate", "#6b7280")


def _rate_bucket(desc):
    try:
        r = float(str(desc).replace("₹", "").strip())
    except ValueError:
        return _NO_RATE
    for label, test, color in _RATE_BUCKETS:
        if test(r):
            return label, color
    return _NO_RATE


def _merc_to_lonlat_bounds(x0, y0, x1, y1):
    import math
    lon = lambda x: x / 6378137.0 * 180 / math.pi
    lat = lambda y: math.degrees(2 * math.atan(math.exp(y / 6378137.0)) - math.pi / 2)
    return lon(x0), lat(y0), lon(x1), lat(y1)


def _basemap_zoom(bounds_lonlat) -> int:
    """Tile zoom giving ~5 tiles across the extent (contextily's zoom='auto'
    fetches several times more tiles than a 14-inch figure needs)."""
    import math
    minx, miny, maxx, maxy = bounds_lonlat
    span = max(maxx - minx, (maxy - miny) * 1.15, 1e-3)  # larger side (lat ~ lon near India)
    return int(min(15, max(4, math.floor(math.log2(5 * 360 / span)))))


def render_png(polygons: pd.DataFrame, hubs: pd.DataFrame | None = None, title: str = "",
               basemap: bool = True, dpi: int = 150) -> bytes:
    """Draw polygons (coloured by rate, labelled) + hub pins on a street basemap; return PNG bytes.

    The basemap (Esri, via contextily) is best-effort: without network the
    photo is still produced, just on a plain background.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    import geopandas as gpd
    from shapely.wkt import loads as wkt_loads

    recs = []
    for _, r in polygons.iterrows():
        try:
            g = wkt_loads(str(r["Polygon WKT"]))
        except Exception:
            continue
        label, color = _rate_bucket(r.get("Description", ""))
        recs.append({"geometry": g, "rate": str(r.get("Description", "") or ""), "bucket": label,
                     "color": color, "code": str(r.get("Cluster_Code", ""))})
    if not recs:
        raise MyMapsError("Nothing to draw -- the selection has no polygon geometry.")
    gdf = gpd.GeoDataFrame(recs, geometry="geometry", crs="EPSG:4326").to_crs(epsg=3857)
    # Biggest first so inner rings stay visible on top of outer ones.
    gdf = gdf.assign(_a=gdf.area).sort_values("_a", ascending=False)

    fig, ax = plt.subplots(figsize=(14, 10))
    try:
        gdf.plot(ax=ax, color=gdf["color"].tolist(), alpha=0.35, edgecolor="#1f2937", linewidth=1.0, zorder=2)
        if len(gdf) <= 250:
            for _, rp in gdf.iterrows():
                p = rp.geometry.representative_point()
                ax.text(p.x, p.y, rp["rate"] or rp["code"], ha="center", va="center", fontsize=8,
                        fontweight="bold", zorder=6,
                        bbox=dict(facecolor="white", edgecolor="none", alpha=0.8, boxstyle="round,pad=0.25"))
        if hubs is not None and not hubs.empty:
            hg = gpd.GeoDataFrame(hubs[["Hub Name"]].copy(),
                                  geometry=gpd.points_from_xy(hubs["Hub_long"], hubs["Hub_lat"]),
                                  crs="EPSG:4326").to_crs(epsg=3857)
            ax.scatter(hg.geometry.x, hg.geometry.y, marker="^", s=220, c="#dc2626",
                       edgecolors="white", linewidths=1.5, zorder=7)
            for _, h in hg.iterrows():
                ax.annotate(h["Hub Name"], (h.geometry.x, h.geometry.y), xytext=(8, 8),
                            textcoords="offset points", fontsize=10, fontweight="bold", color="#7f1d1d",
                            zorder=8, bbox=dict(facecolor="white", edgecolor="#dc2626", alpha=0.9,
                                                boxstyle="round,pad=0.3"))
        minx, miny, maxx, maxy = gdf.total_bounds
        if hubs is not None and not hubs.empty:  # keep hub pins in frame
            minx, maxx = min(minx, hg.geometry.x.min()), max(maxx, hg.geometry.x.max())
            miny, maxy = min(miny, hg.geometry.y.min()), max(maxy, hg.geometry.y.max())
        # Pad, then widen the short side to the figure's 14:10 shape so the
        # photo is never a thin strip.
        cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
        w, hgt = max(maxx - minx, 1000) * 1.16, max(maxy - miny, 1000) * 1.16
        if w / hgt < 1.4:
            w = hgt * 1.4
        else:
            hgt = w / 1.4
        ax.set_xlim(cx - w / 2, cx + w / 2)
        ax.set_ylim(cy - hgt / 2, cy + hgt / 2)
        if basemap:
            try:
                import contextily as ctx
                src = ctx.providers.Esri.WorldStreetMap
                (x0, x1), (y0, y1) = ax.get_xlim(), ax.get_ylim()
                # bounds2img (not add_basemap) so tiles download in parallel:
                # one-at-a-time took 15-70 s per photo, parallel ~3-5 s.
                img, ext = ctx.bounds2img(x0, y0, x1, y1, source=src, n_connections=6, timeout=20,
                                          zoom=_basemap_zoom(_merc_to_lonlat_bounds(x0, y0, x1, y1)))
                ax.imshow(img, extent=ext, interpolation="bilinear", zorder=0)
                ax.set_xlim(x0, x1); ax.set_ylim(y0, y1)
                ctx.add_attribution(ax, src["attribution"], font_size=7)
            except Exception:
                pass
        order = [b[0] for b in _RATE_BUCKETS] + [_NO_RATE[0]]
        present = [b for b in order if b in set(gdf["bucket"])]
        colors = dict(zip(gdf["bucket"], gdf["color"]))
        ax.legend(handles=[Patch(facecolor=colors[b], edgecolor="#1f2937", alpha=0.6, label=b) for b in present],
                  loc="lower right", title="Payout rate", fontsize=9, framealpha=0.95)
        n_pins = polygons["Pincode"].replace("", pd.NA).nunique() if "Pincode" in polygons else 0
        ax.set_title(f"{title}\n{len(gdf)} polygons · {n_pins} pincodes", fontsize=14,
                     fontweight="bold", color="#0B8A7A")
        ax.text(0.01, 0.99, f"Source: Google My Maps · {time.strftime('%d %b %Y')}", transform=ax.transAxes,
                fontsize=8, color="#374151", zorder=9, va="top",
                bbox=dict(facecolor="white", edgecolor="none", alpha=0.8))
        ax.set_axis_off()
        buf = BytesIO()
        fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight", facecolor="white", pad_inches=0.1)
        return buf.getvalue()
    finally:
        plt.close(fig)


def render_hub_photos(polygons: pd.DataFrame, hubs: pd.DataFrame, hub_names, progress_cb=None):
    """One PNG per hub (each framed on its own polygons). Returns [(hub, png_bytes)]."""
    out = []
    for i, hub in enumerate(hub_names):
        sub = get_hub_polygons(polygons, hub)
        if sub.empty:
            continue
        pins = hubs[hubs["Hub Name"].map(_norm_hub) == _norm_hub(hub)] if hubs is not None else None
        out.append((hub, render_png(sub, pins, hub)))
        if progress_cb:
            progress_cb((i + 1) / len(hub_names), hub)
    return out


def photos_zip(photos) -> bytes:
    """Zip [(hub, png)] as <hub>.png files."""
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for hub, png in photos:
            safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", hub) or "hub"
            zf.writestr(f"{safe}.png", png)
    return buf.getvalue()
