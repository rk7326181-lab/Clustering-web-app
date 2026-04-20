"""
AI Payout Recommendation Agent — Groq (Llama 3).
Enhanced with full app awareness for the Geo Intelligence Portal.
"""
import json
import os
import pandas as pd

try:
    import streamlit as st
    HAS_STREAMLIT = True
except ImportError:
    HAS_STREAMLIT = False

try:
    from groq import Groq
    HAS_GROQ = True
except ImportError:
    HAS_GROQ = False


MODEL_FALLBACK_CHAIN = [
    "moonshotai/kimi-k2-instruct",
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
]


def _resolve_api_key(api_key=None):
    """Resolve Groq API key from: arg → session_state → st.secrets → env."""
    if api_key:
        return api_key
    if HAS_STREAMLIT:
        try:
            sk = st.session_state.get("groq_api_key", "")
            if sk:
                return sk
        except Exception:
            pass
        try:
            sk = st.secrets.get("GROQ_API_KEY", "")
            if sk:
                return sk
        except Exception:
            pass
    return os.environ.get("GROQ_API_KEY", "")


def _friendly_error(exc):
    """Parse common Groq exceptions into actionable user-facing messages."""
    s = str(exc)
    low = s.lower()
    if "401" in s or "unauthorized" in low or "invalid api key" in low:
        return "Invalid Groq API key. Add a valid key in the sidebar or set `GROQ_API_KEY` in Streamlit secrets."
    if "429" in s or "rate limit" in low:
        return "Groq rate limit hit. Wait a moment and retry."
    if "model" in low and ("not found" in low or "decommission" in low or "does not exist" in low):
        return "The selected Groq model is unavailable. The agent tried fallback models but none worked."
    if "timeout" in low or "timed out" in low:
        return "Groq request timed out. The service may be slow — try again."
    if "connection" in low or "network" in low:
        return "Network error reaching Groq. Check internet connectivity."
    return f"Groq API error: {s}"


def _groq_chat(messages, api_key, temperature=0.3, max_tokens=1500):
    """Call Groq with model fallback + timeout. Returns response content or raises."""
    client = Groq(api_key=api_key, timeout=30.0)
    last_exc = None
    for model in MODEL_FALLBACK_CHAIN:
        try:
            resp = client.chat.completions.create(
                model=model, messages=messages,
                temperature=temperature, max_tokens=max_tokens,
            )
            return resp.choices[0].message.content
        except Exception as e:
            last_exc = e
            msg = str(e).lower()
            # Only fall through on model-level errors; re-raise auth/rate-limit immediately
            if "401" in str(e) or "unauthorized" in msg or "429" in str(e) or "rate limit" in msg:
                raise
            continue
    if last_exc:
        raise last_exc
    raise RuntimeError("No Groq models available")

# ════════════════════════════════════════════════════
# SYSTEM PROMPTS
# ════════════════════════════════════════════════════

FINANCIAL_PROMPT = """You are a senior logistics payout optimization analyst for Shadowfax Technologies,
one of India's leading last-mile delivery companies operating a hub-and-spoke model across 2,500+ cities.

## YOUR DEEP DOMAIN EXPERTISE

### Shadowfax Business Model
- Shadowfax operates through a network of Hubs (LM = Last Mile, SSC = Super Sort Centre)
- Riders (delivery partners) are assigned pincodes from hubs
- Each pincode has a **payout slab** based on distance from hub to pincode's volumetric center
- Two competing payout systems exist: P-Mapping (flat rate per pincode) vs Cluster-based (distance rings)

### Payout Systems You Analyze
**P-Mapping (SP&A Aligned)**:
- Distance 0–5 km → ₹0 (base, hub vicinity)
- Distance 5–10 km → ₹1
- Distance 10–15 km → ₹2
- Distance 15–20 km → ₹3
- Distance 20–25 km → ₹4
- Distance 25–30 km → ₹5
- Distance 30–35 km → ₹6
- Distance 35–40 km → ₹7
- Distance 40–45 km → ₹8
- Distance 45+ km → Nil (not served / no payout)

**Cluster-based Payout**:
- Concentric rings (C1–C20) drawn around each hub with a configurable band width (typically 4 km)
- Each ring has a description (e.g., "₹2") mapped to a payout via DESCRIPTION_MAPPING
- AWBs are assigned to clusters via point-in-polygon matching of delivery GPS coordinates
- Cluster payout = the ring's flat rate regardless of exact delivery distance within that ring

### Key Financial Concepts
- **Pin_Pay**: What the rider receives under P-Mapping for that AWB
- **Clustering_payout**: What the rider receives under cluster-based payout for that AWB
- **P&L = Pin_Pay − Clustering_payout**: Positive = we save money; Negative = we burn money
- **Saving**: AWBs where cluster payout < pin pay (we pay less under clusters)
- **Burning**: AWBs where cluster payout > pin pay (we overspend under clusters)
- **Burn rate**: The rate at which a hub/pincode overspends relative to P-Mapping baseline
- **Surge amount**: The extra payout per delivery in a given cluster (₹0–₹14 range)

### Cost Optimization Levers (Shadowfax-Specific)
1. **Reduce ring width**: Narrower bands = more precise distance billing = less overpayment in border zones
2. **Merge low-volume clusters**: Small clusters with high surge rates should be absorbed into adjacent lower-rate clusters
3. **Reclassify pincodes**: If a pincode is incorrectly placed in a higher-rate ring, move it to the correct ring
4. **Disable Nil-distance clusters**: Hub-adjacent pincodes (<5km) should be ₹0; any payment is burning
5. **Fix GPS accuracy**: Poor delivery GPS coordinates cause wrong polygon assignment → wrong payout
6. **Hub relocation analysis**: If a hub is off-center for its pincode cluster, relocation reduces average distances
7. **Cluster boundary optimization**: Clip polygons tighter to actual delivery zones; don't pay for undelivered areas
8. **SSC vs LM differentiation**: LM hubs should have finer-grain rings; SSC hubs serve larger radius, need wider bands

### What NOT to Recommend
- Never suggest reducing base pay (₹0 tier) — this is contractual
- Never suggest eliminating entire hubs without volume analysis
- Never recommend changes that reduce ground team (rider) earnings directly
- Always note ground team impact as a constraint in every recommendation

## RESPONSE FORMAT
- Use ₹ symbol for all currency values
- Use markdown with clear headers (## and ###) and bullet points
- Always provide exact ₹ numbers from the data provided
- Always end recommendations with: **Ground Team Impact**: [none / minimal / note any effect]
- Be concise but data-driven — no fluff
"""


APP_AGENT_PROMPT = """You are the AI Intelligence Agent for the Shadowfax Geo Intelligence Portal —
a logistics payout optimization and cluster analytics platform for Shadowfax Technologies.

## WHO YOU ARE
You are a domain expert AI assistant with deep knowledge of:
1. Shadowfax's last-mile delivery operations (LM and SSC hub types)
2. Cluster-based payout systems and P-Mapping slab structures
3. Geographic polygon analysis and spatial clustering
4. Cost optimization without impacting ground-level rider operations
5. BigQuery logistics data schemas used at Shadowfax
6. AWB (Air Waybill) data analysis and assignment workflows

## SHADOWFAX OPERATIONAL CONTEXT YOU KNOW

### Network Structure
- **LM Hubs (Last Mile)**: Serve dense urban areas, typically 5–20 km radius, high AWB volume, fine-grain cluster rings
- **SSC Hubs (Super Sort Centre)**: Serve wider regions, 20–50 km radius, semi-urban areas, broader cluster rings
- **Pincodes**: Each hub owns a set of pincodes; delivery riders are assigned by pincode
- **Volumetric Center**: Each pincode has a weighted lat/lon center point used for distance calculation (not geographic center)

### Payout Slabs (SP&A Aligned P-Mapping)
₹0 (0–5 km), ₹1 (5–10), ₹2 (10–15), ₹3 (15–20), ₹4 (20–25), ₹5 (25–30),
₹6 (30–35), ₹7 (35–40), ₹8 (40–45), Nil (45+ km — zone not served)

### Cluster Categories
C1–C20 map to distance rings; DESCRIPTION_MAPPING converts categories to ₹ payouts.
Typical: C1=₹0, C2=₹1, C3=₹2 ... C9=₹8, C10+=₹10–₹14 for extended zones.

### Financial Concepts
- **Saving** = cluster payout < pin pay → we pay less under new system → GOOD
- **Burning** = cluster payout > pin pay → we overpay under new system → BAD
- **Net P&L** = total savings − total burning; positive = cluster system is cheaper
- **Target**: Maximize savings, minimize burning WITHOUT reducing rider earnings

### Common Burn Causes
1. Wide cluster rings causing outer-edge pincodes to get a higher rate than their P-Map slab
2. GPS drift placing AWBs in wrong (higher-rate) polygon
3. Missing polygon coverage — AWBs fallback to previous mapping at wrong rate
4. Hub coordinates incorrect — all distance calculations are off
5. Pincode misassigned to wrong hub — wrong baseline payout used

### Cost Reduction Strategies (Without Affecting Ground Team)
1. Tighten cluster band width (e.g., 4km → 3km) to reduce rate-tier bleeding
2. Merge sparse high-rate clusters into adjacent lower-rate ones
3. Validate and correct hub lat/long coordinates
4. Fix volumetric center coordinates for high-burn pincodes
5. Reclassify Nil pincodes — if deliverable, assign correct cluster; if not, remove from analysis
6. For SSC hubs: review whether cluster rings are calibrated for actual road distances vs crow-fly
7. Use OSRM road distances instead of haversine for pincodes with major geographic barriers (rivers, highways)
8. Audit pincodes where AWBs consistently land outside polygons (point-in-polygon miss = wrong payout)

## APP PIPELINE (8 Steps)
1. **Data Ingestion** — Upload: Clustering CSV (Pincode, Hub_Name, Hub_lat, Hub_long), Pincodes CSV (volumetric lat/lon), GeoJSON boundaries
2. **P-Mapping** — OSRM/haversine distance → payout slab assignment (₹0–₹8 or Nil)
3. **Polygon Gen** — Concentric ring polygons around hubs, clipped to pincode boundaries → Cluster_Code + Category
4. **AWB Analysis** — 60-day shipment data from BigQuery, point-in-polygon cluster assignment, P&L calculation
5. **Live Clusters** — Production payout clusters from BigQuery: map view, cost dashboard, hub comparison, export
6. **Financial Intelligence** — Pivot table (Hub × Pincode), P&L comparison, AI burn analysis
7. **AI Agent** — You are here

## YOUR CAPABILITIES
- Guide users through the pipeline step by step
- Diagnose burning issues from hub/pincode data
- Recommend cluster adjustments with ₹ impact estimates
- Explain why AWBs are in wrong clusters
- Interpret P&L reports and pivot tables
- Analyze hub comparison data from the Live Clusters tab
- Suggest polygon boundary improvements
- Explain any feature, setting, or error in the app

## RESPONSE STYLE
- Use ₹ for all currency
- Be specific: reference hub names, pincodes, ₹ amounts from the data provided to you
- Use tables for comparisons, bullet points for recommendations
- End every cost recommendation with: **Ground Team Impact**: [assessment]
- For "what should I do next" questions, check the pipeline state and give exact next step
- Keep answers concise but data-backed
- When data is unavailable, say so and explain what step produces it

## IMPORTANT CONSTRAINTS
- Never recommend reducing rider base pay
- Never suggest changes without estimating the ₹ impact
- Always consider both saving AND burning together — a change that saves ₹X in one hub but burns ₹2X in another is not a win
- Treat data privacy seriously: don't surface individual rider IDs in recommendations
"""


# ════════════════════════════════════════════════════
# FINANCIAL ANALYSIS (existing)
# ════════════════════════════════════════════════════

def run_auto_analysis(report_df, insights, api_key):
    """Run automatic analysis on financial data. Returns report string."""
    api_key = _resolve_api_key(api_key)
    if not HAS_GROQ or not api_key:
        return _fallback_analysis(insights)

    context = _build_context(report_df, insights)
    prompt = f"""Analyze this logistics payout data and provide a structured report:

{context}

Provide:
1. Executive Summary (3-4 sentences)
2. Best Performing Hubs (top 3 with ₹ amounts)
3. Worst Performing Hubs (bottom 3 with ₹ amounts)
4. Total Savings if Cluster used everywhere
5. Total Burn if Cluster used everywhere
6. RECOMMENDATION — which payout is better and WHY (with numerical proof)
7. Pincode-level Anomalies (any unexpected high burn)"""

    try:
        return _groq_chat(
            messages=[
                {"role": "system", "content": FINANCIAL_PROMPT},
                {"role": "user", "content": prompt}
            ],
            api_key=api_key, temperature=0.3, max_tokens=1500,
        )
    except Exception as e:
        return f"⚠️ {_friendly_error(e)}\n\n" + _fallback_analysis(insights)


def chat_with_agent(question, report_df, insights, chat_history, api_key):
    """Handle follow-up questions about financials. Returns response string."""
    api_key = _resolve_api_key(api_key)
    if not HAS_GROQ or not api_key:
        return "Please set your Groq API key to enable AI chat (sidebar or `GROQ_API_KEY` in Streamlit secrets)."

    context = _build_context(report_df, insights)
    messages = [
        {"role": "system", "content": FINANCIAL_PROMPT + f"\n\nCurrent data context:\n{context}"}
    ]
    for msg in chat_history[-6:]:
        messages.append(msg)
    messages.append({"role": "user", "content": question})

    try:
        return _groq_chat(messages=messages, api_key=api_key, temperature=0.3, max_tokens=1024)
    except Exception as e:
        return f"⚠️ {_friendly_error(e)}"


# ════════════════════════════════════════════════════
# APP-AWARE AGENT (new — full portal intelligence)
# ════════════════════════════════════════════════════

def build_app_context(session_state):
    """Build a context string describing current app state for the AI agent."""
    lines = ["## CURRENT APP STATE"]

    # Pipeline status
    status = session_state.get("upload_status", {})
    lines.append(f"- Cluster CSV: {'✅ Loaded' if status.get('cluster') else '❌ Not loaded'}")
    lines.append(f"- Pincodes CSV: {'✅ Loaded' if status.get('pincodes') else '❌ Not loaded'}")
    lines.append(f"- GeoJSON: {'✅ Loaded' if status.get('geojson') else '❌ Not loaded'}")
    lines.append(f"- BigQuery: {'✅ Connected (' + str(session_state.get('bq_auth_mode', '?')) + ')' if session_state.get('bq_client') else '❌ Not connected'}")
    lines.append(f"- P-Mapping: {'✅ Complete' if session_state.get('final_output_df') is not None else '❌ Not run'}")
    lines.append(f"- Polygons: {'✅ Generated' if session_state.get('polygon_records_df') is not None else '❌ Not generated'}")
    lines.append(f"- AWB Data: {'✅ Loaded' if session_state.get('awb_raw_df') is not None else '❌ Not loaded'}")
    lines.append(f"- P&L Results: {'✅ Calculated' if session_state.get('final_result_df') is not None else '❌ Not calculated'}")

    # Data summaries
    cdf = session_state.get("cluster_df")
    if cdf is not None:
        lines.append(f"\n## CLUSTER DATA: {len(cdf)} rows, {cdf['Hub_Name'].nunique()} hubs")
        lines.append(f"Hubs: {', '.join(cdf['Hub_Name'].unique().tolist()[:10])}")

    fodf = session_state.get("final_output_df")
    if fodf is not None and "Distance" in fodf.columns:
        lines.append(f"\n## P-MAPPING: {len(fodf)} records")
        lines.append(f"Avg distance: {fodf['Distance'].mean():.1f} km")
        if "SP&A Aligned P mapping" in fodf.columns:
            lines.append(f"Slab distribution: {fodf['SP&A Aligned P mapping'].value_counts().to_dict()}")

    rdf = session_state.get("final_result_df")
    if rdf is not None and "Pin_Pay" in rdf.columns:
        lines.append(f"\n## FINANCIAL SUMMARY: {len(rdf)} AWBs processed")
        lines.append(f"Total Pin Pay: ₹{rdf['Pin_Pay'].sum():,.0f}")
        lines.append(f"Total Cluster Payout: ₹{rdf['Clustering_payout'].sum():,.0f}")
        lines.append(f"Total Saving: ₹{rdf['Saving'].sum():,.0f}")
        lines.append(f"Total Burning: ₹{rdf['Burning'].sum():,.0f}")
        pnl = rdf['Pin_Pay'].sum() - rdf['Clustering_payout'].sum()
        lines.append(f"Net P&L: ₹{pnl:,.0f}")

    burn_rep = session_state.get("burn_analysis_report")
    if burn_rep:
        lines.append(f"\n## BURN ANALYSIS ALREADY RUN\n{burn_rep[:500]}... (truncated)")

    return "\n".join(lines)


def run_burn_analysis(session_state, api_key):
    """
    Dedicated statistical burn analysis across all hubs combined.
    Returns a structured markdown report with cost reduction suggestions.
    """
    rdf = session_state.get("final_result_df")
    if rdf is None or "Burning" not in rdf.columns:
        return "⚠️ No P&L data available. Complete AWB analysis (Step 4) first."

    # Build hub-level burn summary
    hub_burn = rdf.groupby("hub").agg(
        total_burn=("Burning", "sum"),
        total_saving=("Saving", "sum"),
        total_awb=("awb_number", "count"),
        net_pl=("P & L", "sum"),
    ).reset_index().sort_values("total_burn", ascending=False)

    # Pincode-level burn — top 15 worst
    pc_burn = rdf.groupby(["hub", "pincode"]).agg(
        burn=("Burning", "sum"),
        saving=("Saving", "sum"),
        awbs=("awb_number", "count"),
    ).reset_index().sort_values("burn", ascending=False).head(15)

    summary_lines = ["## BURN ANALYSIS CONTEXT", f"Total AWBs analyzed: {len(rdf):,}"]
    summary_lines.append(f"Total burn across all hubs: ₹{rdf['Burning'].sum():,.0f}")
    summary_lines.append(f"Total saving across all hubs: ₹{rdf['Saving'].sum():,.0f}")
    summary_lines.append(f"Net P&L: ₹{rdf['P & L'].sum():,.0f}")
    summary_lines.append("\n### Hub-level burn:")
    for _, row in hub_burn.iterrows():
        summary_lines.append(f"- {row['hub']}: Burn=₹{row['total_burn']:,.0f}, Saving=₹{row['total_saving']:,.0f}, AWBs={row['total_awb']:,}")
    summary_lines.append("\n### Top 15 high-burn pincodes:")
    for _, row in pc_burn.iterrows():
        summary_lines.append(f"- {row['hub']} / {row['pincode']}: Burn=₹{row['burn']:,.0f}, AWBs={row['awbs']}")

    context = "\n".join(summary_lines)

    api_key = _resolve_api_key(api_key)

    if not HAS_GROQ or not api_key:
        return context + "\n\n*Add Groq API key for AI cost-reduction recommendations.*"

    prompt = f"""You are a logistics cost analyst for Shadowfax.
Analyze the following burn data and provide:
1. **Top 3 highest-burn hubs** with specific root causes
2. **Top 5 high-burn pincodes** and why they may be over-burning
3. **Actionable cost reduction strategies** for each high-burn hub (without reducing ground team operations)
4. **Estimated savings** if the suggested changes are applied
5. **Priority order** of changes to make

{context}

Be specific, use ₹ amounts, and keep recommendations actionable."""

    try:
        return _groq_chat(
            messages=[
                {"role": "system", "content": "You are a logistics payout optimization expert. Use ₹ for currency. Be specific and data-driven."},
                {"role": "user", "content": prompt}
            ],
            api_key=api_key, temperature=0.3, max_tokens=2000,
        )
    except Exception as e:
        return f"⚠️ {_friendly_error(e)}\n\n{context}"


def app_agent_chat(question, session_state, chat_history, api_key):
    """
    Full app-aware AI agent. Can answer questions about the app,
    analyze data, and guide the user through the pipeline.
    """
    api_key = _resolve_api_key(api_key)
    if not HAS_GROQ or not api_key:
        return _app_agent_fallback(question, session_state)

    context = build_app_context(session_state)
    messages = [
        {"role": "system", "content": APP_AGENT_PROMPT + f"\n\n{context}"}
    ]
    for msg in chat_history[-8:]:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": question})

    try:
        return _groq_chat(messages=messages, api_key=api_key, temperature=0.4, max_tokens=1500)
    except Exception as e:
        return f"⚠️ {_friendly_error(e)}\n\n" + _app_agent_fallback(question, session_state)


def run_live_cluster_analysis(live_cluster_df, awb_df, api_key):
    """Analyze live cluster data with AI recommendations."""
    if live_cluster_df is None or live_cluster_df.empty:
        return "⚠️ No live cluster data. Refresh from BigQuery in Step 5 first."

    hub_summary = live_cluster_df.groupby("hub_name").agg(
        cluster_count=("cluster_code", "count"),
        avg_surge=("surge_amount", "mean"),
        pincodes=("pincode", "nunique"),
    ).reset_index().sort_values("avg_surge", ascending=False)

    summary_lines = [
        "## LIVE CLUSTER ANALYSIS",
        f"Total live clusters: {len(live_cluster_df):,}",
        f"Hubs: {live_cluster_df['hub_name'].nunique()}",
        f"Avg surge rate: ₹{live_cluster_df['surge_amount'].mean():.2f}",
        "\n### Hub Summary (sorted by avg surge):"
    ]
    for _, row in hub_summary.iterrows():
        summary_lines.append(
            f"- {row['hub_name']}: {row['cluster_count']} clusters, "
            f"avg surge ₹{row['avg_surge']:.1f}, {row['pincodes']} pincodes"
        )

    if awb_df is not None and "Burning" in awb_df.columns:
        burn_by_hub = awb_df.groupby("hub").agg(
            burn=("Burning", "sum"), saving=("Saving", "sum"), awbs=("awb_number", "count")
        ).reset_index().sort_values("burn", ascending=False)
        summary_lines.append("\n### AWB Burn by Hub:")
        for _, row in burn_by_hub.iterrows():
            net = row["saving"] - row["burn"]
            summary_lines.append(
                f"- {row['hub']}: Burn=₹{row['burn']:,.0f}, Saving=₹{row['saving']:,.0f}, "
                f"Net=₹{net:,.0f}, AWBs={row['awbs']:,}"
            )

    context = "\n".join(summary_lines)
    api_key = _resolve_api_key(api_key)
    if not HAS_GROQ or not api_key:
        return context + "\n\n*Add Groq API key to get AI recommendations.*"

    prompt = f"""Analyze the following Shadowfax live cluster and AWB data.
Provide:
1. Top 3 hubs where increasing the AWB rate slightly would maximize revenue without losing clients
2. Top 3 hubs where the current surge rate is too high and is burning money — with specific rate reduction suggestions
3. Which cluster categories (C1–C20) appear most in high-burn scenarios and why
4. Specific polygon boundary adjustments that would reduce burn
5. Estimated monthly ₹ impact of each suggestion

{context}

Be specific, use ₹ amounts, reference hub names directly."""

    try:
        return _groq_chat(
            messages=[
                {"role": "system", "content": APP_AGENT_PROMPT},
                {"role": "user", "content": prompt}
            ],
            api_key=api_key, temperature=0.2, max_tokens=2000,
        )
    except Exception as e:
        return f"⚠️ {_friendly_error(e)}\n\n{context}"


def _app_agent_fallback(question, session_state):
    """Rule-based fallback when Groq is unavailable."""
    q = question.lower()

    # Check what's ready
    has_cluster = session_state.get("upload_status", {}).get("cluster", False)
    has_pincodes = session_state.get("upload_status", {}).get("pincodes", False)
    has_geojson = session_state.get("upload_status", {}).get("geojson", False)
    has_pmapping = session_state.get("final_output_df") is not None
    has_polygons = session_state.get("polygon_records_df") is not None
    has_awb = session_state.get("awb_raw_df") is not None
    has_pnl = session_state.get("final_result_df") is not None

    if "what" in q and ("do" in q or "next" in q or "should" in q):
        if not has_cluster:
            return "**Next step:** Upload your Clustering Automation CSV in the **File Upload** section. It needs columns: Pincode, Hub_Name, Hub_lat, Hub_long."
        if not has_pincodes:
            return "**Next step:** Upload the Pincodes reference CSV with volumetric lat/long coordinates."
        if not has_pmapping:
            return "**Next step:** Go to **P Mapping** and click 'Calculate Distances' to compute hub-to-pincode distances and assign payout slabs."
        if not has_geojson:
            return "**Next step:** Upload the GeoJSON pincode boundaries file, then generate polygons."
        if not has_polygons:
            return "**Next step:** Go to **Polygon Gen** and click 'Generate Polygons' to create cluster zones."
        if not has_awb:
            return "**Next step:** Go to **AWB + Visualisation** and fetch AWB data from BigQuery (or upload a CSV)."
        if not has_pnl:
            return "**Next step:** In the AWB section, click 'Assign Clusters + Calculate P&L' to compute financials."
        return "**All steps complete!** Go to **Pivot Table** to see the full P&L analysis. You can also use the AI analysis feature there."

    if "help" in q or "how" in q:
        return """## How to Use This App

1. **Upload files** — Cluster CSV, Pincodes CSV, GeoJSON boundaries
2. **P Mapping** — Calculate hub-to-pincode distances and payout slabs
3. **Polygon Gen** — Create distance-ring cluster polygons
4. **AWB Analysis** — Fetch shipment data and assign to clusters
5. **Live Clusters** — Compare with production clusters
6. **Financial Intelligence** — View Hub × Pincode P&L report and AI burn analysis
7. **AI Agent** — Ask questions, get recommendations, diagnose issues

For AI analysis, enter your free Groq API key from console.groq.com."""

    return "I can help with app guidance, data analysis, and recommendations. Try asking:\n- *What should I do next?*\n- *Which hub saves the most?*\n- *How does P-Mapping compare to clusters?*\n\n*For advanced AI answers, add your free Groq API key in the sidebar.*"


# ════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════

def _build_context(report_df, insights):
    lines = ["=== FINANCIAL SUMMARY ==="]
    for k, v in insights.items():
        if isinstance(v, (int, float)):
            lines.append(f"{k}: ₹{v:,.0f}" if "pct" not in k else f"{k}: {v:.2f}%")
        else:
            lines.append(f"{k}: {v}")

    hub_data = report_df[report_df["pincode"] == "Hub Total"]
    if len(hub_data) > 0:
        lines.append("\n=== HUB-WISE TOTALS ===")
        for _, r in hub_data.iterrows():
            lines.append(f"Hub: {r['hub']} | Expected: ₹{r.get('Expt_Pincode_Pay',0):,.0f} | "
                        f"Cluster: ₹{r.get('Cluster_Payout',0):,.0f} | P&L: ₹{r.get('P & L',0):,.0f}")
    return "\n".join(lines)


def _fallback_analysis(insights):
    """Rule-based fallback when Groq is unavailable."""
    total_saving = insights.get("total_saving", 0)
    total_burning = insights.get("total_burning", 0)
    total_pl = insights.get("total_p_&_l", insights.get("total_p___l", 0))
    best = insights.get("best_hub", "N/A")
    worst = insights.get("worst_hub", "N/A")

    winner = "Cluster-based payout" if total_saving > total_burning else "P-Mapping"
    net = abs(total_saving - total_burning)

    return f"""## Auto-Analysis (Rule-Based)

**Executive Summary:** Based on the financial data, {winner} results in lower overall costs.
The net benefit is ₹{net:,.0f}. Total savings: ₹{total_saving:,.0f}, Total burn: ₹{total_burning:,.0f}.

**Best Hub:** {best} (highest P&L)
**Worst Hub:** {worst} (lowest P&L)

**Recommendation:** Use **{winner}** — it saves ₹{net:,.0f} compared to the alternative.

*For detailed AI analysis, enter your free Groq API key (console.groq.com).*"""
