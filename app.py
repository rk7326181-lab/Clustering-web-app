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

_FAVICON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "shadowfax_logo.svg")
st.set_page_config(page_title="Geo Intelligence Portal — Shadowfax",
                   page_icon=_FAVICON if os.path.exists(_FAVICON) else "🗺️",
                   layout="wide", initial_sidebar_state="collapsed")

# Shadowfax UI kit (see modules/ui_theme.py and .streamlit/config.toml)
from modules import ui_theme
ui_theme.inject_css()

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

    ui_theme.render_login_head()
    with st.container(key="sfx_login"):
        with st.form("login_form"):
            email = st.text_input("Email", placeholder="your.name@company.com")
            password = st.text_input("Password", type="password", placeholder="Enter app password")
            submitted = st.form_submit_button("Sign in", type="primary", width="stretch")

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
# Session State + BQ Auto-connect
# ═══════════════════════════════════════════════════════
from utils import (init_session_state, reload_from_disk, ensure_output_dirs,
                   clean_pincode, get_download_bytes, lazy_download_data, show_df_download,
                   detect_latlon_cols, detect_geojson_pincode_field,
                   haversine_km, get_pricing, get_hub_color_map,
                   save_file_path, load_file_paths_config, _filter_geojson_to_cluster, remember_cluster_df,
                   CLUSTER_MAP, DESCRIPTION_MAPPING, HUB_COLORS, PRICING_SLABS,
                   PCAT_SOP, RATE_TO_PCAT, rate_to_pcat, pcat_to_payout,
                   OUTPUT_DIR, HUB_IMG_DIR, DATA_DIR, _LAZY_DOWNLOADS as _LAZY_DL)

init_session_state()
ensure_output_dirs()

def html_block(markup):
    """Render multi-line HTML via st.markdown safely: strip indentation and blank lines so
    Markdown never turns part of it into a code block (an empty optional tile left a blank
    line, after which the remaining indented <div>s showed as raw code)."""
    st.markdown("".join(line.strip() for line in markup.splitlines()), unsafe_allow_html=True)


def kpi_row(cards):
    """cards: list of (label, value, color_class) tuples. color_class: blue|green|red|purple|orange"""
    html = '<div class="kpi-row">'
    for label, value, color in cards:
        html += f'<div class="kpi-card {color}"><div class="kpi-label">{label}</div><div class="kpi-value">{value}</div></div>'
    html += '</div>'
    st.markdown(html, unsafe_allow_html=True)
loaded = reload_from_disk()
if "_persisted_ids" not in st.session_state:
    # Frames that just came from DuckDB / CSV are already on disk: remember them so the
    # auto-persist at the bottom doesn't write ~1.3M rows straight back (~4 s per start).
    try:
        from modules.duckdb_store import TABLE_MAP as _TM
        st.session_state["_persisted_ids"] = {k: id(st.session_state[k]) for k in _TM
                                              if st.session_state.get(k) is not None}
    except Exception:
        st.session_state["_persisted_ids"] = {}

# Log system
if "app_logs" not in st.session_state:
    st.session_state["app_logs"] = []

def add_log(msg, level="info"):
    logs = st.session_state["app_logs"]
    logs.append({"msg": msg, "level": level, "time": datetime.now().strftime("%H:%M:%S")})
    if len(logs) > 200:  # Prevent unbounded memory growth
        st.session_state["app_logs"] = logs[-100:]

def stop_page():
    """st.stop() that still draws the footer, so a page that ends early doesn't
    leave a bare grey screen."""
    ui_theme.render_footer(datetime.now().year)
    st.stop()


def render_step_guard(missing, hint):
    """Friendly guard for steps opened before their input data exists: list what's
    missing, offer a jump to Step 1, and stop rendering the rest of the page."""
    items = "".join(f"<li>{m}</li>" for m in missing)
    st.markdown(
        f'<div class="sfx-warn"><b>This step needs data that is not loaded yet:</b>'
        f'<ul>{items}</ul>{hint}</div>', unsafe_allow_html=True)
    st.button("Go to Step 1 — Data Ingestion", key="_guard_goto1", type="primary",
              on_click=lambda: st.session_state.update(nav="1. Data Ingestion"))
    stop_page()

def _add_map_backdrop(ax):
    """Draw the hub-image map backdrop with a guaranteed-reliable floor.

    History: this used to fetch OpenStreetMap tiles, which started blocking
    this app's requests (baked "Access blocked" text into the tile image
    itself). Switched to CartoDB — which then started requiring an API key
    for anonymous fetches, again returning a "watermarked but technically
    valid" image instead of raising an error, so a try/except fallback
    never even triggers. Two different free hosted tile providers have now
    changed policy on us; a third could too.

    So: a live basemap (Esri — the same host already used for years by the
    Satellite/Terrain layers elsewhere in this app with zero incidents) is
    still attempted as a best-effort visual enhancement, but the function
    NEVER depends on it succeeding. The guaranteed layer is the pincode
    boundary shapes already loaded in session_state (geojson_data) — pure
    local data, no network call, so there is nothing left for any third
    party to ever block, rate-limit, or paywall.
    """
    try:
        # modules.tiles (plain HTTP + Pillow): contextily needs rasterio, which Windows
        # Application Control blocks on work laptops.
        from modules import tiles
        tiles.add_to_axes(ax)
    except Exception:
        pass
    try:
        geo = st.session_state.get("geojson_data")
        if geo and geo.get("features"):
            import geopandas as gpd
            from shapely.geometry import shape
            geoms = []
            for feat in geo["features"]:
                try:
                    geoms.append(shape(feat["geometry"]))
                except Exception:
                    continue
            if geoms:
                pgdf = gpd.GeoDataFrame(geometry=geoms, crs="EPSG:4326").to_crs(epsg=3857)
                pgdf.plot(ax=ax, facecolor="#eef3f5", edgecolor="#b8c4c9",
                          linewidth=0.6, alpha=0.6, zorder=1)
    except Exception:
        pass


def _regenerate_hub_image(hub_name, poly_df, cluster_df, hub_col):
    """Render and save a PNG for a single hub using its current polygons. Returns the saved path or None."""
    try:
        import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
        from shapely.wkt import loads as wkt_loads
        import geopandas as gpd
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
            _add_map_backdrop(ax)
        else:
            ax.plot(hlon, hlat, "r^", markersize=14, zorder=5)
        ax.set_title(hub_name, fontsize=14, fontweight="bold", color="#008a71")
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
# HEADER — Shadowfax UI kit: logo · portal name · step tabs · status button.
# Sign-in, keys and pipeline status live in the Connections panel behind the
# status button (never on a tab), so every tab stays clean.
# ═══════════════════════════════════════════════════════
NAV_STEPS = [
    "1. Data Ingestion",
    "2. P Mapping",
    "3. Polygon Gen + Editor",
    "4. AWB + Visualisation",
    "5. Financial Intelligence",
    "6. AI Agent",
    "7. My Maps Polygons",
    "8. Go Live",
]
NAV_LABELS = {
    "1. Data Ingestion": "Data Ingestion",
    "2. P Mapping": "P Mapping",
    "3. Polygon Gen + Editor": "Polygons",
    "4. AWB + Visualisation": "AWB Analysis",
    "5. Financial Intelligence": "Financials",
    "6. AI Agent": "AI Agent",
    "7. My Maps Polygons": "My Maps",
    "8. Go Live": "Go Live",
}

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

bq_mode = st.session_state.get("bq_auth_mode")
_bq_ok = bq_mode in ("adc", "google_oauth", "service_account")
_ai_ok = bool(st.session_state.get("groq_api_key"))
if _bq_ok and _ai_ok:
    _conn_state, _conn_text = "ok", "Connected"
elif _bq_ok:
    _conn_state, _conn_text = "warn", "AI key missing"
else:
    _conn_state, _conn_text = "bad", "Connect BigQuery"

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

with st.container(key="sfx_top"):
    _hc1, _hc2, _hc3 = st.columns([1, 6, 1], vertical_alignment="center", gap="small")
    with _hc1:
        st.markdown(ui_theme.brand_html(), unsafe_allow_html=True)
    with _hc2:
        nav = st.radio("Navigate", NAV_STEPS, index=0, key="nav", horizontal=True,
                       format_func=lambda v: NAV_LABELS.get(v, v), label_visibility="collapsed")
    with _hc3:
        with st.container(key=f"sfx_conn_{_conn_state}"):
            _drawer = st.popover(_conn_text)

with _drawer:
    st.markdown('<div class="sfx-dh"><b>Connections</b>'
                '<span>Sign in to BigQuery, check the AI key and see what is loaded.</span></div>',
                unsafe_allow_html=True)

    # ── 1 · BigQuery ──
    st.markdown('<div class="sfx-dsec first">1 · BigQuery</div>', unsafe_allow_html=True)
    if _bq_ok:
        mode_label = {"adc": "Local Auth", "google_oauth": "Google Account", "service_account": "Service Account", "streamlit_secrets": "Cloud Secrets"}.get(bq_mode, bq_mode)
        st.markdown(f'<div class="sfx-badge sfx-badge--ok"><span class="dot"></span>Connected ({mode_label})</div>', unsafe_allow_html=True)
        if bq_mode == "google_oauth":
            if st.button("Log out of Google", key="bq_logout"):
                from modules.bigquery_client import clear_oauth_credentials
                clear_oauth_credentials()
                st.session_state["bq_client"] = None
                st.session_state["bq_auth_mode"] = "needs_key"
                st.rerun()
    else:
        st.markdown('<div class="sfx-badge sfx-badge--warn"><span class="dot"></span>Not connected. Sign in below.</div>', unsafe_allow_html=True)
        st.markdown('<div class="sfx-label">Google account</div>', unsafe_allow_html=True)

        # Show OAuth error from callback if any
        _oauth_err = st.session_state.pop("_oauth_error", None)
        if _oauth_err:
            st.error(f"Google sign-in failed: {_oauth_err}")

        # Web OAuth flow (for Streamlit Cloud)
        from modules.bigquery_client import get_google_auth_url
        _is_cloud = os.path.exists("/mount/src") or os.environ.get("STREAMLIT_SHARING_MODE") == "true"
        _auth_url, _auth_state = get_google_auth_url()
        if _auth_url:
            st.link_button("Sign in with Google", _auth_url, type="primary", width="stretch")
            st.caption("Takes you to Google to sign in. No JSON key needed. "
                       "If sign-in stops with a connection error (accounts.youtube.com), "
                       "your network is blocking Google's sign-in. Switch networks, or "
                       "upload a service account key below instead.")
        elif _is_cloud:
            # No usable web OAuth client on Cloud — show the working recovery path
            st.warning(
                "Google sign-in from the deployed app needs a 'Web application' OAuth client "
                "(GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET in secrets, with this app's URL as an "
                "authorized redirect URI in Google Cloud Console).\n\n"
                "**Easier:** on your computer run `python generate_bq_token.py` from the repo, "
                "sign in with your Google account, then paste the generated block into this app's "
                "**Settings → Secrets** — the app will then connect automatically every time."
            )
        else:
            # Fallback: local OAuth (desktop — run_local_server) — only works on local machines
            if st.button("Log in with Google", key="google_oauth_btn", type="primary"):
                from modules.bigquery_client import handle_google_oauth_login
                with st.spinner("Opening Google login..."):
                    ok, err = handle_google_oauth_login()
                if ok:
                    add_log("BigQuery connected via Google OAuth", "success")
                    st.rerun()
                else:
                    st.error(f"{err}")
            st.caption("Opens your browser to sign in. No JSON key needed.")
        st.markdown('<div class="sfx-label">Service account</div>', unsafe_allow_html=True)
        sa_file = st.file_uploader("Upload JSON key", type=["json"], key="sidebar_sa_upload")
        if sa_file:
            from modules.bigquery_client import handle_service_account_upload
            ok, err = handle_service_account_upload(sa_file)
            if ok:
                add_log("BigQuery connected via Service Account", "success")
                st.rerun()
            else:
                st.error(f"{err}")

    # ── 2 · AI agent ── (status only — key is never displayed or editable)
    st.markdown('<div class="sfx-dsec">2 · AI agent</div>', unsafe_allow_html=True)
    if _ai_ok:
        st.markdown('<div class="sfx-badge sfx-badge--ok"><span class="dot"></span>AI agent ready</div>', unsafe_allow_html=True)
    else:
        st.markdown(
            '<div class="sfx-badge sfx-badge--warn"><span class="dot"></span>AI key missing</div>'
            '<div class="muted" style="font-size:12px;color:var(--muted);margin-top:6px;line-height:1.45">'
            'Add <b>GROQ_API_KEY</b> to the Streamlit Cloud secrets. '
            'Put it at the <b>top</b> of the secrets file, '
            '<b>above</b> any <code>[section]</code> header, '
            'or TOML will nest it inside the previous section.'
            '</div>',
            unsafe_allow_html=True,
        )

    # ── 3 · Pipeline status ──
    st.markdown(f'<div class="sfx-dsec">3 · Pipeline <span style="color:var(--muted);font-weight:600">'
                f'({sum(1 for _, d in steps if d)} of {len(steps)} ready)</span></div>', unsafe_allow_html=True)
    _checks = "".join(
        f'<div class="sfx-status {"sfx-status--done" if done else "sfx-status--pending"}">'
        f'<span class="icon">✓</span><span class="lbl">{label}</span></div>'
        for label, done in steps)
    st.markdown(f'<div class="sfx-checks">{_checks}</div>', unsafe_allow_html=True)

    # ── 4 · Tools ──
    st.markdown('<div class="sfx-dsec">4 · Tools</div>', unsafe_allow_html=True)
    if st.button("Clear all cache", key="clear_cache",
                 help="Forgets cached results and the local DuckDB copy. Your files on disk are kept."):
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

    # ── AI assistant (reachable from every tab) ──
    with st.expander("AI assistant", expanded=False):
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
            if st.button("Run pipeline", key="sidebar_run_pipeline", width="stretch"):
                st.session_state["auto_run_requested"] = True
                st.rerun()
        with quick_cols[1]:
            if st.button("Show status", key="sidebar_status", width="stretch"):
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

# ═══════════════════════════════════════════════════════
# HERO — one per tab: what the page does + 4 live numbers
# ═══════════════════════════════════════════════════════
_HERO = {
    "1": ("Step 1 of 5 · Data", "Load your <em>data</em>",
          "Add the clustering sheet, the pincode list and the pincode boundaries. "
          "Files you load here are saved and load again next time."),
    "2": ("Step 2 of 5 · P mapping", "Distance-based <em>P mapping</em>",
          "Works out how far each pincode is from its hub and which payout category that distance falls in."),
    "3": ("Step 3 of 5 · Polygons", "Build and edit <em>polygons</em>",
          "Draws payout polygons around each hub from pincode boundaries. "
          "Adjust them on the map, then export them for Google My Maps."),
    "4": ("Step 4 of 5 · Shipments", "Shipments by <em>cluster</em>",
          "Fetches shipments (AWBs) from BigQuery, places each one in a cluster and works out its payout."),
    "5": ("Step 5 of 5 · Financials", "Financial <em>intelligence</em>",
          "Compares payout under the SOP P mapping, the existing mapping and clusters, hub by hub, "
          "so you can see which costs least."),
    "6": ("Assistant", "Ask the <em>AI agent</em>",
          "Ask questions about your data in plain English, or let the agent run the pipeline for you."),
    "7": ("Google My Maps", "Hub polygons from <em>My Maps</em>",
          "Shows the live polygons from your Google My Maps. Edit them in My Maps; "
          "here you can view, search and download them."),
    "8": ("Go live", "Send polygons <em>live</em>",
          "Turns cluster polygons into the Saruman upload file. Hub Ids, boundaries and categories are "
          "filled in for you, and every row is checked before you download it."),
}


def _hero_stats():
    def _rows(key):
        _df = st.session_state.get(key)
        return 0 if _df is None else len(_df)
    def _nunique(col_names):
        # first loaded table that has the column: cluster sheet > P-mapping output > polygons
        for _k in ("cluster_df", "final_output_df", "polygon_records_df"):
            _df = st.session_state.get(_k)
            if _df is None:
                continue
            for _c in col_names:
                if _c in _df.columns:
                    return int(_df[_c].nunique())
        return 0
    _hubs = _nunique(("Hub_Name", "Hub Name"))
    _pins = _nunique(("Pincode",))
    _awbs = _rows("final_result_df") or _rows("awb_raw_df")
    return [
        ("hub", ui_theme.fmt_count(_hubs), "Hubs"),
        ("pin", ui_theme.fmt_count(_pins), "Pincodes"),
        ("poly", ui_theme.fmt_count(_rows("polygon_records_df")), "Polygons"),
        ("box", ui_theme.fmt_count(_awbs), "AWBs loaded"),
    ]


_eb, _ttl, _txt = _HERO.get(nav[0], _HERO["1"])
ui_theme.render_hero(_eb, _ttl, _txt, _hero_stats())

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
                from modules.cluster_assignor import assign_clusters, build_spa_mapping, calculate_financials
                cdf_for_awb = st.session_state.get("cluster_df")
                awb_df, err = fetch_awb_data(bq, cdf_for_awb)
                if err:
                    steps_failed.append(f"Step 4: AWB Fetch ❌ ({err})")
                else:
                    st.session_state["awb_raw_df"] = awb_df
                    auto_progress.progress(0.7, text="Assigning clusters...")
                    poly_df = st.session_state.get("polygon_records_df")
                    fodf_auto = st.session_state.get("final_output_df")
                    if poly_df is None:
                        steps_failed.append("Step 4: Cluster assignment ❌ (no polygons)")
                    elif fodf_auto is None:
                        steps_failed.append("Step 4: Cluster assignment ❌ (no P-Mapping output — run Step 2 first)")
                    else:
                        spa_auto = build_spa_mapping(fodf_auto, overrides=st.session_state.get("pmapping_overrides"))
                        result_df = assign_clusters(awb_df, poly_df, spa_auto)
                        result_df = calculate_financials(result_df)
                        st.session_state["final_result_df"] = result_df
                        result_df.to_csv(os.path.join(OUTPUT_DIR, "Awb_with_cluster_info.csv"), index=False)
                        steps_completed.append(f"Step 4: AWB Analysis ✅ ({len(result_df)} AWBs)")
                        add_log(f"Auto-run: AWB analysis complete ({len(result_df)} AWBs)", "success")
            except Exception as e:
                steps_failed.append(f"Step 4: AWB Analysis ❌ ({e})")
        elif st.session_state.get("final_result_df") is not None:
            steps_completed.append("Step 4: AWB Analysis ✅ (already done)")
        elif not bq:
            steps_failed.append("Step 4: AWB Analysis ⏭ (no BigQuery connection)")

        auto_progress.progress(1.0, text="Pipeline complete!")

        # Show results
        result_html = '<div class="sfx-card">'
        result_html += '<div class="ttl">Pipeline results</div>'
        for s in steps_completed:
            result_html += f'<div style="padding:2px 0;color:var(--ok)">{s}</div>'
        for s in steps_failed:
            result_html += f'<div style="padding:2px 0;color:var(--bad)">{s}</div>'
        result_html += '</div>'
        auto_status.markdown(result_html, unsafe_allow_html=True)

        # Add summary to sidebar chat
        summary = "Pipeline auto-run complete:\n" + "\n".join(steps_completed + steps_failed)
        st.session_state["sidebar_chat_history"].append({"role": "assistant", "content": summary})

# ═══════════════════════════════════════════════════════
# GOOGLE MY MAPS CONNECTOR (used only by page 7)
# ═══════════════════════════════════════════════════════
_MYMAPS_LINKS_FILE = os.path.join(OUTPUT_DIR, "mymaps_links.json")


_MYMAPS_MAX_AGE = 900  # seconds a reading of a map counts as current (here and on disk)


@st.cache_data(ttl=_MYMAPS_MAX_AGE, show_spinner=False)
def _load_mymaps(url_or_id, live=False):
    """Fetch + parse one My Maps map's KML. Cached 15 min; 'Refresh' clears it.
    Unless `live`, a copy downloaded less than 15 min ago (kept on disk) is reused,
    e.g. after a restart, so the map isn't downloaded again within the same 15 min."""
    from modules.mymaps_connector import load_map
    return load_map(url_or_id, cache_dir=os.path.join(OUTPUT_DIR, "mymaps_cache"),
                    max_age=0 if live else _MYMAPS_MAX_AGE)


@st.cache_data(ttl=900, show_spinner=False, max_entries=8)
def _mymaps_all_csv(mid, fetched_at, _polygons):
    """Full-map CSV, built once per fetch (tabs re-render on every rerun)."""
    from modules.mymaps_connector import to_csv_bytes
    return to_csv_bytes(_polygons)


@st.cache_data(ttl=900, show_spinner=False, max_entries=8)
def _mymaps_hub_summary(mid, fetched_at, _polygons):
    """Per-hub counts, built once per fetch (took ~1 s on every click on this page)."""
    from modules.mymaps_connector import hub_summary
    return hub_summary(_polygons)


def _mymaps_links():
    """All My Maps links: admin-configured (secrets/env/default) + ones added in the UI."""
    from modules.mymaps_connector import configured_links, load_saved_links, merge_links
    try:
        _sec = st.secrets
    except Exception:
        _sec = None
    return merge_links(configured_links(_sec), load_saved_links(_MYMAPS_LINKS_FILE))


def _get_mymaps(url, quiet=False, live=False):
    """Return the loaded map dict, or None (showing the error unless quiet).
    live=True (after 'Refresh from My Maps') always downloads from Google."""
    from modules.mymaps_connector import MyMapsError
    try:
        with st.spinner("Reading polygons from Google My Maps..."):
            return _load_mymaps(url, live=live)
    except MyMapsError as e:
        if not quiet:
            st.error(f"Google My Maps: {e}")
    except Exception as e:
        if not quiet:
            st.error(f"Google My Maps: could not read the map ({e})")
    return None

# ═══════════════════════════════════════════════════════
# STEP 1 — DATA INGESTION
# ═══════════════════════════════════════════════════════
if nav.startswith("1"):
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
                        remember_cluster_df(df)
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
                        remember_cluster_df(df)
                        st.session_state["_geojson_filtered"] = False  # Re-filter GeoJSON with new cluster
                        _filter_geojson_to_cluster()
                        add_log(f"Cluster CSV loaded: {len(df)} rows, {df['Hub_Name'].nunique()} hubs", "success")
                        st.markdown(f'<div class="sfx-ok">✅ {len(df)} rows, {df["Hub_Name"].nunique()} hubs</div>', unsafe_allow_html=True)
                        st.dataframe(df, height=180)
                except Exception as e:
                    st.error(str(e))
        else:
            st.caption("Add pincodes manually:")
            manual = st.data_editor(pd.DataFrame({"Pincode": [""], "Hub_Name": [""], "Hub_lat": [0.0], "Hub_long": [0.0]}), num_rows="dynamic", key="manual_cluster", width="stretch")
            if st.button("Use Manual Data", key="use_manual"):
                valid = manual.dropna(subset=["Pincode"]).copy()
                valid = valid[valid["Pincode"] != ""]
                if len(valid) > 0:
                    valid = clean_pincode(valid); st.session_state["cluster_df"] = valid; st.session_state["upload_status"]["cluster"] = True
                    remember_cluster_df(valid)
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
                        st.session_state["geojson_source"] = "upload"  # user's own file: never replaced by the bundled store
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
                    st.session_state["geojson_source"] = "path"  # user's own file: never replaced by the bundled store
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
            html_block(f'''<div class="kpi-row">
                <div class="kpi-card blue"><div class="kpi-label">Total Records</div><div class="kpi-value">{len(fo)}</div></div>
                <div class="kpi-card"><div class="kpi-label">Hubs</div><div class="kpi-value">{fo["Hub_Name"].nunique()}</div></div>
                <div class="kpi-card"><div class="kpi-label">Avg Distance</div><div class="kpi-value">{avg_dist:.1f} km</div></div>
                <div class="kpi-card red"><div class="kpi-label">Nil Distance</div><div class="kpi-value">{nil_count}</div></div>
            </div>''')

        st.markdown('<div class="sfx-header">Results</div>', unsafe_allow_html=True)
        import html as _html
        _tsv_escaped = _html.escape(dfo.to_csv(index=False, sep="\t"))
        st.markdown(f"""<div style="margin:4px 0 8px">
<textarea id="pm_copy_ta" style="position:fixed;left:-9999px;top:-9999px;width:1px;height:1px;opacity:0">{_tsv_escaped}</textarea>
<button onclick="var ta=document.getElementById('pm_copy_ta');ta.style.display='block';ta.select();if(navigator.clipboard){{navigator.clipboard.writeText(ta.value).then(()=>{{this.textContent='✓ Copied!';setTimeout(()=>this.textContent='Copy',2000)}}).catch(()=>{{document.execCommand('copy');this.textContent='✓ Copied!';setTimeout(()=>this.textContent='Copy',2000)}})}}else{{document.execCommand('copy');this.textContent='✓ Copied!';setTimeout(()=>this.textContent='Copy',2000)}}ta.style.display='none';"
 style="padding:7px 18px;background:#fff;color:var(--teal);border:1.5px solid var(--teal);border-radius:9px;cursor:pointer;font-weight:700;font-size:13px;font-family:inherit" onmouseover="this.style.background='var(--mint-3)'" onmouseout="this.style.background='#fff'">Copy</button>
</div>""", unsafe_allow_html=True)
        st.data_editor(dfo, width="stretch", height=300, key="osrm_edit")
        st.download_button("Download final_output.csv", lazy_download_data(fo, "csv"), "final_output.csv", "text/csv", key="dl_fo")

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
                st.dataframe(_ov_df, width="stretch", height=min(160, 40 + len(_ov_df)*35))
                if st.button("Clear All Switches", key="clear_switches"):
                    st.session_state["pmapping_overrides"] = {}
                    st.rerun()

        _show_cols = [c for c in ["Pincode","Hub_Name","Distance","SP&A Aligned P mapping","P_Category","Payout (₹/km)","Amount Capping"] if c in _pdf.columns]
        st.dataframe(_pdf[_show_cols], width="stretch", height=280)
        st.download_button("Download with P Categories", lazy_download_data(_pdf, "csv"),
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
                width="stretch", height=min(400, 35 * len(hub_radius_data) + 38),
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
        html_block(f'''<div class="kpi-row">
            <div class="kpi-card"><div class="kpi-label">Polygons</div><div class="kpi-value">{len(dpdf)}</div></div>
            <div class="kpi-card blue"><div class="kpi-label">Pincodes</div><div class="kpi-value">{dpdf["Pincode"].nunique() if "Pincode" in dpdf.columns else 0}</div></div>
            <div class="kpi-card green"><div class="kpi-label">Hubs</div><div class="kpi-value">{dpdf[hub_col].nunique() if hub_col in dpdf.columns else 0}</div></div>
        </div>''')

        st.markdown('<div class="sfx-header">Polygon Editor</div>', unsafe_allow_html=True)
        edited = st.data_editor(dpdf, width="stretch", height=400, num_rows="dynamic", key="poly_ed")
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
            st.download_button("⬇ Download CSV", lazy_download_data(edited, "csv"), "polygon_edited.csv", "text/csv", key="dl_ed")
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
            from modules.visualizer import create_polygon_map_cached, create_editable_polygon_map, _df_hash
            if edit_polygons:
                # ── GEOMAN EDITOR (replaces unreliable streamlit-folium editing) ──
                from modules.geoman_editor import build_geoman_editor_html
                _geoman_html = build_geoman_editor_html(pdf, hub_filter=hub_filter, height=660)
                st.iframe(_geoman_html, height=660)
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
                    st.iframe(html, height=620)
        except ImportError:
            st.info("Install folium for maps.")

        st.markdown('<div class="sfx-header">Hub Images</div>', unsafe_allow_html=True)
        if st.button("Generate Hub Images", key="gen_img"):
            try:
                import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
                from shapely.wkt import loads as wkt_loads
                import geopandas as gpd
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
                        _add_map_backdrop(ax)
                    else:
                        ax.plot(hlon, hlat, "r^", markersize=14, zorder=5)
                    ax.set_title(hn, fontsize=14, fontweight="bold", color="#008a71")
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
                st.image(path, width="stretch")
                st.download_button(f"Download {hn}", open(path, "rb").read(), os.path.basename(path), "image/png", key=f"di_{hn}")

# ═══════════════════════════════════════════════════════
# STEP 4 — AWB + VISUALISATION
# ═══════════════════════════════════════════════════════
elif nav.startswith("4"):
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
            st.dataframe(awb.head(10), width="stretch", height=300)
            st.caption(f"Total rows: {len(awb):,}")
            st.download_button("Download Awb_with_polygon_mapping.csv", lazy_download_data(awb, "csv"), "Awb_with_polygon_mapping.csv", "text/csv", key="dl_awb_raw")

            # ── Current Pincode Mapping (serviceability, latest day) ──
            _awb_cols = {c.strip().lower(): c for c in awb.columns}
            if "pincode" in _awb_cols and "payment_category" in _awb_cols:
                st.markdown('<div class="sfx-header">Current P-Mapping (serviceability)</div>', unsafe_allow_html=True)
                _map_cols = [_awb_cols["pincode"]] + ([_awb_cols["hub"]] if "hub" in _awb_cols else []) + [_awb_cols["payment_category"]]
                _pin_map = awb[_map_cols].drop_duplicates(subset=[_awb_cols["pincode"]]).copy()
                _pin_map.columns = ["Pincode"] + (["Hub"] if "hub" in _awb_cols else []) + ["Current P Category"]
                _pin_map["Payout (₹)"] = _pin_map["Current P Category"].map(pcat_to_payout)
                _pin_map = _pin_map.sort_values([c for c in ["Hub", "Pincode"] if c in _pin_map.columns]).reset_index(drop=True)
                _n_mapped = _pin_map["Current P Category"].notna().sum()
                _n_unknown = int((_pin_map["Current P Category"].notna() & _pin_map["Payout (₹)"].isna()).sum())
                _cap = f"{len(_pin_map):,} pincodes · {_n_mapped:,} with a production category"
                if _n_unknown:
                    _cap += f" · {_n_unknown} unknown categories — treated as no mapping"
                st.caption(_cap)
                st.dataframe(_pin_map, width="stretch", height=280)
                st.download_button("Download Current P-Mapping", lazy_download_data(_pin_map, "csv"), "Current_pincode_mapping.csv", "text/csv", key="dl_existing_pinmap")

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
                    spa = build_spa_mapping(fodf, overrides=st.session_state.get("pmapping_overrides")); add_log("Cluster assignment started", "info")
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
            _kpi_ex = ""
            if "Existing_Pin_Pay" in rdf.columns:
                _kpi_ex = f'<div class="kpi-card orange"><div class="kpi-label">Current P Pay</div><div class="kpi-value">₹{rdf["Existing_Pin_Pay"].sum():,.0f}</div></div>'
            html_block(f'''<div class="kpi-row">
                <div class="kpi-card blue"><div class="kpi-label">Pin Pay (SOP)</div><div class="kpi-value">₹{rdf["Pin_Pay"].sum():,.0f}</div></div>
                {_kpi_ex}
                <div class="kpi-card purple"><div class="kpi-label">Cluster Pay</div><div class="kpi-value">₹{rdf["Clustering_payout"].sum():,.0f}</div></div>
                <div class="kpi-card green"><div class="kpi-label">Saving</div><div class="kpi-value">₹{rdf["Saving"].sum():,.0f}</div></div>
                <div class="kpi-card red"><div class="kpi-label">Burning</div><div class="kpi-value">₹{rdf["Burning"].sum():,.0f}</div></div>
            </div>''')
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
                st.iframe(_s4_geoman_html, height=660)
                map_out_s4 = None  # st.iframe has no return value
            else:
                # Non-edit mode: use cached HTML for speed
                html = create_polygon_map_cached(
                    _df_hash(poly), _df_hash(cdf), _df_hash(rdf),
                    poly, cdf, rdf, False, viz_mode.lower(), sel_hub, rate_filter, None,
                    s4_show_rate_labels,
                )
                if html:
                    st.iframe(html, height=720)
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
                st.download_button("⬇ CSV", lazy_download_data(_dl4, "csv"), f"{_base4}.csv", "text/csv", key="s4_dl_csv")
            # GeoJSON / KML are built on click (were rebuilt for every polygon on every rerun)
            def _geojson4_bytes(_df=_dl4):
                from shapely.wkt import loads as _wl4g
                from shapely.geometry import mapping as _sm4g
                _wc4g = "Polygon WKT" if "Polygon WKT" in _df.columns else "boundary"
                _feats4 = []
                for _, _r in _df.iterrows():
                    try:
                        _g = _wl4g(str(_r.get(_wc4g, "")))
                        _props = {k: (None if pd.isna(v) else v) for k, v in _r.items() if k != _wc4g}
                        _feats4.append({"type": "Feature", "geometry": _sm4g(_g), "properties": _props})
                    except Exception:
                        continue
                return json.dumps({"type": "FeatureCollection", "features": _feats4}, default=str).encode("utf-8")

            def _kml4_bytes(_df=_dl4):
                from modules.visualizer import generate_kml as _gkml4
                return (_gkml4(_df) or "").encode("utf-8")

            with _dc2:
                try:
                    st.download_button("⬇ GeoJSON", _geojson4_bytes if _LAZY_DL else _geojson4_bytes(),
                                       f"{_base4}.geojson", "application/geo+json", key="s4_dl_geojson")
                except Exception as _eg:
                    st.caption(f"GeoJSON error: {_eg}")
            with _dc3:
                try:
                    st.download_button("⬇ KML", _kml4_bytes if _LAZY_DL else _kml4_bytes(),
                                       f"{_base4}.kml", "application/vnd.google-earth.kml+xml", key="s4_dl_kml")
                except Exception as _ek:
                    st.caption(f"KML error: {_ek}")

# ═══════════════════════════════════════════════════════
# STEP 5 — FINANCIAL INTELLIGENCE
# ═══════════════════════════════════════════════════════
elif nav.startswith("5"):
    rdf = st.session_state.get("final_result_df")
    if rdf is None:
        render_step_guard(["AWB P&L results"], "Run Step 4 → Assign + Financials, or load saved results via Step 1.")
    if "Pin_Pay" not in rdf.columns:
        try:
            from modules.cluster_assignor import calculate_financials
            rdf = calculate_financials(rdf); st.session_state["final_result_df"] = rdf
        except Exception as e:
            st.error(str(e)); stop_page()

    try:
        from modules.dashboard_builder import build_pivot_report, style_report_html, compute_insights, build_comparison_table
        from modules.ai_agent import run_auto_analysis, chat_with_agent
        report = build_pivot_report(rdf); ins = compute_insights(report); comp = build_comparison_table(report)
        _has_existing = "Existing_Pincode_Pay" in report.columns

        dtab1, dtab2, dtab3 = st.tabs(["Pivot Table", "SOP vs Current P vs Cluster" if _has_existing else "P-Map vs Cluster", "AI Analysis"])

        with dtab1:
            # KPI Cards
            _ex_kpi = ""
            if _has_existing:
                _ex_kpi = f'<div class="kpi-card orange"><div class="kpi-label">Current P-Map Pay</div><div class="kpi-value">₹{ins.get("total_existing_pincode_pay", 0):,.0f}</div></div>'
            html_block(f'''<div class="kpi-row">
                <div class="kpi-card blue"><div class="kpi-label">Expected Pay (SOP)</div><div class="kpi-value">₹{ins.get("total_expt_pincode_pay", 0):,.0f}</div></div>
                {_ex_kpi}
                <div class="kpi-card purple"><div class="kpi-label">Cluster Payout</div><div class="kpi-value">₹{ins.get("total_cluster_payout", 0):,.0f}</div></div>
                <div class="kpi-card green"><div class="kpi-label">Saving</div><div class="kpi-value">₹{ins.get("total_saving", 0):,.0f}</div></div>
                <div class="kpi-card red"><div class="kpi-label">Burning</div><div class="kpi-value">₹{ins.get("total_burning", 0):,.0f}</div></div>
                <div class="kpi-card"><div class="kpi-label">Net P&L</div><div class="kpi-value">₹{ins.get("total_p_l", 0):,.0f}</div></div>
            </div>''')

            ic1, ic2 = st.columns(2)
            with ic1:
                b = ins.get("best_hub", "N/A"); bv = ins.get("best_hub_pl", 0)
                st.markdown(f'<div class="sfx-ok"><b>Best hub: {b}</b><br>P&L: ₹{bv:,.0f}</div>', unsafe_allow_html=True)
            with ic2:
                w = ins.get("worst_hub", "N/A"); wv = ins.get("worst_hub_pl", 0)
                st.markdown(f'<div class="sfx-err"><b>Worst hub: {w}</b><br>P&L: ₹{wv:,.0f}</div>', unsafe_allow_html=True)

            st.markdown("---")
            st.markdown('<div class="sfx-header">Detailed P&L Report</div>', unsafe_allow_html=True)
            st.markdown(style_report_html(report), unsafe_allow_html=True)
            st.download_button("Download Report CSV", lazy_download_data(report, "csv"), "Pivot_Table.csv", "text/csv", key="dl_piv")
            with st.expander("Editable View"):
                st.data_editor(report, width="stretch", height=400)

        with dtab2:
            if comp is not None and not comp.empty and "Existing_Pincode_Pay" in comp.columns:
                st.markdown('<div class="sfx-header">SOP P-Mapping vs Current P-Mapping (serviceability) vs Cluster</div>', unsafe_allow_html=True)
                sop_t = comp["Expt_Pincode_Pay"].sum()
                ex_t = comp["Existing_Pincode_Pay"].sum()
                cl_t = comp["Cluster_Payout"].sum()
                _n_unmapped = int(comp["Existing_Pincode_Pay"].isna().sum())

                html_block(f'''<div class="kpi-row">
                    <div class="kpi-card blue"><div class="kpi-label">SOP P-Map Total</div><div class="kpi-value">₹{sop_t:,.0f}</div></div>
                    <div class="kpi-card orange"><div class="kpi-label">Current P-Map Total</div><div class="kpi-value">₹{ex_t:,.0f}</div></div>
                    <div class="kpi-card purple"><div class="kpi-label">Cluster Total</div><div class="kpi-value">₹{cl_t:,.0f}</div></div>
                </div>''')
                if _n_unmapped:
                    st.caption(f"{_n_unmapped} pincode(s) are not in the current serviceability data — shown as — and left out of the Current P total.")

                _totals = {"Cluster-based payout": cl_t, "SOP P-Mapping (Step 2)": sop_t, "Current P-Mapping (serviceability)": ex_t}
                _best_system = min(_totals, key=_totals.get)
                _second = sorted(_totals.values())[1]
                _sv_vs_next = _second - _totals[_best_system]
                _cherry = comp["Saving_Amount"].sum()

                sop_w = (comp["Winner"] == "SOP P-Map Cheapest").sum()
                ex_w = (comp["Winner"] == "Current P-Map Cheapest").sum()
                cl_w = (comp["Winner"] == "Cluster Cheapest").sum()
                tie_w = (comp["Winner"] == "Tie").sum()

                html_block(f'''<div class="kpi-row">
                    <div class="kpi-card blue"><div class="kpi-label">SOP P-Map Cheapest</div><div class="kpi-value">{sop_w} pincodes</div></div>
                    <div class="kpi-card orange"><div class="kpi-label">Current P Cheapest</div><div class="kpi-value">{ex_w} pincodes</div></div>
                    <div class="kpi-card green"><div class="kpi-label">Cluster Cheapest</div><div class="kpi-value">{cl_w} pincodes</div></div>
                    <div class="kpi-card"><div class="kpi-label">Tie</div><div class="kpi-value">{tie_w} pincodes</div></div>
                </div>''')

                st.markdown(f'<div class="sfx-ok">Recommendation: <b>{_best_system}</b> has the lowest total payout '
                            f'(₹{_totals[_best_system]:,.0f}, ₹{_sv_vs_next:,.0f} less than the next option). '
                            f'Picking the cheapest system per pincode would save ₹{_cherry:,.0f} vs the existing production mapping.</div>',
                            unsafe_allow_html=True)

                def color_row3(row):
                    if row["Winner"] == "Cluster Cheapest":
                        return ["background:#e1f4e8"] * len(row)
                    elif row["Winner"] == "Current P-Map Cheapest":
                        return ["background:#fff4d6"] * len(row)
                    elif row["Winner"] == "SOP P-Map Cheapest":
                        return ["background:#e8efec"] * len(row)
                    return ["background:#f3f9f7"] * len(row)

                st.dataframe(comp.style.apply(color_row3, axis=1).format({
                    "Expt_Pincode_Pay": "₹{:,.0f}", "Existing_Pincode_Pay": "₹{:,.0f}",
                    "Cluster_Payout": "₹{:,.0f}", "Difference": "₹{:,.0f}",
                    "Best_Pay": "₹{:,.0f}", "Saving_Amount": "₹{:,.0f}",
                }, na_rep="—"), width="stretch", height=400)
                st.download_button("Download Comparison CSV", lazy_download_data(comp, "csv"), "Comparison.csv", "text/csv", key="dl_comp")
            elif comp is not None and not comp.empty:
                st.markdown('<div class="sfx-header">P-Mapping vs Cluster Comparison</div>', unsafe_allow_html=True)
                cl_w = (comp["Winner"] == "Cluster Cheaper").sum()
                pm_w = (comp["Winner"] == "P-Map Cheaper").sum()
                cl_s = comp[comp["Winner"] == "Cluster Cheaper"]["Saving_Amount"].sum()
                pm_s = comp[comp["Winner"] == "P-Map Cheaper"]["Saving_Amount"].sum()

                html_block(f'''<div class="kpi-row">
                    <div class="kpi-card green"><div class="kpi-label">Cluster Cheaper</div><div class="kpi-value">{cl_w} pincodes</div></div>
                    <div class="kpi-card red"><div class="kpi-label">P-Map Cheaper</div><div class="kpi-value">{pm_w} pincodes</div></div>
                    <div class="kpi-card green"><div class="kpi-label">Cluster Saves</div><div class="kpi-value">₹{cl_s:,.0f}</div></div>
                    <div class="kpi-card red"><div class="kpi-label">P-Map Saves</div><div class="kpi-value">₹{pm_s:,.0f}</div></div>
                </div>''')

                rec = "**Cluster-based payout**" if cl_s > pm_s else "**P-Mapping**"
                st.markdown(f'<div class="sfx-ok">Recommendation: {rec} saves ₹{max(cl_s, pm_s):,.0f}</div>', unsafe_allow_html=True)

                def color_row(row):
                    if row["Winner"] == "Cluster Cheaper":
                        return ["background:#e1f4e8"] * len(row)
                    elif row["Winner"] == "P-Map Cheaper":
                        return ["background:#fdebe8"] * len(row)
                    return ["background:#f3f9f7"] * len(row)

                st.dataframe(comp.style.apply(color_row, axis=1).format({
                    "Expt_Pincode_Pay": "₹{:,.0f}", "Cluster_Payout": "₹{:,.0f}",
                    "Difference": "₹{:,.0f}", "Saving_Amount": "₹{:,.0f}",
                }), width="stretch", height=400)
                st.download_button("Download Comparison CSV", lazy_download_data(comp, "csv"), "Comparison.csv", "text/csv", key="dl_comp")
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
                    f'<div class="sfx-card">'
                    f'<div class="ttl" style="color:var(--bad)">Burn analysis report</div>'
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
                st.markdown(f'<div class="sfx-card"><div class="ttl">Auto-analysis</div>{st.session_state["ai_auto_report"]}</div>', unsafe_allow_html=True)

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
# 7 — GOOGLE MY MAPS POLYGONS (browse / count / download)
# ═══════════════════════════════════════════════════════
elif nav.startswith("7"):
    import re
    from modules import mymaps_connector as mmc

    st.caption("Your Google My Maps maps, inside the portal. Switch between maps, view them live, open the "
               "My Maps editor to make changes, and count / search / download polygons and hub photos.")

    _links = _mymaps_links()
    _by_mid = {l["mid"]: l for l in _links}

    # ── Active map switcher + refresh ──
    _sw1, _sw2 = st.columns([4, 1])
    with _sw1:
        if st.session_state.get("mm_active") not in _by_mid:
            st.session_state.pop("mm_active", None)
        _active_mid = st.selectbox(
            f"Active map ({len(_links)} saved)", list(_by_mid), key="mm_active",
            format_func=lambda m: _by_mid[m]["name"],
            help="The map used by Live My Maps, By Hub and All Hubs Overview. "
                 "Find Polygon can search all maps at once.")
    with _sw2:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        _mm_live = False  # True only in the run where Refresh was clicked
        if st.button("🔄 Refresh from My Maps", key="mm_refresh", width="stretch",
                     help="Re-read all maps now (otherwise each is re-read every 15 minutes)."):
            _load_mymaps.clear()
            _mymaps_all_csv.clear()
            _mymaps_hub_summary.clear()
            _mm_live = True
            # Also reload the embedded live map (a changed src forces the iframe to reload).
            st.session_state["mm_embed_rev"] = st.session_state.get("mm_embed_rev", 0) + 1
            add_log("My Maps refreshed", "info")
    _active = _by_mid[_active_mid]

    # ── Manage links ──
    with st.expander(f"⚙️ Manage My Maps links ({len(_links)})", expanded=False):
        _saved = [l for l in _links if l["source"] == "saved"]
        for _i, _l in enumerate(_links):
            _r1, _r2, _r3 = st.columns([3, 5, 1])
            with _r1:
                st.markdown(f"**{_l['name']}**")
            with _r2:
                _src = {"saved": "added here", "secrets": "from app secrets", "env": "from environment",
                        "default": "built-in default"}.get(_l["source"], _l["source"])
                st.markdown(f"<small>{_src} · <a href='https://www.google.com/maps/d/edit?mid={_l['mid']}' "
                            f"target='_blank'>{_l['mid']}</a></small>", unsafe_allow_html=True)
            with _r3:
                if _l["source"] == "saved" and st.button("Remove", key=f"mm_rm_{_l['mid']}"):
                    mmc.save_links(_MYMAPS_LINKS_FILE, [x for x in _saved if x["mid"] != _l["mid"]])
                    add_log(f"My Maps link removed: {_l['name']}", "warning")
                    st.rerun()
        st.markdown("---")
        with st.form("mm_add_form", clear_on_submit=True):
            st.markdown("**Add a My Maps link**")
            _fa1, _fa2 = st.columns([1, 2])
            with _fa1:
                _new_name = st.text_input("Name (optional)", placeholder="e.g. North hubs")
            with _fa2:
                _new_url = st.text_input("My Maps link", placeholder="https://www.google.com/maps/d/edit?mid=...")
            _add = st.form_submit_button("➕ Add map", type="primary")
        if _add:
            try:
                _new_mid = mmc.extract_map_id(_new_url)
            except mmc.MyMapsError as _e:
                st.error(str(_e))
            else:
                if _new_mid in _by_mid:
                    st.warning(f"That map is already saved as **{_by_mid[_new_mid]['name']}**.")
                else:
                    _chk = _get_mymaps(_new_url)  # proves the map is readable before saving it
                    if _chk is not None:
                        _nm = _new_name.strip() or _chk["title"] or _new_mid
                        mmc.save_links(_MYMAPS_LINKS_FILE, _saved + [{"name": _nm, "url": _new_url.strip()}])
                        st.session_state["mm_active"] = _new_mid
                        add_log(f"My Maps link added: {_nm}", "success")
                        st.rerun()
        st.caption("Each map must be shared as **Anyone with the link → Viewer**. Links added here are saved "
                   "on the server running the app. On Streamlit Cloud that file is reset when the app reboots "
                   "or redeploys — to keep the maps permanently, paste this into the app's **Secrets**:")
        st.code("\n\n".join(f'[[mymaps]]\nname = "{l["name"]}"\nurl = "{l["url"]}"' for l in _links),
                language="toml")

    _edit_link = f"https://www.google.com/maps/d/edit?mid={_active_mid}"
    mm = _get_mymaps(_active["url"], live=_mm_live)  # None if the KML can't be read -- the live view below still works

    tab_live, tab_hub, tab_find, tab_all = st.tabs(["🗺 Live My Maps", "By Hub", "Find Polygon", "All Hubs Overview"])

    # ── Live My Maps (Google's own map, embedded) ──
    with tab_live:
        _lv1, _lv2 = st.columns([3, 1])
        _zoom_hub = None
        with _lv1:
            if mm is not None and not mm["hubs"].empty:
                _zoom_hub = st.selectbox("Zoom to hub", ["(whole map)"] + mm["hubs"]["Hub Name"].tolist(),
                                         key=f"mm_live_hub_{_active_mid}")
        with _lv2:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            st.link_button("✏️ Open My Maps editor", _edit_link, type="primary", width="stretch")
        _embed = f"https://www.google.com/maps/d/embed?mid={_active_mid}&rev={st.session_state.get('mm_embed_rev', 0)}"
        if _zoom_hub and _zoom_hub != "(whole map)":
            _h = mm["hubs"][mm["hubs"]["Hub Name"] == _zoom_hub].iloc[0]
            _embed += f"&ll={_h['Hub_lat']},{_h['Hub_long']}&z=12"
        if hasattr(st, "iframe"):
            st.iframe(_embed, height=720)
        else:
            st.iframe(_embed, height=720)
        st.caption("This is your live My Maps map (view only — Google does not allow its editor inside other "
                   "websites). To change polygons, click **Open My Maps editor**, edit and it saves "
                   "automatically in My Maps; then click **🔄 Refresh from My Maps** here to see the changes "
                   "and update the counts.")

    def _mm_map(sel_df, hub_pts, height=600):
        """Render a selection with the app's standard polygon map."""
        if sel_df.empty:
            return
        if len(sel_df) > 3000:
            st.info(f"{len(sel_df):,} polygons selected — map shows the first 3,000. Downloads include all.")
            sel_df = sel_df.head(3000)
        from modules.visualizer import create_polygon_map
        _pts = hub_pts.rename(columns={"Hub Name": "Hub_Name"})
        m = create_polygon_map(sel_df, _pts if not _pts.empty else None, None, False, "none", None, "All", None, True)
        if m is not None:
            st.iframe(m._repr_html_(), height=height)

    def _mm_downloads(sel_df, hub_pts, slug, key):
        _stamp = datetime.now().strftime("%Y%m%d")
        d1, d2, d3 = st.columns(3)
        with d1:
            st.download_button("⬇ CSV", mmc.to_csv_bytes(sel_df), f"{slug}_polygons_{_stamp}.csv",
                               "text/csv", key=f"{key}_csv", width="stretch")
        with d2:
            st.download_button("⬇ KML (My Maps)", mmc.to_kml(sel_df, hub_pts, slug).encode("utf-8"),
                               f"{slug}_polygons_{_stamp}.kml", "application/vnd.google-earth.kml+xml",
                               key=f"{key}_kml", width="stretch")
        with d3:
            st.download_button("⬇ GeoJSON", mmc.to_geojson(sel_df).encode("utf-8"),
                               f"{slug}_polygons_{_stamp}.geojson", "application/geo+json",
                               key=f"{key}_geojson", width="stretch")

    def _mm_table(sel_df, key):
        _show_wkt = st.checkbox("Show geometry (WKT) column", value=False, key=f"{key}_wkt")
        _cols = [c for c in ["Map", "Hub Name", "Cluster_Code", "Pincode", "Cluster_Category", "Description",
                             "Layer", "Hub Source"] + (["Polygon WKT"] if _show_wkt else []) if c in sel_df.columns]
        st.dataframe(sel_df[_cols], width="stretch", height=min(420, 35 * len(sel_df) + 38),
                     hide_index=True)

    # ── Find a polygon (searches several maps) ──
    with tab_find:
        _f1, _f2 = st.columns([2, 3])
        with _f1:
            _q = st.text_input("Cluster code, pincode or hub", key="mm_query",
                               placeholder="e.g. 206131_A, 206131 or ETW_Udi")
        with _f2:
            _search_mids = st.multiselect("Search in", list(_by_mid), default=list(_by_mid),
                                          # keyed on the map list so a newly added map is searched by default
                                          key=f"mm_search_maps_{abs(hash(tuple(_by_mid))) % 10**8}",
                                          format_func=lambda m: _by_mid[m]["name"])
        st.caption("Comma-separate several codes / pincodes / hubs. Each map is read once and then cached "
                   "for 15 minutes.")
        if _q.strip() and _search_mids:
            _found_parts, _pts_parts, _failed = [], [], []
            for _m in _search_mids:
                _md = mm if _m == _active_mid and mm is not None else _get_mymaps(_by_mid[_m]["url"], quiet=True, live=_mm_live)
                if _md is None:
                    _failed.append(_by_mid[_m]["name"])
                    continue
                _hit = mmc.find_polygons(_md["polygons"], _q)
                if not _hit.empty:
                    _found_parts.append(_hit.assign(Map=_by_mid[_m]["name"]))
                    _pts_parts.append(_md["hubs"][_md["hubs"]["Hub Name"].isin(_hit["Hub Name"])])
            if _failed:
                st.warning(f"Could not read: {', '.join(_failed)} — check the link and that it is shared "
                           f"'Anyone with the link can view'.")
            if not _found_parts:
                st.warning("No polygon matches that in the selected maps.")
            else:
                found = pd.concat(_found_parts, ignore_index=True)
                found_pts = pd.concat(_pts_parts, ignore_index=True).drop_duplicates("Hub Name")
                kpi_row([
                    ("Matches", f"{len(found):,}", "blue"),
                    ("Hubs", f"{found['Hub Name'].replace('', pd.NA).nunique()}", "green"),
                    ("Maps", f"{found['Map'].nunique()}", "purple"),
                    ("Layers", f"{found['Layer'].nunique()}", "orange"),
                ])
                st.markdown("**Matches per map**")
                st.dataframe(found.groupby("Map").agg(Polygons=("Cluster_Code", "size"),
                                                      Hubs=("Hub Name", "nunique")).reset_index(),
                             hide_index=True, width="stretch")
                _mm_map(found, found_pts, height=520)
                _qslug = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in _q.strip())[:40]
                _mm_downloads(found, found_pts, _qslug, "mm_find")
                _mm_table(found, "mm_find")

    if mm is None:
        for _t in (tab_hub, tab_all):
            with _t:
                st.warning(f"Polygon data could not be read from **{_active['name']}** (see the error above). "
                           f"The Live My Maps tab still works.")
        stop_page()
    mpoly, mhubs, minfo = mm["polygons"], mm["hubs"], mm["info"]
    with _sw1:
        _when = datetime.fromtimestamp(minfo["fetched_at"]).strftime("%d %b %H:%M")
        if minfo.get("stale"):
            st.markdown(f'<div class="sfx-warn">Showing the last saved copy from {_when} — {minfo.get("reason")}</div>',
                        unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="sfx-ok">✅ Connected to <b>{mm["title"] or _active["name"]}</b> · read at '
                        f'{_when} · <a href="{_edit_link}" target="_blank">open in My Maps ↗</a></div>',
                        unsafe_allow_html=True)

    # ── By Hub ──
    with tab_hub:
        _all_hubs = mmc.list_hubs(mpoly)
        sel_hubs = st.multiselect("Hub name", _all_hubs, key=f"mm_hubs_{_active_mid}",
                                  placeholder="Type to search hubs…")
        if not sel_hubs:
            st.info(f"Select one or more hubs from **{_active['name']}** to see their polygons.")
        else:
            # Hubs present in several My Maps layers would otherwise come back twice.
            _layers_in = sorted(mmc.get_hub_polygons(mpoly, sel_hubs)["Layer"].unique())
            _default_layers = sorted({l for h in sel_hubs for l in mmc.default_layers_for_hub(mpoly, h)})
            if len(_layers_in) > 1:
                sel_layers = st.multiselect(
                    "My Maps layers", _layers_in, default=_default_layers,
                    key=f"mm_layers_{_active_mid}_{'|'.join(sel_hubs)}",
                    help="This selection exists in more than one My Maps layer. Defaults to layers where the hub "
                         "name is written on the polygons.")
            else:
                sel_layers = _layers_in
            sel = mmc.get_hub_polygons(mpoly, sel_hubs, sel_layers)
            sel_pts = mhubs[mhubs["Hub Name"].isin(sel_hubs)]

            _dups = sel.duplicated(["Hub Name", "Cluster_Code"]).sum()
            kpi_row([
                ("Polygons", f"{len(sel):,}", "blue"),
                ("Pincodes", f"{sel['Pincode'].replace('', pd.NA).nunique():,}", "green"),
                ("Rate bands", f"{sel['Description'].replace('', pd.NA).nunique()}", "purple"),
                ("Layers", f"{sel['Layer'].nunique()}", "orange"),
            ])
            if _dups:
                st.markdown(f'<div class="sfx-warn">{_dups} Cluster_Code(s) appear in more than one selected layer — '
                            f'deselect a layer above to avoid duplicates.</div>', unsafe_allow_html=True)
            _inferred = sel["Hub Source"].str.startswith("inferred").sum()
            if _inferred:
                st.caption(f"ℹ️ {_inferred} polygon(s) have no hub written on them in My Maps; their hub was "
                           f"taken from the same Cluster_Code in another layer or the nearest hub pin "
                           f"(see the 'Hub Source' column).")

            _bc1, _bc2 = st.columns(2)
            with _bc1:
                st.markdown("**Polygons per rate / category**")
                _br = (sel.assign(Rate=sel["Description"].replace("", "—"),
                                  Category=sel["Cluster_Category"].replace("", "—"))
                          .groupby(["Rate", "Category"]).size().reset_index(name="Polygons"))
                st.dataframe(_br, hide_index=True, width="stretch")
            with _bc2:
                st.markdown("**Polygons per hub / pincode**")
                _bp = sel.groupby(["Hub Name", "Pincode"]).size().reset_index(name="Polygons")
                st.dataframe(_bp, hide_index=True, width="stretch", height=min(300, 35 * len(_bp) + 38))

            _mm_map(sel, sel_pts)
            _slug = (sel_hubs[0] if len(sel_hubs) == 1 else f"{len(sel_hubs)}hubs").replace(" ", "_").replace("/", "_")
            _mm_downloads(sel, sel_pts, _slug, "mm_hub")

            # ── Photo: one PNG per selected hub (ZIP when several) ──
            st.markdown("**🖼 Hub photo**")
            _sig = (_active_mid, minfo["fetched_at"], tuple(sel_hubs), tuple(sel_layers))
            _ph_label = "🖼 Make photo" if len(sel_hubs) == 1 else f"🖼 Make photos ({len(sel_hubs)} hubs)"
            if st.button(_ph_label, key="mm_photo_btn",
                         help="Draws the selected hub(s) on a street map, coloured by payout rate. "
                              "Takes a few seconds per hub."):
                _pb = st.progress(0.0, text="Drawing…")
                try:
                    _photos = mmc.render_hub_photos(
                        sel, mhubs, sel_hubs,
                        progress_cb=lambda f, h: _pb.progress(f, text=f"Drew {h}"))
                    st.session_state["mm_photos"] = (_sig, _photos)
                    add_log(f"My Maps photo(s) made: {', '.join(sel_hubs)}", "success")
                except Exception as _pe:
                    st.error(f"Could not draw the photo: {_pe}")
                _pb.empty()
            _stored = st.session_state.get("mm_photos")
            if _stored and _stored[0] == _sig and _stored[1]:
                _photos = _stored[1]
                _stamp = datetime.now().strftime("%Y%m%d")
                if len(_photos) == 1:
                    st.download_button("⬇ Download photo (PNG)", _photos[0][1], f"{_slug}_{_stamp}.png",
                                       "image/png", key="mm_photo_dl", type="primary")
                else:
                    st.download_button(f"⬇ Download {len(_photos)} photos (ZIP)", mmc.photos_zip(_photos),
                                       f"{_slug}_photos_{_stamp}.zip", "application/zip",
                                       key="mm_photo_dl", type="primary")
                _pcols = st.columns(min(2, len(_photos)))
                for _i, (_hn, _png) in enumerate(_photos):
                    with _pcols[_i % len(_pcols)]:
                        st.image(_png, caption=_hn, width="stretch")

            _mm_table(sel, "mm_hub")

    # ── Overview ──
    with tab_all:
        kpi_row([
            ("Total Polygons", f"{len(mpoly):,}", "blue"),
            ("Hubs", f"{len(mmc.list_hubs(mpoly)):,}", "green"),
            ("Pincodes", f"{mpoly['Pincode'].replace('', pd.NA).nunique():,}", "purple"),
            ("Layers", f"{mpoly['Layer'].nunique()}", "orange"),
        ])
        _summ = _mymaps_hub_summary(minfo["mid"], minfo["fetched_at"], mpoly)
        st.markdown(f"**{len(_summ):,} hubs in {_active['name']}**")
        st.dataframe(_summ, hide_index=True, width="stretch", height=460)
        _o1, _o2, _o3 = st.columns(3)
        _mslug = re.sub(r"[^A-Za-z0-9_-]+", "_", _active["name"])[:40]
        with _o1:
            st.download_button("⬇ Hub summary CSV", _summ.to_csv(index=False).encode("utf-8-sig"),
                               f"{_mslug}_hub_summary_{datetime.now().strftime('%Y%m%d')}.csv", "text/csv",
                               key="mm_summ_dl", width="stretch")
        with _o2:
            st.download_button("⬇ All polygons CSV", _mymaps_all_csv(minfo["mid"], minfo["fetched_at"], mpoly),
                               f"{_mslug}_all_polygons_{datetime.now().strftime('%Y%m%d')}.csv", "text/csv",
                               key="mm_all_dl", width="stretch")
        with _o3:
            st.download_button("⬇ Hub locations CSV", mhubs.to_csv(index=False).encode("utf-8-sig"),
                               f"{_mslug}_hub_locations_{datetime.now().strftime('%Y%m%d')}.csv", "text/csv",
                               key="mm_hubs_dl", width="stretch")
        st.markdown("**Polygons per My Maps layer**")
        st.dataframe(mpoly.groupby("Layer").agg(Polygons=("Cluster_Code", "size"),
                                                Hubs=("Hub Name", "nunique")).reset_index(),
                     hide_index=True, width="stretch")

# ═══════════════════════════════════════════════════════
# STEP 8 — GO LIVE (standalone: works without Step 1)
# Builds the Saruman "Upload payout cluster" file (the payout_cluster_upload_sample
# "Main sheet") from polygons, with every row checked. See modules/golive.py.
# ═══════════════════════════════════════════════════════
elif nav.startswith("8"):
    from modules import golive as gl

    @st.cache_data(ttl=3600, show_spinner=False)
    def _gl_hub_info(_client, names):
        return gl.hub_info(_client, names)

    @st.cache_data(ttl=3600, show_spinner=False, max_entries=24)
    def _gl_photo(_polys, _hubs, hub, sig):
        from modules.mymaps_connector import get_hub_polygons, render_png
        return render_png(get_hub_polygons(_polys, hub), _hubs[_hubs["Hub Name"] == hub], hub, source="Go Live preview")

    @st.cache_data(ttl=3600, show_spinner=False)
    def _gl_service(_client, pins):
        return gl.serviceability_hubs(_client, pins)

    st.markdown('<div class="sfx-header">1 · Choose the polygons</div>', unsafe_allow_html=True)
    gl_src = st.radio("Where are the polygons?",
                      ["Paste rows", "Upload a file", "Polygons in this app", "Google My Maps"],
                      horizontal=True, key="gl_src")
    polys = None
    if gl_src == "Paste rows":
        st.caption("Paste exactly what you paste into the Wroking tab: one polygon per line, "
                   "WKT ⇥ name ⇥ category (copy the three columns from your sheet or My Maps export).")
        _txt = st.text_area("Rows", key="gl_paste", height=170, label_visibility="collapsed",
                            placeholder="POLYGON ((78.675316 16.423597, 78.66502 16.432034, ...))\t509375_A\tC1")
        polys = gl.parse_pasted(_txt) if _txt.strip() else None
        if _txt.strip() and (polys is None or polys.empty):
            st.markdown('<div class="sfx-warn">No rows found. Each line needs WKT, name and category separated by tabs.</div>',
                        unsafe_allow_html=True)
    elif gl_src == "Upload a file":
        _f = st.file_uploader("CSV, Excel or KML with polygons", type=["csv", "xlsx", "kml"], key="gl_file")
        if _f is not None:
            try:
                if _f.name.lower().endswith(".kml"):
                    from modules.mymaps_connector import parse_kml
                    polys = gl.normalise_table(parse_kml(_f.getvalue())[0])
                elif _f.name.lower().endswith(".xlsx"):
                    polys = gl.normalise_table(pd.read_excel(_f, dtype=str))
                else:
                    polys = gl.normalise_table(pd.read_csv(_f, dtype=str))
            except Exception as _e:
                st.error(f"Could not read the file: {_e}")
    elif gl_src == "Polygons in this app":
        _p = st.session_state.get("polygon_records_df")
        if _p is None or len(_p) == 0:
            st.markdown('<div class="sfx-warn">No polygons in the app yet. Generate them in Step 3, '
                        'or choose another option above.</div>', unsafe_allow_html=True)
        else:
            polys = gl.normalise_table(_p)
    else:
        _gl_links = _mymaps_links()
        _gl_by = {l["mid"]: l for l in _gl_links}
        _gl_mid = st.selectbox("My Map", list(_gl_by), format_func=lambda m: _gl_by[m]["name"], key="gl_map")
        _mm = _get_mymaps(_gl_by[_gl_mid]["url"]) if _gl_mid else None
        if _mm is not None:
            polys = gl.normalise_table(_mm["polygons"])

    if polys is not None and len(polys):
        _hubs_in = sorted(h for h in polys["Hub Name"].unique() if h)
        if _hubs_in:
            _many = gl_src == "Google My Maps" or len(_hubs_in) > 30
            _sel = st.multiselect(f"Hubs ({len(_hubs_in)} in these polygons)", _hubs_in,
                                  default=[] if _many else _hubs_in, key=f"gl_hubs_{gl_src}",
                                  placeholder="Pick the hubs to send live")
            polys = polys[polys["Hub Name"].isin(_sel)] if _sel else polys.iloc[0:0]
        _desc_opt = st.selectbox("Description (what Saruman should do)", gl.DESCRIPTIONS + ["Other (type it)"],
                                 key="gl_desc", help="Fills the Description column. 'Deactivated Clustering Payout' switches "
                                                      "the clusters off.")
        gl_action = (st.text_input("Description text", key="gl_desc_other").strip() or gl.DESC_ACTIVATE)             if _desc_opt.startswith("Other") else _desc_opt
        st.caption(f"{len(polys):,} polygon(s) selected.")

        st.markdown('<div class="sfx-header">2 · Check every row</div>', unsafe_allow_html=True)
        _bq = st.session_state.get("bq_client")
        if _bq is None:
            st.markdown('<div class="sfx-err">BigQuery is not connected. Hub Ids and today\'s serviceability come from '
                        'BigQuery: connect it with the status button at the top right.</div>', unsafe_allow_html=True)
        elif len(polys):
            _sig = (gl_src, gl_action, len(polys), hash(tuple(polys["Cluster_Code"])), hash(tuple(polys["Polygon WKT"].str[:60])))
            if st.button(f"Check {len(polys):,} polygon(s)", type="primary", key="gl_check"):
                with st.spinner("Looking up Hub Ids and today's serviceability in BigQuery..."):
                    try:
                        _pins = tuple(sorted(set(polys["Pincode"].str.strip()) | set(polys["Cluster_Code"].str[:6])))
                        _svc = _gl_service(_bq, _pins)
                        _names = tuple(sorted(set(polys["Hub Name"]) | {h for v in _svc.values() for h in v}))
                        _info = _gl_hub_info(_bq, _names)
                        st.session_state["gl_rows"] = gl.build_rows(polys, gl_action, {k: v["id"] for k, v in _info.items()}, _svc)
                        st.session_state["gl_info"] = _info
                        st.session_state["gl_sig"] = _sig
                        add_log(f"Go Live: checked {len(polys)} polygons", "info")
                    except Exception as _e:
                        st.error(f"BigQuery lookup failed: {_e}")
            rows = st.session_state.get("gl_rows") if st.session_state.get("gl_sig") == _sig else None
            if rows is not None:
                _n = rows["Status"].value_counts()
                html_block(f'''<div class="kpi-row">
                    <div class="kpi-card"><div class="kpi-label">Ready</div><div class="kpi-value">{_n.get(gl.OK, 0):,}</div></div>
                    <div class="kpi-card"><div class="kpi-label">Need a check</div><div class="kpi-value">{_n.get(gl.CHECK, 0):,}</div></div>
                    <div class="kpi-card red"><div class="kpi-label">Errors (left out)</div><div class="kpi-value">{_n.get(gl.ERROR, 0):,}</div></div>
                    <div class="kpi-card"><div class="kpi-label">Hubs</div><div class="kpi-value">{rows["Hub Name"].replace("", pd.NA).nunique():,}</div></div>
                </div>''')
                _show = st.radio("Show", ["All rows", "Need a check", "Errors"], horizontal=True, key="gl_show")
                _view = rows if _show == "All rows" else rows[rows["Status"] == (gl.CHECK if _show == "Need a check" else gl.ERROR)]
                st.dataframe(_view.drop(columns=["Boundary"]), hide_index=True, width="stretch", height=380,
                             column_config={"Hub Id": st.column_config.NumberColumn(format="%d"),
                                            "Problem": st.column_config.TextColumn(width="large")})

                # ── 3 · Preview: polygons, rates and the registered hub location, per hub ──
                _pv_polys, _pv_hubs = gl.preview_frames(rows, st.session_state.get("gl_info", {}))
                if len(_pv_polys):
                    st.markdown('<div class="sfx-header">3 · Preview before you upload</div>', unsafe_allow_html=True)
                    st.caption("Check each hub: polygons coloured and labelled by rate, and the hub pin at the location "
                               "registered in Shadowfax's hub list.")
                    _pv_hub_list = sorted(_pv_polys["Hub Name"].unique())
                    _pv_hub = st.selectbox(f"Hub to preview ({len(_pv_hub_list)})", _pv_hub_list, key="gl_pv_hub")
                    _pv_sub = _pv_polys[_pv_polys["Hub Name"] == _pv_hub]
                    _km = gl.hub_distance_km(_pv_polys, _pv_hubs, _pv_hub)
                    _rates = (_pv_sub.groupby(["Cluster_Category", "Description"]).size().reset_index(name="n")
                              .assign(k=lambda d: d["Cluster_Category"].str[1:].astype(int)).sort_values("k"))
                    _hub_row = _pv_hubs[_pv_hubs["Hub Name"] == _pv_hub]
                    _loc = (f'{float(_hub_row["Hub_lat"].iloc[0]):.5f}, {float(_hub_row["Hub_long"].iloc[0]):.5f}'
                            if len(_hub_row) else "not in hub list")
                    html_block(f'''<div class="kpi-row">
                        <div class="kpi-card"><div class="kpi-label">Polygons</div><div class="kpi-value">{len(_pv_sub)}</div></div>
                        <div class="kpi-card"><div class="kpi-label">Pincodes</div><div class="kpi-value">{_pv_sub["Pincode"].nunique()}</div></div>
                        <div class="kpi-card"><div class="kpi-label">Rates</div><div class="kpi-value">{" · ".join(_rates["Description"].unique())}</div></div>
                        <div class="kpi-card {"red" if (_km or 0) > 25 else ""}"><div class="kpi-label">Hub to nearest polygon</div><div class="kpi-value">{"—" if _km is None else f"{_km:g} km"}</div></div>
                    </div>''')
                    if _km is not None and _km > 25:
                        st.markdown(f'<div class="sfx-warn">The registered location of <b>{_pv_hub}</b> ({_loc}) is {_km:g} km '
                                    f'from its nearest polygon. Check that these polygons belong to this hub.</div>',
                                    unsafe_allow_html=True)
                    _pt1, _pt2 = st.tabs(["Map", "Photo"])
                    with _pt1:
                        try:
                            from modules.visualizer import create_polygon_map
                            _m = create_polygon_map(_pv_sub, _hub_row, None, False, "none", None, None, None, show_rate_labels=True)
                            st.iframe(_m._repr_html_(), height=560) if _m is not None else st.caption("Nothing to draw.")
                        except Exception as _e:
                            st.caption(f"Map unavailable: {_e}")
                        st.caption(f"Hub location (Shadowfax hub list): {_loc}")
                    with _pt2:
                        _psig = hash((tuple(_pv_sub["Cluster_Code"]), tuple(_pv_sub["Polygon WKT"].str[:40])))
                        _png = _gl_photo(_pv_polys, _pv_hubs, _pv_hub, _psig)
                        st.image(_png, caption=f"{_pv_hub}: polygons by rate on a street map", width="stretch")
                        _c1, _c2, _ = st.columns([1, 1, 2])
                        with _c1:
                            st.download_button("⬇ This hub's photo", _png, f"{_pv_hub}.png", "image/png",
                                               key="gl_pv_png", width="stretch")
                        with _c2:
                            def _all_photos(_p=_pv_polys, _h=_pv_hubs, _l=tuple(_pv_hub_list)):
                                from modules.mymaps_connector import photos_zip, render_hub_photos
                                return photos_zip(render_hub_photos(_p, _h, list(_l)))
                            st.download_button(f"⬇ All {len(_pv_hub_list)} hub photos (.zip)",
                                               _all_photos if _LAZY_DL else _all_photos(),
                                               f"golive_preview_{datetime.now().strftime('%Y%m%d')}.zip", "application/zip",
                                               key="gl_pv_zip", width="stretch")

                st.markdown('<div class="sfx-header">4 · Download the upload file</div>', unsafe_allow_html=True)
                _inc = st.checkbox(f"Include the {_n.get(gl.CHECK, 0):,} row(s) that need a check (after you have reviewed them)",
                                   value=True, key="gl_inc") if _n.get(gl.CHECK, 0) else True
                _main = gl.main_sheet(rows, include_checks=_inc)
                if _main.empty:
                    st.markdown('<div class="sfx-warn">No rows to upload. Fix the errors above first.</div>', unsafe_allow_html=True)
                else:
                    _base = f"payout_cluster_upload_{datetime.now().strftime('%Y%m%d_%H%M')}"
                    st.caption(f"{len(_main):,} row(s) in the same layout as the 'Main sheet' tab "
                               f"(Hub Id, Cluster Code, Description, Boundary, Cluster Category, Pincode, Surge Amount). "
                               f"Upload it in Saruman → Geocode → Upload payout cluster.")
                    _d1, _d2, _ = st.columns([1, 1, 2])
                    with _d1:
                        st.download_button("⬇ Excel (.xlsx)", gl.to_xlsx(_main), f"{_base}.xlsx", type="primary",
                                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                           key="gl_dl_xlsx", width="stretch")
                    with _d2:
                        st.download_button("⬇ CSV", gl.to_csv(_main), f"{_base}.csv", "text/csv",
                                           key="gl_dl_csv", width="stretch")
                    with st.expander("Preview the upload rows"):
                        st.dataframe(_main, hide_index=True, width="stretch", height=260)


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
            colors = {"info": "#7a817e", "success": "#0aa75f", "warning": "#f08a00", "error": "#e5473b"}
            c = colors.get(dot_cls, "#7a817e")
            st.markdown(f'<div class="log-entry log-{dot_cls}"><span class="log-dot" style="background:{c}"></span><span style="flex:1">{log["msg"]}</span><span class="log-time">{log["time"]}</span></div>', unsafe_allow_html=True)
        if st.button("Clear Log", key="clear_log"):
            st.session_state["app_logs"] = []
            st.rerun()

ui_theme.render_footer(datetime.now().year)

# ═══════════════════════════════════════════════════════
# AUTO-PERSIST — Sync session DataFrames to DuckDB
# ═══════════════════════════════════════════════════════
try:
    from modules.duckdb_store import TABLE_MAP, save_df, _is_streamlit_cloud
    # Skip auto-persist on Cloud (read-only FS, /tmp/ is ephemeral anyway).
    # Locally, save a table only when its DataFrame is new or was replaced (a new
    # P-mapping / polygon / AWB result) — never data that was just loaded from disk.
    if not _is_streamlit_cloud():
        _pids = st.session_state.setdefault("_persisted_ids", {})
        for _ss_key in TABLE_MAP:
            _df = st.session_state.get(_ss_key)
            if _df is not None and hasattr(_df, "to_csv") and not _df.empty and _pids.get(_ss_key) != id(_df):
                save_df(_ss_key, _df)
                _pids[_ss_key] = id(_df)
except Exception:
    pass
