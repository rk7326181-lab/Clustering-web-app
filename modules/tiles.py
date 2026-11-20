"""
Street-map backdrop for the static PNG photos (hub images, My Maps / Go Live photos).

contextily needs rasterio, whose compiled DLL is blocked by Windows Application
Control on Shadowfax laptops ("An Application Control policy has blocked this
file"), so on a work laptop every photo silently lost its street map. This module
fetches the same Esri World Street Map tiles with plain HTTP and stitches them
with Pillow: no compiled GIS libraries, so it works on laptops and on Streamlit
Cloud alike. Best-effort: callers keep drawing without a backdrop on failure.
"""
import math
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

ESRI_STREET = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}"
ESRI_ATTRIBUTION = "Tiles © Esri — Esri, HERE, Garmin, USGS, OpenStreetMap contributors"
_R = 6378137.0 * math.pi  # half the Web Mercator world width (m)
_TILE = 256


def zoom_for(x0, y0, x1, y1, tiles_across=5):
    """Zoom level giving about `tiles_across` tiles over the larger side of the extent."""
    span = max(x1 - x0, y1 - y0, 1.0)
    return int(min(17, max(3, math.floor(math.log2(tiles_across * 2 * _R / span)))))


def fetch(x0, y0, x1, y1, zoom=None, url=ESRI_STREET, timeout=15, max_tiles=64):
    """Tiles covering the Web Mercator (EPSG:3857) box -> (RGB uint8 array, (left, right, bottom, top)).
    Use with ax.imshow(img, extent=extent)."""
    import numpy as np
    import requests
    from PIL import Image

    z = zoom if zoom is not None else zoom_for(x0, y0, x1, y1)
    n = 2 ** z
    size = 2 * _R / n
    tx0, tx1 = int((x0 + _R) // size), int((x1 + _R) // size)
    ty0, ty1 = int((_R - y1) // size), int((_R - y0) // size)
    tx0, ty0 = max(tx0, 0), max(ty0, 0)
    tx1, ty1 = min(tx1, n - 1), min(ty1, n - 1)
    if (tx1 - tx0 + 1) * (ty1 - ty0 + 1) > max_tiles and z > 3:  # never fetch a huge mosaic
        return fetch(x0, y0, x1, y1, z - 1, url, timeout, max_tiles)
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (geo-intelligence-portal)"

    def get(t):
        x, y = t
        r = session.get(url.format(z=z, x=x, y=y), timeout=timeout)
        r.raise_for_status()
        return t, Image.open(BytesIO(r.content)).convert("RGB")

    tiles = [(x, y) for y in range(ty0, ty1 + 1) for x in range(tx0, tx1 + 1)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        got = dict(pool.map(get, tiles))
    mosaic = Image.new("RGB", ((tx1 - tx0 + 1) * _TILE, (ty1 - ty0 + 1) * _TILE))
    for (x, y), im in got.items():
        mosaic.paste(im, ((x - tx0) * _TILE, (y - ty0) * _TILE))
    extent = (-_R + tx0 * size, -_R + (tx1 + 1) * size, _R - (ty1 + 1) * size, _R - ty0 * size)
    return np.asarray(mosaic), extent


def add_to_axes(ax, zoom=None, zorder=0, attribution=True):
    """Draw the street map under whatever is already on a Web Mercator matplotlib axes."""
    (x0, x1), (y0, y1) = ax.get_xlim(), ax.get_ylim()
    img, ext = fetch(x0, y0, x1, y1, zoom)
    ax.imshow(img, extent=ext, interpolation="bilinear", zorder=zorder)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    if attribution:
        ax.text(0.005, 0.005, ESRI_ATTRIBUTION, transform=ax.transAxes, ha="left", va="bottom", fontsize=7,
                color="#374151", zorder=20, bbox=dict(facecolor="white", edgecolor="none", alpha=0.7, pad=1.5))
