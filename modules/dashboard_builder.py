"""
CEO Dashboard — Pivot Table, Comparison, Styling, Insights.
"""
import pandas as pd
import numpy as np


def build_pivot_report(final_result_df):
    df = final_result_df.copy()
    for c in ["Pin_Pay", "Clustering_payout", "Saving", "Burning", "P & L"]:
        if c in df.columns: df[c] = pd.to_numeric(df[c], errors="coerce")
    pivot = df.pivot_table(index=["hub", "pincode"],
                           values=["Pin_Pay", "Clustering_payout", "Saving", "Burning", "P & L"],
                           aggfunc="sum").reset_index()
    report = pivot.rename(columns={"Pin_Pay": "Expt_Pincode_Pay", "Clustering_payout": "Cluster_Payout"})
    nc = ["Expt_Pincode_Pay", "Cluster_Payout", "Saving", "Burning", "P & L"]
    for c in nc:
        if c in report.columns: report[c] = pd.to_numeric(report[c], errors="coerce").fillna(0)
    report["P & L %"] = np.where(report["Expt_Pincode_Pay"] == 0, 0,
                                  (report["P & L"] / report["Expt_Pincode_Pay"]) * 100).round(2)
    hub_tot = report.groupby("hub")[nc].sum().reset_index()
    hub_tot["pincode"] = "Hub Total"
    hub_tot["P & L %"] = np.where(hub_tot["Expt_Pincode_Pay"] == 0, 0,
                                   (hub_tot["P & L"] / hub_tot["Expt_Pincode_Pay"]) * 100).round(2)
    grand = pd.DataFrame(report[nc].sum()).T
    grand["hub"] = "Grand Total"; grand["pincode"] = ""
    grand["P & L %"] = np.where(grand["Expt_Pincode_Pay"] == 0, 0,
                                 (grand["P & L"] / grand["Expt_Pincode_Pay"]) * 100).round(2)
    final = pd.concat([report, hub_tot, grand], ignore_index=True).sort_values(["hub", "pincode"])
    cols = ["hub", "pincode"] + nc + ["P & L %"]
    return final[[c for c in cols if c in final.columns]].reset_index(drop=True)


def build_comparison_table(report_df):
    """Side-by-side P-Mapping vs Cluster comparison."""
    data = report_df[(report_df["pincode"] != "Hub Total") & (report_df["hub"] != "Grand Total")].copy()
    if data.empty: return pd.DataFrame()
    comp = data[["hub", "pincode", "Expt_Pincode_Pay", "Cluster_Payout"]].copy()
    comp["Difference"] = comp["Expt_Pincode_Pay"] - comp["Cluster_Payout"]
    comp["Winner"] = comp["Difference"].apply(
        lambda x: "Cluster Cheaper" if x > 0 else ("P-Map Cheaper" if x < 0 else "Equal"))
    comp["Saving_Amount"] = comp["Difference"].abs()
    return comp


def style_report_html(report_df):
    rows = ['<table style="border-collapse:collapse;width:100%;font-family:sans-serif;font-size:13px;">']
    rows.append('<thead><tr style="background:#0B8A7A;color:white;">')
    for c in report_df.columns:
        rows.append(f'<th style="padding:10px 12px;text-align:center;border:1px solid #ddd;">{c}</th>')
    rows.append('</tr></thead><tbody>')
    for _, row in report_df.iterrows():
        is_ht = str(row.get("pincode", "")) == "Hub Total"
        is_gt = str(row.get("hub", "")) == "Grand Total"
        bg = "#E8F4FD" if is_ht else ("#D4EDDA" if is_gt else "white")
        fw = "bold" if is_ht or is_gt else "normal"
        rows.append(f'<tr style="background:{bg};font-weight:{fw};">')
        for c in report_df.columns:
            v = row[c]; s = "padding:8px 10px;text-align:center;border:1px solid #eee;"
            if c in ["P & L", "P & L %"] and isinstance(v, (int, float)):
                s += " color:green;" if v > 0 else (" color:red;" if v < 0 else "")
            d = f"{v:.2f}%" if c == "P & L %" and isinstance(v, float) else (f"{v:,.0f}" if isinstance(v, float) else str(v))
            rows.append(f'<td style="{s}">{d}</td>')
        rows.append('</tr>')
    rows.append('</tbody></table>')
    return "\n".join(rows)


def compute_insights(report_df):
    ins = {}
    hub_data = report_df[report_df["pincode"] == "Hub Total"].copy()
    if len(hub_data) > 0:
        best = hub_data.loc[hub_data["P & L"].idxmax()]
        worst = hub_data.loc[hub_data["P & L"].idxmin()]
        ins["best_hub"], ins["best_hub_pl"] = best["hub"], best["P & L"]
        ins["worst_hub"], ins["worst_hub_pl"] = worst["hub"], worst["P & L"]
    grand = report_df[report_df["hub"] == "Grand Total"]
    if len(grand) > 0:
        g = grand.iloc[0]
        for k in ["Expt_Pincode_Pay", "Cluster_Payout", "Saving", "Burning", "P & L", "P & L %"]:
            ins["total_" + k.lower().replace(" & ", "_").replace(" ", "_").replace("%", "pct")] = g.get(k, 0)
    return ins
