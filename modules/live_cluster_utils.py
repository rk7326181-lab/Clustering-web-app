"""
Utility Functions
=================
Helper functions for formatting, calculations, and common operations.
"""

import pandas as pd
import numpy as np
from datetime import datetime


def format_currency(amount, currency_symbol='₹'):
    """Format number as currency with Indian numbering system"""
    if pd.isna(amount) or amount is None:
        return f"{currency_symbol}0"

    # Convert to float
    amount = float(amount)

    # Format with commas
    if amount >= 10000000:  # 1 crore
        return f"{currency_symbol}{amount/10000000:.2f}Cr"
    elif amount >= 100000:  # 1 lakh
        return f"{currency_symbol}{amount/100000:.2f}L"
    elif amount >= 1000:  # 1 thousand
        return f"{currency_symbol}{amount/1000:.1f}K"
    else:
        return f"{currency_symbol}{amount:.0f}"


def format_number(number):
    """Format large numbers with K, L, Cr suffixes"""
    if pd.isna(number) or number is None:
        return "0"

    number = float(number)

    if number >= 10000000:  # 1 crore
        return f"{number/10000000:.2f}Cr"
    elif number >= 100000:  # 1 lakh
        return f"{number/100000:.2f}L"
    elif number >= 1000:  # 1 thousand
        return f"{number/1000:.1f}K"
    else:
        return f"{number:.0f}"


def format_percentage(value, decimals=1):
    """Format number as percentage"""
    if pd.isna(value) or value is None:
        return "0.0%"
    return f"{float(value):.{decimals}f}%"


def calculate_distance_km(lat1, lon1, lat2, lon2):
    """
    Calculate distance between two points using Haversine formula
    Returns distance in kilometers
    """
    from math import radians, sin, cos, sqrt, atan2

    # Earth's radius in kilometers
    R = 6371.0

    # Convert to radians
    lat1_rad = radians(lat1)
    lon1_rad = radians(lon1)
    lat2_rad = radians(lat2)
    lon2_rad = radians(lon2)

    # Differences
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad

    # Haversine formula
    a = sin(dlat/2)**2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))

    distance = R * c
    return distance


def get_color_for_rate(rate):
    """Get color hex code for surge rate"""
    colors = {
        0: '#9CA3AF',   # Gray
        1: '#BFDBFE',   # Light blue
        2: '#93C5FD',
        3: '#60A5FA',
        4: '#3B82F6',   # Blue
        5: '#2563EB',
        6: '#1D4ED8',
        7: '#FCD34D',   # Yellow
        8: '#FBBF24',
        9: '#F59E0B',
        10: '#F97316',  # Orange
        11: '#EF4444',  # Red
        12: '#DC2626',
        13: '#B91C1C',
        14: '#991B1B'   # Dark red
    }
    return colors.get(int(rate), '#9CA3AF')


def safe_divide(numerator, denominator, default=0):
    """Safely divide two numbers, returning default if denominator is 0"""
    try:
        if denominator == 0:
            return default
        return numerator / denominator
    except (TypeError, ZeroDivisionError):
        return default


def get_date_range(days_back=30):
    """Get date range for the last N days"""
    end_date = datetime.now()
    start_date = end_date - pd.Timedelta(days=days_back)
    return start_date, end_date


def validate_coordinates(lat, lon):
    """Validate latitude and longitude values"""
    try:
        lat = float(lat)
        lon = float(lon)

        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return True, lat, lon
        else:
            return False, None, None
    except (TypeError, ValueError):
        return False, None, None


def aggregate_by_hub(df):
    """Aggregate cluster data by hub"""
    if df is None or len(df) == 0:
        return pd.DataFrame()

    hub_summary = df.groupby('hub_name').agg({
        'cluster_code': 'count',
        'surge_amount': ['mean', 'min', 'max'],
        'pincode': 'nunique'
    }).reset_index()

    hub_summary.columns = [
        'hub_name',
        'cluster_count',
        'avg_rate',
        'min_rate',
        'max_rate',
        'unique_pincodes'
    ]

    return hub_summary


def filter_dataframe(df, filters):
    """
    Apply multiple filters to a dataframe

    filters: dict with keys matching column names
    """
    filtered_df = df.copy()

    for column, value in filters.items():
        if value and value != 'All':
            if isinstance(value, list):
                filtered_df = filtered_df[filtered_df[column].isin(value)]
            else:
                filtered_df = filtered_df[filtered_df[column] == value]

    return filtered_df


def export_to_csv(df, filename):
    """Export dataframe to CSV"""
    try:
        csv = df.to_csv(index=False)
        return csv
    except Exception as e:
        print(f"Error exporting to CSV: {e}")
        return None


def create_summary_stats(df):
    """Create summary statistics for a dataframe"""
    if df is None or len(df) == 0:
        return {}

    stats = {
        'total_rows': len(df),
        'columns': list(df.columns),
        'memory_usage': f"{df.memory_usage(deep=True).sum() / 1024:.2f} KB"
    }

    # Numeric columns
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    for col in numeric_cols:
        stats[f'{col}_mean'] = df[col].mean()
        stats[f'{col}_median'] = df[col].median()
        stats[f'{col}_std'] = df[col].std()

    return stats
