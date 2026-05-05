"""
Map Visualization — Folium with hub color differentiation, toggles.
"""
import hashlib
import pandas as pd
import numpy as np
import requests
import time
import streamlit as st
from shapely.wkt import loads as wkt_loads

try:
    import folium
    from folium.plugins import HeatMap, Fullscreen, MeasureControl, Draw
    from branca.element import MacroElement
    from jinja2 import Template
    HAS_FOLIUM = True
except ImportError:
    HAS_FOLIUM = False
    MacroElement = object
    Template = None

from utils import DESCRIPTION_MAPPING, get_hub_color_map


class OsrmRouteDistanceTool(MacroElement):
    """Interactive route-distance tool — clicks on the map query OSRM for real road distance."""
    _template = Template("""
    {% macro script(this, kwargs) %}
    (function(){
        var mapObj = {{ this._parent.get_name() }};
        var RouteDistControl = L.Control.extend({
            options: { position: 'topleft' },
            onAdd: function(map) {
                var container = L.DomUtil.create('div','leaflet-bar leaflet-control');
                var btn = L.DomUtil.create('a','',container);
                btn.innerHTML = '&#128207;';
                btn.title = 'Route Distance Tool  (click points → get road distance, ESC to clear)';
                btn.href = '#';
                btn.style.cssText = 'font-size:16px;line-height:30px;text-align:center;display:block;width:30px;height:30px;text-decoration:none;';
                L.DomEvent.disableClickPropagation(container);
                var active=false, points=[], layers=[], totalDist=0;
                function clearAll(){
                    layers.forEach(function(l){map.removeLayer(l);}); layers=[];
                    points=[]; totalDist=0; active=false;
                    btn.style.backgroundColor=''; btn.style.color='';
                    map.getContainer().style.cursor='';
                }
                function showInfo(){
                    if(points.length<2) return;
                    var last=points[points.length-1];
                    var lbl=L.marker(last,{icon:L.divIcon({className:'',
                        html:'<div style="background:#fff;border:2px solid #0B8A7A;border-radius:5px;padding:4px 10px;font-size:12px;font-weight:700;white-space:nowrap;color:#0B8A7A;box-shadow:0 2px 6px rgba(0,0,0,.2)">&#128739; '+totalDist.toFixed(2)+' km</div>',
                        iconAnchor:[-8,12]})}).addTo(map);
                    layers.push(lbl);
                }
                btn.onclick=function(e){
                    L.DomEvent.preventDefault(e);
                    if(active){clearAll();}else{
                        active=true;
                        btn.style.backgroundColor='#0B8A7A'; btn.style.color='#fff';
                        map.getContainer().style.cursor='crosshair';
                    }
                };
                function addPoint(lat,lng){
                    if(!active) return;
                    var pt=[lat,lng]; points.push(pt);
                    var dot=L.circleMarker(pt,{radius:5,color:'#0B8A7A',fillColor:'#0B8A7A',fillOpacity:1,weight:2}).addTo(map);
                    layers.push(dot);
                    if(points.length>1){
                        var prev=points[points.length-2], curr=pt;
                        var url='https://router.project-osrm.org/route/v1/driving/'+prev[1]+','+prev[0]+';'+curr[1]+','+curr[0]+'?overview=full&geometries=geojson';
                        fetch(url,{signal:AbortSignal.timeout(8000)})
                            .then(function(r){return r.json();})
                            .then(function(d){
                                if(d.code==='Ok'&&d.routes&&d.routes.length){
                                    var coords=d.routes[0].geometry.coordinates.map(function(c){return[c[1],c[0]];});
                                    totalDist+=d.routes[0].distance/1000;
                                    layers.push(L.polyline(coords,{color:'#0B8A7A',weight:3,opacity:0.85}).addTo(map));
                                } else {
                                    totalDist+=map.distance(L.latLng(prev),L.latLng(curr))/1000;
                                    layers.push(L.polyline([prev,curr],{color:'#ef4444',weight:2,dashArray:'6',opacity:0.7}).addTo(map));
                                }
                                showInfo();
                            })
                            .catch(function(){
                                totalDist+=map.distance(L.latLng(prev),L.latLng(curr))/1000;
                                layers.push(L.polyline([prev,curr],{color:'#ef4444',weight:2,dashArray:'6',opacity:0.7}).addTo(map));
                                showInfo();
                            });
                    }
                }
                window.osrmAddPoint=addPoint;
                map.on('click',function(e){
                    addPoint(e.latlng.lat,e.latlng.lng);
                });
                document.addEventListener('keydown',function(e){if(e.key==='Escape')clearAll();});
                return container;
            }
        });
        new RouteDistControl().addTo(mapObj);
    })();
    {% endmacro %}
    """) if Template else None


# Distinct pincode colors — 30 colors to cycle through within each hub
_PINCODE_PALETTE = [
    "#E6194B", "#3CB44B", "#4363D8", "#F58231", "#911EB4",
    "#42D4F4", "#F032E6", "#BFEF45", "#FABEBE", "#469990",
    "#E6BEFF", "#9A6324", "#800000", "#AAFFC3", "#808000",
    "#000075", "#FF6384", "#36A2EB", "#4BC0C0", "#9966FF",
    "#FF9F40", "#00B3E6", "#E6B333", "#3366E6", "#CC3366",
    "#33CC99", "#6666CC", "#CC6633", "#339966", "#CC3399",
]


def _build_pincode_color_map(df, hub_col, pin_col):
    """Build a nested dict: hub -> pincode -> color for pincode differentiation."""
    if pin_col not in df.columns:
        return {}
    pc_map = {}
    for hub in df[hub_col].unique():
        hub_pincodes = df[df[hub_col] == hub][pin_col].unique().tolist()
        pc_map[hub] = {
            str(pin): _PINCODE_PALETTE[i % len(_PINCODE_PALETTE)]
            for i, pin in enumerate(hub_pincodes)
        }
    return pc_map


def _df_hash(df):
    """Fast hash of a DataFrame for cache key purposes."""
    if df is None:
        return "none"
    return hashlib.md5(pd.util.hash_pandas_object(df).values.tobytes()).hexdigest()


@st.cache_data(ttl=600, show_spinner=False)
def create_polygon_map_cached(poly_hash, cluster_hash, awb_hash,
                               _polygon_df, _cluster_df, _awb_df,
                               satellite, viz_mode, hub_filter, rate_filter, hub_type_filter):
    """Cached wrapper — returns Folium map HTML string for non-edit mode rendering.

    The hash strings are the cache key; DataFrames are prefixed with _ to skip hashing.
    """
    m = create_polygon_map(_polygon_df, _cluster_df, _awb_df, satellite, viz_mode, hub_filter, rate_filter, hub_type_filter)
    if m is None:
        return None
    return m._repr_html_()


def _base_map(center_lat, center_lon, zoom=9, satellite=False, draw_enabled=False):
    m = folium.Map(location=[center_lat, center_lon], zoom_start=zoom, tiles=None)
    # Multi-tile layers — Street / Satellite / Terrain
    folium.TileLayer("OpenStreetMap", name="Street Map").add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri", name="Satellite", overlay=False, control=True
    ).add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
        attr="Esri", name="Terrain", overlay=False, control=True
    ).add_to(m)
    # Draw plugin (only when edit mode is on)
    if draw_enabled:
        Draw(
            export=True,
            position="topleft",
            draw_options={
                "polyline": {"shapeOptions": {"color": "#FF6B35"}},
                "polygon": {"shapeOptions": {"color": "#004E98", "fillOpacity": 0.3}},
                "circle": False,
                "rectangle": True,
                "marker": True,
                "circlemarker": False
            }
        ).add_to(m)
    # Full-screen toggle on every map built on this base
    Fullscreen(
        position="topright",
        title="Full Screen",
        title_cancel="Exit Full Screen",
        force_separate_button=True,
    ).add_to(m)
    return m


def _add_surge_legend(map_obj):
    """Add payout rate legend to map"""
    legend_html = '''
    <div style="
        position: fixed;
        bottom: 50px;
        right: 50px;
        width: 200px;
        background-color: white;
        border: 2px solid #d1d5db;
        border-radius: 8px;
        padding: 12px;
        font-family: Arial, sans-serif;
        font-size: 12px;
        z-index: 9999;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    ">
        <h4 style="margin: 0 0 8px 0; font-size: 13px; color: #1f2937; border-bottom: 2px solid #0B8A7A; padding-bottom: 4px;">
            Payout Rate Legend
        </h4>
        <div style="display: flex; flex-direction: column; gap: 4px;">
            <div style="display: flex; align-items: center;">
                <div style="width: 20px; height: 14px; background-color: #22c55e; margin-right: 6px; border: 1px solid #16a34a; border-radius: 2px;"></div>
                <span>₹0 (0-5 km)</span>
            </div>
            <div style="display: flex; align-items: center;">
                <div style="width: 20px; height: 14px; background-color: #3b82f6; margin-right: 6px; border: 1px solid #2563eb; border-radius: 2px;"></div>
                <span>₹1-₹2 (5-15 km)</span>
            </div>
            <div style="display: flex; align-items: center;">
                <div style="width: 20px; height: 14px; background-color: #8b5cf6; margin-right: 6px; border: 1px solid #7c3aed; border-radius: 2px;"></div>
                <span>₹3-₹4 (15-25 km)</span>
            </div>
            <div style="display: flex; align-items: center;">
                <div style="width: 20px; height: 14px; background-color: #f59e0b; margin-right: 6px; border: 1px solid #d97706; border-radius: 2px;"></div>
                <span>₹5-₹6 (25-35 km)</span>
            </div>
            <div style="display: flex; align-items: center;">
                <div style="width: 20px; height: 14px; background-color: #ef4444; margin-right: 6px; border: 1px solid #dc2626; border-radius: 2px;"></div>
                <span>₹7-₹8 (35-45 km)</span>
            </div>
            <div style="display: flex; align-items: center;">
                <div style="width: 20px; height: 14px; background-color: #6b7280; margin-right: 6px; border: 1px solid #4b5563; border-radius: 2px;"></div>
                <span>Nil (45+ km)</span>
            </div>
        </div>
    </div>
    '''
    map_obj.get_root().html.add_child(folium.Element(legend_html))


def create_polygon_map(polygon_df, cluster_df=None, awb_df=None, satellite=False, viz_mode="none", hub_filter=None, rate_filter=None, hub_type_filter=None):
    if not HAS_FOLIUM: return None
    if polygon_df is None or len(polygon_df) == 0:
        return None
    df = polygon_df.copy(); df.columns = df.columns.str.strip()

    # Compute center from polygon centroids for accurate centering
    center_lat, center_lon = 26.8, 92.7
    polygon_lats, polygon_lons = [], []
    wkt_col = "Polygon WKT" if "Polygon WKT" in df.columns else None
    if wkt_col:
        for wkt in df[wkt_col].dropna().head(50):
            try:
                poly = wkt_loads(str(wkt))
                cx, cy = poly.centroid.x, poly.centroid.y
                polygon_lons.append(cx)
                polygon_lats.append(cy)
            except Exception:
                pass
    if polygon_lats:
        center_lat = np.mean(polygon_lats)
        center_lon = np.mean(polygon_lons)
    elif cluster_df is not None and len(cluster_df) > 0:
        cdf = cluster_df.copy(); cdf.columns = cdf.columns.str.strip()
        lc = "Hub_lat" if "Hub_lat" in cdf.columns else "hub_lat"
        nc = "Hub_long" if "Hub_long" in cdf.columns else "hub_long"
        if lc in cdf.columns: center_lat = cdf[lc].mean()
        if nc in cdf.columns: center_lon = cdf[nc].mean()

    m = _base_map(center_lat, center_lon, satellite=satellite)

    # Hub colors
    hub_col = "Hub Name" if "Hub Name" in df.columns else "hub_name"
    all_hubs = df[hub_col].unique().tolist() if hub_col in df.columns else []
    hub_colors = get_hub_color_map(all_hubs)

    if hub_filter and hub_filter != "All Hubs":
        df = df[df[hub_col] == hub_filter]

    # Pincode color map — different color per pincode within each hub
    pin_col = "Pincode" if "Pincode" in df.columns else "pincode"
    pincode_colors = _build_pincode_color_map(df, hub_col, pin_col)

    # Shipment counts
    ship_counts = {}
    if awb_df is not None and len(awb_df) > 0:
        adf = awb_df.copy(); adf.columns = adf.columns.str.strip().str.lower()
        ship_counts = adf.groupby("cluster_name").size().to_dict()

    for _, row in df.iterrows():
        try:
            wkt = row.get("Polygon WKT", "")
            if pd.isna(wkt) or not wkt: continue
            poly = wkt_loads(wkt)
            # Simplify polygon to reduce map HTML size (~100m tolerance)
            poly = poly.simplify(0.001, preserve_topology=True)
            latlon = [[lat, lon] for lon, lat in poly.exterior.coords]
            cc = row.get("Cluster_Code", "")
            hub = row.get(hub_col, "")
            cat = row.get("Cluster_Category", "")
            rate = DESCRIPTION_MAPPING.get(cat, 0)

            # Rate filter
            if rate_filter and rate_filter != "All":
                expected_rate = rate_filter.replace("₹", "")
                try:
                    if str(int(rate)) != expected_rate:
                        continue
                except (ValueError, TypeError):
                    if expected_rate != "Nil":
                        continue

            ships = ship_counts.get(cc, 0)
            price = rate * ships
            hub_color = hub_colors.get(hub, "#3498db")

            # Per-pincode fill color (different shades within same hub)
            pincode = str(row.get(pin_col, ""))
            if hub in pincode_colors and pincode in pincode_colors[hub]:
                fill_color = pincode_colors[hub][pincode]
            else:
                fill_color = hub_color

            popup = f"<b>{cc}</b><br>Hub: {hub}<br>Pincode: {pincode}<br>Rate: ₹{rate}<br>Shipments: {ships:,}<br>Price: ₹{price:,.0f}"
            folium.Polygon(
                locations=latlon, popup=folium.Popup(popup, max_width=280),
                tooltip=f"{pincode} | ₹{price:,.0f}" if ships > 0 else f"{pincode} | ₹{rate}",
                color=hub_color, weight=2.5, fill=True, fill_color=fill_color, fill_opacity=0.45,
            ).add_to(m)

            # Centroid label — show payout rate + description; burn mode shows cost in red
            cx, cy = poly.centroid.x, poly.centroid.y
            desc = row.get("Description", "")
            if viz_mode == "burn":
                label = f"🔥₹{price:,.0f}" if price > 0 else f"₹{rate}"
                label_bg = "rgba(254,242,242,0.95)"
                label_border = "#EF4444"
            else:
                label = f"₹{price:,.0f}" if ships > 0 else (str(desc) if desc and str(desc) != "nan" else f"₹{rate}")
                label_bg = "rgba(255,255,255,0.92)"
                label_border = fill_color
            folium.Marker(
                location=[cy, cx],
                icon=folium.DivIcon(
                    html=(
                        f'<div style="font-size:12px;font-weight:bold;background:{label_bg};'
                        f'padding:3px 6px;border:2px solid {label_border};border-radius:4px;white-space:nowrap;'
                        f'box-shadow:0 1px 4px rgba(0,0,0,0.2);text-align:center;">{label}</div>'
                    ),
                    icon_size=(80, 28), icon_anchor=(40, 14)),
            ).add_to(m)
        except Exception as e:
            import traceback
            print(f"Polygon render error for {row.get('Cluster_Code', '?')}: {e}")
            continue

    # Hub markers
    if cluster_df is not None:
        cdf = cluster_df.copy(); cdf.columns = cdf.columns.str.strip()
        lc = "Hub_lat" if "Hub_lat" in cdf.columns else "hub_lat"
        nc2 = "Hub_long" if "Hub_long" in cdf.columns else "hub_long"
        nm = "Hub_Name" if "Hub_Name" in cdf.columns else "hub_name"
        if hub_filter and hub_filter != "All Hubs":
            cdf = cdf[cdf[nm] == hub_filter]
        hubs = cdf.drop_duplicates(subset=[nm])
        for _, h in hubs.iterrows():
            if not (pd.notna(h.get(lc)) and pd.notna(h.get(nc2))):
                continue
            _hlat, _hlon = float(h[lc]), float(h[nc2])
            folium.Marker(
                location=[_hlat, _hlon], popup=f"<b>{h[nm]}</b>", tooltip=h[nm],
                icon=folium.DivIcon(
                    html=(
                        f'<div title="{h[nm]} — click to set as route start"'
                        f' onclick="if(window.osrmAddPoint){{window.osrmAddPoint({_hlat},{_hlon});return false;}}"'
                        f' style="cursor:pointer;background:#e74c3c;color:#fff;border:3px solid #fff;border-radius:50%;'
                        f'width:30px;height:30px;display:flex;align-items:center;justify-content:center;'
                        f'font-size:15px;box-shadow:0 2px 8px rgba(0,0,0,.45);font-weight:700;line-height:30px;text-align:center;">&#127968;</div>'
                    ),
                    icon_size=(30, 30), icon_anchor=(15, 15)),
            ).add_to(m)

    # Shipment heatmap
    if awb_df is not None and len(awb_df) > 0 and viz_mode in ("heatmap", "dots"):
        adf = awb_df.copy(); adf.columns = adf.columns.str.strip().str.lower()
        adf["lat"] = pd.to_numeric(adf["lat"], errors="coerce")
        adf["long"] = pd.to_numeric(adf["long"], errors="coerce")
        adf = adf.dropna(subset=["lat", "long"])
        adf = adf[(adf["lat"] != 0) & (adf["long"] != 0)]
        if hub_filter and hub_filter != "All Hubs" and "cluster_name" in adf.columns:
            valid_clusters = df["Cluster_Code"].tolist() if "Cluster_Code" in df.columns else []
            adf = adf[adf["cluster_name"].isin(valid_clusters)]
        if len(adf) > 0:
            if viz_mode == "heatmap":
                HeatMap(adf[["lat", "long"]].values.tolist(), radius=12, blur=8, max_zoom=13).add_to(m)
            elif viz_mode == "dots":
                for _, r in adf.iterrows():
                    folium.CircleMarker(
                        location=[r["lat"], r["long"]], radius=3,
                        color="#0B8A7A", fill=True, fill_opacity=0.6, weight=1,
                    ).add_to(m)

    # Auto-fit map bounds to show all polygons
    if polygon_lats and polygon_lons:
        sw = [min(polygon_lats) - 0.02, min(polygon_lons) - 0.02]
        ne = [max(polygon_lats) + 0.02, max(polygon_lons) + 0.02]
        m.fit_bounds([sw, ne])

    # Map tools
    MeasureControl(
        position="topleft",
        primary_length_unit="kilometers",
        secondary_length_unit="meters",
        primary_area_unit="sqkilometers",
    ).add_to(m)
    if OsrmRouteDistanceTool._template is not None:
        OsrmRouteDistanceTool().add_to(m)
    folium.LayerControl(position="topright", collapsed=False).add_to(m)

    _add_surge_legend(m)

    # Pincode color legend (bottom-left, scrollable)
    if pincode_colors:
        legend_items = ""
        shown_hub = hub_filter if (hub_filter and hub_filter != "All Hubs") else None
        hubs_to_show = [shown_hub] if shown_hub else list(pincode_colors.keys())[:5]
        for hub_name in hubs_to_show:
            if hub_name not in pincode_colors:
                continue
            legend_items += f'<div style="font-weight:700;font-size:11px;margin:6px 0 3px;color:#333;border-bottom:1px solid #eee;padding-bottom:2px">{hub_name}</div>'
            for pin, clr in list(pincode_colors[hub_name].items())[:12]:
                legend_items += (
                    f'<div style="display:flex;align-items:center;gap:4px;padding:1px 0">'
                    f'<span style="width:14px;height:10px;background:{clr};border-radius:2px;flex-shrink:0;border:1px solid rgba(0,0,0,.15)"></span>'
                    f'<span style="font-size:10px;color:#555">{pin}</span></div>'
                )
        if legend_items:
            pc_legend = f'''<div style="position:fixed;bottom:50px;left:10px;max-width:180px;max-height:300px;overflow-y:auto;
                background:rgba(255,255,255,0.95);border:1px solid #d1d5db;border-radius:8px;padding:8px 10px;
                font-family:Arial,sans-serif;z-index:9999;box-shadow:0 2px 8px rgba(0,0,0,.12)">
                <div style="font-size:11px;font-weight:700;color:#1f2937;border-bottom:2px solid #0B8A7A;padding-bottom:3px;margin-bottom:4px">
                    Pincode Colors</div>{legend_items}</div>'''
            m.get_root().html.add_child(folium.Element(pc_legend))

    return m


def create_editable_polygon_map(polygon_df, cluster_df=None, hub_filter=None, satellite=False):
    """
    Create a folium map with polygons in an editable FeatureGroup.
    Returns (map, feature_group) — pass feature_group to st_folium's
    feature_group_to_add_to param so Leaflet-Draw can edit existing polygons.
    """
    if not HAS_FOLIUM:
        return None, None
    if polygon_df is None or len(polygon_df) == 0:
        return None, None

    df = polygon_df.copy()
    df.columns = df.columns.str.strip()

    hub_col = "Hub Name" if "Hub Name" in df.columns else "hub_name"
    if hub_filter and hub_filter != "All Hubs" and hub_col in df.columns:
        df = df[df[hub_col] == hub_filter]

    # Compute center from polygon centroids
    center_lat, center_lon = 26.8, 92.7
    lats, lons = [], []
    wkt_col = "Polygon WKT" if "Polygon WKT" in df.columns else None
    if wkt_col:
        for wkt in df[wkt_col].dropna().head(50):
            try:
                poly = wkt_loads(str(wkt))
                lats.append(poly.centroid.y)
                lons.append(poly.centroid.x)
            except Exception:
                pass
    if lats:
        center_lat = float(np.mean(lats))
        center_lon = float(np.mean(lons))

    m = _base_map(center_lat, center_lon, satellite=satellite)

    all_hubs = df[hub_col].unique().tolist() if hub_col in df.columns else []
    hub_colors = get_hub_color_map(all_hubs)

    # Editable feature group — polygons added here become editable via Draw plugin
    fg = folium.FeatureGroup(name="editable_polygons")

    pin_col = "Pincode" if "Pincode" in df.columns else "pincode"

    for idx, row in df.iterrows():
        try:
            wkt = row.get("Polygon WKT", "")
            if pd.isna(wkt) or not wkt:
                continue
            poly = wkt_loads(wkt)
            latlon = [[lat, lon] for lon, lat in poly.exterior.coords]

            cc = row.get("Cluster_Code", "")
            hub = row.get(hub_col, "")
            pincode = str(row.get(pin_col, ""))
            desc = row.get("Description", "")
            cat = row.get("Cluster_Category", "")
            hub_color = hub_colors.get(hub, "#3498db")

            popup_html = (
                f"<b>{cc}</b><br>Hub: {hub}<br>Pincode: {pincode}"
                f"<br>Rate: ₹{desc}<br>Category: {cat}"
                f"<br><i>Idx: {idx}</i>"
            )

            folium.Polygon(
                locations=latlon,
                popup=folium.Popup(popup_html, max_width=280),
                tooltip=f"{cc} — ₹{desc}",
                color=hub_color,
                weight=2.5,
                fill=True,
                fill_color=hub_color,
                fill_opacity=0.35,
            ).add_to(fg)
        except Exception:
            continue

    # The FG must live on the map so its JS variable is defined; Draw(feature_group=fg)
    # then uses it as drawnItems, making existing polygons editable/deletable.
    fg.add_to(m)
    MeasureControl(
        position="topleft",
        primary_length_unit="kilometers",
        secondary_length_unit="meters",
        primary_area_unit="sqkilometers",
    ).add_to(m)
    if OsrmRouteDistanceTool._template is not None:
        OsrmRouteDistanceTool().add_to(m)
    folium.LayerControl(position="topright", collapsed=False).add_to(m)
    return m, fg


@st.cache_data(ttl=86400, show_spinner=False)
def _get_osrm_route(hub_lat, hub_lon, vol_lat, vol_lon):
    """Fetch road route from OSRM. Returns (list of [lat, lon], distance_km) or (None, None).
    Cached for 24h to avoid repeated API calls for same coordinate pairs."""
    try:
        url = (
            f"http://router.project-osrm.org/route/v1/driving/"
            f"{hub_lon},{hub_lat};{vol_lon},{vol_lat}"
            f"?overview=full&geometries=geojson"
        )
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return None, None
        data = resp.json()
        if data.get("code") != "Ok" or not data.get("routes"):
            return None, None
        route = data["routes"][0]
        coords = route["geometry"]["coordinates"]  # [[lon, lat], ...]
        latlon_coords = [[c[1], c[0]] for c in coords]  # convert to [lat, lon]
        distance_km = route["distance"] / 1000.0  # meters → km
        return latlon_coords, distance_km
    except Exception:
        return None, None


def create_osrm_map(final_output_df, geojson_data=None, satellite=False, hub_filter=None, rate_filter=None, vlat_col=None, vlon_col=None):
    if not HAS_FOLIUM: return None
    df = final_output_df.copy(); df.columns = df.columns.str.strip()
    lc = "Hub_lat" if "Hub_lat" in df.columns else "hub_lat"
    nc = "Hub_long" if "Hub_long" in df.columns else "hub_long"
    nm = "Hub_Name" if "Hub_Name" in df.columns else "hub_name"

    if hub_filter and hub_filter != "All Hubs":
        df = df[df[nm] == hub_filter]

    # Rate filter
    if rate_filter and rate_filter != "All" and "SP&A Aligned P mapping" in df.columns:
        df = df[df["SP&A Aligned P mapping"].astype(str) == rate_filter]

    # Ensure coordinate columns are numeric to avoid string-dtype mean() error
    if lc in df.columns:
        df[lc] = pd.to_numeric(df[lc], errors="coerce")
    if nc in df.columns:
        df[nc] = pd.to_numeric(df[nc], errors="coerce")

    _lat_mean = df[lc].mean() if lc in df.columns else float("nan")
    _lon_mean = df[nc].mean() if nc in df.columns else float("nan")
    center_lat = _lat_mean if pd.notna(_lat_mean) else 26.8
    center_lon = _lon_mean if pd.notna(_lon_mean) else 92.7
    m = _base_map(center_lat, center_lon, zoom=8 if hub_filter in (None, "All Hubs") else 10, satellite=satellite)

    # GeoJSON boundaries
    pincode_color_map = {}  # populated inside if-block; used by label loop below
    pincode_field = None
    if geojson_data is not None:
        pcs = set(df["Pincode"].astype(str).str.strip().str.replace(".0", "", regex=False).tolist())
        pincode_field = None
        for f in geojson_data.get("features", [])[:1]:
            for k in ["pincode", "Pincode", "PINCODE", "pin"]:
                if k in f.get("properties", {}):
                    pincode_field = k; break
        if pincode_field:
            # Per-pincode color map so each pincode in a hub gets a distinct color
            sorted_pcs = sorted(pcs)
            pincode_color_map = {
                pc: _PINCODE_PALETTE[i % len(_PINCODE_PALETTE)]
                for i, pc in enumerate(sorted_pcs)
            }
            for feature in geojson_data.get("features", []):
                pc = str(feature.get("properties", {}).get(pincode_field, "")).strip()
                if pc in pcs:
                    rate_row = df[df["Pincode"].astype(str).str.strip().str.replace(".0", "", regex=False) == pc]
                    rate = rate_row["SP&A Aligned P mapping"].iloc[0] if len(rate_row) > 0 else ""
                    dist_val = rate_row["Distance"].iloc[0] if len(rate_row) > 0 and "Distance" in rate_row.columns else 0
                    dist_str = f"{dist_val:.1f} km" if pd.notna(dist_val) and dist_val > 0 else ""
                    fill_c = pincode_color_map.get(pc, "#3498db")
                    try:
                        folium.GeoJson(
                            {"type": "Feature", "geometry": feature["geometry"],
                             "properties": {"pincode": pc, "rate": str(rate), "distance": dist_str}},
                            style_function=lambda x, fc=fill_c: {
                                "fillColor": fc, "color": "black", "weight": 2,
                                "fillOpacity": 0.25, "dashArray": "",
                            },
                            tooltip=folium.GeoJsonTooltip(
                                fields=["pincode", "rate", "distance"],
                                aliases=["Pincode", "Payout Rate", "Distance"],
                                style="font-size:12px;font-weight:bold;",
                            ),
                        ).add_to(m)
                    except Exception:
                        pass

    # Hub markers — skip rows where lat/lon is NaN
    hubs = df.drop_duplicates(subset=[nm])
    for _, h in hubs.iterrows():
        if pd.notna(h.get(lc)) and pd.notna(h.get(nc)):
            _hlat, _hlon = float(h[lc]), float(h[nc])
            folium.Marker(
                location=[_hlat, _hlon], popup=f"<b>{h[nm]}</b>", tooltip=h[nm],
                icon=folium.DivIcon(
                    html=(
                        f'<div title="{h[nm]} — click to set as route start"'
                        f' onclick="if(window.osrmAddPoint){{window.osrmAddPoint({_hlat},{_hlon});return false;}}"'
                        f' style="cursor:pointer;background:#e74c3c;color:#fff;border:3px solid #fff;border-radius:50%;'
                        f'width:30px;height:30px;display:flex;align-items:center;justify-content:center;'
                        f'font-size:15px;box-shadow:0 2px 8px rgba(0,0,0,.45);font-weight:700;line-height:30px;text-align:center;">&#127968;</div>'
                    ),
                    icon_size=(30, 30), icon_anchor=(15, 15)),
            ).add_to(m)

    # Volumetric point labels — show distance (km) + payout rate
    # Use caller-supplied column names first, then fall back to common name patterns
    _vlat_candidates = ["Volumetric Lat", "volumetric_lat", "vol_lat", "Lat", "lat", "latitude", "Latitude"]
    _vlon_candidates = ["Volumetric Long", "volumetric_long", "vol_long", "Long", "long", "longitude", "Longitude"]
    if vlat_col and vlat_col in df.columns:
        vlat = vlat_col
    else:
        vlat = next((c for c in _vlat_candidates if c in df.columns), None)
    if vlon_col and vlon_col in df.columns:
        vlon = vlon_col
    else:
        vlon = next((c for c in _vlon_candidates if c in df.columns), None)
    if vlat:
        df[vlat] = pd.to_numeric(df[vlat], errors="coerce")
    if vlon:
        df[vlon] = pd.to_numeric(df[vlon], errors="coerce")
    if vlat and vlon:
        for _, row in df.iterrows():
            # Skip rows where coordinates or distance is NaN
            if not (pd.notna(row.get(vlat)) and pd.notna(row.get(vlon)) and pd.notna(row.get("Distance"))):
                continue
            rate = row.get("SP&A Aligned P mapping", "")
            dist = row.get("Distance", 0)
            pc = row.get("Pincode", "")
            hub_name = row.get(nm, "")
            dist_str = f"{dist:.1f} km" if pd.notna(dist) and dist > 0 else "N/A"
            pc_str = str(pc).strip().replace(".0", "")
            pin_color = pincode_color_map.get(pc_str, "#0B8A7A") if geojson_data is not None and pincode_field else "#0B8A7A"
            label_html = (
                f'<div style="font-size:11px;font-weight:bold;background:white;padding:4px 7px;'
                f'border:2px solid {pin_color};border-radius:5px;white-space:nowrap;'
                f'box-shadow:0 2px 6px rgba(0,0,0,0.15);line-height:1.4;">'
                f'<span style="color:#333;">{pc}</span><br>'
                f'<span style="color:{pin_color};font-size:12px;">{rate}</span> '
                f'<span style="color:#666;font-size:10px;">({dist_str})</span>'
                f'</div>'
            )
            popup_html = (
                f"<b>Pincode:</b> {pc}<br>"
                f"<b>Hub:</b> {hub_name}<br>"
                f"<b>Distance:</b> {dist_str}<br>"
                f"<b>Payout Rate:</b> {rate}"
            )
            folium.Marker(
                location=[float(row[vlat]), float(row[vlon])],
                popup=folium.Popup(popup_html, max_width=250),
                tooltip=f"{pc}: {rate} ({dist_str})",
                icon=folium.DivIcon(
                    html=label_html,
                    icon_size=(120, 40), icon_anchor=(60, 20)),
            ).add_to(m)

            # Draw route from hub to volumetric center via OSRM
            h_lat = row.get(lc)
            h_lon = row.get(nc)
            if pd.notna(h_lat) and pd.notna(h_lon):
                route_coords, route_dist_km = _get_osrm_route(
                    float(h_lat), float(h_lon), float(row[vlat]), float(row[vlon])
                )
                if route_coords is not None:
                    folium.PolyLine(
                        locations=route_coords,
                        color="#0B8A7A", weight=2.5, opacity=0.7,
                        tooltip=f"Route: {route_dist_km:.1f} km",
                    ).add_to(m)
                    # Distance label at route midpoint
                    mid_idx = len(route_coords) // 2
                    mid_pt = route_coords[mid_idx]
                    folium.Marker(
                        location=mid_pt,
                        icon=folium.DivIcon(
                            html=(
                                f'<div style="background:rgba(255,255,255,0.92);border:2px solid #0B8A7A;'
                                f'border-radius:4px;padding:2px 6px;font-size:11px;font-weight:700;'
                                f'color:#0B8A7A;white-space:nowrap;box-shadow:0 1px 4px rgba(0,0,0,.2);">'
                                f'{route_dist_km:.1f} km</div>'
                            ),
                            icon_size=(70, 22), icon_anchor=(35, 11)),
                    ).add_to(m)
                else:
                    folium.PolyLine(
                        locations=[[float(h_lat), float(h_lon)], [float(row[vlat]), float(row[vlon])]],
                        color="#0B8A7A", weight=1.5, opacity=0.5, dash_array="6",
                    ).add_to(m)

    # Map tools
    MeasureControl(
        position="topleft",
        primary_length_unit="kilometers",
        secondary_length_unit="meters",
        primary_area_unit="sqkilometers",
    ).add_to(m)
    if OsrmRouteDistanceTool._template is not None:
        OsrmRouteDistanceTool().add_to(m)
    folium.LayerControl(position="topright", collapsed=False).add_to(m)

    _add_surge_legend(m)

    return m


def generate_kml(df):
    """Generate KML string from polygon dataframe."""
    if df is None or df.empty:
        return ""
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>']
    for _, row in df.iterrows():
        name = row.get("Cluster_Code", row.get("cluster_code", "Cluster"))
        desc = f"Hub: {row.get('hub_name', row.get('Hub Name', ''))} | Rate: ₹{row.get('surge_amount', row.get('Description', ''))} | Category: {row.get('Cluster_Category', row.get('cluster_category', ''))}"
        boundary = row.get("boundary", row.get("Polygon WKT", ""))
        lines.append(f"<Placemark><name>{name}</name><description>{desc}</description>")
        lines.append(f"<Polygon><outerBoundaryIs><LinearRing><coordinates>{boundary}</coordinates></LinearRing></outerBoundaryIs></Polygon>")
        lines.append("</Placemark>")
    lines.append("</Document></kml>")
    return "\n".join(lines)
