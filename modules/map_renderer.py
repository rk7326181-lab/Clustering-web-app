"""
Map Renderer Module - UPDATED
===================
Creates interactive Folium maps with cluster polygons and hub markers.
Uses centroid coordinates for accurate rate label placement.
"""

import folium
from folium import plugins
from folium.plugins import MeasureControl
from branca.element import MacroElement
try:
    from jinja2 import Template as _JT
except ImportError:
    _JT = None
import pandas as pd
from shapely import wkt
from shapely.geometry import mapping
import json


class OsrmRouteDistanceTool(MacroElement):
    """Ruler tool — click any point on the map (polygon, marker, or empty area)
    to measure real road distance via OSRM. Press ESC to clear."""
    _template = _JT("""
    {% macro script(this, kwargs) %}
    (function(){
        var mapObj = {{ this._parent.get_name() }};
        var RouteDistControl = L.Control.extend({
            options: { position: 'topleft' },
            onAdd: function(map) {
                var container = L.DomUtil.create('div','leaflet-bar leaflet-control');
                var btn = L.DomUtil.create('a','',container);
                btn.innerHTML = '&#128207;';
                btn.title = 'Road Distance Tool (click points, ESC to clear)';
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
                        active=true; btn.style.backgroundColor='#0B8A7A'; btn.style.color='#fff';
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
                var _lastMs=0;
                function addPointOnce(lat,lng){var now=Date.now();if(now-_lastMs<80)return;_lastMs=now;addPoint(lat,lng);}
                function addLayerListener(layer){
                    if(layer.eachLayer){layer.eachLayer(addLayerListener);layer.on('layeradd',function(ev){addLayerListener(ev.layer);});}
                    else if(layer.on){layer.on('click',function(e){if(!active)return;addPointOnce(e.latlng.lat,e.latlng.lng);});}
                }
                map.eachLayer(addLayerListener);
                map.on('layeradd',function(ev){addLayerListener(ev.layer);});
                map.on('click',function(e){addPointOnce(e.latlng.lat,e.latlng.lng);});
                document.addEventListener('keydown',function(e){if(e.key==='Escape')clearAll();});
                return container;
            }
        });
        new RouteDistControl().addTo(mapObj);
    })();
    {% endmacro %}
    """) if _JT else None


class MapRenderer:
    """Renders interactive maps using Folium"""

    # Pastel palette for pincode-based coloring (30 distinct colors)
    PINCODE_COLORS = [
        '#FFB3BA', '#BAFFC9', '#BAE1FF', '#FFFFBA', '#E8BAFF',
        '#FFB3E6', '#B3FFD9', '#B3D9FF', '#FFE6B3', '#D4BAFF',
        '#BAFFD4', '#FFD4BA', '#BAF2FF', '#FFB3CC', '#C9FFB3',
        '#B3FFEE', '#FFCCB3', '#CCB3FF', '#B3FFC9', '#FFE0CC',
        '#CCE0FF', '#E0FFD1', '#FFD1E0', '#D1FFE0', '#E0D1FF',
        '#FFE8D1', '#D1F0FF', '#F0FFD1', '#FFD1F0', '#FFDFBA',
    ]

    # Color scheme for surge rates
    RATE_COLORS = {
        0: '#9CA3AF',     # Gray - Base rate
        0.5: '#BFDBFE',   # Very light blue
        1: '#BFDBFE',     # Light blue
        1.5: '#93C5FD',
        2: '#93C5FD',
        2.5: '#60A5FA',
        3: '#60A5FA',
        3.5: '#3B82F6',   # Blue
        4: '#3B82F6',
        4.5: '#2563EB',
        5: '#2563EB',
        5.5: '#1D4ED8',
        6: '#1D4ED8',
        6.5: '#FCD34D',
        7: '#FCD34D',     # Yellow
        7.5: '#FBBF24',
        8: '#FBBF24',
        8.5: '#F59E0B',
        9: '#F59E0B',
        9.5: '#F97316',
        10: '#F97316',    # Orange
        10.5: '#EF4444',
        11: '#EF4444',    # Red
        11.5: '#DC2626',
        12: '#DC2626',
        12.5: '#B91C1C',
        13: '#B91C1C',
        13.5: '#991B1B',
        14: '#991B1B'     # Dark red
    }

    def __init__(self):
        self.default_location = [20.5937, 78.9629]  # Center of India
        self.default_zoom = 5

    def _get_rate_color(self, rate):
        """Get color for a given rate (handles decimal rates)"""
        rate = float(rate)

        # Find closest defined rate
        closest_rate = min(self.RATE_COLORS.keys(), key=lambda x: abs(x - rate))
        return self.RATE_COLORS.get(closest_rate, '#9CA3AF')

    def create_cluster_map(self, cluster_df, hub_df, show_rate_labels=True,
                          show_hub_markers=True, selected_hub=None,
                          color_mode='rate'):
        """
        Create interactive map with cluster polygons and hub markers.

        color_mode: 'rate' (color by surge rate) | 'pincode' (color by pincode)
        """
        if cluster_df is None or len(cluster_df) == 0:
            m = folium.Map(location=self.default_location, zoom_start=self.default_zoom,
                           tiles=None, control_scale=True)
            folium.TileLayer("OpenStreetMap", name="Street Map").add_to(m)
            folium.Marker(
                location=self.default_location,
                icon=folium.DivIcon(html="<div style='background:#fee; padding:8px 12px; border:1px solid #f00; border-radius:4px; font-family:Arial; font-size:12px;'>No cluster data available</div>")
            ).add_to(m)
            return m

        # Determine map center
        if selected_hub and len(cluster_df[cluster_df['hub_name'] == selected_hub]) > 0:
            hub_sub = hub_df[hub_df['name'] == selected_hub]
            if len(hub_sub) > 0:
                hub_data = hub_sub.iloc[0]
                center = [hub_data['latitude'], hub_data['longitude']]
                zoom = 11
            else:
                center = [cluster_df[cluster_df['hub_name'] == selected_hub]['center_lat'].mean(),
                          cluster_df[cluster_df['hub_name'] == selected_hub]['center_lon'].mean()]
                zoom = 11
        elif len(cluster_df) > 0 and 'center_lat' in cluster_df.columns:
            center = [cluster_df['center_lat'].mean(), cluster_df['center_lon'].mean()]
            zoom = 10
        else:
            center = self.default_location
            zoom = self.default_zoom

        # Base map with multi-tile layers (Street / Satellite / Terrain)
        m = folium.Map(location=center, zoom_start=zoom, tiles=None, control_scale=True)
        folium.TileLayer("OpenStreetMap", name="Street Map").add_to(m)
        folium.TileLayer(
            tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            attr="Esri", name="Satellite", overlay=False, control=True
        ).add_to(m)
        folium.TileLayer(
            tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
            attr="Esri", name="Terrain", overlay=False, control=True
        ).add_to(m)

        # Build pincode color map for pincode mode
        pincode_color_map = {}
        if color_mode == 'pincode':
            unique_pins = cluster_df['pincode'].dropna().unique() if 'pincode' in cluster_df.columns else []
            for i, pin in enumerate(sorted([str(p) for p in unique_pins])):
                pincode_color_map[pin] = self.PINCODE_COLORS[i % len(self.PINCODE_COLORS)]

        # FeatureGroups for clean LayerControl
        rate_label_fg = folium.FeatureGroup(name="Rate Labels", show=show_rate_labels)
        hub_fg = folium.FeatureGroup(name="Hub Markers", show=show_hub_markers)

        for idx, row in cluster_df.iterrows():
            if pd.notna(row.get('geometry')):
                self._add_cluster_polygon(m, row, show_rate_labels, rate_label_fg,
                                          color_mode=color_mode,
                                          pincode_color_map=pincode_color_map)

        rate_label_fg.add_to(m)

        if show_hub_markers:
            try:
                hub_ids = cluster_df['hub_id'].unique() if 'hub_id' in cluster_df.columns else []
                relevant_hubs = hub_df[hub_df['id'].isin(hub_ids)] if len(hub_ids) > 0 else hub_df
            except Exception:
                relevant_hubs = hub_df
            for idx, hub in relevant_hubs.iterrows():
                self._add_hub_marker(hub_fg, hub)

        hub_fg.add_to(m)

        self._add_legend(m, color_mode=color_mode, pincode_color_map=pincode_color_map)

        plugins.Fullscreen(position='topright').add_to(m)
        MeasureControl(
            position='topleft',
            primary_length_unit='kilometers',
            secondary_length_unit='meters',
            primary_area_unit='sqkilometers',
        ).add_to(m)
        folium.LayerControl(position='topright', collapsed=True).add_to(m)
        if OsrmRouteDistanceTool._template is not None:
            OsrmRouteDistanceTool().add_to(m)

        return m

    def _add_cluster_polygon(self, map_obj, cluster_row, show_label=True, label_fg=None,
                             color_mode='rate', pincode_color_map=None):
        """Add a single cluster polygon to the map with rate label at centroid."""
        try:
            geom = cluster_row['geometry']
            surge_amount = cluster_row.get('surge_amount', 0)

            # Color based on mode
            if color_mode == 'pincode' and pincode_color_map:
                pin = str(cluster_row.get('pincode', ''))
                color = pincode_color_map.get(pin, '#9CA3AF')
            else:
                color = self._get_rate_color(surge_amount)

            # Simplify geometry to reduce map HTML size
            geom = geom.simplify(0.001, preserve_topology=True)

            # Convert geometry to GeoJSON
            geo_json = mapping(geom)

            # Get cluster category for display
            cluster_category = cluster_row.get('cluster_category', f'Rs.{surge_amount}')

            # Create popup content with all details
            popup_html = f"""
            <div style='width: 280px; font-family: Arial, sans-serif;'>
                <h4 style='margin: 0 0 10px 0; color: #1f2937; border-bottom: 2px solid #3b82f6; padding-bottom: 5px;'>
                    {cluster_row.get('cluster_code', 'N/A')}
                </h4>
                <table style='width: 100%; font-size: 12px; border-collapse: collapse;'>
                    <tr style='background-color: #f3f4f6;'>
                        <td style='padding: 5px; font-weight: bold;'>Hub:</td>
                        <td style='padding: 5px;'>{cluster_row.get('hub_name', 'N/A')}</td>
                    </tr>
                    <tr>
                        <td style='padding: 5px; font-weight: bold;'>Pincode:</td>
                        <td style='padding: 5px;'>{cluster_row.get('pincode', 'N/A')}</td>
                    </tr>
                    <tr style='background-color: #f3f4f6;'>
                        <td style='padding: 5px; font-weight: bold;'>Surge Rate:</td>
                        <td style='padding: 5px; color: #059669; font-weight: bold; font-size: 14px;'>{cluster_category}</td>
                    </tr>
                    <tr>
                        <td style='padding: 5px; font-weight: bold;'>Category:</td>
                        <td style='padding: 5px;'>{cluster_row.get('rate_category', 'N/A')}</td>
                    </tr>
                    <tr style='background-color: #f3f4f6;'>
                        <td style='padding: 5px; font-weight: bold;'>Cluster ID:</td>
                        <td style='padding: 5px;'>{cluster_row.get('cluster_suffix', 'N/A') if 'cluster_suffix' in cluster_row else 'N/A'}</td>
                    </tr>
                </table>
            </div>
            """

            # Add polygon to map
            folium.GeoJson(
                geo_json,
                style_function=lambda x, color=color: {
                    'fillColor': color,
                    'color': '#374151',
                    'weight': 2,
                    'fillOpacity': 0.5
                },
                highlight_function=lambda x: {
                    'weight': 4,
                    'fillOpacity': 0.7,
                    'color': '#1f2937'
                },
                tooltip=f"Cluster: {cluster_row.get('cluster_code', 'N/A')} | Rate: {cluster_category}",
                popup=folium.Popup(popup_html, max_width=320)
            ).add_to(map_obj)

            # Add rate label at centroid — into label_fg for clean LayerControl
            if show_label and pd.notna(cluster_row.get('center_lat')) and pd.notna(cluster_row.get('center_lon')):
                if surge_amount == int(surge_amount):
                    rate_text = f"₹{int(surge_amount)}"
                else:
                    rate_text = f"₹{surge_amount:.1f}"

                target = label_fg if label_fg is not None else map_obj
                folium.Marker(
                    location=[cluster_row['center_lat'], cluster_row['center_lon']],
                    icon=folium.DivIcon(html=f"""
                        <div style='
                            font-size: 13px;
                            font-weight: bold;
                            color: #1f2937;
                            text-shadow:
                                -1px -1px 0 white,
                                1px -1px 0 white,
                                -1px 1px 0 white,
                                1px 1px 0 white,
                                0 0 3px white;
                            background-color: rgba(255, 255, 255, 0.85);
                            padding: 3px 8px;
                            border-radius: 4px;
                            border: 1.5px solid #374151;
                            white-space: nowrap;
                            transform: translate(-50%, -50%);
                        '>{rate_text}</div>
                    """)
                ).add_to(target)

        except Exception as e:
            print(f"Warning: Could not add polygon for cluster {cluster_row.get('cluster_code', 'unknown')}: {e}")

    def _add_hub_marker(self, map_obj_or_fg, hub_row):
        """Add a hub location marker to the map"""
        try:
            # Create custom icon (red triangle)
            icon_html = """
            <svg width="30" height="30" viewBox="0 0 30 30" xmlns="http://www.w3.org/2000/svg">
                <polygon points="15,5 25,25 5,25"
                         fill="#EF4444"
                         stroke="#991B1B"
                         stroke-width="2"/>
                <circle cx="15" cy="17" r="3" fill="white"/>
            </svg>
            """

            popup_html = f"""
            <div style='width: 220px; font-family: Arial, sans-serif;'>
                <h4 style='margin: 0 0 10px 0; color: #1f2937; border-bottom: 2px solid #ef4444; padding-bottom: 5px;'>
                    🏢 {hub_row['name']}
                </h4>
                <table style='width: 100%; font-size: 12px; border-collapse: collapse;'>
                    <tr style='background-color: #fef2f2;'>
                        <td style='padding: 5px; font-weight: bold;'>Hub ID:</td>
                        <td style='padding: 5px;'>{hub_row['id']}</td>
                    </tr>
                    <tr>
                        <td style='padding: 5px; font-weight: bold;'>Category:</td>
                        <td style='padding: 5px;'>{hub_row.get('hub_category', 'N/A')}</td>
                    </tr>
                    <tr style='background-color: #fef2f2;'>
                        <td style='padding: 5px; font-weight: bold;'>Latitude:</td>
                        <td style='padding: 5px;'>{hub_row['latitude']:.6f}</td>
                    </tr>
                    <tr>
                        <td style='padding: 5px; font-weight: bold;'>Longitude:</td>
                        <td style='padding: 5px;'>{hub_row['longitude']:.6f}</td>
                    </tr>
                </table>
            </div>
            """

            folium.Marker(
                location=[hub_row['latitude'], hub_row['longitude']],
                popup=folium.Popup(popup_html, max_width=260),
                tooltip=f"Hub: {hub_row['name']}",
                icon=folium.DivIcon(html=f'<div style="margin-left: -15px; margin-top: -15px;">{icon_html}</div>')
            ).add_to(map_obj_or_fg)

        except Exception as e:
            print(f"Warning: Could not add hub marker for {hub_row.get('name', 'unknown')}: {e}")

    def _add_legend(self, map_obj, color_mode='rate', pincode_color_map=None):
        """Add collapsible color legend to the map"""
        if color_mode == 'pincode' and pincode_color_map:
            items = ''
            for pin, clr in list(pincode_color_map.items())[:20]:
                items += (
                    f'<div style="display:flex;align-items:center;margin:2px 0">'
                    f'<div style="width:20px;height:13px;background:{clr};margin-right:6px;'
                    f'border:1px solid rgba(0,0,0,.15);border-radius:2px;opacity:0.7"></div>'
                    f'<span style="font-size:11px">{pin}</span></div>'
                )
            if len(pincode_color_map) > 20:
                items += f'<div style="font-size:10px;color:#6b7280;margin-top:3px">+{len(pincode_color_map)-20} more…</div>'
            pc_legend_html = (
                '<div style="position:fixed;bottom:50px;right:50px;width:190px;'
                'background-color:white;border:2px solid #d1d5db;border-radius:8px;'
                'padding:10px 12px;font-family:Arial,sans-serif;font-size:12px;'
                'z-index:9999;box-shadow:0 4px 6px rgba(0,0,0,0.1);">'
                '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:5px">'
                '<span style="font-size:13px;font-weight:700;color:#1f2937;border-bottom:2px solid #8B5CF6;padding-bottom:3px;flex:1">Pincode Legend</span>'
                '<button onclick="var b=document.getElementById(\'_pin_lg_body\');var v=b.style.display!==\'none\';b.style.display=v?\'none\':\'block\';this.textContent=v?\'+\':\'−\'" '
                'style="background:none;border:1px solid #9ca3af;border-radius:3px;padding:1px 6px;cursor:pointer;font-size:13px;font-weight:700;color:#6b7280;margin-left:6px;line-height:1.3">−</button>'
                '</div>'
                f'<div id="_pin_lg_body" style="max-height:300px;overflow-y:auto">{items}</div>'
                '</div>'
            )
            map_obj.get_root().html.add_child(folium.Element(pc_legend_html))
            return

        legend_html = '''
        <div style="
            position: fixed;
            bottom: 50px;
            right: 50px;
            width: 220px;
            background-color: white;
            border: 2px solid #d1d5db;
            border-radius: 8px;
            padding: 10px 12px;
            font-family: Arial, sans-serif;
            font-size: 12px;
            z-index: 9999;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        ">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
                <span style="font-size:14px;font-weight:700;color:#1f2937;border-bottom:2px solid #3b82f6;padding-bottom:4px;flex:1">Surge Rate Legend</span>
                <button onclick="var b=document.getElementById('_mr_legend_body');var v=b.style.display!=='none';b.style.display=v?'none':'flex';this.textContent=v?'+':'−'" style="background:none;border:1px solid #9ca3af;border-radius:3px;padding:1px 6px;cursor:pointer;font-size:13px;font-weight:700;color:#6b7280;margin-left:6px;line-height:1.3">−</button>
            </div>
            <div id="_mr_legend_body" style="display: flex; flex-direction: column; gap: 6px;">
                <div style="display: flex; align-items: center;">
                    <div style="width: 25px; height: 16px; background-color: #9CA3AF; margin-right: 8px; border: 1px solid #6b7280; border-radius: 2px;"></div>
                    <span style="font-weight: 500;">₹0 (Base)</span>
                </div>
                <div style="display: flex; align-items: center;">
                    <div style="width: 25px; height: 16px; background-color: #60A5FA; margin-right: 8px; border: 1px solid #3b82f6; border-radius: 2px;"></div>
                    <span>₹1-₹3 (Low)</span>
                </div>
                <div style="display: flex; align-items: center;">
                    <div style="width: 25px; height: 16px; background-color: #2563EB; margin-right: 8px; border: 1px solid #1d4ed8; border-radius: 2px;"></div>
                    <span>₹4-₹6 (Medium)</span>
                </div>
                <div style="display: flex; align-items: center;">
                    <div style="width: 25px; height: 16px; background-color: #F59E0B; margin-right: 8px; border: 1px solid #d97706; border-radius: 2px;"></div>
                    <span>₹7-₹10 (High)</span>
                </div>
                <div style="display: flex; align-items: center;">
                    <div style="width: 25px; height: 16px; background-color: #DC2626; margin-right: 8px; border: 1px solid #991b1b; border-radius: 2px;"></div>
                    <span>₹11+ (Very High)</span>
                </div>
                <div style="margin-top: 8px; padding-top: 8px; border-top: 1px solid #e5e7eb;">
                    <div style="display: flex; align-items: center;">
                        <svg width="25" height="20" viewBox="0 0 30 30" style="margin-right: 8px;">
                            <polygon points="15,5 25,25 5,25" fill="#EF4444" stroke="#991B1B" stroke-width="2"/>
                        </svg>
                        <span style="font-weight: 500;">Hub Location</span>
                    </div>
                </div>
            </div>
        </div>
        '''

        map_obj.get_root().html.add_child(folium.Element(legend_html))
