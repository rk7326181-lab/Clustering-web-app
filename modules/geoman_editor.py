"""
Polygon editor using Leaflet + Leaflet.draw — standalone HTML page.

Uses the SAME CDN URLs that Folium already uses for Leaflet.draw
(cdnjs.cloudflare.com) so they are guaranteed to be accessible on
Streamlit Cloud.

The standalone HTML context avoids the streamlit-folium race condition:
there are no Streamlit re-runs inside this HTML, so window.drawnItems
is never reset. Edits are captured reliably and exported as CSV.
"""

import json
import pandas as pd
from shapely.wkt import loads as wkt_loads


def build_geoman_editor_html(
    polygon_df: pd.DataFrame,
    hub_filter: str = "All Hubs",
    height: int = 650,
    awb_df: pd.DataFrame = None,
) -> str:
    """Build a standalone Leaflet + Leaflet.draw polygon editor HTML page.

    awb_df: optional AWB/shipment DataFrame with lat/lon columns.
            Dots shown as a toggleable layer so the user can see shipment
            locations while reshaping cluster boundaries.
    """
    df = polygon_df.copy()
    df.columns = df.columns.str.strip()

    hub_col  = "Hub Name"         if "Hub Name"         in df.columns else "hub_name"
    wkt_col  = "Polygon WKT"      if "Polygon WKT"      in df.columns else "boundary"
    cc_col   = "Cluster_Code"     if "Cluster_Code"     in df.columns else "cluster_code"
    pin_col  = "Pincode"          if "Pincode"          in df.columns else "pincode"
    desc_col = "Description"      if "Description"      in df.columns else "surge_amount"
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

    # ── Build AWB points JSON ─────────────────────────────────────────────
    awb_points = []
    if awb_df is not None and len(awb_df) > 0:
        adf = awb_df.copy()
        adf.columns = adf.columns.str.strip().str.lower()
        lat_col = next((c for c in ["lat", "latitude"] if c in adf.columns), None)
        lon_col = next((c for c in ["long", "lon", "lng", "longitude"] if c in adf.columns), None)
        if lat_col and lon_col:
            adf[lat_col] = pd.to_numeric(adf[lat_col], errors="coerce")
            adf[lon_col] = pd.to_numeric(adf[lon_col], errors="coerce")
            adf = adf.dropna(subset=[lat_col, lon_col])
            adf = adf[(adf[lat_col] != 0) & (adf[lon_col] != 0)]
            # Sample up to 5000 points for performance
            if len(adf) > 5000:
                adf = adf.sample(5000, random_state=42)
            awb_points = [[float(r[lat_col]), float(r[lon_col])] for _, r in adf.iterrows()]
    awb_json = json.dumps(awb_points)
    has_awb = len(awb_points) > 0

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

    map_h = height - 115

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<title>Polygon Editor</title>
<!-- Same CDN URLs Folium uses — proven accessible on Streamlit Cloud -->
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css"/>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet.draw/1.0.4/leaflet.draw.css"/>
<style>
  html,body{{margin:0;padding:0;height:100%;font-family:Arial,sans-serif;background:#0f172a;overflow:hidden;}}
  #map{{height:{map_h}px;width:100%;}}

  /* ── Top bar ── */
  #topbar{{background:#1e293b;color:#fff;padding:5px 8px;display:flex;align-items:center;gap:6px;flex-wrap:wrap;border-bottom:1px solid #334155;}}
  .tbtn{{background:#0B8A7A;color:#fff;border:none;border-radius:5px;padding:5px 12px;font-size:12px;font-weight:700;cursor:pointer;}}
  .tbtn:hover{{background:#097A6C;}}
  #status{{font-size:11px;color:#94a3b8;flex:1;min-width:160px;}}
  #cnt{{font-size:11px;background:#0B8A7A20;color:#4AEDC4;border:1px solid #0B8A7A;border-radius:4px;padding:2px 8px;}}

  /* ── Mode buttons ── */
  #modebar{{background:#1e293b;padding:4px 8px;border-bottom:1px solid #334155;display:flex;gap:4px;flex-wrap:wrap;}}
  .mbtn{{background:#0f172a;color:#94a3b8;border:1px solid #475569;border-radius:4px;padding:4px 10px;font-size:12px;cursor:pointer;font-weight:600;}}
  .mbtn:hover{{background:#334155;color:#fff;}}
  .mbtn.on{{background:#0B8A7A;color:#fff;border-color:#0B8A7A;}}

  /* ── Output ── */
  #outbox{{background:#0f172a;border:1px solid #0B8A7A;border-radius:4px;padding:5px 8px;font-size:10px;color:#4AEDC4;font-family:monospace;margin:3px 6px;max-height:55px;overflow-y:auto;white-space:pre-wrap;word-break:break-all;}}

  /* ── Leaflet.draw toolbar overrides ── */
  .leaflet-draw-toolbar a{{background-color:#1e293b!important;border-color:#475569!important;color:#94a3b8!important;}}
  .leaflet-draw-toolbar a:hover{{background-color:#334155!important;color:#fff!important;}}
  .leaflet-draw-edit-save{{background-color:#0B8A7A!important;color:#fff!important;}}
  .leaflet-draw-edit-remove{{background-color:#DC2626!important;color:#fff!important;}}
</style>
</head>
<body>

<div id="topbar">
  <span id="status">Use the ✏️ Edit, ✚ Draw, 🗑 Delete buttons below — or use Leaflet toolbar (top-left of map)</span>
  <span id="cnt">0 polygons</span>
  <div style="flex:1"></div>
  {'<button class="tbtn" id="awb-btn" style="background:#7C3AED;margin-right:4px" title="Toggle AWB shipment dot visibility">📦 AWB Dots: ON</button>' if has_awb else ''}
  <button class="tbtn" id="copy-btn" title="Copy all polygons as CSV (Ctrl+S)">
    📋 Copy Edited Polygons (CSV)
  </button>
</div>

<div id="modebar">
  <button class="mbtn" id="btn-edit"   title="Drag vertices to reshape polygons">✏️ Edit Vertices</button>
  <button class="mbtn" id="btn-drag"   title="Move whole polygons">🖐 Move Polygon</button>
  <button class="mbtn" id="btn-draw"   title="Draw a new polygon">✚ Draw New Polygon</button>
  <button class="mbtn" id="btn-delete" title="Click polygon to delete it">🗑 Delete Polygon</button>
  <button class="mbtn" id="btn-exit"   title="Exit current mode" style="background:#1e3a5f;color:#94a3b8;">✗ Exit Mode</button>
</div>

<div id="map"></div>
<div id="outbox">Click "Copy Edited Polygons" after editing to export your changes as CSV.</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet.draw/1.0.4/leaflet.draw.js"></script>
<script>

var FC = {fc_json};
var polyLayers = [];
var drawnItems = new L.FeatureGroup();
var COLORS = ['#FF6384','#36A2EB','#FFCE56','#4BC0C0','#9966FF','#FF9F40','#00B3E6','#E6B333','#CC3366','#34D399'];
var hubColors = {{}};
var hIdx = 0;
var activeCtrl = null;

// ── Map setup ──────────────────────────────────────────────────────────────
var map = L.map('map', {{center:[{center_lat:.5f},{center_lon:.5f}], zoom:10}});

var osm = L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{attribution:'© OSM',maxZoom:19}}).addTo(map);
var sat = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',{{attribution:'Esri',maxZoom:19}});
L.control.layers({{'Street Map':osm,'Satellite':sat}},{{}},{{position:'topright'}}).addTo(map);
L.control.scale({{position:'bottomright'}}).addTo(map);

map.addLayer(drawnItems);

// ── Leaflet.draw control (provides the actual editing tools) ───────────────
var drawControl = new L.Control.Draw({{
  position: 'topleft',
  edit: {{
    featureGroup: drawnItems,
    edit: {{
      selectedPathOptions: {{
        maintainColor: true,
        moveMarkers: true
      }}
    }},
    remove: true
  }},
  draw: {{
    polygon: {{
      allowIntersection: false,
      drawError: {{color:'#e1e100', message:'<strong>Error:</strong> shape edges cannot cross!'}},
      shapeOptions: {{color:'#0B8A7A', fillOpacity:0.3}}
    }},
    polyline: false, rectangle: false, circle: false,
    marker: false, circlemarker: false
  }}
}});
map.addControl(drawControl);

// ── Load existing polygons ─────────────────────────────────────────────────
if (FC && FC.features && FC.features.length > 0) {{
  FC.features.forEach(function(feature) {{
    var hub = (feature.properties && feature.properties.hub_name) || '';
    if (!hubColors[hub]) {{ hubColors[hub]=COLORS[hIdx%COLORS.length]; hIdx++; }}
    var color = hubColors[hub];

    L.geoJSON(feature, {{
      style: function() {{ return {{color:color,weight:2.5,fillColor:color,fillOpacity:0.35}}; }},
      onEachFeature: function(f, layer) {{
        layer._props = f.properties || {{}};
        layer.bindPopup(
          '<div style="font-family:Arial;font-size:12px">' +
          '<b>' + (layer._props.cluster_code||'N/A') + '</b><br>' +
          'Hub: ' + (layer._props.hub_name||'') + '<br>' +
          'Pincode: ' + (layer._props.pincode||'') + '<br>' +
          'Rate: ₹' + (layer._props.description||'') + '</div>'
        );
        layer.bindTooltip(layer._props.cluster_code||'',{{sticky:true}});
        drawnItems.addLayer(layer);
        polyLayers.push(layer);
      }}
    }});
  }});

  try {{ map.fitBounds(drawnItems.getBounds().pad(0.05)); }} catch(e){{}}
}}
document.getElementById('cnt').textContent = polyLayers.length + ' polygons';
setStatus('Polygons loaded. Use the buttons below or Leaflet toolbar (top-left) to edit.');

// ── Event listeners ────────────────────────────────────────────────────────
map.on(L.Draw.Event.CREATED, function(e) {{
  var layer = e.layer;
  layer._props = {{ cluster_code:'NEW_'+Date.now(), hub_name:'', pincode:'', description:'', cluster_category:'' }};
  drawnItems.addLayer(layer);
  polyLayers.push(layer);
  document.getElementById('cnt').textContent = drawnItems.getLayers().length + ' polygons';
  setStatus('✅ New polygon drawn. Click "Copy Edited Polygons" to export.');
}});

map.on(L.Draw.Event.EDITED, function(e) {{
  setStatus('✅ ' + e.layers.getLayers().length + ' polygon(s) reshaped. Click "Copy Edited Polygons" to export.');
}});

map.on(L.Draw.Event.DELETED, function(e) {{
  document.getElementById('cnt').textContent = drawnItems.getLayers().length + ' polygons';
  setStatus('✅ Polygon(s) deleted. Click "Copy Edited Polygons" to export.');
}});

// ── Mode button helpers ────────────────────────────────────────────────────
function setStatus(msg) {{ document.getElementById('status').textContent = msg; }}

function setBtnOn(id) {{
  ['btn-edit','btn-drag','btn-draw','btn-delete'].forEach(function(b){{
    var el=document.getElementById(b); if(el) el.classList.remove('on');
  }});
  var el=document.getElementById(id); if(el) el.classList.add('on');
}}

function exitAllModes() {{
  setBtnOn(null);
  if (activeCtrl) {{
    try {{ activeCtrl.disable(); }} catch(e){{}}
    activeCtrl = null;
  }}
  // Also disable any Leaflet.draw active state
  try {{ drawControl._toolbars.edit._modes.edit&&drawControl._toolbars.edit._modes.edit.handler.disable(); }} catch(e){{}}
  try {{ drawControl._toolbars.edit._modes.remove&&drawControl._toolbars.edit._modes.remove.handler.disable(); }} catch(e){{}}
  try {{ drawControl._toolbars.draw._modes.polygon&&drawControl._toolbars.draw._modes.polygon.handler.disable(); }} catch(e){{}}
}}

// ── Button event listeners ─────────────────────────────────────────────────
document.getElementById('btn-edit').addEventListener('click', function() {{
  exitAllModes();
  try {{
    setBtnOn('btn-edit');
    new L.EditToolbar.Edit(map, {{featureGroup:drawnItems}}).enable();
    setStatus('✏️ Edit mode: click a polygon, then drag its vertices to reshape. Click Save (checkmark) to confirm.');
  }} catch(e) {{
    // Fallback: activate Leaflet.draw edit via toolbar
    var editBtn = document.querySelector('.leaflet-draw-edit-edit');
    if (editBtn) editBtn.click();
    setStatus('✏️ Click the pencil icon in the map toolbar (top-left) to edit vertices.');
  }}
}});

document.getElementById('btn-drag').addEventListener('click', function() {{
  exitAllModes();
  setBtnOn('btn-drag');
  setStatus('🗱 Drag mode: Use the move icon in the Leaflet toolbar (top-left of map) to drag polygons.');
  // Visual hint — trigger the edit toolbar
  var editBtn = document.querySelector('.leaflet-draw-edit-edit');
  if (editBtn) editBtn.click();
}});

document.getElementById('btn-draw').addEventListener('click', function() {{
  exitAllModes();
  setBtnOn('btn-draw');
  try {{
    new L.Draw.Polygon(map, drawControl.options.draw.polygon).enable();
    setStatus('✚ Draw mode: Click to add points. Double-click to finish the polygon.');
  }} catch(e) {{
    var drawBtn = document.querySelector('.leaflet-draw-draw-polygon');
    if (drawBtn) drawBtn.click();
    setStatus('✚ Click the polygon icon in the map toolbar to draw a new polygon.');
  }}
}});

document.getElementById('btn-delete').addEventListener('click', function() {{
  exitAllModes();
  setBtnOn('btn-delete');
  try {{
    new L.EditToolbar.Delete(map, {{featureGroup:drawnItems}}).enable();
    setStatus('🗑 Delete mode: click any polygon to remove it. Click Save (checkmark) to confirm.');
  }} catch(e) {{
    var delBtn = document.querySelector('.leaflet-draw-edit-remove');
    if (delBtn) delBtn.click();
    setStatus('🗑 Click the trash icon in the map toolbar to delete polygons.');
  }}
}});

document.getElementById('btn-exit').addEventListener('click', function() {{
  exitAllModes();
  setStatus('Edit mode off. Your changes are preserved — click "Copy Edited Polygons" to export.');
}});

// ── CSV Export ─────────────────────────────────────────────────────────────
function copyCSV() {{
  var rows = ['"cluster_code","hub_name","pincode","description","cluster_category","geometry_wkt"'];
  var count = 0;

  drawnItems.eachLayer(function(layer) {{
    try {{
      var gj = layer.toGeoJSON();
      var geom = gj.geometry;
      if (!geom || !geom.coordinates || !geom.coordinates[0]) return;

      var coords = geom.type === 'Polygon' ? geom.coordinates[0] :
                   (geom.type === 'MultiPolygon' ? geom.coordinates[0][0] : null);
      if (!coords || coords.length < 4) return;

      // Close ring
      var f=coords[0],l=coords[coords.length-1];
      if(f[0]!==l[0]||f[1]!==l[1]) coords=coords.concat([[f[0],f[1]]]);

      var wkt = 'POLYGON((' + coords.map(function(c){{return c[0]+' '+c[1];}}).join(', ') + '))';
      var p = layer._props || {{}};
      function q(v){{return'"'+String(v||'').replace(/"/g,'""')+'"';}}
      rows.push([q(p.cluster_code),q(p.hub_name),q(p.pincode),q(p.description),q(p.cluster_category),q(wkt)].join(','));
      count++;
    }} catch(e) {{}}
  }});

  if (count === 0) {{
    setStatus('⚠️ No polygon data found. Make sure polygons are loaded.');
    return;
  }}

  var csv = rows.join('\\n');
  document.getElementById('outbox').textContent = csv;

  navigator.clipboard && navigator.clipboard.writeText(csv).then(function() {{
    setStatus('✅ ' + count + ' polygon(s) copied to clipboard! Paste in the field below the map.');
    document.getElementById('outbox').style.borderColor='#4AEDC4';
  }}).catch(function() {{
    setStatus('📋 ' + count + ' polygon(s) in box below — select all (Ctrl+A) then copy (Ctrl+C).');
  }});
}}

document.getElementById('copy-btn').addEventListener('click', copyCSV);
document.addEventListener('keydown', function(e){{if((e.ctrlKey||e.metaKey)&&e.key==='s'){{e.preventDefault();copyCSV();}}}});

// ── AWB dots ───────────────────────────────────────────────────────────────
var AWB_POINTS = {awb_json};
var awbLayer = null;
var awbVisible = true;

if (AWB_POINTS && AWB_POINTS.length > 0) {{
  awbLayer = L.layerGroup();
  AWB_POINTS.forEach(function(pt) {{
    L.circleMarker([pt[0], pt[1]], {{
      radius: 3,
      color: '#F59E0B',
      fillColor: '#F59E0B',
      fillOpacity: 0.7,
      weight: 0,
      interactive: false
    }}).addTo(awbLayer);
  }});
  awbLayer.addTo(map);
  setStatus('Polygons + ' + AWB_POINTS.length + ' AWB dots loaded. Edit polygons to match shipment distribution.');
}}

function toggleAWB() {{
  var btn = document.getElementById('awb-btn');
  if (!awbLayer) return;
  if (awbVisible) {{
    map.removeLayer(awbLayer);
    awbVisible = false;
    if (btn) {{ btn.textContent = '📦 AWB Dots: OFF'; btn.style.background = '#475569'; }}
  }} else {{
    map.addLayer(awbLayer);
    awbVisible = true;
    if (btn) {{ btn.textContent = '📦 AWB Dots: ON'; btn.style.background = '#7C3AED'; }}
  }}
}}

var awbBtn = document.getElementById('awb-btn');
if (awbBtn) awbBtn.addEventListener('click', toggleAWB);

</script>
</body>
</html>"""

    return html
