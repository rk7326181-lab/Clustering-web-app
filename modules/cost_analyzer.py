"""
Cost Analyzer Module
====================
Analyzes costs, revenue, and generates optimization recommendations.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta


class CostAnalyzer:
    """Analyzes costs and generates optimization suggestions"""

    def __init__(self):
        self.base_shipment_cost = 50  # Base cost per shipment in rupees

    def generate_mock_shipments(self, cluster_df, days=30):
        """
        Generate mock shipment data for demonstration
        In production, this would query actual shipment data from BigQuery
        """
        np.random.seed(42)

        shipments = []

        for _, cluster in cluster_df.iterrows():
            # Generate random shipment count based on cluster characteristics
            # Clusters with higher rates typically have fewer shipments (distant areas)
            surge_amount = cluster.get('surge_amount', 0)

            if surge_amount == 0:
                avg_daily_shipments = np.random.randint(20, 100)
            elif surge_amount <= 3:
                avg_daily_shipments = np.random.randint(10, 50)
            elif surge_amount <= 6:
                avg_daily_shipments = np.random.randint(5, 30)
            else:
                avg_daily_shipments = np.random.randint(1, 15)

            # Generate daily shipments for the period
            total_shipments = int(avg_daily_shipments * days * np.random.uniform(0.8, 1.2))

            if total_shipments > 0:
                shipments.append({
                    'hub_id': cluster['hub_id'],
                    'hub_name': cluster['hub_name'],
                    'cluster_code': cluster['cluster_code'],
                    'surge_amount': surge_amount,
                    'rate_category': cluster.get('rate_category', 'Unknown'),
                    'shipments': total_shipments,
                    'revenue': total_shipments * surge_amount,
                    'cost': total_shipments * self.base_shipment_cost,
                    'pincode': cluster.get('pincode', '')
                })

        return pd.DataFrame(shipments)

    def calculate_metrics(self, cluster_df, shipment_df):
        """Calculate key performance metrics"""
        metrics = {
            'total_revenue': shipment_df['revenue'].sum(),
            'total_shipments': shipment_df['shipments'].sum(),
            'total_cost': shipment_df['cost'].sum(),
            'avg_cluster_rate': cluster_df['surge_amount'].mean(),
            'active_clusters': len(cluster_df[cluster_df['surge_amount'] > 0]),
            'total_clusters': len(cluster_df),
            'unique_hubs': cluster_df['hub_name'].nunique(),
            'unique_pincodes': cluster_df['pincode'].nunique()
        }

        # Calculate profit
        metrics['profit'] = metrics['total_revenue'] - metrics['total_cost']
        metrics['profit_margin'] = (metrics['profit'] / max(metrics['total_cost'], 1)) * 100

        # Revenue per shipment
        metrics['revenue_per_shipment'] = metrics['total_revenue'] / max(metrics['total_shipments'], 1)

        return metrics

    def generate_suggestions(self, cluster_df, shipment_df, max_suggestions=10):
        """
        Generate cost optimization recommendations

        Analyzes:
        1. Low-density high-rate clusters (merge candidates)
        2. High-density zero-rate clusters (rate increase candidates)
        3. Inefficient hub configurations
        """
        suggestions = []

        # Merge shipment data with cluster data
        analysis_df = shipment_df.merge(
            cluster_df[['cluster_code', 'hub_name', 'center_lat', 'center_lon']],
            on='cluster_code',
            how='left',
            suffixes=('', '_cluster')
        )

        # 1. Find low-density high-rate clusters
        low_density_threshold = shipment_df['shipments'].quantile(0.25)

        low_density_high_rate = analysis_df[
            (analysis_df['shipments'] < low_density_threshold) &
            (analysis_df['surge_amount'] > 0)
        ].sort_values('surge_amount', ascending=False)

        for _, cluster in low_density_high_rate.head(5).iterrows():
            potential_saving = cluster['surge_amount'] * cluster['shipments'] * 0.7
            suggestions.append({
                'action': 'Consider merging low-density cluster',
                'clusters': f"{cluster['cluster_code']} (₹{cluster['surge_amount']})",
                'potential_saving': potential_saving,
                'reasoning': f"Low shipment volume ({cluster['shipments']}) with {cluster['surge_amount']} surcharge. Merging with adjacent base-rate cluster could save costs.",
                'priority': 'High' if potential_saving > 10000 else 'Medium'
            })

        # 2. Find high-density zero-rate clusters
        high_density_threshold = shipment_df['shipments'].quantile(0.75)

        high_density_zero_rate = analysis_df[
            (analysis_df['shipments'] > high_density_threshold) &
            (analysis_df['surge_amount'] == 0)
        ].sort_values('shipments', ascending=False)

        for _, cluster in high_density_zero_rate.head(3).iterrows():
            potential_revenue = cluster['shipments'] * 1  # Adding ₹1 surcharge
            suggestions.append({
                'action': 'Consider adding minimal surge rate',
                'clusters': f"{cluster['cluster_code']} ({cluster['shipments']} shipments)",
                'potential_saving': potential_revenue,  # Actually revenue increase
                'reasoning': f"High shipment volume ({cluster['shipments']}) with no surcharge. Market can likely bear ₹1-₹2 rate increase.",
                'priority': 'Medium'
            })

        # 3. Find clusters with inconsistent rates in same pincode
        pincode_analysis = analysis_df.groupby('pincode').agg({
            'surge_amount': ['min', 'max', 'mean'],
            'cluster_code': 'count',
            'shipments': 'sum'
        }).reset_index()

        pincode_analysis.columns = ['pincode', 'min_rate', 'max_rate', 'avg_rate', 'cluster_count', 'total_shipments']

        inconsistent_pincodes = pincode_analysis[
            (pincode_analysis['max_rate'] - pincode_analysis['min_rate'] > 3) &
            (pincode_analysis['cluster_count'] > 1)
        ]

        for _, pincode_data in inconsistent_pincodes.head(2).iterrows():
            potential_saving = pincode_data['total_shipments'] * 0.5  # Estimate
            suggestions.append({
                'action': 'Standardize rates within pincode',
                'clusters': f"Pincode {pincode_data['pincode']} ({int(pincode_data['cluster_count'])} clusters)",
                'potential_saving': potential_saving,
                'reasoning': f"Rate variance of ₹{pincode_data['max_rate'] - pincode_data['min_rate']:.0f} within same pincode. Standardizing could improve customer satisfaction and reduce confusion.",
                'priority': 'Low'
            })

        # 4. Hub-level efficiency analysis
        hub_performance = analysis_df.groupby('hub_name').agg({
            'shipments': 'sum',
            'revenue': 'sum',
            'surge_amount': 'mean',
            'cluster_code': 'count'
        }).reset_index()

        hub_performance['revenue_per_shipment'] = hub_performance['revenue'] / hub_performance['shipments']
        hub_performance['clusters_per_shipment'] = hub_performance['cluster_code'] / hub_performance['shipments']

        # Find hubs with too many clusters relative to shipment volume
        inefficient_hubs = hub_performance[
            hub_performance['clusters_per_shipment'] > hub_performance['clusters_per_shipment'].quantile(0.8)
        ].sort_values('clusters_per_shipment', ascending=False)

        for _, hub in inefficient_hubs.head(2).iterrows():
            potential_saving = hub['clusters_per_shipment'] * 1000  # Estimate based on cluster overhead
            suggestions.append({
                'action': 'Consolidate clusters in underutilized hub',
                'clusters': f"{hub['hub_name']} ({int(hub['cluster_code'])} clusters, {int(hub['shipments'])} shipments)",
                'potential_saving': potential_saving,
                'reasoning': f"Hub has {hub['cluster_code']:.0f} clusters but only {hub['shipments']:.0f} shipments. Consider consolidating to reduce operational complexity.",
                'priority': 'Medium'
            })

        # Sort by potential saving
        suggestions = sorted(suggestions, key=lambda x: x['potential_saving'], reverse=True)

        return suggestions[:max_suggestions]

    def compare_hubs(self, hub_a_data, hub_b_data, shipment_a, shipment_b):
        """Compare performance between two hubs"""
        metrics_a = self.calculate_metrics(hub_a_data, shipment_a)
        metrics_b = self.calculate_metrics(hub_b_data, shipment_b)

        comparison = {
            'hub_a': metrics_a,
            'hub_b': metrics_b,
            'differences': {}
        }

        # Calculate differences
        for key in metrics_a:
            if isinstance(metrics_a[key], (int, float)) and isinstance(metrics_b[key], (int, float)):
                if metrics_b[key] != 0:
                    pct_diff = ((metrics_a[key] - metrics_b[key]) / metrics_b[key]) * 100
                    comparison['differences'][key] = {
                        'absolute': metrics_a[key] - metrics_b[key],
                        'percentage': pct_diff
                    }

        return comparison
