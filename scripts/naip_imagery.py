"""NAIP RGB aerial over the study bbox -> web overlay (the exact imagery the NDVI came from).

Mosaic the Missouri NAIP tiles, reproject to EPSG:4326 north-up at ~3.5 m, write
data/naip.png (+ naip_bounds.json with the capture date). Toggled in the app so green-roof
flags are verified against the *same-date* imagery, not current Esri.
"""
import json
from collections import Counter

import numpy as np
import rasterio
from rasterio.merge import merge
from rasterio.warp import transform_bounds, reproject, Resampling
from rasterio.transform import from_bounds as tfb
import pystac_client
import planetary_computer as pc
from PIL import Image

BBOX = [-90.27, 38.60, -90.18, 38.66]
RES_M = 3.5
cat = pystac_client.Client.open(
    "https://planetarycomputer.microsoft.com/api/stac/v1", modifier=pc.sign_inplace)


def main():
    items = [x for x in cat.search(collections=["naip"], bbox=BBOX).items() if x.id.startswith("mo_")]
    yr = Counter(x.datetime.year for x in items).most_common(1)[0][0]
    items = [x for x in items if x.datetime.year == yr]
    date = str(items[0].datetime.date())
    print(f"NAIP {date}: {len(items)} MO tiles")
    srcs = [rasterio.open(x.assets["image"].href) for x in items]
    crs = srcs[0].crs
    l, b, r, t = transform_bounds("EPSG:4326", crs, *BBOX)
    mos, wt = merge(srcs, bounds=(l, b, r, t), indexes=[1, 2, 3], res=RES_M, nodata=0)
    for s in srcs:
        s.close()

    w, s, e, n = BBOX
    W = int((e - w) * 111320 * np.cos(np.radians(38.63)) / RES_M)
    H = int((n - s) * 111320 / RES_M)
    dst_tf = tfb(w, s, e, n, W, H)
    rgb = np.zeros((3, H, W), "uint8")
    for i in range(3):
        reproject(mos[i], rgb[i], src_transform=wt, src_crs=crs, dst_transform=dst_tf,
                  dst_crs="EPSG:4326", resampling=Resampling.bilinear, src_nodata=0, dst_nodata=0)
    alpha = (rgb.max(0) > 0).astype("uint8") * 255
    rgba = np.dstack([rgb[0], rgb[1], rgb[2], alpha])
    Image.fromarray(rgba, "RGBA").save("data/naip.png")
    json.dump({"tl": [w, n], "tr": [e, n], "br": [e, s], "bl": [w, s], "date": date},
              open("data/naip_bounds.json", "w"))
    import os
    print(f"wrote data/naip.png ({W}x{H}, {os.path.getsize('data/naip.png') // 1024} KB)")


if __name__ == "__main__":
    main()
