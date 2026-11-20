"""
Shadowfax UI kit for the Geo Intelligence Portal (Streamlit).

Ports shadowfax-ui-kit/shadowfax-ui.css (the Rider Tagging Bot look, built on
shadowfax.in's own tokens) onto Streamlit's DOM. Colours, font and radii for
Streamlit's own widgets come from .streamlit/config.toml [theme]; this file
styles the custom pieces (header, hero, cards, footer) and the widgets the
theme cannot reach.

Rules from SHADOWFAX_FRONTEND_GUIDE.md that shape this file:
  * logo straight on a white header, portal name beside it after a thin divider
  * plain-text tabs with a 4px teal underline; the tab row never wraps
  * lime primary buttons, white/teal secondary buttons
  * settings and credentials sit behind the status button, never on a tab
  * Montserrat from the local woff2 (static/), no web fonts at runtime
  * never scroll sideways, down to 320px phones

Static files are served by Streamlit from ./static at app/static/... (needs
[server] enableStaticServing = true in .streamlit/config.toml).
"""
import html as _html

import streamlit as st

LOGO_URL = "app/static/shadowfax_logo.svg"
PORTAL_NAME = "Geo Intelligence Portal"

_CSS = """
<style>
@font-face { font-family:"Montserrat"; font-weight:500 800; font-style:normal; font-display:swap;
  src:url(app/static/fonts/montserrat-latin.woff2) format("woff2"); }
:root {
  --teal:#008a71; --teal-d:#006b58; --teal-dd:#00473b; --mint:#e8efec; --mint-2:#dff3ec; --mint-3:#f3f9f7;
  --lime:#f1ee1b; --lime-d:#d5d226; --butter:#fffdb1; --butter-2:#fffde0;
  --head:#332f22; --ink:#545454; --muted:#7a817e; --line:#e2e5ea; --line-2:#d7d7d7; --bg:#f6f8f7; --card:#fff;
  --ok:#1e7a46; --ok-bg:#e1f4e8; --bad:#b3261e; --bad-bg:#fdebe8; --warn:#8a5a00; --warn-bg:#fff4d6;
  --radius:14px; --shadow:0 1px 2px rgba(51,47,34,.04),0 6px 20px rgba(51,47,34,.06);
  --hdr:76px; --gutter:36px; --hpad:36px;
}
html, body, .stApp, .stApp button, .stApp input, .stApp textarea, .stApp select {
  font-family:"Montserrat","Segoe UI",system-ui,Arial,sans-serif; }
.stApp { background:var(--bg); color:var(--ink); -webkit-font-smoothing:antialiased; }
:focus-visible { outline:3px solid rgba(0,138,113,.45); outline-offset:2px; }

/* ── Streamlit chrome: our own white header replaces it ── */
header[data-testid="stHeader"] { display:none; }
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="stExpandSidebarButton"] { display:none; }
[data-testid="stMainBlockContainer"], .main .block-container {
  max-width:1360px; padding:0 var(--gutter) 0 !important; }
/* stMain is the query container so 100cqw = the visible page width (scrollbar excluded):
   header and footer use it to span the window without ever causing sideways scroll. */
[data-testid="stMain"] { overflow-x:hidden; container-type:inline-size; }
[data-testid="stMarkdownContainer"] p, [data-testid="stCaptionContainer"] { color:var(--ink); }
[data-testid="stMarkdownContainer"] h1, [data-testid="stMarkdownContainer"] h2,
[data-testid="stMarkdownContainer"] h3, [data-testid="stMarkdownContainer"] h4 { color:var(--head); }
[data-testid="stMarkdownContainer"] h4 { font-weight:700; font-size:16px; }
[data-testid="stMarkdownContainer"] a { color:var(--teal); }
hr { border-color:var(--line) !important; }

/* ── Header: logo on white, portal name, plain-text tabs, lime status button ──
   st.container(key="sfx_top") renders as .st-key-sfx_top inside a stLayoutWrapper; the
   wrapper is what must be sticky (sticky only works against the element's parent). */
[data-testid="stLayoutWrapper"]:has(> .st-key-sfx_top) {
  position:sticky; top:0; z-index:999; height:var(--hdr) !important; background:#fff;
  width:100cqw !important; max-width:none; margin-left:calc((100% - 100cqw) / 2); padding:0 var(--hpad);
  border-bottom:1px solid var(--line); box-shadow:0 2px 14px rgba(51,47,34,.05); }
.st-key-sfx_top { height:100% !important; justify-content:center; gap:0 !important; }
.st-key-sfx_top > [data-testid="stLayoutWrapper"] { height:100%; }
.st-key-sfx_top [data-testid="stHorizontalBlock"] {
  flex-wrap:nowrap !important; align-items:center; gap:30px; height:100%; }
.st-key-sfx_top [data-testid="stColumn"] { width:auto !important; min-width:0; flex:none !important; }
.st-key-sfx_top [data-testid="stColumn"]:nth-child(2) { flex:1 1 0 !important; align-self:stretch; display:flex; }
.st-key-sfx_top [data-testid="stColumn"] [data-testid="stVerticalBlock"] { gap:0; }
.st-key-sfx_top [data-testid="stColumn"]:nth-child(2) > [data-testid="stVerticalBlock"],
.st-key-sfx_top [data-testid="stColumn"]:nth-child(2) [data-testid="stElementContainer"],
.st-key-sfx_top .stRadio, .st-key-sfx_top [data-testid="stRadioGroup"] { height:100%; width:100% !important; min-width:0; }
.st-key-sfx_top [data-testid="stColumn"]:nth-child(2) > [data-testid="stVerticalBlock"] { flex:1 1 auto; }
.sfx-brand { display:flex; align-items:center; gap:16px; flex:none; }
.sfx-brand img { height:50px; width:auto; display:block; }
.sfx-brand .t { border-left:1px solid var(--line-2); padding-left:16px; font-size:15px; font-weight:700; color:var(--head);
  letter-spacing:.1px; white-space:nowrap; line-height:1.6; }

/* tab row = the step navigation radio, restyled as plain text tabs; never wraps, scrolls sideways */
.st-key-sfx_top .stRadio [data-testid="stWidgetLabel"] { display:none; }
.st-key-sfx_top [data-testid="stRadioGroup"] { display:flex; flex-wrap:nowrap !important; gap:2px; align-items:stretch;
  overflow-x:auto; overflow-y:hidden; scrollbar-width:none; }
.st-key-sfx_top [data-testid="stRadioGroup"]::-webkit-scrollbar { display:none; }
.st-key-sfx_top [data-testid="stRadioGroup"] > div { flex:none; display:flex; margin:0; }
.st-key-sfx_top [data-testid="stRadioOption"] { position:relative; margin:0 !important; padding:0 10px; height:100%; display:flex;
  align-items:center; cursor:pointer; white-space:nowrap; background:transparent; }
.st-key-sfx_top [data-testid="stRadioOption"] > div { padding:0; gap:0; }
.st-key-sfx_top [data-testid="stRadioOption"] > div > div:first-child:not([data-testid]) { display:none; }  /* radio circle */
.st-key-sfx_top [data-testid="stRadioOption"] p { font-size:14px; font-weight:600; color:var(--head); margin:0; white-space:nowrap; }
.st-key-sfx_top [data-testid="stRadioOption"]:hover p,
.st-key-sfx_top [data-testid="stRadioOption"][data-selected="true"] p { color:var(--teal); }
.st-key-sfx_top [data-testid="stRadioOption"][data-selected="true"]::after { content:""; position:absolute; left:12px; right:12px;
  bottom:0; height:4px; background:var(--teal); border-radius:4px 4px 0 0; }

/* status button (popover trigger) with a coloured dot */
.st-key-sfx_top [data-testid="stPopoverButton"] { background:var(--lime) !important; color:var(--head) !important; border:0 !important;
  border-radius:9px; padding:9px 16px 9px 18px; font-weight:700; font-size:13px; box-shadow:none; min-height:0; white-space:nowrap; }
.st-key-sfx_top [data-testid="stPopoverButton"]:hover { background:var(--lime-d) !important; }
.st-key-sfx_top [data-testid="stPopoverButton"] p { font-weight:700; font-size:13px; color:var(--head); white-space:nowrap;
  overflow:hidden; text-overflow:ellipsis; max-width:240px; }
.st-key-sfx_top [data-testid="stPopoverButton"]::before { content:""; width:10px; height:10px; border-radius:50%; flex:none;
  margin-right:9px; background:#8a8f80; }
.st-key-sfx_conn_ok [data-testid="stPopoverButton"]::before { background:#0aa75f; box-shadow:0 0 0 3px rgba(10,167,95,.22); }
.st-key-sfx_conn_warn [data-testid="stPopoverButton"]::before { background:#f08a00; box-shadow:0 0 0 3px rgba(240,138,0,.25); }
.st-key-sfx_conn_bad [data-testid="stPopoverButton"]::before { background:#e5473b; box-shadow:0 0 0 3px rgba(229,71,59,.22); }
[data-testid="stToastContainer"] { top:calc(var(--hdr) + 10px) !important; }

/* the Connections panel (drawer) */
[data-testid="stPopoverBody"]:has(.sfx-dh) { width:min(500px, calc(100vw - 24px)) !important; max-width:none;
  max-height:calc(100vh - 100px); overflow-y:auto; padding:0 !important; border-radius:var(--radius); }
[data-testid="stPopoverBody"]:has(.sfx-dh) [data-testid="stVerticalBlock"] { gap:12px; }
.sfx-dh { background:linear-gradient(135deg,var(--teal),var(--teal-dd)); color:#fff; padding:18px 22px;
  border-bottom:5px solid var(--lime); border-radius:var(--radius) var(--radius) 0 0; }
.sfx-dh b { display:block; font-size:20px; font-weight:800; color:#fff; letter-spacing:-.2px; }
.sfx-dh span { font-size:12.5px; color:rgba(255,255,255,.85); }
[data-testid="stPopoverBody"]:has(.sfx-dh) > [data-testid="stVerticalBlock"] > :not(:first-child) { padding:0 22px; }
[data-testid="stPopoverBody"]:has(.sfx-dh) > [data-testid="stVerticalBlock"] > :last-child { padding-bottom:22px; }
.sfx-dsec { font-size:13px; font-weight:700; color:var(--head); margin:6px 0 0; padding-top:12px; border-top:1px solid var(--line); }
.sfx-dsec.first { border-top:0; padding-top:4px; }
.sfx-badge { display:inline-flex; align-items:center; gap:8px; padding:4px 12px; border-radius:12px; font-size:12px; font-weight:700; }
.sfx-badge .dot { width:8px; height:8px; border-radius:50%; display:inline-block; }
.sfx-badge--ok { background:var(--ok-bg); color:var(--ok); } .sfx-badge--ok .dot { background:#0aa75f; }
.sfx-badge--warn { background:var(--warn-bg); color:var(--warn); } .sfx-badge--warn .dot { background:#f08a00; }
.sfx-label { font-size:11px; color:var(--teal); font-weight:700; letter-spacing:1.4px; text-transform:uppercase; margin:6px 0 2px; }
.sfx-checks { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:4px 16px; }
.sfx-status { display:flex; align-items:center; gap:8px; font-size:13px; }
.sfx-status .icon { width:18px; height:18px; border-radius:50%; display:grid; place-items:center; font-size:11px; font-weight:800; flex:none; }
.sfx-status--done .icon { background:var(--teal); color:#fff; } .sfx-status--done .lbl { color:var(--head); font-weight:600; }
.sfx-status--pending .icon { border:1.5px solid var(--line-2); color:transparent; } .sfx-status--pending .lbl { color:var(--muted); }
.sfx-chat-user { background:var(--teal); color:#fff; padding:6px 10px; border-radius:9px; margin:4px 0; font-size:12px; text-align:right; }
.sfx-chat-bot { background:var(--mint-3); color:var(--head); padding:6px 10px; border-radius:9px; margin:4px 0; font-size:12px; border:1px solid var(--line); }

/* ── Hero: mint → butter wash, title, 4 live stats ── */
.sfx-hero { display:grid; grid-template-columns:minmax(260px,1.05fr) 1.6fr; gap:28px; align-items:center; border-radius:18px;
  padding:34px 38px; margin:18px 0 8px; background:linear-gradient(120deg,var(--mint-2) 0%,#f1f8e8 55%,var(--butter-2) 100%);
  border:1px solid #e3ece6; position:relative; overflow:hidden; }
.sfx-hero::after { content:""; position:absolute; right:-70px; top:-60px; width:260px; height:260px; background:var(--butter); opacity:.55;
  clip-path:polygon(8% 0,100% 28%,70% 100%,38% 52%); transform:rotate(8deg); pointer-events:none; }
.sfx-hero > * { position:relative; z-index:1; min-width:0; }
.sfx-hero h1 { margin:2px 0 8px; padding:0; font-size:34px; line-height:1.15; font-weight:800; color:var(--head); letter-spacing:-.5px; }
.sfx-hero h1 em { font-style:normal; color:var(--teal); }
.sfx-hero p { margin:0; color:var(--ink); font-size:14px; line-height:1.6; max-width:52ch; }
.sfx-eyebrow { font-size:11px; font-weight:700; letter-spacing:1.8px; text-transform:uppercase; color:var(--teal); margin-bottom:2px; }
.sfx-stats { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; }
.sfx-stat { background:rgba(255,255,255,.82); border:1px solid rgba(255,255,255,.9); border-radius:14px; padding:16px 12px 14px;
  text-align:center; box-shadow:0 2px 10px rgba(0,71,59,.06); min-width:0; }
.sfx-stat svg { width:28px; height:28px; stroke:var(--teal); fill:none; stroke-width:1.7; stroke-linecap:round; stroke-linejoin:round; margin-bottom:4px; }
.sfx-stat b { display:block; font-size:24px; font-weight:800; color:var(--head); line-height:1.15; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.sfx-stat span { display:block; font-size:10.5px; font-weight:600; letter-spacing:.7px; text-transform:uppercase; color:var(--muted); margin-top:2px; }

/* ── Section titles: 22-28px / 800 with the lime bar ── */
.sfx-header { margin:22px 0 10px; font-size:24px; font-weight:800; letter-spacing:-.4px; color:var(--head); line-height:1.2;
  position:relative; padding-bottom:12px; }
.sfx-header::after { content:""; position:absolute; left:0; bottom:0; width:46px; height:4px; border-radius:3px; background:var(--lime); }
.sfx-section-header { font-size:16px; font-weight:700; color:var(--head); margin:16px 0 8px; padding-bottom:6px; border-bottom:1px solid var(--line); }
.sfx-card { background:var(--card); border:1px solid var(--line); border-radius:var(--radius); padding:20px; margin:8px 0;
  box-shadow:var(--shadow); color:var(--head); }
.sfx-card:empty { display:none; }
.sfx-card .ttl { font-weight:700; color:var(--teal-d); margin-bottom:8px; }

/* plain-English status lines */
.sfx-ok, .sfx-warn, .sfx-err { padding:10px 16px; border-radius:10px; margin:6px 0; font-size:13.5px; color:var(--head); border:1px solid transparent; }
.sfx-ok { background:var(--ok-bg); border-color:#c6e8d3; }
.sfx-warn { background:var(--warn-bg); border-color:#f3e0a8; }
.sfx-err { background:var(--bad-bg); border-color:#f6cdc7; }
.sfx-ok b, .sfx-ok strong { color:var(--ok); } .sfx-err b, .sfx-err strong { color:var(--bad); }
.sfx-warn ul, .sfx-err ul { margin:6px 0; }

/* ── Pill chips (data freshness etc.) ── */
.sfx-chips { display:flex; gap:8px; flex-wrap:wrap; }
.sfx-chip { padding:6px 14px; border-radius:20px; border:1.5px solid var(--line-2); background:#fff; font-size:12.5px;
  font-weight:600; color:var(--head); white-space:nowrap; }

/* ── KPI tiles: alternating mint / butter ── */
.kpi-row { display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:16px; margin:12px 0 24px; }
.kpi-card { border-radius:var(--radius); padding:18px 20px 16px; background:var(--mint-2); border:1.5px solid transparent; min-width:0; }
.kpi-card:nth-child(even) { background:var(--butter); }
.kpi-card .kpi-value { font-size:clamp(20px, 1.4vw + 14px, 30px); font-weight:800; color:var(--teal-d); letter-spacing:-.8px; line-height:1.15;
  overflow-wrap:anywhere; }
.kpi-card:nth-child(even) .kpi-value { color:var(--head); }
.kpi-card .kpi-label { color:var(--ink); font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:.9px; margin-top:3px; }
.kpi-card { display:flex; flex-direction:column-reverse; justify-content:flex-end; }
.kpi-card.red .kpi-value, .kpi-card.red:nth-child(even) .kpi-value { color:var(--bad); }

/* ── Streamlit widgets the theme cannot reach ── */
.stButton > button, .stDownloadButton > button, .stLinkButton > a, .stFormSubmitButton > button {
  font-weight:700; border-radius:9px; transition:background .15s,box-shadow .15s,transform .05s; }
button[data-testid="stBaseButton-secondary"], button[data-testid="stBaseButton-secondaryFormSubmit"],
.stDownloadButton > button, a[data-testid="stBaseLinkButton-secondary"] {
  background:#fff; border:1.5px solid var(--teal); color:var(--teal); }
button[data-testid="stBaseButton-secondary"]:hover, button[data-testid="stBaseButton-secondaryFormSubmit"]:hover,
.stDownloadButton > button:hover, a[data-testid="stBaseLinkButton-secondary"]:hover {
  background:var(--mint-3); border-color:var(--teal); color:var(--teal); }
button[data-testid="stBaseButton-primary"], button[data-testid="stBaseButton-primaryFormSubmit"],
a[data-testid="stBaseLinkButton-primary"] {
  background:var(--lime) !important; border:1.5px solid var(--lime) !important; color:var(--head) !important; }
button[data-testid="stBaseButton-primary"]:hover, button[data-testid="stBaseButton-primaryFormSubmit"]:hover,
a[data-testid="stBaseLinkButton-primary"]:hover { background:var(--lime-d) !important; border-color:var(--lime-d) !important; }
button[data-testid="stBaseButton-primary"] p, button[data-testid="stBaseButton-primaryFormSubmit"] p,
a[data-testid="stBaseLinkButton-primary"] p { color:var(--head) !important; font-weight:700; }
button[data-testid="stBaseButton-secondary"] p, .stDownloadButton > button p { font-weight:700; }
button:active:not(:disabled) { transform:translateY(1px); }

/* in-page tabs: plain text, teal text + 4px teal underline when on */
.stTabs [data-baseweb="tab-list"] { gap:2px; border-bottom:1px solid var(--line); }
.stTabs [data-baseweb="tab-list"] { margin-bottom:6px; }
.stTabs [data-baseweb="tab"] { padding:12px 18px; height:auto; background:transparent; }
.stTabs [data-baseweb="tab"] p, .stTabs [data-baseweb="tab"] [data-testid="stMarkdownContainer"] p {
  font-weight:600; font-size:14.5px; color:var(--head); }
.stTabs [data-baseweb="tab"]:hover p, .stTabs [aria-selected="true"] p,
.stTabs [aria-selected="true"] [data-testid="stMarkdownContainer"] p { color:var(--teal); }
.stTabs [data-baseweb="tab-highlight"] { background:var(--teal); height:4px; border-radius:4px 4px 0 0; }
.stTabs [data-baseweb="tab-border"] { display:none; }

/* cards for grouped content */
[data-testid="stExpander"] details { background:#fff; border:1px solid var(--line); border-radius:var(--radius); }
[data-testid="stExpander"] summary p { font-weight:700; color:var(--teal-d); }
[data-testid="stForm"] { background:#fff; border:1px solid var(--line); border-radius:var(--radius); box-shadow:var(--shadow); }
[data-testid="stFileUploaderDropzone"] { background:var(--mint-3); border:1.5px dashed var(--line-2); border-radius:12px; }
[data-testid="stFileUploaderDropzone"]:hover { border-color:var(--teal); }
[data-testid="stDataFrame"], [data-testid="stTable"] { border-radius:var(--radius); }
[data-testid="stMetricValue"] { font-weight:800; color:var(--head); }
[data-testid="stMetricLabel"] p { font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:.8px; color:var(--muted); }
.stMultiSelect [data-baseweb="tag"] { background:var(--mint-2); color:var(--teal-d); }
.stMultiSelect [data-baseweb="tag"] span { color:var(--teal-d); }
[data-testid="stAlert"] { border-radius:10px; }
.stProgress > div > div > div > div { background:linear-gradient(90deg,var(--teal),#7fcf4a); }
iframe { border-radius:12px; }

/* HTML report tables (dashboard_builder.style_report_html) */
.sfx-table-wrap { overflow:auto; max-height:66vh; border:1px solid var(--line); border-radius:var(--radius); background:#fff; }
.sfx-table { border-collapse:collapse; font-size:13px; min-width:100%; }
.sfx-table th { background:var(--mint); color:var(--teal-d); position:sticky; top:0; z-index:1; font-size:11px; font-weight:700;
  text-transform:uppercase; letter-spacing:.8px; padding:12px 14px; text-align:center; white-space:nowrap; }
.sfx-table td { color:var(--head); padding:9px 12px; border-bottom:1px solid #eef1f0; text-align:center; white-space:nowrap; }
.sfx-table tbody tr:hover td { background:var(--mint-3); }
.sfx-table tr.ht td { background:var(--mint-2); font-weight:700; }
.sfx-table tr.gt td { background:var(--butter); font-weight:800; }
.sfx-table td.pos { color:var(--ok); } .sfx-table td.neg { color:var(--bad); }

/* chat bubbles (AI pages) */
.chat-user { background:var(--teal); color:#fff; padding:10px 16px; border-radius:12px 12px 4px 12px; margin:6px 0 6px auto;
  text-align:right; font-size:14px; max-width:80%; width:fit-content; }
.chat-assistant { background:#fff; border:1px solid var(--line); color:var(--head); padding:10px 16px; border-radius:12px 12px 12px 4px;
  margin:6px 0; font-size:14px; max-width:85%; line-height:1.6; box-shadow:var(--shadow); }

/* activity log */
.log-entry { display:flex; align-items:flex-start; gap:8px; padding:6px 10px; font-size:12.5px; border-bottom:1px solid #eef1f0; color:var(--head); }
.log-dot { width:8px; height:8px; border-radius:50%; margin-top:6px; flex-shrink:0; }
.log-time { color:var(--muted); font-size:11px; flex-shrink:0; font-variant-numeric:tabular-nums; }

/* ── Footer, in the website's green ── */
.sfx-foot { margin-top:40px; color:#fff; padding:26px var(--hpad); position:relative;
  width:100cqw; margin-left:calc((100% - 100cqw) / 2);
  background:linear-gradient(135deg,#00a07f 0%,var(--teal) 45%,var(--teal-dd) 100%); }
.sfx-foot .in { max-width:1288px; margin:0 auto; display:flex; justify-content:space-between; align-items:center; gap:16px; flex-wrap:wrap; font-size:13px; }
.sfx-foot b { font-weight:800; font-size:15px; } .sfx-foot em { color:var(--lime); font-weight:600; font-style:normal; }
.sfx-foot .c { opacity:.85; font-size:12px; }
[data-testid="stMainBlockContainer"] { padding-bottom:0 !important; min-height:100vh; display:flex; flex-direction:column; }
[data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] { flex:1 0 auto; }
/* short pages: push the footer to the bottom of the window */
[data-testid="stElementContainer"]:has(.sfx-foot) { margin-top:auto; }

/* ── Login ── */
.sfx-login { max-width:440px; margin:9vh auto 0; text-align:center; }
.sfx-login img { height:50px; width:auto; }
.sfx-login h1 { font-size:26px; font-weight:800; color:var(--head); margin:18px 0 4px; padding:0; letter-spacing:-.4px; }
.sfx-login h1 em { font-style:normal; color:var(--teal); }
.sfx-login p { color:var(--muted); font-size:13.5px; margin:0 0 18px; }
.st-key-sfx_login { max-width:440px; margin:0 auto; }

/* ── Responsive (same breakpoints as the kit) ── */
@media (max-width:1320px) {
  :root { --gutter:22px; --hpad:22px; }
  .st-key-sfx_top [data-testid="stHorizontalBlock"] { gap:18px; }
  .st-key-sfx_top [data-testid="stRadioOption"] { padding:0 11px; } .st-key-sfx_top [data-testid="stRadioOption"] p { font-size:13.5px; }
  .st-key-sfx_top [data-testid="stRadioOption"][data-selected="true"]::after { left:8px; right:8px; }
  .st-key-sfx_top [data-testid="stPopoverButton"] p { max-width:180px; }
}
/* 9 tabs: the portal name gives way below 1560px so every tab stays visible */
@media (max-width:1560px) {
  .sfx-brand .t { display:none; }
}
@media (max-width:1140px) {
  .st-key-sfx_top [data-testid="stPopoverButton"] { padding:9px 14px; }
  .st-key-sfx_top [data-testid="stPopoverButton"] p { max-width:140px; }
  .sfx-hero { grid-template-columns:1fr; padding:28px 26px; }
}
/* Two-row header (logo + status, then a full-width tab row) from 1220px down:
   9 tabs don't fit beside the logo on small laptops and tablets. */
@media (max-width:1220px) {
  :root { --hdr:112px; }
  .st-key-sfx_top [data-testid="stHorizontalBlock"] { flex-wrap:wrap !important; gap:0 12px; align-content:stretch; }
  .st-key-sfx_top [data-testid="stColumn"]:nth-child(1) { flex:1 1 auto !important; height:64px; display:flex; align-items:center; }
  .st-key-sfx_top [data-testid="stColumn"]:nth-child(2) { order:3; flex:1 1 100% !important; width:100% !important; height:47px;
    border-top:1px solid var(--line); }
  .st-key-sfx_top [data-testid="stColumn"]:nth-child(3) { order:2; height:64px; display:flex; align-items:center; }
  .st-key-sfx_top [data-testid="stColumn"]:nth-child(odd) > [data-testid="stVerticalBlock"] { justify-content:center; height:100%; }
  .st-key-sfx_top [class*="st-key-sfx_conn_"] { justify-content:center; align-items:flex-end; }
}
@media (max-width:900px) {
  :root { --gutter:12px; --hpad:14px; }
  .sfx-brand img { height:40px; }
  .st-key-sfx_top [data-testid="stRadioOption"] { padding:0 12px; } .st-key-sfx_top [data-testid="stRadioOption"] p { font-size:13px; }
  .st-key-sfx_top [data-testid="stRadioOption"][data-selected="true"]::after { left:8px; right:8px; }
  .st-key-sfx_top [data-testid="stPopoverButton"] { padding:8px 13px; }
  .st-key-sfx_top [data-testid="stPopoverButton"] p { font-size:12px; max-width:170px; }
  .sfx-hero { padding:22px 18px; } .sfx-hero h1 { font-size:27px; } .sfx-stats { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .sfx-header { font-size:21px; }
  .sfx-foot { padding:20px 0; }
}
@media (max-width:480px) {
  .st-key-sfx_top [data-testid="stPopoverButton"] p { max-width:110px; }
  .sfx-hero h1 { font-size:24px; } .sfx-stats { gap:10px; } .sfx-stat b { font-size:20px; }
  .sfx-checks { grid-template-columns:1fr; }
}
</style>
"""

# Line icons (teal, 1.7 stroke) for the hero stat tiles.
ICONS = {
    "hub": '<svg viewBox="0 0 24 24"><path d="M12 21s-7-6.1-7-11.5A7 7 0 0 1 19 9.5C19 14.9 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/></svg>',
    "pin": '<svg viewBox="0 0 24 24"><path d="M3 6.5 9 4l6 2.5L21 4v13.5L15 20l-6-2.5L3 20z"/><path d="M9 4v13.5M15 6.5V20"/></svg>',
    "poly": '<svg viewBox="0 0 24 24"><path d="M5 7 12 3l7 5-2 10H7z"/><circle cx="5" cy="7" r="1.6"/><circle cx="12" cy="3" r="1.6"/><circle cx="19" cy="8" r="1.6"/><circle cx="17" cy="18" r="1.6"/><circle cx="7" cy="18" r="1.6"/></svg>',
    "box": '<svg viewBox="0 0 24 24"><path d="M21 8 12 3 3 8v8l9 5 9-5z"/><path d="M3 8l9 5 9-5M12 13v8"/></svg>',
    "map": '<svg viewBox="0 0 24 24"><path d="M3 6.5 9 4l6 2.5L21 4v13.5L15 20l-6-2.5L3 20z"/><path d="M9 4v13.5M15 6.5V20"/></svg>',
}


def inject_css():
    # st.html with only <style> goes to Streamlit's event container: no element, no gap.
    st.html(_CSS)


def brand_html():
    return (f'<div class="sfx-brand"><img src="{LOGO_URL}" alt="Shadowfax - Think ahead!" width="133" height="50">'
            f'<div class="t">{PORTAL_NAME}</div></div>')


def render_login_head():
    st.markdown(
        f'<div class="sfx-login"><img src="{LOGO_URL}" alt="Shadowfax - Think ahead!" width="133" height="50">'
        f'<h1>Geo Intelligence <em>Portal</em></h1>'
        f'<p>Sign in with your work email and the portal password.</p></div>',
        unsafe_allow_html=True)


def fmt_count(n):
    """1234 -> '1,234'; 12345678 -> '12.3M' so it fits a stat tile."""
    if n is None:
        return "0"
    n = int(n)
    if n >= 10_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 100_000:
        return f"{n / 1_000:.0f}K"
    return f"{n:,}"


def render_hero(eyebrow, title_html, text, stats):
    """stats: list of (icon_key, value_str, caption). title_html may contain one <em>word</em>."""
    tiles = "".join(
        f'<div class="sfx-stat">{ICONS.get(ic, ICONS["box"])}<b>{_html.escape(str(v))}</b><span>{_html.escape(cap)}</span></div>'
        for ic, v, cap in stats)
    st.markdown(
        f'<div class="sfx-hero"><div><div class="sfx-eyebrow">{_html.escape(eyebrow)}</div>'
        f'<h1>{title_html}</h1><p>{_html.escape(text)}</p></div>'
        f'<div class="sfx-stats">{tiles}</div></div>',
        unsafe_allow_html=True)


def render_footer(year):
    st.markdown(
        f'<div class="sfx-foot"><div class="in"><span><b>{PORTAL_NAME}</b> &nbsp;&middot;&nbsp; <em>Think ahead!</em></span>'
        f'<span class="c">&copy; {year} Shadowfax Technologies Limited</span></div></div>',
        unsafe_allow_html=True)
