# Deployment — Self-Hosted via Tailscale (Private)

This app runs on a dedicated Windows PC/server on your own network and is
reachable **only** over a private [Tailscale](https://tailscale.com) network —
not the public internet. No public port-forwarding, no Streamlit Cloud.

This is one of two apps meant to run side-by-side on the same server:

| App | Repo | Port |
|---|---|---|
| **Clustering-web-app** (this repo) | Geo Intelligence Portal | **8501** |
| cluster-payout-optimization | Cluster Optimizer | 8502 |

See that repo's own `DEPLOYMENT.md` for its setup — the steps below only cover
this repo. Do both once each; they don't interfere with each other.

---

## 1. One-time server setup

Prerequisites on the dedicated Windows PC: **Python 3.11** and **Git**.

```powershell
# Clone (or pull if it's already there)
git clone https://github.com/rk7326181-lab/Clustering-web-app.git
cd Clustering-web-app

# Create an isolated virtual environment named `venv` — the start scripts
# auto-detect it (fall back to system Python if you skip this)
python -m venv venv
venv\Scripts\pip install --upgrade pip
venv\Scripts\pip install -r requirements.txt
```

### Secrets (never committed to Git)

```powershell
Copy-Item .streamlit\secrets.toml.example .streamlit\secrets.toml
notepad .streamlit\secrets.toml   # fill in real values — see comments in the file
```

`.streamlit\secrets.toml` holds BigQuery credentials and the app login
password. It's already in `.gitignore`. Fill in:
- `allowed_emails` / `app_password` — who can log into the app
- **either** `[google_oauth]` (personal Gmail token — expires every ~2 days
  under this workspace's policy; run `generate_bq_token.py` to (re)generate)
  **or** `[gcp_credentials]` (a service account key — doesn't expire; ask the
  BI/GCP team for one)

Optional — `.env` for the Groq AI key (also gitignored, already auto-loaded):

```powershell
Copy-Item .env.example .env
notepad .env
```

---

## 2. Install Tailscale and join the private network

On the dedicated server:

1. Download and install Tailscale for Windows: https://tailscale.com/download/windows
2. Run:
   ```powershell
   tailscale up
   ```
   This opens a browser to sign in (use your organization's Tailscale/Google
   account) and adds this machine to your private tailnet.
3. Note this machine's Tailscale address:
   ```powershell
   tailscale ip -4
   ```
   or use its **MagicDNS name** (Tailscale admin console → Machines), e.g.
   `shadowfax-server.your-tailnet.ts.net` — more stable than an IP.

On every **teammate's device** that needs access: install Tailscale, sign in
with an account you've authorized, and join the same tailnet. That's the
"only authorized devices can connect" control — a device not in the tailnet
cannot reach the server at all, regardless of network.

### Restrict which tailnet devices may reach this server (recommended)

By default any device on your tailnet can reach any other. To scope it
down, edit ACLs at https://login.tailscale.com/admin/acls, e.g.:

```json
{
  "tagOwners": { "tag:sfx-apps-server": ["you@shadowfax.in"] },
  "acls": [
    { "action": "accept", "src": ["you@shadowfax.in", "teammate@shadowfax.in"],
      "dst": ["tag:sfx-apps-server:8501", "tag:sfx-apps-server:8502"] }
  ]
}
```
Then tag the server (`tailscale up --advertise-tags=tag:sfx-apps-server`) and
only the listed users can reach ports 8501/8502 on it — everyone else on the
tailnet is denied even though they're on the same network.

### Extra layer: Windows Firewall scoped to Tailscale only (optional, recommended)

Even though the app binds to `0.0.0.0` (required for Tailscale to reach it),
you can stop your regular LAN/Wi-Fi from also reaching it:

```powershell
# Run as Administrator, once:
powershell -ExecutionPolicy Bypass -File .\deploy\Setup-Firewall.ps1
```

This adds a firewall rule that only allows port 8501 from Tailscale's address
range (`100.64.0.0/10`) and localhost — LAN devices outside the tailnet are
blocked at the OS level, on top of Tailscale's own device authentication.

---

## 3. Start / stop / restart / status

Double-click, from `deploy\`, or run the equivalent PowerShell commands from
the repo root:

| Action | Double-click | Command |
|---|---|---|
| Start | `deploy\Start-App.bat` | `powershell -ExecutionPolicy Bypass -File deploy\start.ps1` |
| Stop | `deploy\Stop-App.bat` | `powershell -ExecutionPolicy Bypass -File deploy\stop.ps1` |
| Restart | `deploy\Restart-App.bat` | `powershell -ExecutionPolicy Bypass -File deploy\restart.ps1` |
| Status | `deploy\Status-App.bat` | `powershell -ExecutionPolicy Bypass -File deploy\status.ps1` |

- Runs as a background process (no terminal window to keep open).
- Refuses to double-start; `Restart-App.bat` is the safe way to pick up code
  or secrets changes.
- Logs: `deploy\logs\app_<timestamp>.log` (+ `.err.log` for errors).
- PID tracked in `deploy\run\app.pid` (used by stop/restart/status).

**Any team member with access to this server can run these same four
commands** — nothing here is tied to one person's account or setup.

---

## 4. Access the app

- **From the server itself:** `http://localhost:8501`
- **Remotely, from any device on the tailnet:** `http://<tailscale-ip-or-magicdns-name>:8501`
  (find it with `tailscale ip -4` on the server, or `deploy\Status-App.bat`)

The app is never reachable from the public internet — only from devices
signed into your Tailscale network (and, if `Setup-Firewall.ps1` was run,
that's enforced at the OS firewall too).

---

## 5. Updating the app later

```powershell
git pull
venv\Scripts\pip install -r requirements.txt   # only if requirements changed
deploy\Restart-App.bat
```

---

## 6. Handoff notes

- Everything needed to run this app lives in this repo: code, `.streamlit\config.toml`
  (port/bind address), `deploy\` (start/stop/restart/status/firewall scripts).
- Only `.streamlit\secrets.toml` and `.env` are server-local and NOT in Git —
  keep a secure backup of these two files (e.g. a password manager), since a
  fresh `git clone` won't include them.
- If BigQuery shows "not connected", the Gmail token has likely expired
  (~every 2 days under this workspace's policy) — open the status button
  (top right) for the Connections panel's instructions, or run `generate_bq_token.py` and update `.streamlit\secrets.toml`.

## Desktop mode (Go Live → Upload to Saruman / Push to My Maps)

Two Go Live actions cannot run on Streamlit Cloud:

* **Upload to Saruman**: `sarumanadmin.shadowfax.in` only resolves inside the
  Shadowfax network (10.101.0.131), so it needs a laptop on office Wi-Fi or VPN.
* **Push to Google My Maps**: Google has no API to write to My Maps, so a robot
  drives the My Maps website in a signed-in Chrome window ("Reimport and merge →
  Merge matching items" for polygons already in the layer, "Add more items" for
  new ones), then reads the map back to confirm every polygon.

Start it on the laptop by double-clicking **`deploy\Start-Desktop.bat`**: it sets
`GEO_PORTAL_DESKTOP=1`, installs `requirements-desktop.txt` (Playwright, which
drives the installed Chrome) if needed, and opens the app at
http://localhost:8501. In Go Live → step 5, click **Open robot window** and sign
in there once to Google (and Saruman; Chrome's password manager fills the shared
login). The robot window has its own Chrome profile in
`%LOCALAPPDATA%\GeoPortal\robot-chrome`; the app never stores a password.

Safeguards: Saruman replaces *every* cluster of each hub in the file at midnight
and rejects the whole file on any invalid row, so the upload is blocked while
any of a hub's clusters has an error, pasted/uploaded files need a "contains every
cluster of each hub" confirmation, and nothing is uploaded without the
"I have checked the preview" confirmation.
