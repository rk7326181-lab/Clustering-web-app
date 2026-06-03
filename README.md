# Shadowfax Geo Intelligence Portal

> A geospatial clustering and payout optimization tool for last-mile delivery operations — built with Streamlit, Folium, Shapely, and BigQuery.

[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://python.org)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.30+-FF4B4B?logo=streamlit&logoColor=white)](https://streamlit.io)
[![Folium](https://img.shields.io/badge/Folium-0.15+-77B829)](https://python-visualization.github.io/folium/)
[![BigQuery](https://img.shields.io/badge/BigQuery-Google_Cloud-4285F4?logo=google-cloud&logoColor=white)](https://cloud.google.com/bigquery)
[![Groq](https://img.shields.io/badge/AI-Groq_LLaMA_3-F55036)](https://groq.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## What This App Does

The **Geo Intelligence Portal** helps logistics and operations teams:

- **Cluster delivery pincodes** around hubs using distance-based concentric ring polygons
- **Calculate payout tiers** (₹0 to ₹8+) based on road or straight-line distance from hub to pincode centroid
- **Compare payout models** — P-Mapping (haversine / OSRM) vs. polygon-based cluster payout
- **Visualize interactively** — Folium maps with OSRM route distance tool, polygon editor, heatmaps
- **Analyze financials** — per-hub P&L: savings vs. burn across all pincodes
- **Export** to CSV, XLSX, KML (Google Earth), and PNG hub images
- **Query with AI** — Groq-powered LLaMA 3 agent for natural language cost analysis

---

## Application Flow (7 Steps)

```
Step 1 › Data Ingestion
        Upload Cluster CSV + Pincodes CSV + GeoJSON boundaries
        (or auto-load from BigQuery / previously saved outputs)

Step 2 › P-Mapping
        Haversine or OSRM road distance — hub centroid → pincode centroid
        Assigns payout slab: ₹0 (0–5 km) ➜ ₹8 (40–45 km) ➜ Nil (45+ km)
        Manual P-category override per pincode supported

Step 3 › Polygon Generation + Editor
        Generates concentric ring polygons clipped to pincode GeoJSON boundaries
        Interactive Leaflet editor — drag vertices, add/delete polygons
        Export as CSV / XLSX / KML

Step 4 › AWB Analysis
        Fetches shipment data from BigQuery (60-day window) or manual CSV upload
        Point-in-polygon cluster assignment via Shapely STRtree spatial index
        Calculates P&L: P-Mapping payout vs. Cluster payout per AWB

Step 5 › Live Clusters
        Pulls production cluster config from BigQuery
        Side-by-side: test clusters vs. live clusters

Step 6 › Financial Intelligence
        Pivot: Hub × Pincode → Saving / Burning / P&L %
        AI burn analysis: top 5 high-cost pincodes + fix recommendations

Step 7 › AI Agent
        Natural language chat — "Why is hub X burning?"
        Groq LLaMA 3 with full app + domain context
```

---

## Tech Stack

| Component | Library / Service | Cost |
|---|---|---|
| Web framework | Streamlit ≥ 1.30 | Free |
| Interactive maps | Folium 0.15 + streamlit-folium 0.22 | Free |
| Geometry engine | Shapely ≥ 2.0, GeoPandas ≥ 0.14 | Free |
| Road routing | OSRM public API (project-osrm.org) | Free |
| Basemap tiles | OpenStreetMap + ESRI via contextily | Free |
| AI / LLM | Groq API — LLaMA 3.1 8B / 70B | Free tier |
| Data warehouse | Google BigQuery | Free tier (1 TB/month queries) |
| Local DB cache | DuckDB ≥ 0.9 | Free |
| KML export | simplekml | Free |
| Auth | Google OAuth 2.0 / Service Account | Free |

---

## Project Structure

```
Clustering-web-app/
├── app.py                          # Main Streamlit app — 7-step pipeline
├── requirements.txt                # Python dependencies
├── packages.txt                    # System libs: libgdal, libgeos, libproj
│
├── modules/
│   ├── polygon_generator.py        # Concentric ring polygons + KML export
│   ├── visualizer.py               # Folium maps (polygon, OSRM, editable)
│   ├── map_renderer.py             # MapRenderer class (cluster map builder)
│   ├── ai_agent.py                 # Groq LLaMA 3 chat + financial analysis
│   ├── cost_analyzer.py            # Hub cost metrics, savings/burn, recommendations
│   ├── dashboard_builder.py        # Pivot table + financial report builder
│   ├── data_loader.py              # CSV / BigQuery / Kepler.gl format loading
│   ├── live_cluster_utils.py       # Live cluster fetch + comparison logic
│   ├── cluster_assignor.py         # Point-in-polygon AWB assignment (STRtree)
│   ├── bigquery_client.py          # BigQuery client + OAuth flow
│   └── duckdb_store.py             # Local DuckDB session cache
│
├── utils/
│   └── __init__.py                 # Constants, geometry helpers, payout slabs
│
├── data/                           # Reference data (auto-loaded on startup)
│   ├── Clustering_Automation.csv   # Hub-pincode input
│   ├── Pincodes_1.csv              # Pincode volumetric centroids
│   ├── final_output.csv            # Pre-computed P-Mapping distances
│   └── Awb_with_cluster_info.csv   # AWB cluster assignment results
│
├── outputs/                        # Generated on first run (auto-created)
│   ├── Clustering_payout_polygon_*.csv / .xlsx / .kml
│   ├── Awb_with_polygon_mapping.csv
│   ├── live_clusters_cache.json
│   └── Hub_Payout_Views_Final_All_Hubs/   # PNG map per hub
│
├── .streamlit/
│   └── config.toml                 # Theme: #0B8A7A, upload limit: 500 MB
└── .devcontainer/
    └── devcontainer.json           # GitHub Codespaces / VS Code Dev Container
```

---

## Input Data Format

### Clustering CSV
```
Pincode  | Hub_Name       | Hub_lat  | Hub_long
---------|----------------|----------|----------
110001   | Delhi_Central  | 28.6315  | 77.2167
400001   | Mumbai_CST     | 18.9402  | 72.8356
```

### Pincodes Reference CSV
```
Pincode | Volumetric Lat | Volumetric Long   ← column names auto-detected
--------|----------------|----------------
110001  | 28.630         | 77.218
```

### GeoJSON Boundaries
- One feature per pincode with `Polygon` or `MultiPolygon` geometry
- Pincode field in properties: `pincode`, `Pincode`, `PINCODE`, or `pin` (auto-detected)

---

## Payout Slabs

| Distance from Hub | Payout Rate | Cluster Category |
|---|---|---|
| 0 – 5 km | ₹0 | C1 |
| 5 – 10 km | ₹1 | C3 |
| 10 – 15 km | ₹2 | C5 |
| 15 – 20 km | ₹3 | C7 |
| 20 – 25 km | ₹4 | C9 |
| 25 – 30 km | ₹5 | C11 |
| 30 – 35 km | ₹6 | C12 |
| 35 – 40 km | ₹7 | C13 |
| 40 – 45 km | ₹8 | C14 |
| 45+ km | Nil | — |

---

## Local Setup

### Prerequisites
- Python 3.11+
- Linux / WSL / macOS (for system geo libraries)

### 1 — Clone
```bash
git clone https://github.com/rk7326181-lab/Clustering-web-app.git
cd Clustering-web-app
```

### 2 — System dependencies (Linux / WSL / macOS)
```bash
sudo apt update && sudo apt install -y \
    libgdal-dev libgeos-dev libproj-dev proj-data proj-bin gdal-bin
```

### 3 — Python dependencies
```bash
pip install -r requirements.txt
```

### 4 — Credentials (optional — app works offline without BigQuery)
Create `.streamlit/secrets.toml`:
```toml
# Access control
allowed_emails = ["your.email@company.com"]
app_password   = "your_password"

# Groq AI — free at groq.com
GROQ_API_KEY = "gsk_..."

# BigQuery service account (optional)
[gcp_service_account]
type             = "service_account"
project_id       = "your-project-id"
private_key_id   = "..."
private_key      = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email     = "..."
client_id        = "..."
```

### 5 — Run
```bash
streamlit run app.py
```
Open `http://localhost:8501`

---

## Deploy Free on Streamlit Cloud

1. Fork this repo on GitHub
2. Go to [share.streamlit.io](https://share.streamlit.io) → **New app** → select your fork
3. Set **Main file path**: `app.py`
4. Paste your `secrets.toml` content into **Advanced → Secrets**
5. Click **Deploy** — live in ~3 minutes, free forever on Community tier

---

## Launch in GitHub Codespaces (Zero Local Setup)

Click **Code** → **Codespaces** → **Create codespace on main**.

The dev container automatically:
- Installs all system + Python dependencies
- Starts the Streamlit server on port 8501
- Opens a browser preview

---

## Using Without BigQuery (Fully Offline)

The app works end-to-end without any cloud connection:

| Step | Offline Method |
|---|---|
| Step 1 | Upload CSVs + GeoJSON manually |
| Step 2 | P-Mapping runs locally (haversine, no API) |
| Step 3 | Polygon generation runs in Python (Shapely) |
| Step 4 | Upload an AWB CSV instead of BigQuery fetch |
| Steps 5–7 | Use pre-loaded data from Steps 1–4 |

All results are cached in a local DuckDB file and auto-reloaded on next session startup.

---

## Map Features

| Feature | Description |
|---|---|
| OSRM Route Distance Tool | Click any two points → get real road distance in km |
| Polygon Editor | Drag vertices, add/delete zones, save back to data |
| Heatmap / Dot overlay | AWB delivery density over cluster zones |
| Fullscreen | Available on every map |
| Measure control | Distance + area measurement on every map |
| Layer switcher | Street / Satellite / Terrain basemaps |
| Pincode color legend | Distinct color per pincode within each hub |

---

## Export Formats

| Format | Contents |
|---|---|
| **CSV** | Polygon records: WKT geometry, cluster codes, payout tiers |
| **XLSX** | Spreadsheet version with same data |
| **KML** | Google Earth: hub markers + styled ring polygons |
| **PNG** | Static hub map image — per hub, OSM basemap (matplotlib + contextily) |

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GROQ_API_KEY` | No | Groq key for AI features — free at [groq.com](https://groq.com) |
| `APP_PASSWORD` | No | Password gate for the app |
| `GOOGLE_APPLICATION_CREDENTIALS` | No | Path to service account JSON for BigQuery |

---

## Known Limitations

- BigQuery table names (`bi-team-400508.*`) are hardcoded — update in `modules/bigquery_client.py` for your project
- OSRM uses the public `router.project-osrm.org` API — rate-limited; self-host for production workloads
- Hub image generation (`Generate Hub Images`) runs sequentially — slow for 50+ hubs
- Groq free tier has request-per-minute limits — AI agent may queue under heavy use

---

## Roadmap

- [ ] Demo mode — bundled sample data, zero uploads needed
- [ ] DuckDB-only mode — full offline operation without BigQuery
- [ ] H3 hexagon density overlay (Uber H3)
- [ ] Demand-weighted tier suggestions (flag pincodes where order volume mismatches tier)
- [ ] Cluster versioning with diff view between configurations
- [ ] PyDeck GPU-rendered map for 10,000+ polygon datasets
- [ ] LangChain tool-calling agent with write capabilities
- [ ] Bulk P-category override for 100+ pincodes at once
- [ ] Voronoi hub catchment zone view

---

## Contributing

1. Fork the repo
2. Create a branch: `git checkout -b feature/your-feature`
3. Commit: `git commit -m "Add your feature"`
4. Push: `git push origin feature/your-feature`
5. Open a Pull Request

---

## Built With

[Streamlit](https://streamlit.io) · [Folium](https://python-visualization.github.io/folium/) · [Shapely](https://shapely.readthedocs.io) · [GeoPandas](https://geopandas.org) · [DuckDB](https://duckdb.org) · [Groq](https://groq.com) · [OSRM](http://project-osrm.org) · [contextily](https://contextily.readthedocs.io) · [simplekml](https://simplekml.readthedocs.io) · [Google BigQuery](https://cloud.google.com/bigquery)
