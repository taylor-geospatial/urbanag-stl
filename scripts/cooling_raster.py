"""Smooth neighborhood cooling-potential SURFACE (not blocky cells).

Resample NDVI (Sentinel) + LST (Landsat) onto a common ~15 m grid, Gaussian-smooth both,
regress LST on NDVI, then per pixel: cooling if greened to NDVI 0.4 = -slope*(0.4-ndvi).
Smooth again and colorize with plasma -> data/cooling.png (+ cooling_bounds.json,
cooling_stats.json). Rendered as an image overlay like the heat layer.
"""
import json
import sys

import numpy as np
import matplotlib
from scipy.ndimage import gaussian_filter
from rasterio.warp import reproject, Resampling
from rasterio.transform import from_bounds as transform_from_bounds

sys.path.insert(0, "scripts")
from analyze_rooftops import clearest, read_4326

BBOX = [-90.27, 38.60, -90.18, 38.66]
TARGET = 0.40
RES_M = 15.0
SIGMA = 2.2  # ~33 m smoothing
PLASMA = matplotlib.colormaps["plasma"]


def to_grid(arr, src_tf, dst_tf, h, w):
    out = np.full((h, w), np.nan, "float32")
    reproject(arr, out, src_transform=src_tf, src_crs="EPSG:4326",
              dst_transform=dst_tf, dst_crs="EPSG:4326", resampling=Resampling.bilinear,
              src_nodata=np.nan, dst_nodata=np.nan)
    return out


def smooth(a, sigma):
    # nan-aware Gaussian: blur values and weights, divide
    v = np.nan_to_num(a)
    w = np.isfinite(a).astype("float32")
    vb = gaussian_filter(v, sigma)
    wb = gaussian_filter(w, sigma)
    out = vb / np.where(wb > 1e-6, wb, np.nan)
    out[wb < 0.15] = np.nan
    return out


def main():
    w, s, e, n = BBOX
    width = int((e - w) * 111320 * np.cos(np.radians(38.63)) / RES_M)
    height = int((n - s) * 111320 / RES_M)
    dst_tf = transform_from_bounds(w, s, e, n, width, height)
    print(f"target grid {width}x{height} @ ~{RES_M} m")

    s2 = clearest("sentinel-2-l2a", "2023-06-01/2024-09-15", (6, 7, 8))
    red, tfn = read_4326(s2.assets["B04"].href)
    nir, _ = read_4326(s2.assets["B08"].href)
    ndvi = (nir - red) / (nir + red + 1e-6)
    ndvi[~np.isfinite(ndvi)] = np.nan

    ls = clearest("landsat-c2-l2", "2023-06-01/2024-09-15", (7, 8),
                  {"platform": {"in": ["landsat-8", "landsat-9"]}})
    dn, tfl = read_4326(ls.assets["lwir11"].href)
    lst = dn * 0.00341802 + 149.0 - 273.15
    lst[(dn == 0) | (lst < -25) | (lst > 80)] = np.nan

    nd = smooth(to_grid(ndvi, tfn, dst_tf, height, width), SIGMA)
    lt = smooth(to_grid(lst, tfl, dst_tf, height, width), SIGMA)

    m = np.isfinite(nd) & np.isfinite(lt)
    slope, _ = np.polyfit(nd[m], lt[m], 1)
    r = float(np.corrcoef(nd[m], lt[m])[0, 1])
    print(f"smoothed LST~NDVI slope={slope:.1f} r={r:.2f}")

    cooling = np.clip(-slope * (TARGET - nd), 0, None)
    cooling[~np.isfinite(nd)] = np.nan
    cooling = smooth(cooling, SIGMA)
    vmax = float(np.nanpercentile(cooling, 98))
    norm = np.clip(cooling / (vmax + 1e-6), 0, 1)
    rgba = (PLASMA(norm) * 255).astype("uint8")
    rgba[..., 3] = np.where(np.isfinite(cooling) & (cooling > 0.05), 200, 0).astype("uint8")

    from PIL import Image
    Image.fromarray(rgba, "RGBA").save("data/cooling.png")
    json.dump({"tl": [w, n], "tr": [e, n], "br": [e, s], "bl": [w, s]}, open("data/cooling_bounds.json", "w"))
    json.dump({"neighborhood_slope": round(float(slope), 1), "neighborhood_r": round(r, 2),
               "target_ndvi": TARGET, "max_cooling_C": round(vmax, 1)},
              open("data/cooling_stats.json", "w"))
    print(f"wrote data/cooling.png  max cooling ~{vmax:.1f} °C")


if __name__ == "__main__":
    main()
