"""
Data Loader Module - UPDATED for Kepler CSV Format
==================
Handles loading data from Kepler CSV format or BigQuery and preprocessing.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from shapely import wkt
from shapely.geometry import Polygon, Point
import json
import re


class DataLoader:
    """Handles data loading from various sources"""

    def __init__(self, use_bigquery=False):
        self.use_bigquery = use_bigquery
        self.project_root = Path(__file__).parent.parent

    def load_from_csv(self):
        """Load data from local CSV files"""
        try:
            # Try to load Kepler format first (new format)
            kepler_path = self.project_root / "data" / "kepler_gl_final_main_17022026_csv.csv"

            if kepler_path.exists():
                print(f"Loading Kepler format CSV from {kepler_path}")
                return self._load_kepler_format(kepler_path)

            # Fallback to old format
            cluster_path = self.project_root / "data" / "clustering_live_02042026.csv"
            hub_path = self.project_root / "data" / "hub_Lat_Long02042026.csv"

            cluster_df = pd.read_csv(cluster_path)
            hub_df = pd.read_csv(hub_path)

            cluster_df = self._clean_cluster_data(cluster_df)
            hub_df = self._clean_hub_data(hub_df)

            return cluster_df, hub_df

        except Exception as e:
            raise Exception(f"Error loading CSV files: {str(e)}")

    def _load_kepler_format(self, filepath):
        """Load data from Kepler GL final format CSV"""
        try:
            # Read Kepler CSV
            df = pd.read_csv(filepath)

            # Rename columns to match expected format
            column_mapping = {
                'Hub ID': 'hub_id',
                'WKT': 'boundary',
                'CLUSTER_CODE': 'cluster_code',
                'Hub_Name': 'hub_name',
                'Cluster_Category': 'cluster_category',
                'Hub lat': 'hub_lat',
                'Hub Long': 'hub_lon',
                'latitude': 'center_lat',  # Centroid latitude
                'longitude': 'center_lon'  # Centroid longitude
            }

            df = df.rename(columns=column_mapping)

            # Extract pincode from cluster_code (e.g., "577526_A" -> "577526")
            df['pincode'] = df['cluster_code'].apply(self._extract_pincode)

            # Extract cluster suffix (e.g., "577526_A" -> "A")
            df['cluster_suffix'] = df['cluster_code'].apply(self._extract_cluster_suffix)

            # Parse surge amount from cluster_category (e.g., "Rs.4" -> 4)
            df['surge_amount'] = df['cluster_category'].apply(self._parse_surge_amount)

            # Create description field
            df['description'] = df['cluster_code']

            # Add default fields
            df['is_active'] = True
            df['cluster_type'] = 'payout_cluster'

            # Create cluster_df
            cluster_df = df[[
                'hub_id', 'hub_name', 'cluster_code', 'description',
                'boundary', 'pincode', 'surge_amount', 'is_active',
                'cluster_type', 'center_lat', 'center_lon', 'cluster_category'
            ]].copy()

            # Create hub_df (unique hubs only)
            hub_df = df[['hub_id', 'hub_name', 'hub_lat', 'hub_lon']].drop_duplicates(subset=['hub_id'])
            hub_df = hub_df.rename(columns={
                'hub_id': 'id',
                'hub_name': 'name',
                'hub_lat': 'latitude',
                'hub_lon': 'longitude'
            })
            hub_df['hub_category'] = 'ECOM_SELF_LM'
            hub_df['creation_date'] = pd.Timestamp.now()

            print(f"✅ Loaded {len(cluster_df)} clusters from {len(hub_df)} unique hubs")
            print(f"✅ Surge rates range: ₹{cluster_df['surge_amount'].min():.1f} - ₹{cluster_df['surge_amount'].max():.1f}")

            return cluster_df, hub_df

        except Exception as e:
            raise Exception(f"Error loading Kepler format: {str(e)}")

    @staticmethod
    def _extract_pincode(cluster_code):
        """Extract pincode from cluster code (e.g., '577526_A' -> '577526')"""
        if pd.isna(cluster_code):
            return ''

        # Split by underscore and take first part
        parts = str(cluster_code).split('_')
        return parts[0] if parts else ''

    @staticmethod
    def _extract_cluster_suffix(cluster_code):
        """Extract cluster suffix (e.g., '577526_A' -> 'A')"""
        if pd.isna(cluster_code):
            return ''

        # Split by underscore and take last part
        parts = str(cluster_code).split('_')
        return parts[-1] if len(parts) > 1 else ''

    @staticmethod
    def _parse_surge_amount(cluster_category):
        """Parse surge amount from category (e.g., 'Rs.4' -> 4.0)"""
        if pd.isna(cluster_category):
            return 0.0

        # Remove 'Rs.' prefix and convert to float
        category_str = str(cluster_category).replace('Rs.', '').replace('₹', '').strip()

        try:
            return float(category_str)
        except (ValueError, AttributeError):
            return 0.0

    def load_from_bigquery(self, year=2026, month=3):
        """Load data from BigQuery"""
        try:
            from google.cloud import bigquery

            # Initialize BigQuery client
            credentials_path = self.project_root / "config" / "credentials.json"
            client = bigquery.Client.from_service_account_json(str(credentials_path))

            # Query cluster data
            cluster_query = """
            SELECT
                id,
                created,
                modified,
                hub_id,
                hub_name,
                cluster_code,
                description,
                boundary,
                is_active,
                cluster_category,
                cluster_type,
                pincode,
                surge_amount
            FROM `bi-team-400508.geocode_geoclusters`
            WHERE is_active = true
            """

            cluster_df = client.query(cluster_query).to_dataframe()

            # Query hub data
            hub_query = f"""
            SELECT
                id,
                name,
                latitude,
                longitude,
                hub_category,
                creation_date
            FROM `bi-team-400508.ecommerce_hub_locations`
            WHERE EXTRACT(YEAR FROM creation_date) <= {year}
            AND EXTRACT(MONTH FROM creation_date) <= {month}
            """

            hub_df = client.query(hub_query).to_dataframe()

            # Clean data
            cluster_df = self._clean_cluster_data(cluster_df)
            hub_df = self._clean_hub_data(hub_df)

            return cluster_df, hub_df

        except Exception as e:
            raise Exception(f"Error loading from BigQuery: {str(e)}")

    def _clean_cluster_data(self, df):
        """Clean and standardize cluster data"""
        # Ensure required columns exist
        required_cols = ['hub_id', 'hub_name', 'cluster_code', 'boundary']
        for col in required_cols:
            if col not in df.columns:
                raise ValueError(f"Missing required column: {col}")

        # Handle surge_amount
        if 'surge_amount' not in df.columns:
            if 'cluster_category' in df.columns:
                df['surge_amount'] = df['cluster_category'].apply(self._parse_surge_amount)
            else:
                df['surge_amount'] = 0

        # Convert surge_amount to numeric
        df['surge_amount'] = pd.to_numeric(df['surge_amount'], errors='coerce').fillna(0)

        # Clean pincode
        if 'pincode' not in df.columns:
            if 'cluster_code' in df.columns:
                df['pincode'] = df['cluster_code'].apply(self._extract_pincode)
            else:
                df['pincode'] = ''

        df['pincode'] = df['pincode'].astype(str).str.strip()

        # Remove duplicates
        df = df.drop_duplicates(subset=['cluster_code'])

        return df

    def _clean_hub_data(self, df):
        """Clean and standardize hub data"""
        # Rename columns if needed
        if 'name' not in df.columns and 'hub_name' in df.columns:
            df = df.rename(columns={'hub_name': 'name'})

        # Ensure numeric coordinates
        df['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
        df['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')

        # Remove rows with missing coordinates
        df = df.dropna(subset=['latitude', 'longitude'])

        return df

    def process_data(self, cluster_df, hub_df):
        """Process and merge cluster and hub data"""
        processed_df = cluster_df.copy()

        # Parse WKT boundaries and extract centroid if not provided
        processed_df['geometry'] = None

        # Use provided centroid if available, otherwise calculate from geometry
        if 'center_lat' not in processed_df.columns or 'center_lon' not in processed_df.columns:
            processed_df['center_lat'] = None
            processed_df['center_lon'] = None
            calculate_centroid = True
        else:
            calculate_centroid = False

        for idx, row in processed_df.iterrows():
            try:
                if pd.notna(row['boundary']) and row['boundary']:
                    # Parse WKT
                    geom = wkt.loads(row['boundary'])
                    processed_df.at[idx, 'geometry'] = geom

                    # Get centroid if not provided
                    if calculate_centroid or pd.isna(row.get('center_lat')):
                        centroid = geom.centroid
                        processed_df.at[idx, 'center_lat'] = centroid.y
                        processed_df.at[idx, 'center_lon'] = centroid.x
            except Exception as e:
                print(f"Warning: Could not parse boundary for cluster {row.get('cluster_code', 'unknown')}: {e}")
                continue

        # Merge with hub data to get hub coordinates if not already present
        if 'hub_lat' not in processed_df.columns or 'hub_lon' not in processed_df.columns:
            hub_lookup = hub_df.set_index('id')[['latitude', 'longitude']].to_dict('index')

            processed_df['hub_lat'] = processed_df['hub_id'].map(
                lambda x: hub_lookup.get(x, {}).get('latitude', None)
            )
            processed_df['hub_lon'] = processed_df['hub_id'].map(
                lambda x: hub_lookup.get(x, {}).get('longitude', None)
            )

        # Create rate category
        processed_df['rate_category'] = processed_df['surge_amount'].apply(self._categorize_rate)

        # Ensure cluster_category exists (for display)
        if 'cluster_category' not in processed_df.columns:
            processed_df['cluster_category'] = processed_df['surge_amount'].apply(
                lambda x: f"Rs.{x:.1f}" if x > 0 else "Rs.0"
            )

        return processed_df

    @staticmethod
    def _categorize_rate(rate):
        """Categorize surge rates"""
        if rate == 0:
            return "₹0 (Base)"
        elif rate <= 3:
            return "₹1-₹3 (Low)"
        elif rate <= 6:
            return "₹4-₹6 (Medium)"
        elif rate <= 10:
            return "₹7-₹10 (High)"
        else:
            return "₹11+ (Very High)"
