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
    """
    Build a standalone Leaflet + Leaflet-Geoman HTML page.

    Returns the HTML string for use with streamlit.components.v1.html().
    """
    # ── Identify geometry + metadata columns ──────────────────────────────
    df = polygon_df.copy()
    df.columns = df.columns.str.strip()

    hub_col  = "Hub Name"   if "Hub Name"   in df.columns else "hub_name"
    wkt_col  = "Polygon WKT" if "Polygon WKT" in df.columns else "boundary"
    cc_col   = "Cluster_Code" if "Cluster_Code" in df.columns else "cluster_code"
    pin_col  = "Pincode"    if "Pincode"    in df.columns else "pincode"
    desc_col = "Description" if "Description" in df.columns else "surge_amount"
    cat_col  = "Cluster_Category" if "Cluster_Category" in df.columns else "cluster_category"

    if hub_filter and hub_filter not in ("All Hubs", "All") and hub_col in df.columns:
        df = df[df[hub_col] == hub_filter]

    # ── Build GeoJSON FeatureCollection from WKT ──────────────────────────
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
            # GeoJSON uses [lon, lat]
            feature = {
                "type": "Feature",
                "properties": {
                    "cluster_code":    str(row.get(cc_col,   "")),
                    "hub_name":        str(row.get(hub_col,  "")),
                    "pincode":         str(row.get(pin_col,  "")),
                    "description":     str(row.get(desc_col, "")),
                    "cluster_category":str(row.get(cat_col,  "")),
                },
                "geometry": {"type": "Polygon", "coordinates": coords},
            }
            features.append(feature)

    fc_json = json.dumps({"type": "FeatureCollection", "features": features})

    # ── Compute map center ─────────────────────────────────────────────────
    center_lat, center_lon = 20.59, 78.96
    if features:
        lats, lons = [], []
        for f in features[:50]:
            for coord in f["geometry"]["coordinates"][0]:
                lons.append(coord[0])
                lats.append(coord[1])
        if lats:
            center_lat = sum(lats) / len(lats)
            center_lon = sum(lons) / len(lons)

    # ── HTML ───────────────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>Polygon Editor</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <link rel="stylesheet" href="https://unpkg.com/@geoman-io/leaflet-geoman@2.14.0/dist/leaflet-geoman.css"/>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: Arial, sans-serif; background: #1a1a2e; }}
    #map {{ height: {height - 110}px; width: 100%; }}
    #toolbar {{
      background: #16213e; color: #fff; padding: 8px 12px;
      display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
    }}
    #toolbar .lbl {{ font-size: 12px; color: #aaa; margin-right: 4px; }}
    .btn {{
      background: #0B8A7A; color: #fff; border: none; border-radius: 6px;
      padding: 6px 14px; font-size: 12px; font-weight: 700; cursor: pointer;
    }}
    .btn:hover {{ background: #097A6C; }}
    .btn-red {{ background: #EF4444; }}
    .btn-red:hover {{ background: #DC2626; }}
    .btn-blue {{ background: #3B82F6; }}
    .btn-blue:hover {{ background: #2563EB; }}
    #output-area {{
      background: #0f3460; border: 1px solid #0B8A7A; border-radius: 6px;
      padding: 8px 12px; font-size: 11px; color: #4AEDC4;
      margin-top: 6px; min-height: 40px; max-height: 80px; overflow-y: auto;
      word-break: break-all; white-space: pre-wrap;
    }}
    #status {{ font-size: 11px; color: #4AEDC4; min-width: 180px; }}
    .badge {{
      background: #0B8A7A30; color: #4AEDC4; border: 1px solid #0B8A7A;
      border-radius: 4px; padding: 2px 8px; font-size: 11px;
    }}
  </style>
</head>
<body>

<div id="toolbar">
  <span class="lbl">✏️ EDIT POLYGONS:</span>
  <span id="status">Click Edit (pencil) on map toolbar to start editing</span>
  <span id="poly-count" class="badge">0 polygons</span>
  <div style="flex:1"></div>
  <button class="btn" onclick="copyEdits()" title="Copy edited GeoJSON to clipboard">
    📋 Copy Edited GeoJSON
  </button>
  <button class="btn btn-blue" onclick="selectAll()" title="Select all polygons for editing">
    Select All
  </button>
  <button class="btn btn-red" onclick="cancelEdits()" title="Cancel current edit">
    ✗ Cancel
  </button>
</div>

<div id="map"></div>

<div id="output-area">Edited polygon data will appear here after clicking "Copy Edited GeoJSON"</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/@geoman-io/leaflet-geoman@2.14.0/dist/leaflet-geoman.umd.js"></script>
<script>

var GEOJSON_DATA = {fc_json};
var editedData = null;

// ── Map setup ─────────────────────────────────────────────────────────────
var map = L.map('map', {{ center: [{center_lat}, {center_lon}], zoom: 10 }});

L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
  attribution: '© OpenStreetMap',
  maxZoom: 19
}}).addTo(map);

// Satellite layer
var satellite = L.tileLayer(
  'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',
  {{ attribution: 'Esri' }}
);
var baseMaps = {{ 'Street': L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{attribution:'© OSM'}}), 'Satellite': satellite }};
L.control.layers(baseMaps).addTo(map);

// ── Load polygon data ─────────────────────────────────────────────────────
var polyLayers = [];
var colorMap = {{}};
var hues = ['#FF6384','#36A2EB','#FFCE56','#4BC0C0','#9966FF','#FF9F40','#00B3E6','#E6B333'];
var hIdx = 0;

if (GEOJSON_DATA && GEOJSON_DATA.features) {{
  GEOJSON_DATA.features.forEach(function(feature) {{
    var hub = feature.properties.hub_name || '';
    if (!colorMap[hub]) {{
      colorMap[hub] = hues[hIdx % hues.length];
      hIdx++;
    }}
    var color = colorMap[hub];

    var poly = L.geoJSON(feature, {{
      style: {{ color: color, weight: 2, fillColor: color, fillOpacity: 0.3 }},
      onEachFeature: function(f, layer) {{
        var p = f.properties || {{}};
        layer.bindPopup(
          '<b>' + (p.cluster_code || 'N/A') + '</b><br>' +
          'Hub: ' + (p.hub_name || '') + '<br>' +
          'Pincode: ' + (p.pincode || '') + '<br>' +
          'Rate: ₹' + (p.description || '') + '<br>' +
          'Category: ' + (p.cluster_category || '')
        );
        layer.bindTooltip(p.cluster_code || '', {{sticky: true}});
        layer._featureProps = p;
        polyLayers.push(layer);
      }}
    }}).addTo(map);
  }});

  // Fit bounds
  if (polyLayers.length > 0) {{
    try {{
      var group = L.featureGroup(polyLayers);
      map.fitBounds(group.getBounds().pad(0.05));
    }} catch(e) {{}}
  }}
}}

document.getElementById('poly-count').textContent = polyLayers.length + ' polygons';

// ── Leaflet-Geoman setup ──────────────────────────────────────────────────
map.pm.addControls({{
  position:       'topleft',
  drawMarker:     false,
  drawPolyline:   false,
  drawRectangle:  false,
  drawCircle:     false,
  drawCircleMarker: false,
  drawText:       false,
  drawPolygon:    true,  // Allow drawing new polygons
  editMode:       true,  // Enable vertex dragging
  dragMode:       true,  // Enable moving polygons
  cutPolygon:     false,
  removalMode:    true,
}});

// Make all existing polygon layers editable by Geoman
polyLayers.forEach(function(layer) {{
  if (layer.eachLayer) {{
    layer.eachLayer(function(l) {{
      if (l.pm) l.pm.enable();
    }});
  }}
}});

// ── Event listeners ───────────────────────────────────────────────────────
var statusEl = document.getElementById('status');

map.on('pm:globaleditmodetoggled', function(e) {{
  statusEl.textContent = e.enabled
    ? '✏️ Edit mode ON — drag vertices to reshape'
    : 'Edit mode OFF';
}});

map.on('pm:globaldragmodetoggled', function(e) {{
  statusEl.textContent = e.enabled
    ? '✋ Drag mode ON — drag polygons to move'
    : 'Drag mode OFF';
}});

// Fired AFTER each polygon edit is committed
map.on('pm:update', function(e) {{
  statusEl.textContent = '✅ Edit saved — click "Copy Edited GeoJSON" to export';
  editedData = null; // Reset so next copy picks up fresh data
}});

map.on('pm:create', function(e) {{
  statusEl.textContent = '🆕 New polygon drawn — give it a name after copying';
  e.layer._featureProps = {{ cluster_code: 'NEW_' + Date.now(), hub_name: '', pincode: '', description: '', cluster_category: '' }};
  polyLayers.push(e.layer);
  document.getElementById('poly-count').textContent = polyLayers.length + ' polygons';
}});

map.on('pm:remove', function(e) {{
  var idx = polyLayers.indexOf(e.layer);
  if (idx > -1) polyLayers.splice(idx, 1);
  document.getElementById('poly-count').textContent = polyLayers.length + ' polygons';
  statusEl.textContent = '🗑️ Polygon removed';
}});

// ── Export functions ──────────────────────────────────────────────────────
function getAllFeatures() {{
  var features = [];
  map.eachLayer(function(layer) {{
    // Get all GeoJSON-capable polygon layers (not tile layers, etc.)
    if (layer.toGeoJSON && (layer instanceof L.Polygon || layer instanceof L.GeoJSON)) {{
      if (layer instanceof L.GeoJSON) {{
        layer.eachLayer(function(l) {{
          if (l.toGeoJSON) {{
            var f = l.toGeoJSON();
            if (l._featureProps) f.properties = Object.assign({{}}, l._featureProps, f.properties);
            if (f.geometry && f.geometry.type && f.geometry.type.includes('Polygon')) features.push(f);
          }}
        }});
      }} else {{
        var f = layer.toGeoJSON();
        if (layer._featureProps) f.properties = Object.assign({{}}, layer._featureProps, f.properties);
        if (f.geometry && f.geometry.type && f.geometry.type.includes('Polygon')) features.push(f);
      }}
    }}
  }});
  return features;
}}

function copyEdits() {{
  var features = getAllFeatures();
  if (features.length === 0) {{
    alert('No polygon data found. Make sure the map has loaded polygons.');
    return;
  }}

  // Build CSV format (cluster_code, hub_name, pincode, description, cluster_category, geometry_wkt)
  var rows = ['"cluster_code","hub_name","pincode","description","cluster_category","geometry_wkt"'];

  features.forEach(function(f) {{
    var p = f.properties || {{}};
    var coords = f.geometry.coordinates[0];
    var wkt = 'POLYGON((' + coords.map(function(c) {{ return c[0] + ' ' + c[1]; }}).join(', ') + '))';
    function q(v) {{ return '"' + String(v || '').replace(/"/g, '""') + '"'; }}
    rows.push([q(p.cluster_code), q(p.hub_name), q(p.pincode), q(p.description), q(p.cluster_category), q(wkt)].join(','));
  }});

  var csv = rows.join('\\n');

  // Show in output area
  var out = document.getElementById('output-area');
  out.textContent = csv;

  // Copy to clipboard
  if (navigator.clipboard) {{
    navigator.clipboard.writeText(csv).then(function() {{
      statusEl.textContent = '✅ ' + features.length + ' polygons copied! Paste in the "Import" field below the map.';
      out.style.borderColor = '#4AEDC4';
    }}).catch(function() {{
      statusEl.textContent = '⚠️ Copy failed — manually select & copy text from the box below.';
    }});
  }} else {{
    out.select();
    document.execCommand('copy');
    statusEl.textContent = '✅ Copied (fallback)! Paste in the "Import" field below.';
  }}
}}

function selectAll() {{
  map.pm.enableGlobalEditMode();
  statusEl.textContent = '✏️ Edit mode ON — drag vertices on any polygon';
}}

function cancelEdits() {{
  map.pm.disableGlobalEditMode();
  map.pm.disableGlobalDragMode();
  statusEl.textContent = 'Edits cancelled';
}}

</script>
</body>
</html>"""

    return html
