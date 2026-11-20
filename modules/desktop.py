"""
Desktop mode: the two actions Streamlit Cloud cannot do, run on a laptop.

* Upload to Saruman: sarumanadmin.shadowfax.in only resolves inside the Shadowfax
  network (10.101.0.131), so only a laptop on the office network / VPN can reach it.
* Push to Google My Maps: Google has no API to write to My Maps, so a robot drives
  the My Maps website in a real, signed-in Chrome window:
    layer menu -> Reimport and merge -> "Merge matching items"  (polygons already in
    the layer, matched on name = Cluster Code: shape and description are updated)
    layer menu -> Reimport and merge -> "Add more items"         (new polygons only;
    "Add" does not de-duplicate, so existing names are never sent through it)
  then the map is read back to confirm every polygon.

The robot uses its own Chrome profile (%LOCALAPPDATA%\\GeoPortal\\robot-chrome) with a
debugging port, started on demand. People sign in to Google and Saruman in that window
themselves; the app only reuses those sessions and never handles a password (Saruman's
saved login is filled in by Chrome's own password manager).

Start desktop mode with deploy\\Start-Desktop.bat (sets GEO_PORTAL_DESKTOP=1).
Needs `pip install -r requirements-desktop.txt` (Playwright, which drives the
installed Chrome; no browser download).
"""
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request

ROBOT_PORT = int(os.environ.get("GEO_PORTAL_ROBOT_PORT", "9334"))
PROFILE_DIR = os.environ.get("GEO_PORTAL_ROBOT_PROFILE") or os.path.join(
    os.environ.get("LOCALAPPDATA") or tempfile.gettempdir(), "GeoPortal", "robot-chrome")
SARUMAN_ADD_URL = "https://sarumanadmin.shadowfax.in/admin/geocode/uploadpayloutcluster/add/"
_CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Google\Chrome\Application\chrome.exe"),
]


class RobotError(Exception):
    """A step the robot could not complete; the message is shown to the user."""


# ── Mode + robot Chrome ──────────────────────────────────────────────────────
def is_desktop():
    on_cloud = os.path.exists("/mount/src") or os.environ.get("STREAMLIT_SHARING_MODE") == "true"
    return os.environ.get("GEO_PORTAL_DESKTOP") == "1" and not on_cloud


def playwright_available():
    try:
        import playwright  # noqa: F401
        return True
    except Exception:
        return False


def _chrome_exe():
    return next((p for p in _CHROME_CANDIDATES if p and os.path.exists(p)), None) or shutil.which("chrome")


def chrome_running():
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{ROBOT_PORT}/json/version", timeout=2)
        return True
    except Exception:
        return False


def start_chrome(url="https://www.google.com/maps/d/"):
    """Open the robot Chrome window (its own profile + debugging port) if it isn't open."""
    if chrome_running():
        return True
    exe = _chrome_exe()
    if not exe:
        raise RobotError("Google Chrome is not installed on this computer.")
    os.makedirs(PROFILE_DIR, exist_ok=True)
    subprocess.Popen([exe, f"--user-data-dir={PROFILE_DIR}", f"--remote-debugging-port={ROBOT_PORT}",
                      "--no-first-run", "--no-default-browser-check", "--window-size=1400,900", url])
    for _ in range(40):
        if chrome_running():
            return True
        time.sleep(0.5)
    raise RobotError("The robot Chrome window did not start.")


class _Robot:
    """with _Robot() as ctx: ... -> the robot Chrome's browser context (Playwright)."""
    def __enter__(self):
        if not playwright_available():
            raise RobotError("Desktop mode needs Playwright: run  pip install -r requirements-desktop.txt")
        start_chrome()
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.connect_over_cdp(f"http://127.0.0.1:{ROBOT_PORT}", timeout=30000)
        return self.browser.contexts[0]

    def __exit__(self, *exc):
        self._pw.stop()  # disconnects only: the robot window stays open and signed in
        return False


def _new_page(ctx):
    pg = ctx.new_page()
    pg.on("dialog", lambda d: d.accept())  # e.g. "Leave site?" when the robot closes a tab
    return pg


def _close(pg):
    try:
        pg.goto("about:blank")
        pg.close()
    except Exception:
        pass


# ── Status ───────────────────────────────────────────────────────────────────
def status():
    """{'chrome': bool, 'google': bool|None, 'saruman': bool|None} (None = not checked)."""
    out = {"chrome": chrome_running(), "google": None, "saruman": None}
    if not out["chrome"] or not playwright_available():
        return out
    try:
        with _Robot() as ctx:
            r = ctx.request.get("https://www.google.com/maps/d/", max_redirects=0)
            out["google"] = r.status == 200
            r = ctx.request.get(SARUMAN_ADD_URL, max_redirects=0, timeout=10000)
            out["saruman"] = r.status == 200
    except Exception:
        pass
    return out


# ── Saruman ──────────────────────────────────────────────────────────────────
def _saruman_page(ctx):
    pg = _new_page(ctx)
    pg.goto(SARUMAN_ADD_URL, wait_until="domcontentloaded", timeout=45000)
    if "/login/" in pg.url:
        pg.wait_for_timeout(1500)  # give Chrome's password manager a moment to fill the form
        filled = pg.evaluate("() => !!(document.querySelector('input[name=username]')?.value && "
                             "document.querySelector('input[name=password]')?.value)")
        if not filled:
            raise RobotError("Saruman is not logged in. Click 'Open robot window', log in to Saruman there once "
                             "(let Chrome save the login), then try again.")
        pg.locator("input[type=submit]").click()
        pg.wait_for_load_state("domcontentloaded")
        if "/login/" in pg.url:
            raise RobotError("Saruman refused the saved login. Log in once in the robot window, then try again.")
    if pg.locator("input[type=file][name=file]").count() == 0:
        raise RobotError("Could not find Saruman's 'Upload payout cluster' form.")
    return pg


def upload_to_saruman(xlsx_bytes, filename):
    """Upload the payout-cluster workbook and click Save. Returns {'ok', 'message', 'screenshot'}.
    Saruman rejects the whole file on any invalid entry and applies accepted files at midnight."""
    path = os.path.join(tempfile.mkdtemp(prefix="saruman_"), filename)
    with open(path, "wb") as f:
        f.write(xlsx_bytes)
    with _Robot() as ctx:
        pg = _saruman_page(ctx)
        try:
            pg.locator("input[type=file][name=file]").set_input_files(path)
            pg.locator("input[type=submit][name=_save]").click()
            pg.wait_for_load_state("domcontentloaded", timeout=120000)
            pg.wait_for_timeout(1500)
            msgs = pg.evaluate("() => [...document.querySelectorAll('.messagelist li, .errornote, .errorlist li')]"
                               ".map(e => ({cls: e.className, text: e.innerText.trim()}))")
            shot = pg.screenshot(full_page=True)
            errors = [m["text"] for m in msgs if "error" in m["cls"] or "errornote" in m["cls"]]
            ok = not errors and ("/add/" not in pg.url or any("success" in m["cls"] for m in msgs))
            text = "; ".join(m["text"] for m in msgs) or ("Saved." if ok else "Saruman did not confirm the upload.")
            return {"ok": ok, "message": text, "screenshot": shot}
        finally:
            _close(pg)


# ── Google My Maps ───────────────────────────────────────────────────────────
def read_map(ctx, mid):
    """Parse the map as the signed-in user sees it (works for private maps too)."""
    from modules.mymaps_connector import parse_kml
    r = ctx.request.get(f"https://www.google.com/maps/d/kml?mid={mid}&forcekml=1", timeout=90000)
    if r.status != 200 or b"<kml" not in r.body()[:2048].lower():
        raise RobotError("Could not read the map: is the robot window signed in to a Google account that can edit it?")
    return parse_kml(r.body())


def map_layers(mid):
    """(title, {layer: polygon count}) incl. empty layers, from the editor + the signed-in KML."""
    with _Robot() as ctx:
        pdf, _, title = read_map(ctx, mid)
        counts = pdf.groupby("Layer").size().to_dict() if len(pdf) else {}
        pg = _new_page(ctx)
        try:
            pg.goto(f"https://www.google.com/maps/d/edit?mid={mid}", wait_until="domcontentloaded", timeout=60000)
            pg.wait_for_selector('[id^="ly"][id$="-layer-header"]', timeout=60000)
            names = [(h.inner_text().strip().splitlines() or [""])[0].strip()
                     for h in pg.locator('[id^="ly"][id$="-layer-header"]').all()]
        finally:
            _close(pg)
    return title, {n: counts.get(n, 0) for n in names if n}


def _push_csv(rows, path):
    """CSV My Maps imports: WKT (position), name (= Cluster Code, the merge key), description
    in the 'Hub: | Pincode: | Category: | Rate:' form the app's My Maps reader understands."""
    import pandas as pd
    desc = [f"Hub: {h} | Pincode: {p} | Category: {c} | Rate: {r}"
            for h, p, c, r in zip(rows["Hub Name"], rows["Pincode"], rows["Cluster_Category"], rows["Description"])]
    pd.DataFrame({"WKT": rows["Polygon WKT"].values, "name": rows["Cluster_Code"].values, "description": desc}) \
        .to_csv(path, index=False)


def _layer_header(pg, layer):
    heads = pg.locator('[id^="ly"][id$="-layer-header"]')
    for i in range(heads.count()):
        h = heads.nth(i)
        if (h.inner_text().strip().splitlines() or [""])[0].strip() == layer:
            return h
    raise RobotError(f"Layer '{layer}' was not found on the map.")


def _pickers(pg):
    return [f for f in pg.frames if "docs.google.com/picker" in f.url]


def _upload_in_picker(pg, path, known):
    """The Google file picker opened by Import / Reimport: Upload tab -> Browse -> file.
    `known` = picker frames that existed before the menu was opened: an earlier picker
    stays (hidden) on the page, and handing the file to it silently does nothing."""
    for _ in range(40):
        fresh = [f for f in _pickers(pg) if f not in known]
        pk = next((f for f in reversed(fresh) if f.locator("text=Upload >> visible=true").count()), None)
        if pk:
            break
        pg.wait_for_timeout(500)
    else:
        raise RobotError("The My Maps file picker did not open.")
    pk.locator("text=Upload >> visible=true").first.click()
    pg.wait_for_timeout(1500)
    with pg.expect_file_chooser(timeout=20000) as fc:
        pk.locator("text=Browse >> visible=true").first.click()
    fc.value.set_files(path)


def _finish_import_dialogs(pg, merge):
    """Answer My Maps' import questions: match on name (merge), or WKT/name for a fresh layer."""
    for _ in range(40):
        pg.wait_for_timeout(1000)
        dl = pg.locator("[role=dialog]:visible")
        if dl.count() == 0:
            if pg.locator("text=/Layer was updated|imported/i >> visible=true").count():
                return
            continue
        d = dl.last
        text = d.inner_text()
        if "match places" in text:
            names = d.locator("text=name >> visible=true")
            if names.count() < 2:
                raise RobotError("My Maps did not offer a 'name' column to match on.")
            names.nth(0).click(); pg.wait_for_timeout(300); names.nth(1).click(); pg.wait_for_timeout(300)
            d.get_by_text("Finish", exact=True).click()
        elif "position your placemarks" in text:
            d.get_by_text("WKT", exact=True).click(); pg.wait_for_timeout(300)
            d.get_by_text("Continue", exact=True).click()
        elif "title your markers" in text:
            d.get_by_text("name", exact=True).click(); pg.wait_for_timeout(300)
            d.get_by_text("Finish", exact=True).click()
        elif "error" in text.lower() or "couldn't" in text.lower():
            raise RobotError("My Maps reported a problem: " + " ".join(text.split())[:200])
    # no confirmation seen: the caller verifies by reading the map back


def _open_editor(pg, mid):
    """(Re)load the map editor: each import step starts on a clean page, because My Maps
    reuses or leaves behind file-picker frames from the previous step."""
    pg.goto(f"https://www.google.com/maps/d/edit?mid={mid}", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_selector('[id^="ly"][id$="-layer-header"]', timeout=60000)
    pg.wait_for_timeout(2500)


def _reimport(pg, layer, option, path, merge):
    known = _pickers(pg)
    head = _layer_header(pg, layer)
    head.locator('[aria-label="Layer options"]').click()
    pg.wait_for_timeout(800)
    pg.locator("[role=menuitem]:visible", has_text="Reimport and merge").hover()
    pg.wait_for_timeout(800)
    pg.locator("[role=menuitem]:visible", has_text=option).click()
    _upload_in_picker(pg, path, known)
    _finish_import_dialogs(pg, merge)


def push_to_mymaps(mid, layer, rows, progress=lambda msg: None):
    """Push polygons (app polygon columns) into one layer of a My Map, then verify.
    Returns {'updated', 'added', 'verified', 'missing', 'duplicates'}."""
    rows = rows.drop_duplicates("Cluster_Code").reset_index(drop=True)
    work = tempfile.mkdtemp(prefix="mymaps_push_")
    with _Robot() as ctx:
        progress("Reading the layer...")
        before, _, _ = read_map(ctx, mid)
        existing = set(before.loc[before["Layer"] == layer, "Cluster_Code"]) if len(before) else set()
        empty_layer = not existing
        final_layer = layer
        upd, new = rows[rows["Cluster_Code"].isin(existing)], rows[~rows["Cluster_Code"].isin(existing)]
        pg = _new_page(ctx)
        try:
            if len(upd):
                _open_editor(pg, mid)
                progress(f"Updating {len(upd)} polygon(s) already in '{layer}' (Merge matching items)...")
                p = os.path.join(work, "update.csv"); _push_csv(upd, p)
                _reimport(pg, layer, "Merge matching items", p, merge=True)
                pg.wait_for_timeout(4000)
            if len(new):
                _open_editor(pg, mid)
            if len(new) and empty_layer:
                progress(f"Importing {len(new)} polygon(s) into the empty layer '{layer}'...")
                # My Maps renames a layer to the imported file's name: keep the layer's name
                safe = "".join(ch for ch in layer if ch not in r'\/:*?"<>|').strip() or "polygons"
                p = os.path.join(work, safe if safe.lower().endswith(".csv") else safe + ".csv")
                _push_csv(new, p)
                final_layer = os.path.splitext(os.path.basename(p))[0] if not layer.lower().endswith(".csv") else layer
                known = _pickers(pg)
                head = _layer_header(pg, layer)
                imp = head.locator("xpath=..").locator("text=Import >> visible=true")
                if imp.count() == 0:
                    raise RobotError(f"Layer '{layer}' is not empty in the editor but has no polygons to update.")
                imp.first.click()
                _upload_in_picker(pg, p, known)
                _finish_import_dialogs(pg, merge=False)
                pg.wait_for_timeout(4000)
            elif len(new):
                progress(f"Adding {len(new)} new polygon(s) to '{layer}' (Add more items)...")
                p = os.path.join(work, "add.csv"); _push_csv(new, p)
                _reimport(pg, layer, "Add more items", p, merge=False)
                pg.wait_for_timeout(4000)
        finally:
            _close(pg)
        progress("Checking the map...")
        want = set(rows["Cluster_Code"])
        names = {layer, final_layer, final_layer + ".csv"}
        after = None
        for _ in range(12):  # the KML export can lag a few seconds behind an edit
            after, _, _ = read_map(ctx, mid)
            got = after[after["Layer"].isin(names)]
            if want <= set(got["Cluster_Code"]):
                break
            time.sleep(5)
        got = after[after["Layer"].isin(names)]
        cats = dict(zip(got["Cluster_Code"], got["Cluster_Category"]))
        ok = [c for c, cat in zip(rows["Cluster_Code"], rows["Cluster_Category"]) if cats.get(c) == cat]
        dup = got["Cluster_Code"].value_counts()
        return {"layer": got["Layer"].iloc[0] if len(got) else layer,
                "updated": len(upd), "added": len(new), "verified": len(ok),
                "missing": sorted(want - set(got["Cluster_Code"])),
                "duplicates": sorted(dup[dup > 1].index.intersection(list(want)))}


def open_window(url):
    """Bring up the robot window on a page (e.g. to sign in once)."""
    start_chrome(url)
    with _Robot() as ctx:
        pg = ctx.new_page()
        pg.goto(url, wait_until="domcontentloaded")
        pg.bring_to_front()
