"""
Clustering and P Mapping — Shadowfax Geo Intelligence Portal
Real BigQuery only. No demo mode.
"""
import streamlit as st
import pandas as pd
import numpy as np
import os, json, math, time, gc
from io import BytesIO
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

st.set_page_config(page_title="Geo Intelligence Portal — Shadowfax", page_icon="🗺️", layout="wide", initial_sidebar_state="expanded")

# ═══════════════════════════════════════════════════════
# HANDLE OAUTH CALLBACK — Must run BEFORE access control
# so the auth code from Google redirect is processed
# ═══════════════════════════════════════════════════════
_oauth_code = st.query_params.get("code")
if _oauth_code and st.session_state.get("bq_client") is None:
    try:
        from modules.bigquery_client import handle_oauth_callback
        _client, _err = handle_oauth_callback(_oauth_code)
        if _client:
            st.session_state["bq_client"] = _client
            st.session_state["bq_auth_mode"] = "google_oauth"
            st.session_state["authenticated"] = True  # Auto-authenticate on OAuth success
            st.query_params.clear()
            st.rerun()
        else:
            st.query_params.clear()
            st.session_state["_oauth_error"] = _err
    except Exception:
        st.query_params.clear()

# ═══════════════════════════════════════════════════════
# ACCESS CONTROL — Only allowed users can use the app
# ═══════════════════════════════════════════════════════
def _check_access():
    """Gate the app behind email + password authentication."""
    if st.session_state.get("authenticated"):
        return True

    # Read allowed users from secrets
    try:
        allowed_emails = list(st.secrets.get("allowed_emails", []))
        app_password = st.secrets.get("app_password", "")
    except Exception:
        allowed_emails = []
        app_password = os.environ.get("APP_PASSWORD", "")

    # If no access control is configured, allow everyone (local dev)
    if not allowed_emails and not app_password:
        st.session_state["authenticated"] = True
        return True

    st.markdown("""
    <style>
    .login-box{max-width:420px;margin:80px auto;padding:40px;border-radius:16px;
    background:linear-gradient(135deg,#0B2B26 0%,#143D36 100%);
    box-shadow:0 20px 60px rgba(0,0,0,0.3);text-align:center}
    .login-box h2{color:#4AEDC4;font-size:1.6rem;margin-bottom:4px}
    .login-box p{color:#8FBCB0;font-size:0.9rem}
    </style>
    <div class="login-box">
        <h2>🗺️ Geo Intelligence Portal</h2>
        <p>Authorized access only</p>
    </div>
    """, unsafe_allow_html=True)

    with st.form("login_form"):
        email = st.text_input("Email", placeholder="your.name@company.com")
        password = st.text_input("Password", type="password", placeholder="Enter app password")
        submitted = st.form_submit_button("Sign In", type="primary", use_container_width=True)

    if submitted:
        email_ok = (not allowed_emails) or (email.strip().lower() in [e.lower() for e in allowed_emails])
        pass_ok = (not app_password) or (password == app_password)

        if email_ok and pass_ok:
            st.session_state["authenticated"] = True
            st.session_state["user_email"] = email.strip()
            st.rerun()
        else:
            if not email_ok:
                st.error("This email is not authorized. Contact your admin.")
            elif not pass_ok:
                st.error("Incorrect password.")

    return False


if not _check_access():
    st.stop()

# ═══════════════════════════════════════════════════════
# CSS — Matching React Geo Intelligence Portal Design
# ═══════════════════════════════════════════════════════
st.markdown('<link href="https://fonts.googleapis.com/css2?family=Work+Sans:wght@400;500;600;700;800&amp;family=IBM+Plex+Sans:wght@300;400;500;600&amp;family=IBM+Plex+Mono:wght@400;500&amp;display=swap" rel="stylesheet">', unsafe_allow_html=True)
st.markdown("""<style>
/* ══════════════════════════════════════════
   SHADOWFAX GEO INTELLIGENCE PORTAL — V3
   Dual-theme adaptive design. Uses Streamlit
   CSS variables so light + dark modes both work.
   Toggle via Settings ▸ Theme in the ☰ menu.
   ══════════════════════════════════════════ */

/* ── Theme-Adaptive Custom Properties ── */
:root{
  --sfx:var(--primary-color,#0B8A7A);
  --sfx-hover:#097A6C;
  --sfx-soft:color-mix(in srgb,var(--primary-color,#0B8A7A) 12%,var(--background-color,#F8F9FA));
  --sfx-border:color-mix(in srgb,var(--text-color,#1A1A2E) 13%,var(--background-color,#FFFFFF));
  --sfx-border-strong:color-mix(in srgb,var(--text-color,#1A1A2E) 22%,var(--background-color,#FFFFFF));
  --sfx-muted:color-mix(in srgb,var(--text-color,#1A1A2E) 48%,var(--background-color,#FFFFFF));
  --sfx-surface:var(--background-color,#FFFFFF);
  --sfx-surface2:var(--secondary-background-color,#F1F5F9);
  --sfx-text:var(--text-color,#1A1A2E);
}

/* ── Base ── */
.main .block-container{padding-top:1rem;max-width:1600px}
.stApp{font-family:'IBM Plex Sans',sans-serif}
header[data-testid="stHeader"]{border-bottom:1px solid var(--sfx-border)}

/* ── Sidebar ── */
section[data-testid="stSidebar"]{width:280px!important}
section[data-testid="stSidebar"] .stMarkdown p,
section[data-testid="stSidebar"] label{font-family:'IBM Plex Sans',sans-serif;font-size:13px}
section[data-testid="stSidebar"] .stMarkdown h1,
section[data-testid="stSidebar"] .stMarkdown h2,
section[data-testid="stSidebar"] .stMarkdown h3{font-family:'Work Sans',sans-serif}
section[data-testid="stSidebar"] hr{border-color:var(--sfx-border)!important;margin:10px 0!important}
section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p{color:var(--sfx)!important;font-weight:600;font-size:11px;letter-spacing:0.5px;text-transform:uppercase}
section[data-testid="stSidebar"] .stRadio label{font-size:13.5px;font-weight:500;padding:5px 0;line-height:1.5}
section[data-testid="stSidebar"] .stRadio [data-baseweb="radio"] span{color:var(--sfx)!important}
section[data-testid="stSidebar"] .stRadio [role="radiogroup"]{gap:2px}
section[data-testid="stSidebar"] .stTextInput input{background:var(--sfx-surface2);border:1px solid var(--sfx-border);border-radius:6px}
section[data-testid="stSidebar"] .stButton>button{background:var(--sfx-surface2);border:1px solid var(--sfx-border);font-weight:500}
section[data-testid="stSidebar"] .stButton>button:hover{background:var(--sfx-soft);border-color:var(--sfx);color:var(--sfx)}

/* ── Sidebar Brand ── */
.sfx-brand{display:flex;align-items:center;gap:12px;padding:14px 8px 10px}
.sfx-brand img{height:48px;flex-shrink:0;border-radius:4px}
.sfx-brand-text{font-size:15px;font-weight:700;color:var(--sfx-text);font-family:'Work Sans',sans-serif;letter-spacing:-0.2px;line-height:1.3}
.sfx-brand-sub{font-size:10px;color:var(--sfx-muted);font-weight:500;letter-spacing:0.8px;text-transform:uppercase;margin-top:2px}

/* ── Sidebar Badges ── */
.sfx-badge{padding:6px 12px;border-radius:6px;font-size:11px;font-weight:600;text-align:center;display:flex;align-items:center;justify-content:center;gap:6px}
.sfx-badge .dot{width:8px;height:8px;border-radius:50%;display:inline-block}
.sfx-badge--ok{background:var(--sfx-soft);color:var(--sfx);border:1px solid var(--sfx)}
.sfx-badge--ok .dot{background:var(--sfx)}
.sfx-badge--warn{background:color-mix(in srgb,#F59E0B 12%,var(--sfx-surface));color:#D97706;border:1px solid #F59E0B}
.sfx-badge--warn .dot{background:#F59E0B}

/* ── Sidebar Labels / Status ── */
.sfx-label{font-size:11px;color:var(--sfx);font-weight:700;letter-spacing:1.2px;margin:8px 0 4px}
.sfx-status{display:flex;align-items:center;gap:8px;padding:2px 0}
.sfx-status .icon{font-size:12px;font-weight:700}
.sfx-status .lbl{font-size:12px;font-family:'IBM Plex Sans',sans-serif}
.sfx-status--done .icon{color:var(--sfx)}
.sfx-status--done .lbl{color:var(--sfx-text)}
.sfx-status--pending .icon{color:var(--sfx-border-strong)}
.sfx-status--pending .lbl{color:var(--sfx-muted)}
.sfx-footer{text-align:center;font-size:10px;color:var(--sfx-muted);padding:8px 0 12px;font-family:'IBM Plex Sans',sans-serif}

/* ── Sidebar Chat ── */
.sfx-chat-user{background:var(--sfx);color:#FFF;padding:6px 10px;border-radius:8px;margin:4px 0;font-size:12px;text-align:right}
.sfx-chat-bot{background:var(--sfx-surface2);color:var(--sfx-text);padding:6px 10px;border-radius:8px;margin:4px 0;font-size:12px;border:1px solid var(--sfx-border)}

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"]{gap:2px;border-bottom:2px solid var(--sfx-border);border-radius:8px 8px 0 0;padding:0 4px}
.stTabs [data-baseweb="tab"]{padding:10px 22px;font-weight:600;font-size:13px;color:var(--sfx-muted);border-radius:6px 6px 0 0;border:none;font-family:'Work Sans',sans-serif;letter-spacing:0.02em}
.stTabs [aria-selected="true"]{background:var(--sfx-soft)!important;color:var(--sfx)!important;border-bottom:3px solid var(--sfx)!important;font-weight:700}
.stTabs [data-baseweb="tab"]:hover{color:var(--sfx)!important}

/* ── Buttons ── */
.stButton>button{border:1.5px solid var(--sfx);color:var(--sfx);background:var(--sfx-surface);font-weight:600;border-radius:8px;font-family:'IBM Plex Sans',sans-serif;font-size:13px;padding:8px 20px;transition:background .15s ease,color .15s ease,box-shadow .15s ease}
.stButton>button:hover{background:var(--sfx);color:#FFF;box-shadow:0 2px 8px rgba(11,138,122,.2)}
button[kind="primary"]{background:var(--sfx)!important;color:#FFF!important;border:none!important;font-weight:700!important;border-radius:8px!important}
button[kind="primary"]:hover{background:var(--sfx-hover)!important;box-shadow:0 3px 12px rgba(11,138,122,.3)!important}
.stDownloadButton>button{border:1.5px solid var(--sfx);color:var(--sfx);background:var(--sfx-surface);font-weight:600;border-radius:6px;font-size:12px}
.stDownloadButton>button:hover{background:var(--sfx);color:#FFF}

/* ── Metrics ── */
div[data-testid="stMetricValue"]{font-size:1.5rem;font-weight:700;font-family:'Work Sans',sans-serif}
div[data-testid="stMetricLabel"]{font-size:12px;color:var(--sfx-muted);font-weight:600;text-transform:uppercase;letter-spacing:.05em}

/* ── Data Tables ── */
.stDataFrame{border:1px solid var(--sfx-border);border-radius:8px;overflow:hidden}
[data-testid="stDataFrameResizable"]{border-radius:8px}
[data-testid="stDataFrame"] [data-testid="glideDataEditor"]{--gdg-bg-header:var(--sfx-surface2);--gdg-bg-header-has-focus:var(--sfx-border);--gdg-text-header:var(--sfx-text);--gdg-bg-cell:var(--sfx-surface);--gdg-text-dark:var(--sfx-text);--gdg-text-medium:var(--sfx-muted);--gdg-border-color:var(--sfx-border);--gdg-bg-header-hovered:var(--sfx-border);--gdg-accent-color:var(--sfx);--gdg-accent-light:var(--sfx-soft);--gdg-link-color:var(--sfx)}
[data-testid="stDataEditor"] [data-testid="glideDataEditor"]{--gdg-bg-header:var(--sfx-surface2);--gdg-bg-header-has-focus:var(--sfx-border);--gdg-text-header:var(--sfx-text);--gdg-bg-cell:var(--sfx-surface);--gdg-text-dark:var(--sfx-text);--gdg-border-color:var(--sfx-border);--gdg-accent-color:var(--sfx)}

/* ── Custom Classes ── */
.sfx-header{background:var(--sfx);color:#FFF;padding:14px 24px;border-radius:10px;font-family:'Work Sans',sans-serif;font-size:17px;font-weight:700;margin:16px 0 10px;letter-spacing:-0.3px}
.sfx-card{background:var(--sfx-surface);border:1px solid var(--sfx-border);border-radius:12px;padding:20px;margin:8px 0;box-shadow:0 1px 3px rgba(0,0,0,.04);color:var(--sfx-text)}
.sfx-ok{background:var(--sfx-soft);border-left:4px solid var(--sfx);padding:10px 16px;border-radius:0 8px 8px 0;margin:6px 0;color:var(--sfx-text);font-size:14px}
.sfx-warn{background:color-mix(in srgb,#F59E0B 10%,var(--sfx-surface));border-left:4px solid #F59E0B;padding:10px 16px;border-radius:0 8px 8px 0;margin:6px 0;color:var(--sfx-text)}
.sfx-err{background:color-mix(in srgb,#EF4444 10%,var(--sfx-surface));border-left:4px solid #EF4444;padding:10px 16px;border-radius:0 8px 8px 0;margin:6px 0;color:var(--sfx-text)}
.sfx-section-header{font-family:'Work Sans',sans-serif;font-size:15px;font-weight:700;color:var(--sfx-text);margin:16px 0 8px;padding-bottom:6px;border-bottom:2px solid var(--sfx-border)}

/* ── Step Pills ── */
.step-pills{display:flex;gap:8px;padding:10px 0;flex-wrap:wrap}
.step-pill{display:inline-flex;align-items:center;gap:6px;padding:7px 16px;border-radius:20px;font-size:12px;font-weight:600;font-family:'Work Sans',sans-serif;letter-spacing:.02em}
.step-pill.idle{background:var(--sfx-surface);color:var(--sfx-muted);border:1px solid var(--sfx-border)}
.step-pill.complete{background:var(--sfx-soft);color:var(--sfx);border:1px solid var(--sfx)}
.step-pill.active{background:var(--sfx);color:#FFF;border:1px solid var(--sfx)}

/* ── KPI Cards ── */
.kpi-row{display:flex;gap:14px;margin:12px 0 24px;flex-wrap:wrap}
.kpi-card{flex:1;min-width:150px;background:var(--sfx-surface);border:1px solid var(--sfx-border);border-radius:12px;padding:20px 24px;text-align:center;position:relative;overflow:hidden}
.kpi-card::before{content:"";position:absolute;top:0;left:0;right:0;height:3px}
.kpi-card .kpi-label{font-size:11px;color:var(--sfx-muted);font-weight:600;text-transform:uppercase;letter-spacing:.8px;margin-bottom:6px}
.kpi-card .kpi-value{font-size:26px;color:var(--sfx-text);font-weight:800;font-family:'Work Sans',sans-serif;letter-spacing:-0.5px;line-height:1}
.kpi-card.green .kpi-value{color:var(--sfx)}
.kpi-card.green::before{background:var(--sfx)}
.kpi-card.red .kpi-value{color:#EF4444}
.kpi-card.red::before{background:#EF4444}
.kpi-card.blue .kpi-value{color:#3B82F6}
.kpi-card.blue::before{background:#3B82F6}
.kpi-card.purple .kpi-value{color:#7C3AED}
.kpi-card.purple::before{background:#7C3AED}
.kpi-card.orange .kpi-value{color:#F97316}
.kpi-card.orange::before{background:#F97316}

/* ── Chat Bubbles (main content) ── */
.chat-user{background:var(--sfx);color:#FFF;padding:10px 16px;border-radius:12px 12px 4px 12px;margin:6px 0;text-align:right;font-size:14px;max-width:80%;margin-left:auto}
.chat-assistant{background:var(--sfx-surface);border:1px solid var(--sfx-border);color:var(--sfx-text);padding:10px 16px;border-radius:12px 12px 12px 4px;margin:6px 0;font-size:14px;max-width:85%;line-height:1.6}

/* ── Log Entries ── */
.log-entry{display:flex;align-items:flex-start;gap:8px;padding:6px 10px;font-size:12px;font-family:'IBM Plex Mono',monospace;border-bottom:1px solid var(--sfx-border)}
.log-dot{width:8px;height:8px;border-radius:50%;margin-top:4px;flex-shrink:0}
.log-info .log-dot{background:var(--sfx-muted)}
.log-success .log-dot{background:var(--sfx)}
.log-warning .log-dot{background:#F59E0B}
.log-error .log-dot{background:#EF4444}
.log-time{color:var(--sfx-muted);font-size:11px;flex-shrink:0}

/* ── Scrollbar ── */
::-webkit-scrollbar{width:6px}
::-webkit-scrollbar-track{background:var(--sfx-surface)}
::-webkit-scrollbar-thumb{background:var(--sfx-border-strong);border-radius:3px}

/* ── Expanders ── */
[data-testid="stExpander"]{border:1px solid var(--sfx-border);border-radius:10px}
[data-testid="stExpanderToggle"] p{font-weight:600;font-size:14px}

/* ── File Uploaders ── */
[data-testid="stFileUploader"]{border:2px dashed var(--sfx-border-strong);border-radius:10px}
[data-testid="stFileUploader"]:hover{border-color:var(--sfx)}

/* ── Selectbox / Inputs ── */
.stSelectbox [data-baseweb="select"]>div{border-radius:8px}
.stSelectbox [data-baseweb="select"]>div:hover{border-color:var(--sfx)}
.stMultiSelect [data-baseweb="select"]>div{border-radius:8px}
.stMultiSelect [data-baseweb="tag"]{background:var(--sfx-soft);color:var(--sfx);border-radius:4px}
.stTextInput input{border-radius:8px}
.stTextInput input:focus{border-color:var(--sfx);box-shadow:0 0 0 1px var(--sfx)}
.stNumberInput input{border-radius:8px;font-weight:600;font-size:15px}
.stNumberInput input:focus{border-color:var(--sfx);box-shadow:0 0 0 1px var(--sfx)}

/* ── Sidebar Button Override ── */
section[data-testid="stSidebar"] button[kind="primary"]{background:var(--sfx)!important;color:#FFF!important;border-radius:8px!important;font-size:12px!important}

/* ── Alerts / Progress / Spinner ── */
[data-testid="stAlert"]{border-radius:8px;font-size:13px}
.stProgress>div>div{background:var(--sfx)!important;border-radius:4px}
</style>""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════
# Session State + BQ Auto-connect
# ═══════════════════════════════════════════════════════
from utils import (init_session_state, reload_from_disk, ensure_output_dirs,
                   clean_pincode, get_download_bytes, show_df_download,
                   detect_latlon_cols, detect_geojson_pincode_field,
                   haversine_km, get_pricing, get_hub_color_map,
                   save_file_path, load_file_paths_config, _filter_geojson_to_cluster,
                   CLUSTER_MAP, DESCRIPTION_MAPPING, HUB_COLORS, PRICING_SLABS,
                   PCAT_SOP, RATE_TO_PCAT, rate_to_pcat,
                   OUTPUT_DIR, HUB_IMG_DIR, DATA_DIR)

init_session_state()
ensure_output_dirs()

def kpi_row(cards):
    """cards: list of (label, value, color_class) tuples. color_class: blue|green|red|purple|orange"""
    html = '<div class="kpi-row">'
    for label, value, color in cards:
        html += f'<div class="kpi-card {color}"><div class="kpi-label">{label}</div><div class="kpi-value">{value}</div></div>'
    html += '</div>'
    st.markdown(html, unsafe_allow_html=True)
loaded = reload_from_disk()

# Log system
if "app_logs" not in st.session_state:
    st.session_state["app_logs"] = []

def add_log(msg, level="info"):
    logs = st.session_state["app_logs"]
    logs.append({"msg": msg, "level": level, "time": datetime.now().strftime("%H:%M:%S")})
    if len(logs) > 200:  # Prevent unbounded memory growth
        st.session_state["app_logs"] = logs[-100:]

def render_step_guard(missing, hint):
    """Friendly guard for steps opened before their input data exists: list what's
    missing, offer a jump to Step 1, and stop rendering the rest of the page."""
    items = "".join(f"<li>{m}</li>" for m in missing)
    st.markdown(
        f'<div class="sfx-warn"><b>This step needs data that is not loaded yet:</b>'
        f'<ul>{items}</ul>{hint}</div>', unsafe_allow_html=True)
    st.button("Go to Step 1 — Data Ingestion", key="_guard_goto1",
              on_click=lambda: st.session_state.update(nav="1. Data Ingestion"))
    st.stop()

def _regenerate_hub_image(hub_name, poly_df, cluster_df, hub_col):
    """Render and save a PNG for a single hub using its current polygons. Returns the saved path or None."""
    try:
        import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
        from shapely.wkt import loads as wkt_loads
        import geopandas as gpd
        import contextily as ctx
        ensure_output_dirs()
        hps = poly_df[poly_df[hub_col] == hub_name]
        if hps.empty:
            return None
        cdf2 = cluster_df.copy(); cdf2.columns = cdf2.columns.str.strip()
        hi2 = cdf2[cdf2["Hub_Name"] == hub_name]
        if hi2.empty:
            return None
        hlat, hlon = float(hi2.iloc[0]["Hub_lat"]), float(hi2.iloc[0]["Hub_long"])
        hcm = get_hub_color_map([hub_name])
        fig, ax = plt.subplots(figsize=(14, 10))
        polys_for_gdf, poly_labels = [], []
        for _, row in hps.iterrows():
            wkt = row.get("Polygon WKT", "")
            if pd.isna(wkt) or not wkt:
                continue
            try:
                polys_for_gdf.append(wkt_loads(wkt))
                poly_labels.append(str(row.get("Description", "")))
            except Exception:
                pass
        if polys_for_gdf:
            gdf = gpd.GeoDataFrame({"label": poly_labels}, geometry=polys_for_gdf, crs="EPSG:4326").to_crs(epsg=3857)
            gdf.plot(ax=ax, alpha=0.25, color=hcm.get(hub_name, "#3498db"), edgecolor="black", linewidth=1.5, zorder=2)
            for _, rp in gdf.iterrows():
                rep_pt = rp.geometry.representative_point()
                cx, cy = rep_pt.x, rep_pt.y
                ax.text(cx, cy, rp["label"], ha="center", va="center", fontsize=9, fontweight="bold",
                        bbox=dict(facecolor="white", edgecolor="none", alpha=0.85, boxstyle="round,pad=0.3"), zorder=6)
            hub_gdf = gpd.GeoDataFrame(geometry=[gpd.points_from_xy([hlon], [hlat])[0]], crs="EPSG:4326").to_crs(epsg=3857)
            ax.plot(hub_gdf.geometry.iloc[0].x, hub_gdf.geometry.iloc[0].y, "r^", markersize=14, zorder=5)
            try:
                ctx.add_basemap(ax, source=ctx.providers.OpenStreetMap.Mapnik, zoom='auto')
            except Exception:
                try:
                    ctx.add_basemap(ax, source=ctx.providers.CartoDB.Positron, zoom='auto')
                except Exception:
                    pass
        else:
            ax.plot(hlon, hlat, "r^", markersize=14, zorder=5)
        ax.set_title(hub_name, fontsize=14, fontweight="bold", color="#0B8A7A")
        ax.set_axis_off()
        path = os.path.join(HUB_IMG_DIR, f"{hub_name.replace(' ', '_').replace('/', '_')}_Full_View.png")
        plt.savefig(path, dpi=200, bbox_inches="tight", facecolor="white", pad_inches=0.1)
        plt.close(fig)
        plt.close("all")
        gc.collect()
        st.session_state.setdefault("hub_images", {})[hub_name] = path
        add_log(f"Regenerated image for {hub_name}", "success")
        return path
    except Exception as e:
        add_log(f"Image regen failed for {hub_name}: {e}", "error")
        return None

# Auto-detect BigQuery on startup
from modules.bigquery_client import init_bq_on_startup
init_bq_on_startup()

# (OAuth callback handled at top of file, before access control)

if loaded:
    for f in loaded:
        add_log(f"Auto-loaded: {f}", "success")

# ═══════════════════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════════════════
# Load Shadowfax logo
import base64

@st.cache_data(show_spinner=False)
def _load_logo():
    logo_path = os.path.join(os.path.dirname(__file__), "shadowfax_logo.jpeg")
    if os.path.exists(logo_path):
        with open(logo_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        return f"data:image/jpeg;base64,{b64}"
    return "https://www.shadowfax.in/wp-content/uploads/2023/10/Logo-1.svg"

_logo_src = _load_logo()

st.sidebar.markdown(f"""<div class="sfx-brand">
<img src="{_logo_src}">
<div>
<div class="sfx-brand-text">Geo Intelligence Portal</div>
<div class="sfx-brand-sub">Shadowfax Technologies</div>
</div>
</div>""", unsafe_allow_html=True)

# ── Dark Mode Toggle ──
_dark = st.sidebar.toggle("🌙 Dark Mode", value=st.session_state.get("dark_mode", False), key="dark_mode_toggle")
st.session_state["dark_mode"] = _dark
if _dark:
    st.markdown("""<style>
    /* ── DARK MODE OVERRIDES ── */
    :root{--background-color:#0E1117!important;--secondary-background-color:#262730!important;--text-color:#FAFAFA!important}
    .stApp{background:#0E1117!important;color:#FAFAFA!important}
    header[data-testid="stHeader"]{background:#0E1117!important;border-color:#333!important}
    section[data-testid="stSidebar"]{background:#262730!important;border-color:#333!important}
    section[data-testid="stSidebar"]>div:first-child{background:#262730!important}
    /* Inputs & Selects */
    [data-baseweb="select"]>div{background:#1E1E2E!important;color:#FAFAFA!important;border-color:#444!important}
    [data-baseweb="input"] input,.stTextInput input,.stNumberInput input{background:#1E1E2E!important;color:#FAFAFA!important;border-color:#444!important}
    [data-baseweb="popover"]>div{background:#262730!important;color:#FAFAFA!important}
    [data-baseweb="menu"]{background:#262730!important}
    [data-baseweb="menu"] li{color:#FAFAFA!important}
    [data-baseweb="menu"] li:hover{background:#333!important}
    /* Tabs */
    .stTabs [data-baseweb="tab-list"]{background:#1E1E2E!important;border-color:#333!important}
    .stTabs [data-baseweb="tab"]{color:#999!important}
    /* Expanders */
    [data-testid="stExpander"]{background:#1E1E2E!important;border-color:#333!important}
    /* File uploader */
    [data-testid="stFileUploader"]{background:#1E1E2E!important;border-color:#444!important}
    [data-testid="stFileUploadDropzone"]{background:#1E1E2E!important;color:#FAFAFA!important}
    /* Data grid */
    [data-testid="stDataFrame"]{background:#0E1117!important;border-color:#333!important}
    [data-testid="stDataFrame"] [data-testid="glideDataEditor"]{--gdg-bg-header:#1E1E2E!important;--gdg-bg-cell:#0E1117!important;--gdg-text-dark:#FAFAFA!important;--gdg-text-header:#CCC!important;--gdg-border-color:#333!important;--gdg-text-medium:#AAA!important;--gdg-bg-cell-medium:#151520!important;--gdg-accent-light:#1A2730!important}
    [data-testid="stDataEditor"]{background:#0E1117!important;border-color:#333!important}
    [data-testid="stDataEditor"] [data-testid="glideDataEditor"]{--gdg-bg-header:#1E1E2E!important;--gdg-bg-cell:#0E1117!important;--gdg-text-dark:#FAFAFA!important;--gdg-text-header:#CCC!important;--gdg-border-color:#333!important;--gdg-bg-cell-medium:#151520!important}
    /* DataFrame wrapper & canvas */
    [data-testid="stDataFrame"]>div{background:#0E1117!important}
    [data-testid="stDataFrameResizable"]{background:#0E1117!important;border-color:#333!important}
    /* HTML tables fallback */
    .stApp table{background:#0E1117!important;color:#FAFAFA!important}
    .stApp table th{background:#1E1E2E!important;color:#CCC!important;border-color:#333!important}
    .stApp table td{background:#0E1117!important;color:#FAFAFA!important;border-color:#333!important}
    /* Dataframe search/filter */
    [data-testid="stDataFrame"] input{background:#1E1E2E!important;color:#FAFAFA!important;border-color:#444!important}
    /* Buttons — keep teal, adjust bg */
    .stButton>button{background:#1E1E2E!important;border-color:var(--sfx)!important;color:var(--sfx)!important}
    .stButton>button:hover{background:var(--sfx)!important;color:#FFF!important}
    section[data-testid="stSidebar"] .stButton>button{background:#333!important;border-color:#444!important;color:#DDD!important}
    section[data-testid="stSidebar"] .stButton>button:hover{background:var(--sfx)!important;color:#FFF!important;border-color:var(--sfx)!important}
    /* Labels, captions, markdown text */
    .stMarkdown, .stMarkdown p, label, .stCaption, [data-testid="stWidgetLabel"]{color:#FAFAFA!important}
    section[data-testid="stSidebar"] .stMarkdown p,section[data-testid="stSidebar"] label{color:#DDD!important}
    /* Metric values */
    div[data-testid="stMetricValue"]{color:#FAFAFA!important}
    /* Toggle itself */
    [data-testid="stToggle"] label span:last-child{color:#DDD!important}
    /* Radio in sidebar */
    section[data-testid="stSidebar"] .stRadio label{color:#DDD!important}
    /* Alert overrides */
    [data-testid="stAlert"]{background:#1E1E2E!important;color:#FAFAFA!important}
    /* Scrollbar */
    ::-webkit-scrollbar-track{background:#0E1117!important}
    ::-webkit-scrollbar-thumb{background:#444!important}
    /* Warning badge fix for dark */
    .sfx-badge--warn{color:#FCD34D!important}
    /* Multiselect tags */
    .stMultiSelect [data-baseweb="tag"]{background:#1A2730!important;color:var(--sfx)!important}
    /* Download button */
    .stDownloadButton>button{background:#1E1E2E!important;border-color:var(--sfx)!important;color:var(--sfx)!important}
    .stDownloadButton>button:hover{background:var(--sfx)!important;color:#FFF!important}
    /* Column config panel */
    [data-testid="stColumnConfigDialog"]{background:#262730!important;color:#FAFAFA!important}
    /* Progress bar track */
    .stProgress>div{background:#262730!important}
    /* Tooltips */
    [data-baseweb="tooltip"]>div{background:#262730!important;color:#FAFAFA!important}
    /* KPI cards in dark */
    .kpi-card{background:#1E1E2E!important;border-color:#333!important}
    .kpi-card .kpi-label{color:#AAA!important}
    .kpi-card .kpi-value{color:#FAFAFA!important}
    .kpi-card.green .kpi-value{color:var(--sfx)!important}
    .kpi-card.red .kpi-value{color:#EF4444!important}
    .kpi-card.blue .kpi-value{color:#60A5FA!important}
    .kpi-card.purple .kpi-value{color:#A78BFA!important}
    .kpi-card.orange .kpi-value{color:#FB923C!important}
    /* Custom card classes */
    .sfx-card{background:#1E1E2E!important;border-color:#333!important;color:#FAFAFA!important}
    .sfx-ok{background:#0E2420!important;color:#FAFAFA!important}
    .sfx-warn{background:#1E1A0E!important;color:#FAFAFA!important}
    .sfx-err{background:#1E0E0E!important;color:#FAFAFA!important}
    .sfx-section-header{color:#FAFAFA!important;border-color:#333!important}
    /* Step pills */
    .step-pill.idle{background:#1E1E2E!important;color:#888!important;border-color:#333!important}
    .step-pill.complete{background:#0E2420!important}
    /* Chat */
    .chat-assistant{background:#1E1E2E!important;border-color:#333!important;color:#FAFAFA!important}
    .sfx-chat-bot{background:#1E1E2E!important;border-color:#333!important;color:#FAFAFA!important}
    /* Log entries */
    .log-entry{border-color:#333!important}
    </style>""", unsafe_allow_html=True)

st.sidebar.markdown('<hr>', unsafe_allow_html=True)

# BigQuery Connection Status
bq_mode = st.session_state.get("bq_auth_mode")
if bq_mode in ("adc", "google_oauth", "service_account"):
    mode_label = {"adc": "Local Auth", "google_oauth": "Google Account", "service_account": "Service Account", "streamlit_secrets": "Cloud Secrets"}.get(bq_mode, bq_mode)
    st.sidebar.markdown(f'<div class="sfx-badge sfx-badge--ok"><span class="dot"></span>BigQuery Connected ({mode_label})</div>', unsafe_allow_html=True)
    if bq_mode == "google_oauth":
        if st.sidebar.button("Logout Google", key="bq_logout"):
            from modules.bigquery_client import clear_oauth_credentials
            clear_oauth_credentials()
            st.session_state["bq_client"] = None
            st.session_state["bq_auth_mode"] = "needs_key"
            st.rerun()
else:
    st.sidebar.markdown('<div class="sfx-badge sfx-badge--warn"><span class="dot"></span>BigQuery: Connect Below</div>', unsafe_allow_html=True)
    st.sidebar.markdown('<div class="sfx-label">GOOGLE ACCOUNT</div>', unsafe_allow_html=True)

    # Show OAuth error from callback if any
    _oauth_err = st.session_state.pop("_oauth_error", None)
    if _oauth_err:
        st.sidebar.error(f"Google sign-in failed: {_oauth_err}")

    # Web OAuth flow (for Streamlit Cloud)
    from modules.bigquery_client import get_google_auth_url
    _is_cloud = os.path.exists("/mount/src") or os.environ.get("STREAMLIT_SHARING_MODE") == "true"
    _auth_url, _auth_state = get_google_auth_url()
    if _auth_url:
        st.sidebar.link_button("🔐 Sign in with Google", _auth_url, type="primary", use_container_width=True)
        st.sidebar.caption("Redirects to Google for sign-in. No JSON key needed.")
    elif _is_cloud:
        # Web OAuth not configured — desktop flow won't work on Cloud, so show instructions
        st.sidebar.error(
            "Google OAuth not configured. Add `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, "
            "and `REDIRECT_URI` to Streamlit secrets (or add `client_id` / `client_secret` "
            "under the `[gcp_credentials]` section)."
        )
    else:
        # Fallback: local OAuth (desktop — run_local_server) — only works on local machines
        if st.sidebar.button("Login with Google", key="google_oauth_btn", type="primary"):
            from modules.bigquery_client import handle_google_oauth_login
            with st.sidebar.spinner("Opening Google login..."):
                ok, err = handle_google_oauth_login()
            if ok:
                add_log("BigQuery connected via Google OAuth", "success")
                st.rerun()
            else:
                st.sidebar.error(f"{err}")
        st.sidebar.caption("Opens browser for sign-in. No JSON key needed.")
    st.sidebar.markdown('<div class="sfx-label">SERVICE ACCOUNT</div>', unsafe_allow_html=True)
    sa_file = st.sidebar.file_uploader("Upload JSON key", type=["json"], key="sidebar_sa_upload")
    if sa_file:
        from modules.bigquery_client import handle_service_account_upload
        ok, err = handle_service_account_upload(sa_file)
        if ok:
            add_log("BigQuery connected via Service Account", "success")
            st.rerun()
        else:
            st.sidebar.error(f"{err}")

st.sidebar.markdown('<hr>', unsafe_allow_html=True)

# Groq API key — loaded from secrets/env, never shown or copied by users.
# Uses the same robust resolver as ai_agent.py (handles multiple secret name variants).
if not st.session_state.get("groq_api_key"):
    try:
        from modules.ai_agent import _resolve_api_key as _resolve_groq_key
        _groq_loaded = _resolve_groq_key() or ""
        if _groq_loaded:
            st.session_state["groq_api_key"] = _groq_loaded
    except Exception:
        pass

# Show status only — key is never displayed or editable
if st.session_state.get("groq_api_key"):
    st.sidebar.markdown('<div class="sfx-badge sfx-badge--ok"><span class="dot"></span>AI Agent Ready</div>', unsafe_allow_html=True)
else:
    st.sidebar.markdown(
        '<div class="sfx-badge sfx-badge--warn"><span class="dot"></span>AI Agent Key Missing</div>'
        '<div style="font-size:10px;color:var(--sfx-muted);margin-top:4px;line-height:1.3">'
        'Add <b>GROQ_API_KEY</b> to Streamlit Cloud secrets. '
        'Place it at the <b>top</b> of the secrets file, '
        '<b>above</b> any <code>[section]</code> header, '
        'or TOML will nest it inside the previous section.'
        '</div>',
        unsafe_allow_html=True,
    )

st.sidebar.markdown('<hr>', unsafe_allow_html=True)

# Navigation
nav = st.sidebar.radio("NAVIGATE", [
    "1. Data Ingestion",
    "2. P Mapping",
    "3. Polygon Gen + Editor",
    "4. AWB + Visualisation",
    "5. Financial Intelligence",
    "6. AI Agent",
], index=0, key="nav")

st.sidebar.markdown('<hr>', unsafe_allow_html=True)

# Pipeline Status
st.sidebar.markdown('<div class="sfx-label">PIPELINE STATUS</div>', unsafe_allow_html=True)
status = st.session_state["upload_status"]
steps = [
    ("Cluster CSV", status["cluster"]),
    ("Pincodes CSV", status["pincodes"]),
    ("GeoJSON", status["geojson"]),
    ("BigQuery", st.session_state.get("bq_client") is not None),
    ("P-Mapping", st.session_state.get("final_output_df") is not None),
    ("Polygons", st.session_state.get("polygon_records_df") is not None),
    ("AWB Data", st.session_state.get("awb_raw_df") is not None),
    ("P&L Results", st.session_state.get("final_result_df") is not None),
]
for label, done in steps:
    cls = "sfx-status--done" if done else "sfx-status--pending"
    icon = "✓" if done else "○"
    st.sidebar.markdown(f'<div class="sfx-status {cls}"><span class="icon">{icon}</span><span class="lbl">{label}</span></div>', unsafe_allow_html=True)

# ── Clear Cache Button ──
st.sidebar.markdown('<hr>', unsafe_allow_html=True)
if st.sidebar.button("Clear All Cache", key="clear_cache"):
    st.cache_data.clear()
    st.cache_resource.clear()
    try:
        from modules.duckdb_store import drop_all
        drop_all()
    except Exception:
        pass
    for cache_key in ["_pip_awb_stats", "_pip_data_id", "_hub_pin_counts_cache", "_ms_hex_cache"]:
        st.session_state.pop(cache_key, None)
    add_log("All caches cleared", "warning")
    st.rerun()

# ── Sidebar AI Chat (accessible from all steps) ──
st.sidebar.markdown('<hr>', unsafe_allow_html=True)
with st.sidebar.expander("🤖 AI Assistant", expanded=False):
    if "sidebar_chat_history" not in st.session_state:
        st.session_state["sidebar_chat_history"] = []

    # Show recent chat messages (last 6)
    for msg in st.session_state["sidebar_chat_history"][-6:]:
        if msg["role"] == "user":
            st.markdown(f'<div class="sfx-chat-user">{msg["content"]}</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="sfx-chat-bot">{msg["content"][:300]}{"..." if len(msg["content"]) > 300 else ""}</div>', unsafe_allow_html=True)

    # Quick action buttons
    quick_cols = st.columns(2)
    with quick_cols[0]:
        if st.button("▶ Run Pipeline", key="sidebar_run_pipeline", use_container_width=True):
            st.session_state["auto_run_requested"] = True
            st.rerun()
    with quick_cols[1]:
        if st.button("📊 Status", key="sidebar_status", use_container_width=True):
            from modules.ai_agent import build_app_context
            ctx = build_app_context(st.session_state)
            st.session_state["sidebar_chat_history"].append({"role": "user", "content": "Show pipeline status"})
            st.session_state["sidebar_chat_history"].append({"role": "assistant", "content": ctx})
            st.rerun()

    # Chat input
    sidebar_q = st.text_input("Ask anything...", key="sidebar_ai_q", placeholder="What should I do next?")
    if sidebar_q and st.button("Send", key="sidebar_ai_send"):
        from modules.ai_agent import app_agent_chat
        api_key = st.session_state.get("groq_api_key")
        answer = app_agent_chat(sidebar_q, st.session_state, st.session_state["sidebar_chat_history"], api_key)
        st.session_state["sidebar_chat_history"].append({"role": "user", "content": sidebar_q})
        st.session_state["sidebar_chat_history"].append({"role": "assistant", "content": answer})
        st.rerun()

st.sidebar.markdown('<div class="sfx-footer">© 2026 Shadowfax Technologies</div>', unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════
# HEADER — Step Progress Pills
# ═══════════════════════════════════════════════════════
step_names = {1: "Data Ingestion", 2: "P-Mapping", 3: "Polygon Gen", 4: "AWB Analysis", 5: "Financial Intel", 6: "AI Agent"}
step_done = {
    1: status["cluster"] and status["pincodes"],
    2: st.session_state.get("final_output_df") is not None,
    3: st.session_state.get("polygon_records_df") is not None,
    4: st.session_state.get("final_result_df") is not None,
    5: False,
    6: False,
}
current_step = int(nav[0]) if nav[0].isdigit() else 6
pills_html = '<div class="step-pills">'
for i, name in step_names.items():
    cls = "complete" if step_done[i] else ("active" if i == current_step else "idle")
    icon = "✓" if step_done[i] else str(i)
    pills_html += f'<span class="step-pill {cls}">{icon}  {name}</span>'
pills_html += '</div>'
st.markdown(pills_html, unsafe_allow_html=True)

if loaded:
    st.toast(f"Auto-loaded: {', '.join(loaded)}", icon="📂")

# ── Auto-Run Pipeline Handler ──
if st.session_state.get("auto_run_requested"):
    st.session_state["auto_run_requested"] = False
    st.markdown('<div class="sfx-header">🤖 Auto-Running Pipeline...</div>', unsafe_allow_html=True)
    auto_progress = st.empty()
    auto_status = st.empty()

    steps_completed = []
    steps_failed = []

    # Step 1 check
    if not (st.session_state.get("upload_status", {}).get("cluster") and st.session_state.get("upload_status", {}).get("pincodes")):
        auto_status.markdown('<div class="sfx-err">❌ Step 1: Upload Cluster CSV and Pincodes CSV first. Cannot auto-run without data.</div>', unsafe_allow_html=True)
        st.session_state["sidebar_chat_history"].append({"role": "assistant", "content": "Cannot auto-run: Please upload Cluster CSV and Pincodes CSV first (Step 1)."})
    else:
        steps_completed.append("Step 1: Data ✅ (already loaded)")

        # Step 2: P-Mapping
        if st.session_state.get("final_output_df") is None:
            try:
                auto_progress.progress(0.15, text="Running P-Mapping...")
                cdf = st.session_state["cluster_df"]
                pdf = st.session_state["pincodes_df"]
                vlat = st.session_state.get("vol_lat_col", "Volumetric Lat")
                vlon = st.session_state.get("vol_long_col", "Volumetric Long")
                merged = pd.merge(clean_pincode(cdf.copy()), clean_pincode(pdf.copy()), on="Pincode", how="left")
                from utils import haversine_km_vectorized, get_pricing_vectorized
                hl = pd.to_numeric(merged["Hub_lat"], errors="coerce")
                ho = pd.to_numeric(merged["Hub_long"], errors="coerce")
                vl_col = pd.to_numeric(merged[vlat], errors="coerce")
                vo_col = pd.to_numeric(merged[vlon], errors="coerce")
                valid = hl.notna() & ho.notna() & vl_col.notna() & vo_col.notna()
                merged["Distance"] = np.nan
                if valid.any():
                    merged.loc[valid, "Distance"] = haversine_km_vectorized(
                        hl[valid].values, ho[valid].values, vl_col[valid].values, vo_col[valid].values
                    )
                merged["SP&A Aligned P mapping"] = pd.Series(get_pricing_vectorized(merged["Distance"])).map(rate_to_pcat).values
                out_cols = ["Pincode", "Hub_Name", "Hub_lat", "Hub_long", vlat, vlon, "Distance", "SP&A Aligned P mapping"]
                final = merged[[c for c in out_cols if c in merged.columns]].copy()
                st.session_state["final_output_df"] = final
                ensure_output_dirs()
                final.to_csv(os.path.join(OUTPUT_DIR, "final_output.csv"), index=False)
                steps_completed.append(f"Step 2: P-Mapping ✅ ({len(final)} records)")
                add_log(f"Auto-run: P-Mapping complete ({len(final)} records)", "success")
            except Exception as e:
                steps_failed.append(f"Step 2: P-Mapping ❌ ({e})")
        else:
            steps_completed.append("Step 2: P-Mapping ✅ (already done)")

        # Step 3: Polygon Gen
        if st.session_state.get("polygon_records_df") is None:
            try:
                auto_progress.progress(0.35, text="Generating Polygons...")
                from modules.polygon_generator import generate_polygons
                fodf = st.session_state["final_output_df"]
                poly_df = generate_polygons(fodf)
                st.session_state["polygon_records_df"] = poly_df
                poly_df.to_csv(os.path.join(OUTPUT_DIR, "Clustering_payout_polygon_latest.csv"), index=False)
                steps_completed.append(f"Step 3: Polygon Gen ✅ ({len(poly_df)} polygons)")
                add_log(f"Auto-run: Polygons generated ({len(poly_df)})", "success")
            except Exception as e:
                steps_failed.append(f"Step 3: Polygon Gen ❌ ({e})")
        else:
            steps_completed.append("Step 3: Polygon Gen ✅ (already done)")

        # Step 4: AWB Analysis (requires BigQuery)
        bq = st.session_state.get("bq_client")
        if st.session_state.get("final_result_df") is None and bq:
            try:
                auto_progress.progress(0.55, text="Fetching AWB data from BigQuery...")
                from modules.bigquery_client import fetch_awb_data
                from modules.cluster_assignor import assign_clusters, calculate_financials
                cdf_for_awb = st.session_state.get("cluster_df")
                awb_df, err = fetch_awb_data(bq, cdf_for_awb)
                if err:
                    steps_failed.append(f"Step 4: AWB Fetch ❌ ({err})")
                else:
                    st.session_state["awb_raw_df"] = awb_df
                    auto_progress.progress(0.7, text="Assigning clusters...")
                    poly_df = st.session_state.get("polygon_records_df")
                    if poly_df is not None:
                        result_df = assign_clusters(awb_df, poly_df)
                        result_df = calculate_financials(result_df)
                        st.session_state["final_result_df"] = result_df
                        result_df.to_csv(os.path.join(OUTPUT_DIR, "Awb_with_cluster_info.csv"), index=False)
                        steps_completed.append(f"Step 4: AWB Analysis ✅ ({len(result_df)} AWBs)")
                        add_log(f"Auto-run: AWB analysis complete ({len(result_df)} AWBs)", "success")
                    else:
                        steps_failed.append("Step 4: Cluster assignment ❌ (no polygons)")
            except Exception as e:
                steps_failed.append(f"Step 4: AWB Analysis ❌ ({e})")
        elif st.session_state.get("final_result_df") is not None:
            steps_completed.append("Step 4: AWB Analysis ✅ (already done)")
        elif not bq:
            steps_failed.append("Step 4: AWB Analysis ⏭ (no BigQuery connection)")

        auto_progress.progress(1.0, text="Pipeline complete!")

        # Show results
        result_html = '<div class="sfx-card" style="border-left:4px solid #0B8A7A">'
        result_html += '<div style="font-weight:700;color:#0B8A7A;margin-bottom:8px;font-family:Work Sans,sans-serif">Pipeline Results</div>'
        for s in steps_completed:
            result_html += f'<div style="padding:2px 0;color:#0B8A7A">{s}</div>'
        for s in steps_failed:
            result_html += f'<div style="padding:2px 0;color:#EF4444">{s}</div>'
        result_html += '</div>'
        auto_status.markdown(result_html, unsafe_allow_html=True)

        # Add summary to sidebar chat
        summary = "Pipeline auto-run complete:\n" + "\n".join(steps_completed + steps_failed)
        st.session_state["sidebar_chat_history"].append({"role": "assistant", "content": summary})

# ═══════════════════════════════════════════════════════
# STEP 1 — DATA INGESTION
# ═══════════════════════════════════════════════════════
if nav.startswith("1"):
    st.markdown('<div class="sfx-header">Step 1 — Data Ingestion</div>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown('<div class="sfx-card">', unsafe_allow_html=True)
        st.markdown("#### Clustering Automation")
        mode = st.radio("Input mode", ["Upload CSV", "Manual Entry"], horizontal=True, key="cluster_mode")
        if mode == "Upload CSV":
            # Show remembered path if available
            _cfg_paths = load_file_paths_config()
            _cl_saved_path = _cfg_paths.get("cluster_csv", "")
            if _cl_saved_path:
                st.markdown(f'<div class="sfx-ok">📂 Path saved — auto-loads on next start</div>', unsafe_allow_html=True)
            # Optional: allow specifying a file path instead of uploading
            _cl_path_inp = st.text_input("Or enter file path (auto-remembered)", value=_cl_saved_path, key="cl_path_inp", placeholder=r"C:\path\to\clustering.csv")
            if _cl_path_inp and _cl_path_inp != _cl_saved_path and os.path.exists(_cl_path_inp):
                try:
                    df = pd.read_csv(_cl_path_inp, encoding="ISO-8859-1"); df.columns = df.columns.str.strip()
                    req = ["Pincode", "Hub_Name", "Hub_lat", "Hub_long"]
                    if all(c in df.columns for c in req):
                        df = clean_pincode(df); st.session_state["cluster_df"] = df; st.session_state["upload_status"]["cluster"] = True
                        save_file_path("cluster_csv", _cl_path_inp)
                        add_log(f"Cluster CSV loaded from path: {len(df)} rows", "success")
                        st.markdown(f'<div class="sfx-ok">✅ {len(df)} rows from path</div>', unsafe_allow_html=True)
                except Exception as e:
                    st.error(str(e))
            f1 = st.file_uploader("Upload .csv", type=["csv"], key="up_cluster")
            if f1:
                try:
                    df = pd.read_csv(f1, encoding="ISO-8859-1"); df.columns = df.columns.str.strip()
                    req = ["Pincode", "Hub_Name", "Hub_lat", "Hub_long"]
                    miss = [c for c in req if c not in df.columns]
                    if miss:
                        st.error(f"Missing: {', '.join(miss)}")
                    else:
                        df = clean_pincode(df); st.session_state["cluster_df"] = df; st.session_state["upload_status"]["cluster"] = True
                        st.session_state["_geojson_filtered"] = False  # Re-filter GeoJSON with new cluster
                        _filter_geojson_to_cluster()
                        add_log(f"Cluster CSV loaded: {len(df)} rows, {df['Hub_Name'].nunique()} hubs", "success")
                        st.markdown(f'<div class="sfx-ok">✅ {len(df)} rows, {df["Hub_Name"].nunique()} hubs</div>', unsafe_allow_html=True)
                        st.dataframe(df, height=180)
                except Exception as e:
                    st.error(str(e))
        else:
            st.caption("Add pincodes manually:")
            manual = st.data_editor(pd.DataFrame({"Pincode": [""], "Hub_Name": [""], "Hub_lat": [0.0], "Hub_long": [0.0]}), num_rows="dynamic", key="manual_cluster", use_container_width=True)
            if st.button("Use Manual Data", key="use_manual"):
                valid = manual.dropna(subset=["Pincode"]).copy()
                valid = valid[valid["Pincode"] != ""]
                if len(valid) > 0:
                    valid = clean_pincode(valid); st.session_state["cluster_df"] = valid; st.session_state["upload_status"]["cluster"] = True
                    add_log(f"Manual cluster data: {len(valid)} rows", "success")
                    st.markdown(f'<div class="sfx-ok">✅ {len(valid)} rows</div>', unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with c2:
        st.markdown('<div class="sfx-card">', unsafe_allow_html=True)
        st.markdown("#### Pincodes Reference")
        # Show persistent status
        _pin_saved = os.path.exists(os.path.join(OUTPUT_DIR, "pincodes_ref.csv"))
        if st.session_state.get("pincodes_df") is not None and not st.session_state.get("_pin_new_upload"):
            st.markdown('<div class="sfx-ok">📂 Auto-loaded from disk — re-upload to replace</div>', unsafe_allow_html=True)
        f2 = st.file_uploader("Upload pincodes.csv", type=["csv"], key="up_pin")
        if f2:
            try:
                df = pd.read_csv(f2); df.columns = df.columns.str.strip()
                if "Pincode" not in df.columns:
                    st.error("Missing Pincode column")
                else:
                    df = clean_pincode(df); lat_c, lon_c = detect_latlon_cols(df)
                    if lat_c and lon_c:
                        st.session_state["vol_lat_col"] = lat_c; st.session_state["vol_long_col"] = lon_c
                        st.markdown(f'<div class="sfx-ok">✅ {len(df)} rows. Detected: <b>{lat_c}</b>, <b>{lon_c}</b></div>', unsafe_allow_html=True)
                    else:
                        st.warning("Select lat/lon columns:")
                        lat_c = st.selectbox("Lat", df.columns.tolist(), key="sl")
                        lon_c = st.selectbox("Lon", df.columns.tolist(), key="sln")
                        st.session_state["vol_lat_col"] = lat_c; st.session_state["vol_long_col"] = lon_c
                    st.session_state["pincodes_df"] = df; st.session_state["upload_status"]["pincodes"] = True
                    st.session_state["_pin_new_upload"] = True
                    add_log(f"Pincodes CSV loaded: {len(df)} rows", "success")
                    # Persist to disk + remember path for future sessions
                    try:
                        ensure_output_dirs()
                        df.to_csv(os.path.join(OUTPUT_DIR, "pincodes_ref.csv"), index=False, encoding="utf-8-sig")
                        add_log("Pincodes CSV saved to disk (persistent)", "success")
                    except Exception:
                        pass
                    st.dataframe(df.head(5), height=150)
                    st.markdown('<div class="sfx-ok">📂 Saved — will auto-load next session</div>', unsafe_allow_html=True)
            except Exception as e:
                st.error(str(e))
        if _pin_saved:
            if st.button("🗑 Clear Saved Pincodes", key="clear_pin_disk"):
                try:
                    os.remove(os.path.join(OUTPUT_DIR, "pincodes_ref.csv"))
                    st.session_state["pincodes_df"] = None
                    st.session_state["upload_status"]["pincodes"] = False
                    add_log("Saved pincodes cleared from disk", "warning")
                    st.rerun()
                except Exception as _ce:
                    st.error(str(_ce))
        st.markdown("</div>", unsafe_allow_html=True)
    with c3:
        st.markdown('<div class="sfx-card">', unsafe_allow_html=True)
        st.markdown("#### GeoJSON Boundaries")
        # Show persistent status
        _geo_saved = os.path.exists(os.path.join(OUTPUT_DIR, "geojson_boundaries.json"))
        if st.session_state.get("geojson_data") is not None and not st.session_state.get("_geo_new_upload"):
            st.markdown('<div class="sfx-ok">📂 Auto-loaded from disk — re-upload to replace</div>', unsafe_allow_html=True)
        geo_mode = st.radio("Method", ["Upload", "File Path", "Skip"], horizontal=True, key="geo_mode")
        if geo_mode == "Upload":
            f3 = st.file_uploader("Upload .geojson", type=["geojson", "json"], key="up_geo")
            if f3:
                try:
                    data = json.load(f3)
                    if "features" not in data:
                        st.error("Invalid GeoJSON")
                    else:
                        pf = detect_geojson_pincode_field(data); st.session_state["geojson_data"] = data; st.session_state["upload_status"]["geojson"] = True
                        st.session_state["geojson_pincode_field"] = pf
                        st.session_state["_geo_new_upload"] = True
                        add_log(f"GeoJSON loaded: {len(data['features']):,} features", "success")
                        # Persist to disk for future sessions
                        try:
                            ensure_output_dirs()
                            with open(os.path.join(OUTPUT_DIR, "geojson_boundaries.json"), "w", encoding="utf-8") as _gf:
                                json.dump(data, _gf)
                            add_log("GeoJSON saved to disk (persistent)", "success")
                        except Exception:
                            pass
                        st.markdown(f'<div class="sfx-ok">✅ {len(data["features"]):,} features. Field: <b>{pf}</b></div>', unsafe_allow_html=True)
                except Exception as e:
                    st.error(str(e))
        elif geo_mode == "File Path":
            _cfg_now = load_file_paths_config()
            fp = st.text_input("Path (remembered across sessions)", value=_cfg_now.get("geojson", ""), key="gp",
                               placeholder=r"C:\path\to\boundaries.geojson")
            if st.button("Load", key="lgp") and fp:
                try:
                    with open(fp, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    pf = detect_geojson_pincode_field(data); st.session_state["geojson_data"] = data; st.session_state["upload_status"]["geojson"] = True
                    st.session_state["geojson_pincode_field"] = pf
                    save_file_path("geojson", fp)
                    add_log(f"GeoJSON loaded from path: {len(data['features']):,} features", "success")
                    # Persist to disk
                    try:
                        ensure_output_dirs()
                        with open(os.path.join(OUTPUT_DIR, "geojson_boundaries.json"), "w", encoding="utf-8") as _gf:
                            json.dump(data, _gf)
                    except Exception:
                        pass
                    st.markdown(f'<div class="sfx-ok">✅ {len(data["features"]):,} features — path saved for auto-reload</div>', unsafe_allow_html=True)
                except Exception as e:
                    st.error(str(e))
        else:
            st.session_state["geojson_source"] = "skipped"
            st.markdown('<div class="sfx-warn">GeoJSON skipped — polygon generation will require manual upload.</div>', unsafe_allow_html=True)
        if _geo_saved:
            if st.button("🗑 Clear Saved GeoJSON", key="clear_geo_disk"):
                try:
                    os.remove(os.path.join(OUTPUT_DIR, "geojson_boundaries.json"))
                    st.session_state["geojson_data"] = None
                    st.session_state["upload_status"]["geojson"] = False
                    add_log("Saved GeoJSON cleared from disk", "warning")
                    st.rerun()
                except Exception as _ce:
                    st.error(str(_ce))
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="sfx-header">Load Existing Files</div>', unsafe_allow_html=True)
    lc1, lc2, lc3, lc4 = st.columns(4)
    for col, key, paths, label in [
        (lc1, "final_output_df", [os.path.join(OUTPUT_DIR, "final_output.csv"), os.path.join(DATA_DIR, "final_output.csv")], "final_output"),
        (lc2, "polygon_records_df", [os.path.join(OUTPUT_DIR, "Clustering_payout_polygon_latest.csv"), os.path.join(OUTPUT_DIR, "Clustering_payout_polygon_4KM.csv"), os.path.join(DATA_DIR, "Clustering_payout_polygon_4KM.csv")], "polygons"),
        (lc3, "awb_raw_df", [os.path.join(OUTPUT_DIR, "Awb_with_polygon_mapping.csv"), os.path.join(DATA_DIR, "Awb_with_polygon_mapping.csv")], "AWB raw"),
        (lc4, "final_result_df", [os.path.join(OUTPUT_DIR, "Awb_with_cluster_info.csv"), os.path.join(DATA_DIR, "Awb_with_cluster_info.csv")], "AWB cluster"),
    ]:
        with col:
            if st.button(f"Load {label}", key=f"ql_{key}"):
                for p in paths:
                    if os.path.exists(p):
                        st.session_state[key] = pd.read_csv(p); add_log(f"Loaded {label} from disk", "success"); st.success("Loaded"); break
                else:
                    st.warning("Not found")

    # Payout Slab Reference
    with st.expander("Payout Slab Reference", expanded=False):
        slab_html = '<div style="display:flex;gap:6px;flex-wrap:wrap;margin:8px 0">'
        slab_colors = ["#22c55e", "#3b82f6", "#8b5cf6", "#f59e0b", "#ef4444", "#ec4899", "#14b8a6", "#f97316", "#6366f1", "#6b7280"]
        for i, (lo, hi, label) in enumerate(PRICING_SLABS):
            c = slab_colors[i % len(slab_colors)]
            slab_html += f'<span style="background:{c}20;color:{c};border:1px solid {c}40;padding:4px 10px;border-radius:12px;font-size:12px;font-weight:600">{lo}-{hi}km = {label}</span>'
        slab_html += '<span style="background:#6b728020;color:#6b7280;border:1px solid #6b728040;padding:4px 10px;border-radius:12px;font-size:12px;font-weight:600">45+ km = Nil</span></div>'
        st.markdown(slab_html, unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════
# STEP 2 — P MAPPING
# ═══════════════════════════════════════════════════════
elif nav.startswith("2"):
    st.markdown('<div class="sfx-header">Step 2 — P Mapping (Distance-Based Payout)</div>', unsafe_allow_html=True)
    cdf = st.session_state.get("cluster_df"); pdf = st.session_state.get("pincodes_df")
    if cdf is None or pdf is None:
        _missing = [n for n, v in [("Cluster CSV (Pincode / Hub / lat / long)", cdf), ("Pincodes reference CSV", pdf)] if v is None]
        render_step_guard(_missing, "Upload in Step 1 — files are remembered and auto-load on the next run.")
    vlat = st.session_state.get("vol_lat_col", "Volumetric Lat"); vlon = st.session_state.get("vol_long_col", "Volumetric Long")
    fc1, fc2 = st.columns(2)
    with fc1:
        hub_filter = st.selectbox("Hub", ["All Hubs"] + cdf["Hub_Name"].unique().tolist(), key="osrm_hub")
    fcdf = cdf if hub_filter == "All Hubs" else cdf[cdf["Hub_Name"] == hub_filter]
    with fc2:
        pc_filter = st.selectbox("Pincode", ["All"] + fcdf["Pincode"].unique().tolist(), key="osrm_pc")
    if pc_filter != "All":
        fcdf = fcdf[fcdf["Pincode"] == pc_filter]
    merged = pd.merge(clean_pincode(fcdf.copy()), clean_pincode(pdf.copy()), on="Pincode", how="left")
    use_osrm = st.checkbox("Use OSRM API (road distance)", value=False)
    if st.button("Calculate Distances", type="primary", key="calc_dist"):
        prog = st.progress(0); add_log("P-Mapping calculation started", "info")
        from utils import haversine_km_vectorized, get_pricing_vectorized
        if use_osrm:
            # OSRM: row-by-row (API calls required)
            import requests as _req
            dists = []
            for i, (_, row) in enumerate(merged.iterrows()):
                hl, ho, vl, vo = row.get("Hub_lat"), row.get("Hub_long"), row.get(vlat), row.get(vlon)
                dk = None
                if pd.notna(hl) and pd.notna(ho) and pd.notna(vl) and pd.notna(vo):
                    try:
                        r = _req.get(f"http://router.project-osrm.org/route/v1/driving/{ho},{hl};{vo},{vl}?overview=false", timeout=10).json()
                        if r.get("code") == "Ok":
                            dk = r["routes"][0]["distance"] / 1000
                    except Exception:
                        pass
                    if dk is None:
                        dk = haversine_km(float(hl), float(ho), float(vl), float(vo))
                dists.append(dk); prog.progress((i + 1) / len(merged))
            merged["Distance"] = dists
        else:
            # Vectorized haversine — ~100x faster than row-by-row
            prog.progress(0.3)
            hl = pd.to_numeric(merged["Hub_lat"], errors="coerce")
            ho = pd.to_numeric(merged["Hub_long"], errors="coerce")
            vl = pd.to_numeric(merged[vlat], errors="coerce")
            vo_col = pd.to_numeric(merged[vlon], errors="coerce")
            valid = hl.notna() & ho.notna() & vl.notna() & vo_col.notna()
            merged["Distance"] = np.nan
            if valid.any():
                merged.loc[valid, "Distance"] = haversine_km_vectorized(
                    hl[valid].values, ho[valid].values, vl[valid].values, vo_col[valid].values
                )
            prog.progress(0.8)
        merged["SP&A Aligned P mapping"] = pd.Series(get_pricing_vectorized(merged["Distance"])).map(rate_to_pcat).values
        out_cols = ["Pincode", "Hub_Name", "Hub_lat", "Hub_long", vlat, vlon, "Distance", "SP&A Aligned P mapping"]
        final = merged[[c for c in out_cols if c in merged.columns]].copy()
        st.session_state["final_output_df"] = final; final.to_csv(os.path.join(OUTPUT_DIR, "final_output.csv"), index=False); prog.empty()
        add_log(f"P-Mapping complete: {len(final)} records", "success")
        st.markdown('<div class="sfx-ok">✅ P-Mapping calculation complete!</div>', unsafe_allow_html=True)

    fo = st.session_state.get("final_output_df")
    if fo is not None:
        dfo = fo.copy()
        if hub_filter != "All Hubs":
            dfo = dfo[dfo["Hub_Name"] == hub_filter]
        if pc_filter != "All":
            dfo = dfo[dfo["Pincode"].astype(str) == str(pc_filter)]

        # KPI Cards
        if "Distance" in fo.columns:
            avg_dist = fo["Distance"].mean()
            nil_count = (fo["SP&A Aligned P mapping"] == "Nil").sum() if "SP&A Aligned P mapping" in fo.columns else 0
            st.markdown(f'''<div class="kpi-row">
                <div class="kpi-card blue"><div class="kpi-label">Total Records</div><div class="kpi-value">{len(fo)}</div></div>
                <div class="kpi-card"><div class="kpi-label">Hubs</div><div class="kpi-value">{fo["Hub_Name"].nunique()}</div></div>
                <div class="kpi-card"><div class="kpi-label">Avg Distance</div><div class="kpi-value">{avg_dist:.1f} km</div></div>
                <div class="kpi-card red"><div class="kpi-label">Nil Distance</div><div class="kpi-value">{nil_count}</div></div>
            </div>''', unsafe_allow_html=True)

        st.markdown('<div class="sfx-header">Results</div>', unsafe_allow_html=True)
        import html as _html
        _tsv_escaped = _html.escape(dfo.to_csv(index=False, sep="\t"))
        st.markdown(f"""<div style="margin:4px 0 8px">
<textarea id="pm_copy_ta" style="position:fixed;left:-9999px;top:-9999px;width:1px;height:1px;opacity:0">{_tsv_escaped}</textarea>
<button onclick="var ta=document.getElementById('pm_copy_ta');ta.style.display='block';ta.select();if(navigator.clipboard){{navigator.clipboard.writeText(ta.value).then(()=>{{this.textContent='✓ Copied!';setTimeout(()=>this.textContent='Copy',2000)}}).catch(()=>{{document.execCommand('copy');this.textContent='✓ Copied!';setTimeout(()=>this.textContent='Copy',2000)}})}}else{{document.execCommand('copy');this.textContent='✓ Copied!';setTimeout(()=>this.textContent='Copy',2000)}}ta.style.display='none';"
 style="padding:5px 18px;background:#0B8A7A;color:#fff;border:none;border-radius:6px;cursor:pointer;font-weight:600;font-size:13px" onmouseover="this.style.opacity='.8'" onmouseout="this.style.opacity='1'">Copy</button>
</div>""", unsafe_allow_html=True)
        st.data_editor(dfo, use_container_width=True, height=300, key="osrm_edit")
        st.download_button("Download final_output.csv", get_download_bytes(fo, "csv"), "final_output.csv", "text/csv", key="dl_fo")

        if "SP&A Aligned P mapping" in fo.columns:
            dc = fo["SP&A Aligned P mapping"].value_counts().sort_index()
            _rcols = st.columns(min(len(dc), 8))
            for _i, (_r, _c) in enumerate(dc.items()):
                with _rcols[_i % len(_rcols)]:
                    st.metric(_r, _c)

        # ═══ P Category Switch (inline in Results) ═══════════
        if "pmapping_overrides" not in st.session_state:
            st.session_state["pmapping_overrides"] = {}
        _ov = st.session_state["pmapping_overrides"]

        def _get_pcat(row):
            pin = str(row.get("Pincode", "")).strip()
            if pin in _ov:
                return _ov[pin]
            return str(row.get("SP&A Aligned P mapping", "P1"))

        _pdf = dfo.copy()
        _pdf["P_Category"]     = _pdf.apply(_get_pcat, axis=1)
        _pdf["Payout (₹/km)"]  = _pdf["P_Category"].map(lambda p: PCAT_SOP.get(p, (0, 0))[0])
        _pdf["Amount Capping"] = _pdf["P_Category"].map(lambda p: PCAT_SOP.get(p, (0, 0))[1])

        with st.expander("Switch P Category for Pincodes", expanded=False):
            _sw1, _sw2, _sw3 = st.columns([3, 2, 1])
            with _sw1:
                _pin_opts = sorted(_pdf["Pincode"].astype(str).str.strip().unique().tolist())
                _pins_sel = st.multiselect("Select Pincodes", options=_pin_opts, key="sw_pincodes")
            with _sw2:
                _pcat_opts = sorted(PCAT_SOP.keys(), key=lambda x: int(x[1:]))
                _new_pcat  = st.selectbox(
                    "New P Category",
                    options=_pcat_opts,
                    format_func=lambda p: f"{p}  (₹{PCAT_SOP[p][0]}/km · cap ₹{PCAT_SOP[p][1]})",
                    key="sw_new_pcat"
                )
            with _sw3:
                st.write(""); st.write("")
                if st.button("Switch", type="primary", key="do_switch"):
                    if _pins_sel:
                        for _p in _pins_sel:
                            st.session_state["pmapping_overrides"][_p] = _new_pcat
                        st.success(f"Switched {len(_pins_sel)} pincode(s) → {_new_pcat}")
                        st.rerun()
                    else:
                        st.warning("Select at least one pincode.")

            if _ov:
                _ov_df = pd.DataFrame([
                    {"Pincode": k, "P_Category": v,
                     "Payout (₹/km)": PCAT_SOP.get(v,(0,0))[0],
                     "Amount Capping": PCAT_SOP.get(v,(0,0))[1]}
                    for k, v in _ov.items()
                ])
                st.caption(f"{len(_ov)} override(s) active")
                st.dataframe(_ov_df, use_container_width=True, height=min(160, 40 + len(_ov_df)*35))
                if st.button("Clear All Switches", key="clear_switches"):
                    st.session_state["pmapping_overrides"] = {}
                    st.rerun()

        _show_cols = [c for c in ["Pincode","Hub_Name","Distance","SP&A Aligned P mapping","P_Category","Payout (₹/km)","Amount Capping"] if c in _pdf.columns]
        st.dataframe(_pdf[_show_cols], use_container_width=True, height=280)
        st.download_button("Download with P Categories", get_download_bytes(_pdf, "csv"),
                           "final_output_with_pcategory.csv", "text/csv", key="dl_fo_pcat")

        st.markdown('<div class="sfx-header">Map</div>', unsafe_allow_html=True)
        st.caption("Use the layer control (top-right) to switch between Street / Satellite / Terrain views.")
        _s2mc1, _s2mc2 = st.columns(2)
        with _s2mc1:
            edit_mode_s2 = st.toggle("Edit Mode", key="s2_edit_mode", value=False)
        with _s2mc2:
            s2_rate_filter = st.selectbox("P-Category Filter", ["All"] + sorted(PCAT_SOP.keys(), key=lambda x: int(x[1:])) + ["Nil"], key="s2_map_rate")
        if edit_mode_s2:
            st.info("Edit Mode ON — draw polygons on the map, click existing polygons to edit.")
        try:
            import folium
            from streamlit_folium import st_folium
            from modules.visualizer import create_osrm_map
            m = create_osrm_map(fo, st.session_state.get("geojson_data"), satellite=False, hub_filter=hub_filter, rate_filter=s2_rate_filter,
                                vlat_col=st.session_state.get("vol_lat_col"), vlon_col=st.session_state.get("vol_long_col"))
            if edit_mode_s2:
                from folium.plugins import Draw
                Draw(export=True, position="topleft", draw_options={"polyline": {"shapeOptions": {"color": "#FF6B35"}}, "polygon": {"shapeOptions": {"color": "#004E98", "fillOpacity": 0.3}}, "circle": False, "rectangle": True, "marker": True, "circlemarker": False}).add_to(m)
            if m:
                map_out_s2 = st_folium(m, width=None, height=550)
                if map_out_s2 and map_out_s2.get("last_clicked"):
                    click_lat = map_out_s2["last_clicked"]["lat"]
                    click_lon = map_out_s2["last_clicked"]["lng"]
                    st.markdown(f'<div class="sfx-card"><b>Clicked:</b> {click_lat:.6f}, {click_lon:.6f}</div>', unsafe_allow_html=True)
        except ImportError:
            st.info("Install folium + streamlit-folium for maps.")
        except Exception as _map_err:
            st.error(f"Map error: {_map_err}")

# ═══════════════════════════════════════════════════════
# STEP 3 — POLYGON GENERATION + EDITOR
# ═══════════════════════════════════════════════════════
elif nav.startswith("3"):
    st.markdown('<div class="sfx-header">Step 3 — Polygon Generation + Editor</div>', unsafe_allow_html=True)
    cdf = st.session_state.get("cluster_df")
    if cdf is None:
        render_step_guard(["Cluster CSV (hub–pincode list)"], "Polygon generation needs hub coordinates from the Cluster CSV — upload it in Step 1.")
    hub_list = cdf["Hub_Name"].unique().tolist()
    hub_filter = st.selectbox("Filter by Hub", ["All Hubs"] + hub_list, key="poly_hub")

    with st.expander("Polygon Generation", expanded=st.session_state.get("polygon_records_df") is None):
        geo = st.session_state.get("geojson_data")
        if geo:
            st.markdown(f'<div class="sfx-ok">✅ GeoJSON — {len(geo.get("features", [])):,} features</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="sfx-warn">No GeoJSON loaded. Upload one or load polygon CSV below.</div>', unsafe_allow_html=True)
        radius = st.number_input(
            "Default Distance Band Width (km)",
            min_value=0.5, max_value=20.0,
            value=st.session_state.get("radius_limit_km", 5.0),
            step=0.01, format="%.2f", key="rad",
            help="Applies to all hubs unless per-hub radii are set below. Supports precise values like 4.14, 4.24, 4.3 km."
        )
        st.session_state["radius_limit_km"] = radius

        # ── Per-Hub Radius Customization ──
        with st.expander("Per-Hub Radius Customization", expanded=bool(st.session_state.get("hub_radius_map"))):
            st.caption("Set a custom distance band width for individual hubs. Hubs not listed here use the default above.")
            existing_map = st.session_state.get("hub_radius_map", {})
            hub_radius_data = []
            for hub in hub_list:
                hub_radius_data.append({
                    "Hub_Name": hub,
                    "Radius (km)": existing_map.get(hub, radius),
                    "Custom": hub in existing_map,
                })
            hub_radius_df = pd.DataFrame(hub_radius_data)
            edited_hr = st.data_editor(
                hub_radius_df,
                column_config={
                    "Hub_Name": st.column_config.TextColumn("Hub Name", disabled=True),
                    "Radius (km)": st.column_config.NumberColumn(
                        "Radius (km)", min_value=0.5, max_value=20.0, step=0.01, format="%.2f"
                    ),
                    "Custom": st.column_config.CheckboxColumn("Override Default"),
                },
                use_container_width=True, height=min(400, 35 * len(hub_radius_data) + 38),
                key="hub_radius_editor",
            )
            new_map = {}
            for _, row in edited_hr.iterrows():
                if row["Custom"]:
                    new_map[row["Hub_Name"]] = float(row["Radius (km)"])
            st.session_state["hub_radius_map"] = new_map
            if new_map:
                st.markdown(f'<div class="sfx-ok">{len(new_map)} hub(s) with custom radius</div>', unsafe_allow_html=True)

        if geo and st.button("Generate Polygons", type="primary", key="gen_poly"):
            try:
                from modules.polygon_generator import convert_geojson_to_boundaries, generate_cluster_polygons, save_polygon_outputs
                hub_radius_map = st.session_state.get("hub_radius_map", {})
                add_log("Polygon generation started", "info")
                if hub_radius_map:
                    add_log(f"Per-hub radii: {hub_radius_map}", "info")
                with st.status("Generating cluster polygons...", expanded=True) as _poly_status:
                    st.write("Converting GeoJSON boundaries...")
                    bdf = convert_geojson_to_boundaries(geo, st.session_state.get("geojson_pincode_field"))
                    st.session_state["pin_boundaries_df"] = bdf
                    st.write(f"Building concentric ring polygons for {len(bdf)} pincodes...")
                    _prog = st.progress(0)
                    rdf, kml, skip = generate_cluster_polygons(
                        cdf, bdf, radius,
                        hub_radius_map=hub_radius_map if hub_radius_map else None,
                        progress_cb=lambda p: _prog.progress(p),
                    )
                    _prog.empty()
                    st.write("Saving outputs (CSV / XLSX / KML)...")
                    csv_p, xlsx_p, kml_p = save_polygon_outputs(rdf, kml, radius, hub_radius_map=hub_radius_map if hub_radius_map else None)
                    st.session_state["polygon_records_df"] = rdf
                    _poly_status.update(label=f"✅ {len(rdf)} polygons generated", state="complete", expanded=False)
                add_log(f"Polygon generation complete: {len(rdf)} polygons", "success")
                st.markdown(f'<div class="sfx-ok">✅ {len(rdf)} polygons generated!</div>', unsafe_allow_html=True)
                if skip:
                    add_log(f"Skipped pincodes: {', '.join(skip)}", "warning")
                    st.markdown(f'<div class="sfx-warn">Skipped: {", ".join(skip)}</div>', unsafe_allow_html=True)
                st.download_button("Download CSV", open(csv_p, "rb").read(), os.path.basename(csv_p), key="dl_gcsv")
            except Exception as e:
                add_log(f"Polygon generation error: {str(e)}", "error")
                st.error(str(e)); import traceback; st.code(traceback.format_exc())
        st.markdown("---")
        _ul1, _ul2 = st.columns(2)
        with _ul1:
            pu = st.file_uploader("Or load polygon CSV", type=["csv"], key="up_poly2")
            if pu:
                st.session_state["polygon_records_df"] = pd.read_csv(pu)
                add_log("Polygon CSV loaded from upload", "success"); st.success("Loaded")
        with _ul2:
            pu_kml = st.file_uploader("Or load polygon KML", type=["kml", "xml"], key="up_poly_kml")
            if pu_kml:
                try:
                    import xml.etree.ElementTree as ET
                    _kml_ns = {"kml": "http://www.opengis.net/kml/2.2"}
                    _tree = ET.parse(pu_kml)
                    _root = _tree.getroot()
                    # Try both namespaced and non-namespaced tags
                    _placemarks = _root.findall(".//kml:Placemark", _kml_ns)
                    if not _placemarks:
                        _placemarks = _root.findall(".//Placemark")
                    _kml_rows = []
                    for _pm in _placemarks:
                        _name = (_pm.find("kml:name", _kml_ns) or _pm.find("name"))
                        _name = _name.text.strip() if _name is not None and _name.text else ""
                        _desc = (_pm.find("kml:description", _kml_ns) or _pm.find("description"))
                        _desc = _desc.text.strip() if _desc is not None and _desc.text else ""
                        # Polygon geometry
                        _poly_el = (_pm.find(".//kml:Polygon", _kml_ns) or _pm.find(".//Polygon"))
                        if _poly_el is None:
                            continue
                        _coords_el = (_poly_el.find(".//kml:outerBoundaryIs//kml:coordinates", _kml_ns)
                                      or _poly_el.find(".//outerBoundaryIs//coordinates"))
                        if _coords_el is None or not _coords_el.text:
                            continue
                        _pts = []
                        for _tok in _coords_el.text.strip().split():
                            _parts = _tok.split(",")
                            if len(_parts) >= 2:
                                try:
                                    _pts.append((float(_parts[0]), float(_parts[1])))
                                except ValueError:
                                    pass
                        if len(_pts) < 4:
                            continue
                        _wkt = "POLYGON((" + ", ".join(f"{x} {y}" for x, y in _pts) + "))"
                        _kml_rows.append({
                            "Cluster_Code": _name,
                            "Hub Name": "",
                            "Pincode": "",
                            "Cluster_Category": "",
                            "Description": "",
                            "Polygon WKT": _wkt,
                        })
                    if _kml_rows:
                        _kml_df = pd.DataFrame(_kml_rows)
                        existing = st.session_state.get("polygon_records_df")
                        if existing is not None and not existing.empty:
                            st.session_state["polygon_records_df"] = pd.concat([existing, _kml_df], ignore_index=True)
                        else:
                            st.session_state["polygon_records_df"] = _kml_df
                        add_log(f"KML loaded: {len(_kml_rows)} polygons", "success")
                        st.success(f"Loaded {len(_kml_rows)} polygons from KML")
                    else:
                        st.warning("No polygon placemarks found in KML file.")
                except Exception as _kml_err:
                    st.error(f"KML parse error: {_kml_err}")

    pdf = st.session_state.get("polygon_records_df")
    if pdf is not None:
        hub_col = "Hub Name" if "Hub Name" in pdf.columns else "hub_name"
        dpdf = pdf if hub_filter == "All Hubs" else pdf[pdf.get(hub_col, pd.Series()) == hub_filter]

        # KPI Cards
        st.markdown(f'''<div class="kpi-row">
            <div class="kpi-card"><div class="kpi-label">Polygons</div><div class="kpi-value">{len(dpdf)}</div></div>
            <div class="kpi-card blue"><div class="kpi-label">Pincodes</div><div class="kpi-value">{dpdf["Pincode"].nunique() if "Pincode" in dpdf.columns else 0}</div></div>
            <div class="kpi-card green"><div class="kpi-label">Hubs</div><div class="kpi-value">{dpdf[hub_col].nunique() if hub_col in dpdf.columns else 0}</div></div>
        </div>''', unsafe_allow_html=True)

        st.markdown('<div class="sfx-header">Polygon Editor</div>', unsafe_allow_html=True)
        edited = st.data_editor(dpdf, use_container_width=True, height=400, num_rows="dynamic", key="poly_ed")
        ec1, ec2, ec3 = st.columns(3)
        with ec1:
            if st.button("Save Changes", type="primary", key="save_poly"):
                if hub_filter == "All Hubs":
                    st.session_state["polygon_records_df"] = edited
                else:
                    full = st.session_state["polygon_records_df"]
                    full = full[full[hub_col] != hub_filter]
                    st.session_state["polygon_records_df"] = pd.concat([full, edited], ignore_index=True)
                st.session_state["polygon_records_df"].to_csv(os.path.join(OUTPUT_DIR, "Clustering_payout_polygon_edited.csv"), index=False, encoding="utf-8-sig")
                add_log("Polygon data saved", "success")
                st.markdown('<div class="sfx-ok">✅ Saved!</div>', unsafe_allow_html=True)
        with ec2:
            st.download_button("⬇ Download CSV", get_download_bytes(edited, "csv"), "polygon_edited.csv", "text/csv", key="dl_ed")
        with ec3:
            # Standalone KML download for the polygon data (no hub markers — raw polygon KML)
            _kml_wkt_col = "Polygon WKT" if "Polygon WKT" in edited.columns else ("boundary" if "boundary" in edited.columns else None)
            if _kml_wkt_col:
                try:
                    from shapely.wkt import loads as _kml_wkt_loads
                    def _xesc2(s):
                        return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")
                    _poly_marks = []
                    for _, _kr in edited.iterrows():
                        _wkt2 = _kr.get(_kml_wkt_col, "")
                        if pd.isna(_wkt2) or not _wkt2: continue
                        try:
                            _g2 = _kml_wkt_loads(str(_wkt2))
                        except Exception: continue
                        _polys2 = list(_g2.geoms) if _g2.geom_type == "MultiPolygon" else [_g2]
                        _nm2 = _xesc2(_kr.get("Cluster_Code", _kr.get("cluster_code", "")))
                        _desc2 = " | ".join(filter(None, [
                            f"Hub: {_xesc2(_kr.get(hub_col,''))}" if _kr.get(hub_col) else "",
                            f"Pincode: {_xesc2(_kr.get('Pincode',''))}" if _kr.get("Pincode") else "",
                            f"Rate: ₹{_xesc2(_kr.get('Description',''))}" if _kr.get("Description") else "",
                        ]))
                        for _pg2 in _polys2:
                            _ext2 = " ".join(f"{x},{y},0" for x,y in _pg2.exterior.coords)
                            _poly_marks.append(
                                f"<Placemark><name>{_nm2}</name><description>{_desc2}</description>"
                                f"<styleUrl>#polyStyle</styleUrl>"
                                f"<Polygon><outerBoundaryIs><LinearRing><coordinates>{_ext2}</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>"
                            )
                    _kml_raw = (
                        '<?xml version="1.0" encoding="UTF-8"?>'
                        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
                        f'<name>Polygons</name>'
                        '<Style id="polyStyle"><LineStyle><color>ff0B8A7A</color><width>2</width></LineStyle>'
                        '<PolyStyle><color>550B8A7A</color></PolyStyle></Style>'
                        + "".join(_poly_marks) + "</Document></kml>"
                    )
                    _scope2 = "AllHubs" if hub_filter == "All Hubs" else hub_filter.replace(" ","_").replace("/","_")
                    st.download_button(
                        "⬇ Download KML",
                        _kml_raw.encode("utf-8"),
                        f"polygons_{_scope2}.kml",
                        "application/vnd.google-earth.kml+xml",
                        key="dl_poly_kml",
                    )
                except Exception as _kml_ex:
                    st.caption(f"KML unavailable: {_kml_ex}")
            else:
                st.caption("No geometry column for KML")

        # ── Google My Maps-compatible export (polygons + hub point) ─────────
        st.markdown('<div class="sfx-header">Export for Google My Maps</div>', unsafe_allow_html=True)
        st.caption("Downloads polygons + hub location in one file. Upload the CSV or KML directly into Google My Maps.")
        mm_c1, mm_c2, mm_c3 = st.columns([2, 1, 1])
        with mm_c1:
            st.markdown(
                f"Scope: **{'All Hubs' if hub_filter == 'All Hubs' else hub_filter}** "
                f"({len(dpdf)} polygon row(s))"
            )
        export_wkt_col = "Polygon WKT" if "Polygon WKT" in dpdf.columns else ("boundary" if "boundary" in dpdf.columns else None)
        if export_wkt_col is None:
            st.warning("No polygon geometry column (Polygon WKT / boundary) found — regenerate polygons first.")
        else:
            hubs_for_export = [hub_filter] if hub_filter != "All Hubs" else cdf["Hub_Name"].dropna().unique().tolist()
            hub_loc_lookup = {}
            cdf2 = cdf.copy(); cdf2.columns = cdf2.columns.str.strip()
            for hn in hubs_for_export:
                hr = cdf2[cdf2["Hub_Name"] == hn]
                if not hr.empty:
                    try:
                        hub_loc_lookup[hn] = (float(hr.iloc[0]["Hub_lat"]), float(hr.iloc[0]["Hub_long"]))
                    except Exception:
                        pass

            with mm_c2:
                if st.button("⬇ CSV (My Maps)", key="mm_csv_btn", type="primary"):
                    rows = []
                    for hn, (hlat, hlon) in hub_loc_lookup.items():
                        rows.append({
                            "Name": f"HUB: {hn}",
                            "Type": "Hub",
                            "Hub Name": hn,
                            "Cluster_Code": "",
                            "Pincode": "",
                            "Cluster_Category": "",
                            "Rate": "",
                            "Latitude": hlat,
                            "Longitude": hlon,
                            "WKT": f"POINT({hlon} {hlat})",
                        })
                    for _, r in dpdf.iterrows():
                        wkt = r.get(export_wkt_col, "")
                        if pd.isna(wkt) or not wkt:
                            continue
                        rows.append({
                            "Name": str(r.get("Cluster_Code", r.get("cluster_code", ""))),
                            "Type": "Polygon",
                            "Hub Name": r.get(hub_col, ""),
                            "Cluster_Code": r.get("Cluster_Code", r.get("cluster_code", "")),
                            "Pincode": r.get("Pincode", r.get("pincode", "")),
                            "Cluster_Category": r.get("Cluster_Category", ""),
                            "Rate": r.get("Description", r.get("surge_amount", "")),
                            "Latitude": "",
                            "Longitude": "",
                            "WKT": str(wkt),
                        })
                    mm_df = pd.DataFrame(rows)
                    scope_slug = "AllHubs" if hub_filter == "All Hubs" else hub_filter.replace(" ", "_").replace("/", "_")
                    st.download_button(
                        "Download My Maps CSV",
                        mm_df.to_csv(index=False).encode("utf-8-sig"),
                        f"mymaps_{scope_slug}_{datetime.now().strftime('%Y%m%d')}.csv",
                        "text/csv",
                        key="mm_csv_dl",
                    )
                    st.caption("In My Maps: **Import** → select this CSV → positioning column = **WKT** → title column = **Name**.")

            with mm_c3:
                if st.button("⬇ KML (My Maps)", key="mm_kml_btn"):
                    try:
                        from shapely.wkt import loads as _mm_wkt
                        def _xesc(s):
                            return (str(s).replace("&", "&amp;").replace("<", "&lt;")
                                    .replace(">", "&gt;").replace('"', "&quot;"))
                        placemarks = []
                        for hn, (hlat, hlon) in hub_loc_lookup.items():
                            placemarks.append(
                                f"<Placemark><name>HUB: {_xesc(hn)}</name>"
                                f"<styleUrl>#hubStyle</styleUrl>"
                                f"<Point><coordinates>{hlon},{hlat},0</coordinates></Point></Placemark>"
                            )
                        for _, r in dpdf.iterrows():
                            wkt = r.get(export_wkt_col, "")
                            if pd.isna(wkt) or not wkt:
                                continue
                            try:
                                g = _mm_wkt(str(wkt))
                            except Exception:
                                continue
                            polys = list(g.geoms) if g.geom_type == "MultiPolygon" else [g]
                            name_val = _xesc(r.get("Cluster_Code", r.get("cluster_code", "")))
                            desc_bits = []
                            for k_lab, k_field in [("Hub", hub_col), ("Pincode", "Pincode"),
                                                   ("Category", "Cluster_Category"), ("Rate", "Description")]:
                                if k_field in r and not pd.isna(r[k_field]):
                                    desc_bits.append(f"{k_lab}: {_xesc(r[k_field])}")
                            desc = " | ".join(desc_bits)
                            for pg in polys:
                                ext = " ".join(f"{x},{y},0" for x, y in pg.exterior.coords)
                                inner = "".join(
                                    f"<innerBoundaryIs><LinearRing><coordinates>"
                                    f"{' '.join(f'{x},{y},0' for x, y in ring.coords)}"
                                    f"</coordinates></LinearRing></innerBoundaryIs>"
                                    for ring in pg.interiors
                                )
                                placemarks.append(
                                    f"<Placemark><name>{name_val}</name>"
                                    f"<description>{desc}</description>"
                                    f"<styleUrl>#polyStyle</styleUrl>"
                                    f"<Polygon><outerBoundaryIs><LinearRing><coordinates>{ext}</coordinates>"
                                    f"</LinearRing></outerBoundaryIs>{inner}</Polygon></Placemark>"
                                )
                        kml = (
                            '<?xml version="1.0" encoding="UTF-8"?>'
                            '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
                            f"<name>Polygons - {_xesc(hub_filter)}</name>"
                            '<Style id="hubStyle"><IconStyle><color>ff0000ff</color><scale>1.2</scale>'
                            '<Icon><href>http://maps.google.com/mapfiles/kml/paddle/red-stars.png</href></Icon></IconStyle></Style>'
                            '<Style id="polyStyle"><LineStyle><color>ff984e00</color><width>2</width></LineStyle>'
                            '<PolyStyle><color>55984e00</color></PolyStyle></Style>'
                            + "".join(placemarks)
                            + "</Document></kml>"
                        )
                        scope_slug = "AllHubs" if hub_filter == "All Hubs" else hub_filter.replace(" ", "_").replace("/", "_")
                        st.download_button(
                            "Download My Maps KML",
                            kml.encode("utf-8"),
                            f"mymaps_{scope_slug}_{datetime.now().strftime('%Y%m%d')}.kml",
                            "application/vnd.google-earth.kml+xml",
                            key="mm_kml_dl",
                        )
                        st.caption("In My Maps: **Import** → select this KML. Hubs render as red stars, polygons as filled shapes.")
                    except Exception as e:
                        st.error(f"KML export error: {e}")

        st.markdown('<div class="sfx-header">Map</div>', unsafe_allow_html=True)
        st.caption("Use the layer control (top-right) to switch between Street / Satellite / Terrain views.")
        _s3mc1, _s3mc2, _s3mc3, _s3mc4 = st.columns([2, 1, 1, 1])
        with _s3mc1:
            edit_polygons = st.toggle(
                "🎨 Edit Polygons (Reshape / Draw / Delete)",
                key="s3_edit_polygons",
                value=False,
                help="Single hub only. Drag vertices to reshape, draw new polygons, or delete existing ones.",
            )
            if not edit_polygons:
                st.session_state.pop("_s3_drawings", None)
        with _s3mc2:
            s3_rate_filter = st.selectbox("Rate Filter", ["All"] + [f"₹{i}" for i in range(0, 9)] + ["Nil"], key="s3_map_rate")
        with _s3mc3:
            s3_viz_mode = st.radio("View Mode", ["Default", "Burn"], horizontal=True, key="s3_viz_mode",
                                   help="Burn: color polygons by financial burn (requires AWB data from Step 4)")
        with _s3mc4:
            s3_show_rate_labels = st.checkbox("Show Rate Labels", value=True, key="s3_show_rate_labels")
        if edit_polygons and hub_filter == "All Hubs":
            st.warning("⚠️ Select a single hub from the filter above to enable editing. Editing is disabled for 'All Hubs' view.")
            edit_polygons = False
        if not edit_polygons:
            st.session_state.pop("_s3_drawings", None)
            st.session_state.pop("_s3_import_done", None)
        if edit_polygons:
            st.info(
                "**Leaflet-Geoman editor — reliable vertex editing:**  \n"
                "1️⃣ Click **✏ Edit** (pencil icon) on the map left toolbar — all polygons become editable  \n"
                "2️⃣ Drag any **orange vertex handle** to reshape the polygon boundary  \n"
                "3️⃣ Click **📋 Copy Edited GeoJSON** button (top of map) — copies CSV to clipboard  \n"
                "4️⃣ Paste into the **Import field below the map** → click **Save**"
            )
        try:
            import folium
            from streamlit_folium import st_folium
            import streamlit.components.v1 as components
            from modules.visualizer import create_polygon_map_cached, create_editable_polygon_map, _df_hash
            if edit_polygons:
                # ── GEOMAN EDITOR (replaces unreliable streamlit-folium editing) ──
                from modules.geoman_editor import build_geoman_editor_html
                _geoman_html = build_geoman_editor_html(pdf, hub_filter=hub_filter, height=660)
                components.html(_geoman_html, height=660, scrolling=False)
                # Legacy streamlit-folium edit map (kept as fallback for data capture)
                map_out_s3 = None
                # Buffer all_drawings if available from previous interaction
                if False:  # Disabled — Geoman handles editing directly
                    m, edit_fg = create_editable_polygon_map(pdf, cdf, hub_filter=hub_filter, satellite=False)
                # Geoman handles editing — no st_folium needed here
                map_out_s3 = None

                # ── Import edited polygons (pasted from Geoman map) ───────────
                st.markdown('<div class="sfx-header">💾 Import Edited Polygons</div>', unsafe_allow_html=True)
                st.info(
                    "**Edit vertices:** click ✏️ Edit Vertices → drag → click 📋 Copy → paste below → Save.  \n"
                    "**Delete polygon:** click 🗑 Delete Polygon → click the red polygon → "
                    "the updated CSV is **auto-copied to clipboard** → paste below → Save."
                )
                _sc1, _sc2 = st.columns(2)
                # Show Save button only when there's pasted data
                _geoman_paste = st.text_area(
                    "Paste edited polygon CSV here",
                    key="s3_geoman_paste",
                    placeholder='Paste CSV from "Copy Edited GeoJSON" button above...',
                    height=100,
                )
                # Clear paste guard when textarea is cleared
                if not _geoman_paste:
                    st.session_state.pop("_s3_import_done", None)
                with _sc1:
                    if st.button("💾 Save Pasted Edits", type="primary", key="s3_save_paste",
                                 disabled=not bool(_geoman_paste),
                                 help="Paste the CSV from the map above first"):
                        if not _geoman_paste.strip():
                            st.error("Paste the CSV from the map's 'Copy Edited GeoJSON' button first.")
                        elif st.session_state.get("_s3_import_done"):
                            st.info("Already saved. Clear the text area to save again.")
                        else:
                            st.session_state["_s3_import_done"] = True
                            try:
                                import io as _io
                                _imp = pd.read_csv(_io.StringIO(_geoman_paste.strip()))
                                _poly_s3 = st.session_state.get("polygon_records_df").copy()
                                _wc_s3 = "Polygon WKT" if "Polygon WKT" in _poly_s3.columns else "boundary"
                                _cc_s3 = "Cluster_Code" if "Cluster_Code" in _poly_s3.columns else "cluster_code"
                                st.session_state.setdefault("edit_undo_stack", []).append(_poly_s3.copy())
                                _updated_s3 = 0
                                for _, _ir in _imp.iterrows():
                                    _cc_val = str(_ir.get("cluster_code", "")).strip()
                                    _wkt_val = str(_ir.get("geometry_wkt", "")).strip()
                                    if not _cc_val or not _wkt_val:
                                        continue
                                    _mask = _poly_s3[_cc_s3].astype(str).str.strip() == _cc_val
                                    if _mask.any():
                                        _poly_s3.loc[_mask, _wc_s3] = _wkt_val
                                        _updated_s3 += 1
                                    else:
                                        # New polygon — map CSV lowercase cols to DataFrame title-case cols
                                        _col_map = {
                                            "hub_name": "Hub Name",
                                            "pincode": "Pincode",
                                            "description": "Description",
                                            "cluster_category": "Cluster_Category",
                                        }
                                        _new_row = {_wc_s3: _wkt_val, _cc_s3: _cc_val}
                                        for _k, _v in _ir.items():
                                            if _k in ("cluster_code", "geometry_wkt"):
                                                continue
                                            _dest = _col_map.get(_k, _k)
                                            _new_row[_dest] = _v
                                        # Inherit hub from filter if not set
                                        if not _new_row.get("Hub Name") and hub_filter not in ("All Hubs", "All"):
                                            _new_row["Hub Name"] = hub_filter
                                        _poly_s3 = pd.concat([_poly_s3, pd.DataFrame([_new_row])], ignore_index=True)
                                        _updated_s3 += 1
                                # ── Remove polygons the user deleted in the editor ──
                                # Any polygon that was in this hub BEFORE editing but is
                                # ABSENT from the pasted CSV has been deleted.  We scope
                                # the removal to the currently-filtered hub so polygons
                                # from other hubs are never accidentally removed.
                                _pasted_codes = set(
                                    _imp["cluster_code"].astype(str).str.strip().tolist()
                                )
                                _hub_col_s3 = (
                                    "Hub Name" if "Hub Name" in _poly_s3.columns
                                    else "hub_name"
                                )
                                if hub_filter and hub_filter not in ("All Hubs", "All"):
                                    _in_hub_mask = (
                                        _poly_s3[_hub_col_s3].astype(str).str.strip()
                                        == hub_filter
                                    )
                                    _to_del = (
                                        _in_hub_mask
                                        & ~_poly_s3[_cc_s3].astype(str).str.strip()
                                        .isin(_pasted_codes)
                                    )
                                else:
                                    # All-hubs paste: remove anything not in pasted CSV
                                    _to_del = ~_poly_s3[_cc_s3].astype(str).str.strip().isin(_pasted_codes)
                                _n_deleted = int(_to_del.sum())
                                if _n_deleted > 0:
                                    _poly_s3 = _poly_s3[~_to_del].reset_index(drop=True)
                                    _updated_s3 += _n_deleted  # count towards change total

                                st.session_state["polygon_records_df"] = _poly_s3
                                try:
                                    _poly_s3.to_csv(os.path.join(OUTPUT_DIR, "Clustering_payout_polygon_edited.csv"),
                                                    index=False, encoding="utf-8-sig")
                                except Exception:
                                    pass
                                _del_msg = f", {_n_deleted} deleted" if _n_deleted > 0 else ""
                                add_log(f"Geoman: saved {_updated_s3} polygon changes ({_n_deleted} deleted)", "success")
                                st.success(f"✅ Saved {_updated_s3} polygon changes{_del_msg}!")
                                st.rerun()
                            except Exception as _pe:
                                st.session_state.pop("_s3_import_done", None)
                                st.error(f"Parse error: {_pe} — Make sure you copied the CSV from the map button.")
                # (Geoman import block above handles all saving)
                with _sc2:
                    if st.session_state.get("edit_undo_stack") and st.button("↶ Undo Last Edit", key="s3_undo_btn"):
                        st.session_state["polygon_records_df"] = st.session_state["edit_undo_stack"].pop()
                        st.session_state["_s3_drawings"] = []
                        add_log("Undid last polygon edit", "warning")
                        st.rerun()

                # ── New Polygon Metadata Form ──────────────────────────────
                pending_new = st.session_state.get("_pending_new_polys")
                if pending_new:
                    st.markdown('<div class="sfx-header">🆕 Name Your New Polygon(s)</div>', unsafe_allow_html=True)
                    st.info(f"You drew **{len(pending_new)} new polygon(s)**. Fill in the details below:")
                    for _pn_idx, _pn_item in enumerate(pending_new):
                        with st.form(key=f"s3_new_poly_form_{_pn_idx}"):
                            st.write(f"**Polygon {_pn_idx + 1}**")
                            _nc1, _nc2 = st.columns(2)
                            with _nc1:
                                new_code = st.text_input("Cluster Code *", placeholder="e.g. 400701_A", key=f"s3_code_{_pn_idx}")
                                new_pin  = st.text_input("Pincode", placeholder="e.g. 400701", key=f"s3_pin_{_pn_idx}")
                            with _nc2:
                                new_rate = st.number_input("Surge Rate ₹", min_value=0.0, max_value=20.0, step=0.5, key=f"s3_rate_{_pn_idx}")
                                new_cat  = st.text_input("Category", placeholder="e.g. C3", key=f"s3_cat_{_pn_idx}")
                            if st.form_submit_button("✅ Add this polygon", type="primary"):
                                if not new_code.strip():
                                    st.error("Cluster Code is required.")
                                else:
                                    poly_df = st.session_state.get("polygon_records_df").copy()
                                    target_hub = st.session_state.get("_pending_new_polys_hub", hub_filter)
                                    _wc_new = "Polygon WKT" if "Polygon WKT" in poly_df.columns else "boundary"
                                    new_row = dict(_pn_item)
                                    new_row.update({
                                        "Cluster_Code": new_code.strip(),
                                        hub_col: target_hub,
                                        "Description": str(int(new_rate)) if new_rate == int(new_rate) else str(new_rate),
                                        "Cluster_Category": new_cat.strip(),
                                        "Pincode": new_pin.strip(),
                                        "surge_amount": new_rate,
                                    })
                                    poly_df = pd.concat([poly_df, pd.DataFrame([new_row])], ignore_index=True)
                                    # Remove this item from pending list
                                    remaining = [p for j, p in enumerate(pending_new) if j != _pn_idx]
                                    st.session_state["polygon_records_df"] = poly_df
                                    st.session_state["_pending_new_polys"] = remaining if remaining else None
                                    st.session_state["_pending_new_polys_hub"] = target_hub if remaining else None
                                    try:
                                        poly_df.to_csv(os.path.join(OUTPUT_DIR, "Clustering_payout_polygon_edited.csv"),
                                                      index=False, encoding="utf-8-sig")
                                    except Exception:
                                        pass
                                    add_log(f"Added new polygon {new_code} to {target_hub}", "success")
                                    st.success(f"✅ Polygon '{new_code}' added!")
                                    st.rerun()

                # (end of edit_polygons block)

            else:
                _s3_awb = st.session_state.get("final_result_df")
                _s3_vm = s3_viz_mode.lower() if s3_viz_mode != "Default" else "none"
                html = create_polygon_map_cached(
                    _df_hash(pdf), _df_hash(cdf), _df_hash(_s3_awb),
                    pdf, cdf, _s3_awb, False, _s3_vm, hub_filter, s3_rate_filter, None,
                    s3_show_rate_labels,
                )
                if html:
                    components.html(html, height=620, scrolling=False)
        except ImportError:
            st.info("Install folium for maps.")

        st.markdown('<div class="sfx-header">Hub Images</div>', unsafe_allow_html=True)
        if st.button("Generate Hub Images", key="gen_img"):
            try:
                import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
                from shapely.wkt import loads as wkt_loads
                import geopandas as gpd
                import contextily as ctx
                out_dir = HUB_IMG_DIR; ensure_output_dirs()
                all_hubs = pdf[hub_col].unique().tolist(); hcm = get_hub_color_map(all_hubs)
                _img_status = st.status(f"Generating {len(all_hubs)} hub image(s)...", expanded=True)
                for hi, hn in enumerate(all_hubs):
                    _img_status.update(label=f"Rendering {hn} ({hi + 1}/{len(all_hubs)})...", state="running")
                    hps = pdf[pdf[hub_col] == hn]
                    if hps.empty:
                        continue
                    cdf2 = cdf.copy(); cdf2.columns = cdf2.columns.str.strip(); hi2 = cdf2[cdf2["Hub_Name"] == hn]
                    if hi2.empty:
                        continue
                    hlat, hlon = float(hi2.iloc[0]["Hub_lat"]), float(hi2.iloc[0]["Hub_long"])
                    fig, ax = plt.subplots(figsize=(14, 10))
                    # Collect polygons for basemap bounds
                    polys_for_gdf = []
                    poly_labels = []
                    for _, row in hps.iterrows():
                        wkt = row.get("Polygon WKT", "")
                        if pd.isna(wkt) or not wkt:
                            continue
                        try:
                            poly = wkt_loads(wkt)
                            polys_for_gdf.append(poly)
                            poly_labels.append(str(row.get("Description", "")))
                        except:
                            pass
                    if polys_for_gdf:
                        # Create GeoDataFrame in EPSG:4326, then reproject to Web Mercator for contextily
                        gdf = gpd.GeoDataFrame({"label": poly_labels}, geometry=polys_for_gdf, crs="EPSG:4326")
                        gdf_wm = gdf.to_crs(epsg=3857)
                        # Plot polygons — transparent fill with visible outlines
                        gdf_wm.plot(ax=ax, alpha=0.25, color=hcm.get(hn, "#3498db"), edgecolor="black", linewidth=1.5, zorder=2)
                        # Add payout labels — use representative_point() so labels land inside
                        # the polygon ring, not at the centroid of the hole (hub location)
                        for idx_p, row_p in gdf_wm.iterrows():
                            rep_pt = row_p.geometry.representative_point()
                            cx, cy = rep_pt.x, rep_pt.y
                            ax.text(cx, cy, row_p["label"], ha="center", va="center", fontsize=9, fontweight="bold",
                                    bbox=dict(facecolor="white", edgecolor="none", alpha=0.85, boxstyle="round,pad=0.3"), zorder=6)
                        # Plot hub marker (reproject hub point to Web Mercator)
                        hub_gdf = gpd.GeoDataFrame(geometry=[gpd.points_from_xy([hlon], [hlat])[0]], crs="EPSG:4326").to_crs(epsg=3857)
                        hub_x, hub_y = hub_gdf.geometry.iloc[0].x, hub_gdf.geometry.iloc[0].y
                        ax.plot(hub_x, hub_y, "r^", markersize=14, zorder=5)
                        # Add OpenStreetMap basemap
                        try:
                            ctx.add_basemap(ax, source=ctx.providers.OpenStreetMap.Mapnik, zoom='auto')
                        except Exception:
                            try:
                                ctx.add_basemap(ax, source=ctx.providers.CartoDB.Positron, zoom='auto')
                            except Exception:
                                pass
                    else:
                        ax.plot(hlon, hlat, "r^", markersize=14, zorder=5)
                    ax.set_title(hn, fontsize=14, fontweight="bold", color="#0B8A7A")
                    # Remove axes/scale — user doesn't want any scale
                    ax.set_axis_off()
                    path = os.path.join(out_dir, f"{hn.replace(' ', '_').replace('/', '_')}_Full_View.png")
                    plt.savefig(path, dpi=200, bbox_inches="tight", facecolor="white", pad_inches=0.1)
                    plt.close(fig)
                    plt.close("all")  # Release any leaked figure references
                    gc.collect()
                    st.session_state["hub_images"][hn] = path
                _img_status.update(label=f"✅ {len(all_hubs)} hub image(s) generated", state="complete", expanded=False)
                add_log(f"Generated {len(all_hubs)} hub images", "success")
                st.markdown(f'<div class="sfx-ok">✅ {len(all_hubs)} images generated</div>', unsafe_allow_html=True)
            except Exception as e:
                st.error(str(e))
        hub_images = st.session_state.get("hub_images", {})
        existing_hub_images = {hn: p for hn, p in hub_images.items() if os.path.exists(p)}
        if existing_hub_images:
            import zipfile
            zip_buf = BytesIO()
            with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for hn, p in existing_hub_images.items():
                    zf.write(p, os.path.basename(p))
            zip_buf.seek(0)
            st.download_button(
                "⬇ Download All Hub Images (ZIP)",
                zip_buf.read(),
                "hub_images.zip",
                "application/zip",
                key="dl_all_hub_imgs",
                type="primary",
            )
        for hn, path in existing_hub_images.items():
            with st.expander(f"{hn}"):
                st.image(path, use_container_width=True)
                st.download_button(f"Download {hn}", open(path, "rb").read(), os.path.basename(path), "image/png", key=f"di_{hn}")

# ═══════════════════════════════════════════════════════
# STEP 4 — AWB + VISUALISATION
# ═══════════════════════════════════════════════════════
elif nav.startswith("4"):
    st.markdown('<div class="sfx-header">Step 4 — AWB Analysis + Visualisation</div>', unsafe_allow_html=True)
    st1, st2, st3 = st.tabs(["Fetch AWB Data", "Assign + Financials", "Hub Visualisation"])

    with st1:
        bq_client = st.session_state.get("bq_client")
        bq_mode = st.session_state.get("bq_auth_mode")
        cdf = st.session_state.get("cluster_df")

        if bq_client:
            mode_label = {"adc": "Local Auth", "google_oauth": "Google Account", "service_account": "Service Account", "streamlit_secrets": "Cloud Secrets"}.get(bq_mode, bq_mode)
            st.markdown(f'<div class="sfx-ok">BigQuery Connected ({mode_label})</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="sfx-err">BigQuery not connected. Use <b>Login with Google</b> in the sidebar, or upload a Service Account JSON key.</div>', unsafe_allow_html=True)

        last_fetch = st.session_state.get("last_bq_fetch")
        if last_fetch:
            st.caption(f"Data cached. Last fetched: {last_fetch.strftime('%Y-%m-%d %H:%M:%S')}")

        fc1, fc2 = st.columns(2)
        with fc1:
            fetch_btn = st.button("Fetch AWB Data from BigQuery", type="primary", key="fetch_awb", disabled=(bq_client is None or cdf is None))
        with fc2:
            refresh_btn = st.button("Force Refresh (ignore cache)", key="refresh_awb", disabled=(bq_client is None or cdf is None))

        if cdf is None:
            st.markdown('<div class="sfx-warn">Upload Clustering Automation CSV first (Step 1).</div>', unsafe_allow_html=True)

        do_fetch = fetch_btn or refresh_btn
        if fetch_btn and last_fetch and st.session_state.get("awb_raw_df") is not None:
            elapsed = (datetime.now() - last_fetch).total_seconds()
            if elapsed < 3600 and not refresh_btn:
                st.info(f"Using cached data ({int(elapsed / 60)}min old). Click 'Force Refresh' to re-fetch.")
                do_fetch = False

        if do_fetch and bq_client and cdf is not None:
            from modules.bigquery_client import fetch_awb_data
            pincodes = cdf["Pincode"].astype(str).str.strip().str.replace(".0", "", regex=False).tolist()
            st.caption(f"Querying {len(pincodes)} pincodes: {', '.join(pincodes[:10])}{'...' if len(pincodes) > 10 else ''}")
            start_time = time.time(); add_log("BigQuery AWB fetch started", "info")
            with st.status("Fetching AWB data from BigQuery...", expanded=True) as _bq_status:
                st.write(f"Querying {len(pincodes)} pincodes (30–60 s)...")
                result_df, error = fetch_awb_data(bq_client, cdf)
            elapsed = time.time() - start_time
            if error:
                _bq_status.update(label="❌ BigQuery query failed", state="error", expanded=True)
                add_log(f"BigQuery error: {error}", "error")
                st.markdown(f'<div class="sfx-err">{error}</div>', unsafe_allow_html=True)
                if st.button("Retry", key="retry_awb"):
                    st.rerun()
            else:
                _bq_status.update(label=f"✅ {len(result_df):,} rows fetched in {elapsed:.1f}s", state="complete", expanded=False)
                st.session_state["awb_raw_df"] = result_df; st.session_state["last_bq_fetch"] = datetime.now()
                add_log(f"AWB data fetched: {len(result_df):,} rows in {elapsed:.1f}s", "success")
                st.markdown(f'<div class="sfx-ok">✅ {len(result_df):,} rows fetched in {elapsed:.1f}s</div>', unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("#### Or load AWB data from CSV")
        af = st.file_uploader("Upload Awb_with_polygon_mapping.csv", type=["csv"], key="up_awb_csv")
        if af:
            df = pd.read_csv(af); st.session_state["awb_raw_df"] = df; st.session_state["last_bq_fetch"] = datetime.now()
            add_log(f"AWB CSV loaded: {len(df):,} rows", "success")
            st.markdown(f'<div class="sfx-ok">✅ Loaded {len(df):,} rows from CSV</div>', unsafe_allow_html=True)

        awb = st.session_state.get("awb_raw_df")
        if awb is not None:
            st.markdown('<div class="sfx-header">AWB Data Preview</div>', unsafe_allow_html=True)
            st.dataframe(awb.head(10), use_container_width=True, height=300)
            st.caption(f"Total rows: {len(awb):,}")
            st.download_button("Download Awb_with_polygon_mapping.csv", get_download_bytes(awb, "csv"), "Awb_with_polygon_mapping.csv", "text/csv", key="dl_awb_raw")

    with st2:
        st.markdown('<div class="sfx-header">Cluster Assignment + P&L</div>', unsafe_allow_html=True)
        awb = st.session_state.get("awb_raw_df"); poly = st.session_state.get("polygon_records_df"); fodf = st.session_state.get("final_output_df")
        if awb is None:
            st.markdown('<div class="sfx-warn">Fetch or load AWB data first.</div>', unsafe_allow_html=True)
        elif poly is None:
            st.markdown('<div class="sfx-warn">Generate or load polygon data first (Step 3).</div>', unsafe_allow_html=True)
        elif fodf is None:
            st.markdown('<div class="sfx-warn">Run P-Mapping first (Step 2).</div>', unsafe_allow_html=True)
        else:
            st.caption(f"Ready: {len(awb):,} AWBs x {len(poly)} polygons")
            if st.button("Assign Clusters + Calculate P&L", type="primary", key="assign"):
                try:
                    from modules.cluster_assignor import assign_clusters, build_spa_mapping, calculate_financials
                    spa = build_spa_mapping(fodf); add_log("Cluster assignment started", "info")
                    prog = st.progress(0, "Assigning clusters...")
                    start = time.time()
                    res = assign_clusters(awb, poly, spa, progress_cb=lambda p: prog.progress(p))
                    prog.empty(); fin = calculate_financials(res)
                    st.session_state["final_result_df"] = fin; fin.to_csv(os.path.join(OUTPUT_DIR, "Awb_with_cluster_info.csv"), index=False)
                    el = time.time() - start
                    add_log(f"P&L calculated: {len(fin):,} AWBs in {el:.1f}s", "success")
                    st.markdown(f'<div class="sfx-ok">✅ {len(fin):,} AWBs processed in {el:.1f}s</div>', unsafe_allow_html=True)
                except Exception as e:
                    add_log(f"Cluster assignment error: {str(e)}", "error")
                    st.error(str(e)); import traceback; st.code(traceback.format_exc())

        rdf = st.session_state.get("final_result_df")
        if rdf is not None and "Pin_Pay" in rdf.columns:
            st.markdown(f'''<div class="kpi-row">
                <div class="kpi-card blue"><div class="kpi-label">Pin Pay</div><div class="kpi-value">₹{rdf["Pin_Pay"].sum():,.0f}</div></div>
                <div class="kpi-card purple"><div class="kpi-label">Cluster Pay</div><div class="kpi-value">₹{rdf["Clustering_payout"].sum():,.0f}</div></div>
                <div class="kpi-card green"><div class="kpi-label">Saving</div><div class="kpi-value">₹{rdf["Saving"].sum():,.0f}</div></div>
                <div class="kpi-card red"><div class="kpi-label">Burning</div><div class="kpi-value">₹{rdf["Burning"].sum():,.0f}</div></div>
            </div>''', unsafe_allow_html=True)
            show_df_download(rdf.head(200), "fin_data", "Financial Data (first 200)")

    with st3:
        st.markdown('<div class="sfx-header">Hub Visualisation Map</div>', unsafe_allow_html=True)
        poly = st.session_state.get("polygon_records_df"); cdf = st.session_state.get("cluster_df"); rdf = st.session_state.get("final_result_df")
        if poly is None:
            render_step_guard(["Polygon data"], "Generate polygons in Step 3, or load saved polygons via Step 1. The other two tabs on this page work without it.")
        hub_col = "Hub Name" if "Hub Name" in poly.columns else "hub_name"
        hubs = poly[hub_col].unique().tolist()
        vc1, vc2, vc3, vc4, vc5 = st.columns(5)
        with vc1:
            sel_hub = st.selectbox("Hub", ["All Hubs"] + hubs, key="viz_hub")
        with vc2:
            viz_mode = st.radio("Shipment View", ["Burn", "Heatmap", "Dots"], horizontal=True, key="viz_mode")
        with vc3:
            edit_mode_s4 = st.toggle("Edit Mode", key="s4_edit_mode", value=False)
            if not edit_mode_s4:
                st.session_state.pop("_s4_drawings", None)
        with vc4:
            rate_filter = st.selectbox("Rate Filter", ["All"] + [f"₹{i}" for i in range(0, 9)] + ["Nil"], key="viz_rate")
        with vc5:
            s4_show_rate_labels = st.checkbox("Show Rate Labels", value=True, key="s4_show_rate_labels")
        hub_type = "All Types"
        st.caption("Use the layer control (top-right) to switch between Street / Satellite / Terrain views.")
        if not edit_mode_s4:
            st.session_state.pop("_s4_import_done", None)
            st.session_state.pop("s4_geoman_paste", None)
        if edit_mode_s4:
            st.info(
                "**Polygon Editor (Leaflet.draw) — same as Step 3:**  \n"
                "✏️ Edit Vertices | 🖐 Move Polygon | ✚ Draw New | 🗑 Delete  \n"
                "After editing → **📋 Copy Edited Polygons** → paste below → **Save**"
            )
        try:
            import folium
            from streamlit_folium import st_folium
            import streamlit.components.v1 as components
            from modules.visualizer import create_polygon_map, create_polygon_map_cached, create_editable_polygon_map, _df_hash
            if edit_mode_s4:
                # Edit mode: Geoman/Leaflet.draw editor (same as Step 3)
                # Uses the verified working Leaflet.draw + cdnjs CDN approach.
                from modules.geoman_editor import build_geoman_editor_html as _s4_build_editor
                st.info(
                    "**How to edit polygons:**  \n"
                    "1️⃣ Click **✏️ Edit Vertices** button → drag orange handles to reshape  \n"
                    "2️⃣ Use **✚ Draw New Polygon** to add a new cluster boundary  \n"
                    "3️⃣ Click **📋 Copy Edited Polygons (CSV)** → paste below → **Save**  \n"
                    "💡 Also: use the **Leaflet toolbar** (top-left of map) for the same tools"
                )
                _s4_awb_df = st.session_state.get("awb_raw_df")
                _s4_geoman_html = _s4_build_editor(poly, hub_filter=sel_hub, height=660, awb_df=_s4_awb_df)
                components.html(_s4_geoman_html, height=660, scrolling=False)
                map_out_s4 = None  # components.html has no return value
            else:
                # Non-edit mode: use cached HTML for speed
                html = create_polygon_map_cached(
                    _df_hash(poly), _df_hash(cdf), _df_hash(rdf),
                    poly, cdf, rdf, False, viz_mode.lower(), sel_hub, rate_filter, None,
                    s4_show_rate_labels,
                )
                if html:
                    components.html(html, height=720, scrolling=False)
                map_out_s4 = None
            # ── Import Edited Polygons (same as Step 3) ───────────────────────
            if edit_mode_s4:
                st.markdown('<div class="sfx-header">💾 Import Edited Polygons</div>', unsafe_allow_html=True)
                st.info(
                    "**Steps:** In the map above → edit vertices → "
                    "click **📋 Copy Edited Polygons (CSV)** → paste below → **Save**."
                )
                _s4_paste = st.text_area(
                    "Paste edited polygon CSV here",
                    key="s4_geoman_paste",
                    placeholder='Paste CSV from "Copy Edited Polygons" button above...',
                    height=100,
                )
                if not _s4_paste:
                    st.session_state.pop("_s4_import_done", None)
                _s4c1, _s4c2 = st.columns(2)
                with _s4c1:
                    if st.button("💾 Save Pasted Edits", type="primary", key="s4_save_paste",
                                 disabled=not bool(_s4_paste)):
                        if st.session_state.get("_s4_import_done"):
                            st.info("Already saved. Clear text to save again.")
                        else:
                            st.session_state["_s4_import_done"] = True
                            try:
                                import io as _io4
                                _imp4 = pd.read_csv(_io4.StringIO(_s4_paste.strip()))
                                _poly4 = st.session_state.get("polygon_records_df").copy()
                                _wc4i = "Polygon WKT" if "Polygon WKT" in _poly4.columns else "boundary"
                                _cc4i = "Cluster_Code" if "Cluster_Code" in _poly4.columns else "cluster_code"
                                st.session_state.setdefault("edit_undo_stack", []).append(_poly4.copy())
                                _upd4 = 0
                                for _, _ir4 in _imp4.iterrows():
                                    _ccv = str(_ir4.get("cluster_code", "")).strip()
                                    _wv  = str(_ir4.get("geometry_wkt", "")).strip()
                                    if not _ccv or not _wv:
                                        continue
                                    _mask4 = _poly4[_cc4i].astype(str).str.strip() == _ccv
                                    if _mask4.any():
                                        _poly4.loc[_mask4, _wc4i] = _wv
                                        _upd4 += 1
                                    else:
                                        _col_map4 = {
                                            "hub_name": "Hub Name",
                                            "pincode": "Pincode",
                                            "description": "Description",
                                            "cluster_category": "Cluster_Category",
                                        }
                                        _nr4 = {_wc4i: _wv, _cc4i: _ccv}
                                        for _k4, _v4 in _ir4.items():
                                            if _k4 in ("cluster_code", "geometry_wkt"):
                                                continue
                                            _nr4[_col_map4.get(_k4, _k4)] = _v4
                                        if not _nr4.get("Hub Name") and sel_hub not in ("All Hubs", "All"):
                                            _nr4["Hub Name"] = sel_hub
                                        _poly4 = pd.concat([_poly4, pd.DataFrame([_nr4])], ignore_index=True)
                                        _upd4 += 1
                                st.session_state["polygon_records_df"] = _poly4
                                try:
                                    _poly4.to_csv(os.path.join(OUTPUT_DIR, "Clustering_payout_polygon_edited.csv"),
                                                  index=False, encoding="utf-8-sig")
                                except Exception:
                                    pass
                                add_log(f"Step4: saved {_upd4} polygon edits", "success")
                                st.success(f"✅ Saved {_upd4} polygon edits!")
                                st.rerun()
                            except Exception as _e4:
                                st.session_state.pop("_s4_import_done", None)
                                st.error(f"Parse error: {_e4}")
                with _s4c2:
                    if st.session_state.get("edit_undo_stack") and st.button("↶ Undo Last Edit", key="s4_undo_geoman"):
                        st.session_state["polygon_records_df"] = st.session_state["edit_undo_stack"].pop()
                        add_log("Undid last polygon edit (Step 4)", "warning")
                        st.rerun()

            if False:  # old click handlers — no longer needed with Geoman editor
                pass

            # ── AUTO-SAVE on Leaflet-Draw ✓ Save (Step 4) ────────────────────
            if edit_mode_s4 and map_out_s4 and map_out_s4.get("all_drawings"):
                from shapely.geometry import Polygon as _SP4
                from shapely.wkt import loads as _wl4a
                _draw4 = map_out_s4["all_drawings"]
                _pd4 = st.session_state.get("polygon_records_df").copy()
                _wc4 = "Polygon WKT" if "Polygon WKT" in _pd4.columns else "boundary"
                _hc4 = "Hub Name" if "Hub Name" in _pd4.columns else "hub_name"
                _undo4 = st.session_state.setdefault("edit_undo_stack", [])
                _undo4.append(_pd4.copy())
                if len(_undo4) > 10:
                    st.session_state["edit_undo_stack"] = _undo4[-10:]
                _iter4 = _pd4[_pd4[_hc4] == sel_hub] if sel_hub != "All Hubs" else _pd4
                _orig4 = []
                for _i4, _r4 in _iter4.iterrows():
                    try:
                        _g4 = _wl4a(str(_r4.get(_wc4, "")))
                        _orig4.append((_i4, _g4.centroid.x, _g4.centroid.y))
                    except Exception:
                        continue
                _matched4, _cnt4, _changed4 = set(), 0, False
                for _drw4 in _draw4:
                    if _drw4.get("geometry", {}).get("type") != "Polygon":
                        continue
                    _co4 = _drw4["geometry"].get("coordinates", [[]])[0]
                    if len(_co4) < 4:
                        continue
                    _np4 = _SP4([(_c[0], _c[1]) for _c in _co4])
                    _nw4 = "POLYGON((" + ", ".join(f"{_c[0]} {_c[1]}" for _c in _co4) + "))"
                    _cx4, _cy4 = _np4.centroid.x, _np4.centroid.y
                    _best4, _bd4 = None, float("inf")
                    for (_oi4, _ox4, _oy4) in _orig4:
                        if _oi4 in _matched4:
                            continue
                        _d4 = ((_ox4 - _cx4)**2 + (_oy4 - _cy4)**2)**0.5
                        if _d4 < _bd4 and _d4 < 0.05:
                            _bd4 = _d4; _best4 = _oi4
                    if _best4 is not None:
                        if _nw4 != str(_pd4.at[_best4, _wc4]):
                            _pd4.at[_best4, _wc4] = _nw4; _changed4 = True
                        _matched4.add(_best4); _cnt4 += 1
                _del4 = [_i for (_i, _, _) in _orig4 if _i not in _matched4]
                if _del4:
                    _pd4 = _pd4.drop(index=_del4).reset_index(drop=True); _changed4 = True
                # Only save+rerun if shapes actually changed (prevents infinite loop)
                if _changed4:
                    st.session_state["polygon_records_df"] = _pd4
                    try:
                        _pd4.to_csv(os.path.join(OUTPUT_DIR, "Clustering_payout_polygon_edited.csv"),
                                    index=False, encoding="utf-8-sig")
                    except Exception:
                        pass
                    add_log(f"[{sel_hub}] auto-saved: {_cnt4} reshaped, {len(_del4)} deleted", "success")
                    st.rerun()

            # Undo button
            if edit_mode_s4 and st.session_state.get("edit_undo_stack"):
                if st.button("↶ Undo Last Edit", key="s4_undo_btn"):
                    st.session_state["polygon_records_df"] = st.session_state["edit_undo_stack"].pop()
                    add_log("Undid last polygon edit (Step 4)", "warning")
                    st.rerun()

        except ImportError:
            st.info("Install folium for maps.")

        # ── Download Polygons ─────────────────────────────────────────────────
        if poly is not None and len(poly) > 0:
            st.markdown('<div class="sfx-header">Download Polygons</div>', unsafe_allow_html=True)
            _dl4 = poly.copy()
            _hcol_dl = "Hub Name" if "Hub Name" in _dl4.columns else "hub_name"
            if sel_hub != "All Hubs" and _hcol_dl in _dl4.columns:
                _dl4 = _dl4[_dl4[_hcol_dl] == sel_hub]
            _base4 = f"polygons_{sel_hub.replace(' ','_').replace('/','_')}_{datetime.now().strftime('%Y%m%d')}"
            _dc1, _dc2, _dc3 = st.columns(3)
            with _dc1:
                st.download_button("⬇ CSV", get_download_bytes(_dl4, "csv"), f"{_base4}.csv", "text/csv", key="s4_dl_csv")
            with _dc2:
                try:
                    from shapely.wkt import loads as _wl4g
                    from shapely.geometry import mapping as _sm4g
                    _wc4g = "Polygon WKT" if "Polygon WKT" in _dl4.columns else "boundary"
                    _feats4 = []
                    for _, _r in _dl4.iterrows():
                        try:
                            _g = _wl4g(str(_r.get(_wc4g, "")))
                            _props = {k: (None if pd.isna(v) else v) for k, v in _r.items() if k != _wc4g}
                            _feats4.append({"type": "Feature", "geometry": _sm4g(_g), "properties": _props})
                        except Exception:
                            continue
                    _fc4g = {"type": "FeatureCollection", "features": _feats4}
                    st.download_button("⬇ GeoJSON", json.dumps(_fc4g, default=str).encode("utf-8"), f"{_base4}.geojson", "application/geo+json", key="s4_dl_geojson")
                except Exception as _eg:
                    st.caption(f"GeoJSON error: {_eg}")
            with _dc3:
                try:
                    from modules.visualizer import generate_kml as _gkml4
                    _kml4 = _gkml4(_dl4)
                    if _kml4:
                        st.download_button("⬇ KML", _kml4.encode("utf-8"), f"{_base4}.kml", "application/vnd.google-earth.kml+xml", key="s4_dl_kml")
                except Exception as _ek:
                    st.caption(f"KML error: {_ek}")

# ═══════════════════════════════════════════════════════
# STEP 5 — FINANCIAL INTELLIGENCE
# ═══════════════════════════════════════════════════════
elif nav.startswith("5"):
    st.markdown('<div class="sfx-header">Step 5 — Financial Intelligence</div>', unsafe_allow_html=True)
    rdf = st.session_state.get("final_result_df")
    if rdf is None:
        render_step_guard(["AWB P&L results"], "Run Step 4 → Assign + Financials, or load saved results via Step 1.")
    if "Pin_Pay" not in rdf.columns:
        try:
            from modules.cluster_assignor import calculate_financials
            rdf = calculate_financials(rdf); st.session_state["final_result_df"] = rdf
        except Exception as e:
            st.error(str(e)); st.stop()

    try:
        from modules.dashboard_builder import build_pivot_report, style_report_html, compute_insights, build_comparison_table
        from modules.ai_agent import run_auto_analysis, chat_with_agent
        report = build_pivot_report(rdf); ins = compute_insights(report); comp = build_comparison_table(report)

        dtab1, dtab2, dtab3 = st.tabs(["Pivot Table", "P-Map vs Cluster", "AI Analysis"])

        with dtab1:
            # KPI Cards
            st.markdown(f'''<div class="kpi-row">
                <div class="kpi-card blue"><div class="kpi-label">Expected Pay</div><div class="kpi-value">₹{ins.get("total_expt_pincode_pay", 0):,.0f}</div></div>
                <div class="kpi-card purple"><div class="kpi-label">Cluster Payout</div><div class="kpi-value">₹{ins.get("total_cluster_payout", 0):,.0f}</div></div>
                <div class="kpi-card green"><div class="kpi-label">Saving</div><div class="kpi-value">₹{ins.get("total_saving", 0):,.0f}</div></div>
                <div class="kpi-card red"><div class="kpi-label">Burning</div><div class="kpi-value">₹{ins.get("total_burning", 0):,.0f}</div></div>
                <div class="kpi-card"><div class="kpi-label">Net P&L</div><div class="kpi-value">₹{ins.get("total_p___l", 0):,.0f}</div></div>
            </div>''', unsafe_allow_html=True)

            ic1, ic2 = st.columns(2)
            with ic1:
                b = ins.get("best_hub", "N/A"); bv = ins.get("best_hub_pl", 0)
                st.markdown(f'<div class="sfx-ok"><b style="color:var(--primary-color)">Best Hub: {b}</b><br>P&L: ₹{bv:,.0f}</div>', unsafe_allow_html=True)
            with ic2:
                w = ins.get("worst_hub", "N/A"); wv = ins.get("worst_hub_pl", 0)
                st.markdown(f'<div style="background:#FEF2F2;padding:16px;border-radius:8px;border-left:5px solid #EF4444"><b style="color:#EF4444">Worst Hub: {w}</b><br>P&L: ₹{wv:,.0f}</div>', unsafe_allow_html=True)

            st.markdown("---")
            st.markdown('<div class="sfx-header">Detailed P&L Report</div>', unsafe_allow_html=True)
            st.markdown(style_report_html(report), unsafe_allow_html=True)
            st.download_button("Download Report CSV", get_download_bytes(report, "csv"), "Pivot_Table.csv", "text/csv", key="dl_piv")
            with st.expander("Editable View"):
                st.data_editor(report, use_container_width=True, height=400)

        with dtab2:
            st.markdown('<div class="sfx-header">P-Mapping vs Cluster Comparison</div>', unsafe_allow_html=True)
            if comp is not None and not comp.empty:
                cl_w = (comp["Winner"] == "Cluster Cheaper").sum()
                pm_w = (comp["Winner"] == "P-Map Cheaper").sum()
                cl_s = comp[comp["Winner"] == "Cluster Cheaper"]["Saving_Amount"].sum()
                pm_s = comp[comp["Winner"] == "P-Map Cheaper"]["Saving_Amount"].sum()

                st.markdown(f'''<div class="kpi-row">
                    <div class="kpi-card green"><div class="kpi-label">Cluster Cheaper</div><div class="kpi-value">{cl_w} pincodes</div></div>
                    <div class="kpi-card red"><div class="kpi-label">P-Map Cheaper</div><div class="kpi-value">{pm_w} pincodes</div></div>
                    <div class="kpi-card green"><div class="kpi-label">Cluster Saves</div><div class="kpi-value">₹{cl_s:,.0f}</div></div>
                    <div class="kpi-card red"><div class="kpi-label">P-Map Saves</div><div class="kpi-value">₹{pm_s:,.0f}</div></div>
                </div>''', unsafe_allow_html=True)

                rec = "**Cluster-based payout**" if cl_s > pm_s else "**P-Mapping**"
                st.markdown(f'<div class="sfx-ok">Recommendation: {rec} saves ₹{max(cl_s, pm_s):,.0f}</div>', unsafe_allow_html=True)

                def color_row(row):
                    if row["Winner"] == "Cluster Cheaper":
                        return ["background:#EDF4EE"] * len(row)
                    elif row["Winner"] == "P-Map Cheaper":
                        return ["background:#FEF2F2"] * len(row)
                    return ["background:#F7FAF7"] * len(row)

                st.dataframe(comp.style.apply(color_row, axis=1).format({
                    "Expt_Pincode_Pay": "₹{:,.0f}", "Cluster_Payout": "₹{:,.0f}",
                    "Difference": "₹{:,.0f}", "Saving_Amount": "₹{:,.0f}",
                }), use_container_width=True, height=400)
                st.download_button("Download Comparison CSV", get_download_bytes(comp, "csv"), "Comparison.csv", "text/csv", key="dl_comp")
            else:
                st.info("Comparison requires financial data.")

        with dtab3:
            st.markdown('<div class="sfx-header">AI Analysis</div>', unsafe_allow_html=True)
            api_key = st.session_state.get("groq_api_key")
            if not api_key:
                st.markdown('<div class="sfx-warn">Enter free Groq API key in sidebar. Get it at <a href="https://console.groq.com" target="_blank">console.groq.com</a></div>', unsafe_allow_html=True)

            # Burn Analysis — All Hubs Combined
            st.markdown("#### Burn Analysis — All Hubs Combined")
            if st.button("Run Burn Analysis", type="primary", key="burn_analysis"):
                from modules.ai_agent import run_burn_analysis
                with st.spinner("Analyzing burn patterns across all hubs..."):
                    burn_report = run_burn_analysis(st.session_state, api_key)
                    st.session_state["burn_analysis_report"] = burn_report
                    add_log("Burn analysis complete", "success")
            if st.session_state.get("burn_analysis_report"):
                st.markdown(
                    f'<div class="sfx-card" style="border-left:4px solid #EF4444">'
                    f'<div style="font-weight:700;color:#EF4444;margin-bottom:8px;font-family:\'Work Sans\',sans-serif">Burn Analysis Report</div>'
                    f'{st.session_state["burn_analysis_report"]}</div>',
                    unsafe_allow_html=True
                )
            st.markdown("---")

            if st.session_state.get("ai_auto_report") is None:
                if st.button("Run Auto-Analysis", type="primary", key="ai_auto"):
                    with st.spinner("AI analyzing..."):
                        st.session_state["ai_auto_report"] = run_auto_analysis(report, ins, api_key)
                        add_log("AI auto-analysis complete", "success")
            if st.session_state.get("ai_auto_report"):
                st.markdown(f'<div class="sfx-card" style="border-left:4px solid #0B8A7A"><div style="font-weight:700;color:#0B8A7A;margin-bottom:8px;font-family:\'Work Sans\',sans-serif">Auto-Analysis</div>{st.session_state["ai_auto_report"]}</div>', unsafe_allow_html=True)

            st.markdown("---")
            st.markdown("#### Ask about the financial data")
            user_q = st.text_input("Question...", key="ai_q", placeholder="Which hub burns the most?")
            if user_q and st.button("Send", key="ai_send"):
                with st.spinner("Thinking..."):
                    answer = chat_with_agent(user_q, report, ins, st.session_state.get("ai_chat_history", []), api_key)
                    st.session_state["ai_chat_history"].append({"role": "user", "content": user_q})
                    st.session_state["ai_chat_history"].append({"role": "assistant", "content": answer})
            for msg in st.session_state.get("ai_chat_history", []):
                if msg["role"] == "user":
                    st.markdown(f'<div class="chat-user">{msg["content"]}</div>', unsafe_allow_html=True)
                else:
                    st.markdown(f'<div class="chat-assistant">{msg["content"]}</div>', unsafe_allow_html=True)
    except Exception as e:
        st.error(str(e)); import traceback; st.code(traceback.format_exc())

# ═══════════════════════════════════════════════════════
# STEP 6 — AI AGENT (Full App-Aware Assistant)
# ═══════════════════════════════════════════════════════
elif nav.startswith("6"):
    st.markdown('<div class="sfx-header">AI Agent — Geo Intelligence Assistant</div>', unsafe_allow_html=True)

    api_key = st.session_state.get("groq_api_key")
    if not api_key:
        st.markdown('<div class="sfx-warn">Enter your free Groq API key in the sidebar to enable AI. Get it at <a href="https://console.groq.com" target="_blank">console.groq.com</a></div>', unsafe_allow_html=True)

    # Suggested questions — Shadowfax-domain-specific
    st.markdown("#### Quick Questions")
    suggestions = [
        "Where are we burning money and why?",
        "Which hubs should we optimize first?",
        "How do I reduce burn without cutting rider pay?",
        "Why are AWBs landing in the wrong cluster?",
        "What does a good cluster configuration look like?",
        "Explain P-Mapping vs Cluster payout",
        "Which pincodes have the worst P&L?",
        "What should I do next in the pipeline?",
        "How do I fix the GPS drift issue?",
        "What is the difference between LM and SSC hubs?",
        "How do I calculate net P&L for a hub?",
        "Which cluster categories cause the most burn?",
    ]
    for row_start in range(0, len(suggestions), 4):
        row_cols = st.columns(4)
        for col_idx, sq in enumerate(suggestions[row_start:row_start+4]):
            with row_cols[col_idx]:
                if st.button(sq, key=f"sq_{row_start + col_idx}"):
                    st.session_state["agent_pending_q"] = sq

    st.markdown("---")

    # Chat history
    if "agent_chat_history" not in st.session_state:
        st.session_state["agent_chat_history"] = []

    for msg in st.session_state["agent_chat_history"]:
        if msg["role"] == "user":
            st.markdown(f'<div class="chat-user">{msg["content"]}</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="chat-assistant">{msg["content"]}</div>', unsafe_allow_html=True)

    # Input
    pending = st.session_state.pop("agent_pending_q", None)
    user_input = st.text_input("Ask the AI Agent...", value=pending or "", key="agent_input", placeholder="How does P-Mapping work? / Which hub burns the most?")
    if user_input and st.button("Send", type="primary", key="agent_send"):
        from modules.ai_agent import app_agent_chat
        with st.spinner("Thinking..."):
            answer = app_agent_chat(user_input, st.session_state, st.session_state["agent_chat_history"], api_key)
        st.session_state["agent_chat_history"].append({"role": "user", "content": user_input})
        st.session_state["agent_chat_history"].append({"role": "assistant", "content": answer})
        add_log("AI Agent query processed", "info")
        st.rerun()

    if st.button("Clear Chat", key="agent_clear"):
        st.session_state["agent_chat_history"] = []
        st.rerun()

    # Pipeline status card
    with st.expander("Current Pipeline State", expanded=False):
        from modules.ai_agent import build_app_context
        ctx = build_app_context(st.session_state)
        st.code(ctx, language="markdown")

# ═══════════════════════════════════════════════════════
# BOTTOM — Activity Log (always visible via expander)
# ═══════════════════════════════════════════════════════
st.markdown("---")
with st.expander("Activity Log", expanded=False):
    logs = st.session_state.get("app_logs", [])
    if not logs:
        st.caption("No activity yet.")
    else:
        for log in reversed(logs[-30:]):
            dot_cls = log["level"]
            colors = {"info": "#8896A6", "success": "#0B8A7A", "warning": "#F59E0B", "error": "#EF4444"}
            c = colors.get(dot_cls, "#8896A6")
            st.markdown(f'<div class="log-entry log-{dot_cls}"><span class="log-dot" style="background:{c}"></span><span style="flex:1;color:var(--text-color)">{log["msg"]}</span><span class="log-time">{log["time"]}</span></div>', unsafe_allow_html=True)
        if st.button("Clear Log", key="clear_log"):
            st.session_state["app_logs"] = []
            st.rerun()

# ═══════════════════════════════════════════════════════
# AUTO-PERSIST — Sync session DataFrames to DuckDB
# ═══════════════════════════════════════════════════════
try:
    from modules.duckdb_store import TABLE_MAP, save_df, _is_streamlit_cloud
    # Skip auto-persist on Cloud (read-only FS, /tmp/ is ephemeral anyway)
    # On local, only persist once per session to avoid repeated writes on every rerun
    if not _is_streamlit_cloud() and not st.session_state.get("_duckdb_persisted"):
        _any_saved = False
        for _ss_key in TABLE_MAP:
            _df = st.session_state.get(_ss_key)
            if _df is not None and hasattr(_df, "to_csv") and not _df.empty:
                save_df(_ss_key, _df)
                _any_saved = True
        if _any_saved:
            st.session_state["_duckdb_persisted"] = True
except Exception:
    pass
