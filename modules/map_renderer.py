"""
Map Renderer Module - UPDATED
===================
Creates interactive Folium maps with cluster polygons and hub markers.
Uses centroid coordinates for accurate rate label placement.
"""

import folium
from folium import plugins
import pandas as pd
from shapely import wkt
from shapely.geometry import mapping
import json


class MapRenderer:
    """Renders interactive maps using Folium"""

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
                          show_hub_markers=True, selected_hub=None):
        """
        Create interactive map with cluster polygons and hub markers

        Parameters:
        -----------
        cluster_df : DataFrame
            Processed cluster data with geometry and centroid coordinates
        hub_df : DataFrame
            Hub location data
        show_rate_labels : bool
            Whether to show rate labels on clusters
        show_hub_markers : bool
            Whether to show hub location markers
        selected_hub : str or None
            If specified, center map on this hub
        """

        # Determine map center
        if selected_hub and len(cluster_df[cluster_df['hub_name'] == selected_hub]) > 0:
            hub_data = hub_df[hub_df['name'] == selected_hub].iloc[0]
            center = [hub_data['latitude'], hub_data['longitude']]
            zoom = 11
        elif len(cluster_df) > 0 and 'center_lat' in cluster_df.columns:
            # Use centroid of all clusters
            center = [
                cluster_df['center_lat'].mean(),
                cluster_df['center_lon'].mean()
            ]
            zoom = 10
        else:
            center = self.default_location
            zoom = self.default_zoom

        # Create base map
        m = folium.Map(
            location=center,
            zoom_start=zoom,
            tiles='OpenStreetMap',
            control_scale=True
        )

        # Add cluster polygons
        for idx, row in cluster_df.iterrows():
            if pd.notna(row.get('geometry')):
                self._add_cluster_polygon(m, row, show_rate_labels)

        # Add hub markers
        if show_hub_markers:
            relevant_hubs = hub_df[hub_df['id'].isin(cluster_df['hub_id'].unique())]
            for idx, hub in relevant_hubs.iterrows():
                self._add_hub_marker(m, hub)

        # Add legend
        self._add_legend(m)

        # Add fullscreen button
        plugins.Fullscreen(position='topright').add_to(m)

        return m

    def _add_cluster_polygon(self, map_obj, cluster_row, show_label=True):
        """Add a single cluster polygon to the map with rate label at centroid"""
        try:
            geom = cluster_row['geometry']
            surge_amount = cluster_row.get('surge_amount', 0)

            # Get color based on surge rate
            color = self._get_rate_color(surge_amount)

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

            # Add rate label at centroid
            if show_label and pd.notna(cluster_row.get('center_lat')) and pd.notna(cluster_row.get('center_lon')):
                # Format the surge amount for display
                if surge_amount == int(surge_amount):
                    rate_text = f"₹{int(surge_amount)}"
                else:
                    rate_text = f"₹{surge_amount:.1f}"

                # Create label with better styling
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
                ).add_to(map_obj)

        except Exception as e:
            print(f"Warning: Could not add polygon for cluster {cluster_row.get('cluster_code', 'unknown')}: {e}")

    def _add_hub_marker(self, map_obj, hub_row):
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
            ).add_to(map_obj)

        except Exception as e:
            print(f"Warning: Could not add hub marker for {hub_row.get('name', 'unknown')}: {e}")

    def _add_legend(self, map_obj):
        """Add color legend to the map"""
        legend_html = '''
        <div style="
            position: fixed;
            bottom: 50px;
            right: 50px;
            width: 220px;
            background-color: white;
            border: 2px solid #d1d5db;
            border-radius: 8px;
            padding: 12px;
            font-family: Arial, sans-serif;
            font-size: 12px;
            z-index: 9999;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        ">
            <h4 style="margin: 0 0 10px 0; font-size: 14px; color: #1f2937; border-bottom: 2px solid #3b82f6; padding-bottom: 5px;">
                Surge Rate Legend
            </h4>
            <div style="display: flex; flex-direction: column; gap: 6px;">
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
