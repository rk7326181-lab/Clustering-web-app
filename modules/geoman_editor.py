"""
Geoman polygon editor — builds a standalone Leaflet-Geoman HTML page.

Leaflet-Geoman fires pm:update / pm:create / pm:remove events AFTER each
edit is committed (no race condition vs streamlit-folium's all_drawings).
Data is captured in the HTML itself and copied to clipboard / shown in a
text area so the user can paste it into the Streamlit import field.
"""

import json
import pandas as pd
from shapely.wkt import loads as wkt_loads


def build_geoman_editor_html(
    polygon_df: pd.DataFrame,
    hub_filter: str = "All Hubs",
    height: int = 650,
) -> str:
    """Build a standalone Leaflet + Leaflet-Geoman HTML page."""
    df = polygon_df.copy()
    df.columns = df.columns.str.strip()

    hub_col  = "Hub Name"       if "Hub Name"       in df.columns else "hub_name"
    wkt_col  = "Polygon WKT"    if "Polygon WKT"    in df.columns else "boundary"
    cc_col   = "Cluster_Code"   if "Cluster_Code"   in df.columns else "cluster_code"
    pin_col  = "Pincode"        if "Pincode"        in df.columns else "pincode"
    desc_col = "Description"    if "Description"    in df.columns else "surge_amount"
    cat_col  = "Cluster_Category" if "Cluster_Category" in df.columns else "cluster_category"

    if hub_filter and hub_filter not in ("All Hubs", "All") and hub_col in df.columns:
        df = df[df[hub_col] == hub_filter]

    features = []
    for _, row in df.iterrows():
        wkt = row.get(wkt_col, "")
        if not wkt or (isinstance(wkt, float) and pd.isna(wkt)):
            continue
        try:
            geom = wkt_loads(str(wkt))
        except Exception:
            continue
        polys = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
        for poly in polys:
            coords = [[[round(x, 6), round(y, 6)] for x, y in poly.exterior.coords]]
            features.append({
                "type": "Feature",
                "properties": {
                    "cluster_code":     str(row.get(cc_col,   "")),
                    "hub_name":         str(row.get(hub_col,  "")),
                    "pincode":          str(row.get(pin_col,  "")),
                    "description":      str(row.get(desc_col, "")),
                    "cluster_category": str(row.get(cat_col,  "")),
                },
                "geometry": {"type": "Polygon", "coordinates": coords},
            })

    fc_json = json.dumps({"type": "FeatureCollection", "features": features})

    center_lat, center_lon = 20.59, 78.96
    if features:
        lats, lons = [], []
        for f in features[:50]:
            for coord in f["geometry"]["coordinates"][0]:
                lons.append(coord[0]); lats.append(coord[1])
        if lats:
            center_lat = sum(lats) / len(lats)
            center_lon = sum(lons) / len(lons)

    map_h = height - 120

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<title>Polygon Editor</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<link rel="stylesheet" href="https://unpkg.com/@geoman-io/leaflet-geoman@latest/dist/leaflet-geoman.css"/>
<style>
  html,body {{ margin:0;padding:0;height:100%;font-family:Arial,sans-serif;background:#0f172a; }}
  #map {{ height:{map_h}px;width:100%; }}

  /* ── Force Geoman toolbar icons to be visible ── */
  .leaflet-pm-toolbar {{
    display:flex !important;
    flex-direction:column !important;
  }}
  .leaflet-pm-toolbar .leaflet-pm-actions-container {{ display:none; }}
  .button-container.active .leaflet-pm-actions-container {{ display:block; }}
  .leaflet-pm-toolbar a {{
    width:30px !important; height:30px !important;
    display:flex !important; align-items:center; justify-content:center;
    background:#fff !important; border:none !important;
    cursor:pointer; border-radius:2px;
    box-shadow:0 1px 5px rgba(0,0,0,0.65) !important;
    margin-bottom:1px;
  }}
  .leaflet-pm-toolbar a:hover {{ background:#f0f0f0 !important; }}
  .leaflet-pm-toolbar a.active {{ background:#0B8A7A !important; color:#fff !important; }}
  /* Make icons visible — SVG masks need fill */
  .leaflet-pm-icon {{ width:16px;height:16px;display:inline-block; }}

  /* ── Top action bar ── */
  #topbar {{
    background:#1e293b; color:#fff; padding:6px 10px;
    display:flex; align-items:center; gap:6px; flex-wrap:wrap;
    border-bottom:1px solid #334155;
  }}
  .tbtn {{
    background:#0B8A7A; color:#fff; border:none; border-radius:5px;
    padding:5px 12px; font-size:12px; font-weight:700; cursor:pointer;
    display:flex; align-items:center; gap:4px;
  }}
  .tbtn:hover {{ background:#097A6C; }}
  .tbtn-gray {{ background:#475569; }}
  .tbtn-gray:hover {{ background:#334155; }}
  .tbtn-red {{ background:#DC2626; }}
  .tbtn-red:hover {{ background:#B91C1C; }}
  #status {{ font-size:11px; color:#94a3b8; flex:1; min-width:180px; }}
  #cnt {{ font-size:11px; background:#0B8A7A30; color:#4AEDC4;
          border:1px solid #0B8A7A; border-radius:4px; padding:2px 8px; }}

  /* ── Output area ── */
  #outbox {{
    background:#0f172a; border:1px solid #0B8A7A; border-radius:5px;
    padding:6px 10px; font-size:10px; color:#4AEDC4; font-family:monospace;
    margin:4px 8px; max-height:60px; overflow-y:auto;
    word-break:break-all; white-space:pre-wrap; min-height:26px;
  }}

  /* ── Mode indicator buttons ── */
  #mode-btns {{ display:flex; gap:4px; }}
  .mode-btn {{
    background:#1e293b; color:#94a3b8; border:1px solid #475569;
    border-radius:4px; padding:4px 10px; font-size:11px; cursor:pointer;
    font-weight:600;
  }}
  .mode-btn.on {{ background:#0B8A7A; color:#fff; border-color:#0B8A7A; }}
  .mode-btn:hover {{ background:#334155; color:#fff; }}
</style>
</head>
<body>

<div id="topbar">
  <span id="status">Select an edit mode using the buttons below</span>
  <span id="cnt">0 polygons</span>
  <div style="flex:1"></div>
  <button class="tbtn" onclick="copyCSV()" title="Copy edited polygons as CSV">
    📋 Copy Edited Polygons (CSV)
  </button>
</div>

<div id="mode-btns" style="padding:4px 8px; background:#1e293b; border-bottom:1px solid #334155; display:flex; gap:4px; flex-wrap:wrap;">
  <button class="mode-btn" id="btn-edit"   onclick="toggleMode('edit')"   title="Drag vertex handles to reshape polygons">✏️ Edit Vertices</button>
  <button class="mode-btn" id="btn-drag"   onclick="toggleMode('drag')"   title="Move entire polygons">🖐 Drag Polygon</button>
  <button class="mode-btn" id="btn-draw"   onclick="toggleMode('draw')"   title="Draw a new polygon">✚ Draw New</button>
  <button class="mode-btn" id="btn-delete" onclick="toggleMode('delete')" title="Click a polygon to delete it">🗑 Delete</button>
  <button class="mode-btn tbtn-gray" onclick="disableAll()" title="Exit all edit modes">✗ Exit</button>
</div>

<div id="map"></div>
<div id="outbox">CSV will appear here after clicking "Copy Edited Polygons"</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/@geoman-io/leaflet-geoman@latest/dist/leaflet-geoman.umd.js"></script>
<script>

var FC = {fc_json};
var polyLayers = [];
var colorPalette = ['#FF6384','#36A2EB','#FFCE56','#4BC0C0','#9966FF','#FF9F40','#00B3E6','#E6B333','#CC3366','#34D399'];
var hubColors = {{}};
var hIdx = 0;
var activeMode = null;

// ── Map ────────────────────────────────────────────────────────────────────
var map = L.map('map', {{
  center: [{center_lat:.4f}, {center_lon:.4f}],
  zoom: 10,
  zoomControl: true
}});

var osmTile = L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
  attribution: '© OpenStreetMap', maxZoom: 19
}}).addTo(map);

var satTile = L.tileLayer(
  'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',
  {{ attribution: 'Esri', maxZoom: 19 }}
);

L.control.layers({{'Street Map': osmTile, 'Satellite': satTile}}, {{}}, {{position:'topright'}}).addTo(map);
L.control.scale({{position:'bottomright'}}).addTo(map);

// ── Load polygons ──────────────────────────────────────────────────────────
if (FC && FC.features && FC.features.length > 0) {{
  FC.features.forEach(function(feature) {{
    var hub = (feature.properties && feature.properties.hub_name) || '';
    if (!hubColors[hub]) {{
      hubColors[hub] = colorPalette[hIdx % colorPalette.length];
      hIdx++;
    }}
    var color = hubColors[hub];

    var gjLayer = L.geoJSON(feature, {{
      style: function() {{
        return {{ color: color, weight: 2.5, fillColor: color, fillOpacity: 0.35, opacity:0.9 }};
      }},
      onEachFeature: function(f, layer) {{
        var p = f.properties || {{}};
        layer.bindPopup(
          '<div style="font-family:Arial;font-size:12px">' +
          '<b>' + (p.cluster_code||'N/A') + '</b><br>' +
          'Hub: ' + (p.hub_name||'') + '<br>' +
          'Pincode: ' + (p.pincode||'') + '<br>' +
          'Rate: ₹' + (p.description||'') +
          '</div>'
        );
        layer.bindTooltip(p.cluster_code||'', {{sticky:true, className:'leaflet-tooltip'}});
        layer._props = p;
        polyLayers.push(layer);
      }}
    }}).addTo(map);
  }});

  // Fit map to polygons
  try {{
    var group = L.featureGroup(polyLayers);
    map.fitBounds(group.getBounds().pad(0.05));
  }} catch(e) {{}}
}} else {{
  document.getElementById('status').textContent = 'No polygons loaded. Select a hub first.';
}}

document.getElementById('cnt').textContent = polyLayers.length + ' polygons';

// ── Geoman init ────────────────────────────────────────────────────────────
map.pm.setGlobalOptions({{
  allowSelfIntersection: false,
  snappable: true,
  snapDistance: 15,
}});

// ── Mode toggle buttons ────────────────────────────────────────────────────
function setAllBtnsOff() {{
  ['btn-edit','btn-drag','btn-draw','btn-delete'].forEach(function(id) {{
    var el = document.getElementById(id);
    if(el) el.classList.remove('on');
  }});
}}

function disableAll() {{
  map.pm.disableGlobalEditMode();
  map.pm.disableGlobalDragMode();
  map.pm.disableDraw();
  map.pm.disableGlobalRemovalMode();
  setAllBtnsOff();
  activeMode = null;
  document.getElementById('status').textContent = 'All modes off — click a mode button to start editing';
}}

function toggleMode(mode) {{
  // If clicking active mode, turn it off
  if (activeMode === mode) {{
    disableAll();
    return;
  }}
  // Disable all first
  map.pm.disableGlobalEditMode();
  map.pm.disableGlobalDragMode();
  map.pm.disableDraw();
  map.pm.disableGlobalRemovalMode();
  setAllBtnsOff();
  activeMode = mode;
  document.getElementById('btn-' + mode).classList.add('on');

  if (mode === 'edit') {{
    map.pm.enableGlobalEditMode({{ allowSelfIntersection: false }});
    document.getElementById('status').textContent = '✏️ Edit mode: drag orange vertex handles to reshape polygons';
  }} else if (mode === 'drag') {{
    map.pm.enableGlobalDragMode();
    document.getElementById('status').textContent = '🖐 Drag mode: click and drag a polygon to move it';
  }} else if (mode === 'draw') {{
    map.pm.enableDraw('Polygon');
    document.getElementById('status').textContent = '✚ Draw mode: click to add vertices, double-click to finish';
  }} else if (mode === 'delete') {{
    map.pm.enableGlobalRemovalMode();
    document.getElementById('status').textContent = '🗑 Delete mode: click a polygon to remove it';
  }}
}}

// ── Event listeners ────────────────────────────────────────────────────────
map.on('pm:edit', function(e) {{
  document.getElementById('status').textContent = '✅ Polygon reshaped — click "Copy Edited Polygons (CSV)" to export';
}});

map.on('pm:dragend', function(e) {{
  document.getElementById('status').textContent = '✅ Polygon moved — click "Copy Edited Polygons (CSV)" to export';
}});

map.on('pm:create', function(e) {{
  e.layer._props = {{
    cluster_code: 'NEW_' + (Date.now() % 100000),
    hub_name: '', pincode: '', description: '', cluster_category: ''
  }};
  polyLayers.push(e.layer);
  document.getElementById('cnt').textContent = polyLayers.length + ' polygons';
  document.getElementById('status').textContent = '🆕 New polygon drawn — export CSV and fill in metadata after pasting';
}});

map.on('pm:remove', function(e) {{
  var idx = polyLayers.indexOf(e.layer);
  if (idx > -1) polyLayers.splice(idx, 1);
  document.getElementById('cnt').textContent = polyLayers.length + ' polygons';
  document.getElementById('status').textContent = '🗑 Polygon deleted';
}});

// ── CSV export ─────────────────────────────────────────────────────────────
function layerToFeature(layer) {{
  try {{
    var gj = null;
    if (layer instanceof L.GeoJSON) {{
      var sub = [];
      layer.eachLayer(function(l) {{ if(l.toGeoJSON) sub.push(l); }});
      if (sub.length > 0) return sub.map(function(l) {{
        var f = l.toGeoJSON();
        if(l._props) f.properties = Object.assign({{}}, l._props, f.properties);
        return f;
      }});
      return [];
    }} else if (layer.toGeoJSON) {{
      gj = layer.toGeoJSON();
      if(layer._props) gj.properties = Object.assign({{}}, layer._props, gj.properties);
      return [gj];
    }}
  }} catch(e) {{ return []; }}
  return [];
}}

function copyCSV() {{
  var rows = ['"cluster_code","hub_name","pincode","description","cluster_category","geometry_wkt"'];
  var count = 0;

  map.eachLayer(function(layer) {{
    var skip = (layer instanceof L.TileLayer) ||
               (layer instanceof L.LayerGroup && !(layer instanceof L.GeoJSON)) ||
               layer._url; // tile layers have _url
    if (skip) return;

    var feats = layerToFeature(layer);
    feats.forEach(function(f) {{
      if (!f || !f.geometry) return;
      var g = f.geometry;
      // Handle both Polygon and MultiPolygon
      var rings = g.type === 'Polygon' ? g.coordinates : (g.type === 'MultiPolygon' ? g.coordinates[0] : null);
      if (!rings || !rings[0]) return;
      var coords = rings[0];
      if (coords.length < 4) return;

      // Close ring if not closed
      var first = coords[0], last = coords[coords.length-1];
      if (first[0] !== last[0] || first[1] !== last[1]) coords = coords.concat([first]);

      var wkt = 'POLYGON((' + coords.map(function(c) {{ return c[0] + ' ' + c[1]; }}).join(', ') + '))';
      var p = f.properties || {{}};
      function q(v) {{ return '"' + String(v||'').replace(/"/g,'""') + '"'; }}
      rows.push([q(p.cluster_code), q(p.hub_name), q(p.pincode), q(p.description), q(p.cluster_category), q(wkt)].join(','));
      count++;
    }});
  }});

  if (count === 0) {{
    document.getElementById('status').textContent = '⚠️ No polygon data found — load polygons first';
    return;
  }}

  var csv = rows.join('\\n');
  document.getElementById('outbox').textContent = csv;

  if (navigator.clipboard && navigator.clipboard.writeText) {{
    navigator.clipboard.writeText(csv).then(function() {{
      document.getElementById('status').textContent = '✅ ' + count + ' polygons copied to clipboard! Paste in the field below the map.';
      document.getElementById('outbox').style.borderColor = '#4AEDC4';
    }}).catch(function() {{
      document.getElementById('status').textContent = '⚠️ Auto-copy failed — manually select and copy the text from the box below.';
    }});
  }} else {{
    document.getElementById('status').textContent = '📋 ' + count + ' polygons in box below — select all and copy (Ctrl+A, Ctrl+C)';
  }}
}}

// Keyboard shortcut: Ctrl+S = copy CSV
document.addEventListener('keydown', function(e) {{
  if ((e.ctrlKey || e.metaKey) && e.key === 's') {{
    e.preventDefault();
    copyCSV();
  }}
}});

</script>
</body>
</html>"""

    return html
