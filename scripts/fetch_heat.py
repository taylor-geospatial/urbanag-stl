"""Real Landsat surface temperature (LST) over the STL study area -> RGBA PNG overlay.

Microsoft Planetary Computer STAC (no auth to search; assets signed for read).
Landsat Collection-2 Level-2 band ST_B10 ('lwir11'): ST_Kelvin = DN*0.00341802 + 149.0.
Output: data/heat_lst.png (EPSG:4326, north-up, colorized) + data/heat_bounds.json.
"""
import json
import numpy as np
import rasterio
from rasterio.warp import calculate_default_transform, reproject, Resampling
import pystac_client
import planetary_computer as pc
import matplotlib

BBOX = [-90.27, 38.60, -90.18, 38.66]   # W,S,E,N — matches buildings study area


def main():
    cat = pystac_client.Client.open(
        "https://planetarycomputer.microsoft.com/api/stac/v1",
        modifier=pc.sign_inplace,
    )
    search = cat.search(
        collections=["landsat-c2-l2"],
        bbox=BBOX,
        datetime="2023-06-15/2024-09-10",
        query={"eo:cloud_cover": {"lt": 8}, "platform": {"in": ["landsat-8", "landsat-9"]}},
    )
    items = [it for it in search.items() if it.datetime.month in (6,7,8,9)]
    items.sort(key=lambda it: it.properties.get("eo:cloud_cover", 100))
    if not items:
        raise SystemExit("no Landsat items found")
    item = items[0]
    print(f"using {item.id}  cloud={item.properties.get('eo:cloud_cover')}%  {item.datetime.date()}")

    href = item.assets["lwir11"].href
    with rasterio.open(href) as src:
        # window for the bbox in the scene CRS
        from rasterio.warp import transform_bounds
        l, b, r, t = transform_bounds("EPSG:4326", src.crs, *BBOX)
        win = src.window(l, b, r, t)
        dn = src.read(1, window=win).astype("float32")
        wt = src.window_transform(win)
        src_crs = src.crs
        nod = src.nodata

    lst_k = dn * 0.00341802 + 149.0
    lst_c = lst_k - 273.15
    lst_c[(dn == (nod or 0)) | (lst_c < -20) | (lst_c > 80)] = np.nan

    # reproject the small window to EPSG:4326 north-up
    h, w = lst_c.shape
    dst_tf, dw, dh = calculate_default_transform(src_crs, "EPSG:4326", w, h,
                                                 left=wt.c, bottom=wt.f + wt.e * h,
                                                 right=wt.c + wt.a * w, top=wt.f)
    dst = np.full((dh, dw), np.nan, "float32")
    reproject(lst_c, dst, src_transform=wt, src_crs=src_crs,
              dst_transform=dst_tf, dst_crs="EPSG:4326", resampling=Resampling.bilinear,
              src_nodata=np.nan, dst_nodata=np.nan)

    valid = dst[np.isfinite(dst)]
    lo, hi = np.percentile(valid, [2, 98])
    print(f"LST °C range (2–98 pct): {lo:.1f} … {hi:.1f}")

    norm = np.clip((dst - lo) / (hi - lo + 1e-6), 0, 1)
    # match the app's heat ramp
    cmap = matplotlib.colors.LinearSegmentedColormap.from_list(
        "heat", ["#2b3a8f", "#2e8bc0", "#7fd3a8", "#f2e25c", "#f0922b", "#e23b2e"])
    rgba = (cmap(norm) * 255).astype("uint8")
    rgba[..., 3] = np.where(np.isfinite(dst), 205, 0).astype("uint8")

    from PIL import Image
    Image.fromarray(rgba, "RGBA").save("data/heat_lst.png")

    # geographic corners from the dst transform (north-up)
    west, north = dst_tf.c, dst_tf.f
    east = west + dst_tf.a * dw
    south = north + dst_tf.e * dh
    bounds = {"tl": [west, north], "tr": [east, north], "br": [east, south], "bl": [west, south],
              "min": round(float(lo), 1), "max": round(float(hi), 1),
              "scene": item.id, "date": str(item.datetime.date())}
    json.dump(bounds, open("data/heat_bounds.json", "w"))
    print("wrote data/heat_lst.png + heat_bounds.json", bounds)


if __name__ == "__main__":
    main()
