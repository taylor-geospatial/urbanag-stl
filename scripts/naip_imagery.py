"""NAIP RGB aerial over the study bbox -> web overlay (same scene the NDVI came from).

Reads each Missouri NAIP tile DECIMATED through its overviews (WarpedVRT + out_shape) so
the network read is small/fast (rasterio.merge reads full 60 cm and times out on PC).
Writes data/naip.png (EPSG:4326 north-up) + naip_bounds.json with the capture date.
"""
import json
from collections import Counter

import numpy as np
import rasterio
from rasterio.vrt import WarpedVRT
from rasterio.enums import Resampling
import pystac_client
import planetary_computer as pc
from PIL import Image

BBOX = [-90.27, 38.60, -90.18, 38.66]
RES_M = 3.0
cat = pystac_client.Client.open(
    "https://planetarycomputer.microsoft.com/api/stac/v1", modifier=pc.sign_inplace)


def search_naip():
    import time
    for attempt in range(5):
        try:
            return [x for x in cat.search(collections=["naip"], bbox=BBOX).items() if x.id.startswith("mo_")]
        except Exception as e:
            print(f"  search attempt {attempt + 1} failed ({type(e).__name__}); retrying...")
            time.sleep(8)
    raise SystemExit("PC STAC search kept timing out")


def main():
    W_, S_, E_, N_ = BBOX
    items = search_naip()
    yr = Counter(x.datetime.year for x in items).most_common(1)[0][0]
    items = [x for x in items if x.datetime.year == yr]
    date = str(items[0].datetime.date())
    width = int((E_ - W_) * 111320 * np.cos(np.radians(38.63)) / RES_M)
    height = int((N_ - S_) * 111320 / RES_M)
    print(f"NAIP {date}: {len(items)} tiles -> {width}x{height} @ ~{RES_M} m")

    rgb = np.zeros((3, height, width), "uint8")
    filled = np.zeros((height, width), bool)
    for it in items:
        with rasterio.open(it.assets["image"].href) as s:
            with WarpedVRT(s, crs="EPSG:4326", resampling=Resampling.bilinear) as vrt:
                win = vrt.window(W_, S_, E_, N_)
                arr = vrt.read(indexes=[1, 2, 3], window=win, out_shape=(3, height, width),
                               boundless=True, fill_value=0)
        m = (arr.max(0) > 0) & ~filled
        for i in range(3):
            rgb[i][m] = arr[i][m]
        filled |= m
        print(f"  +{it.id}  coverage now {filled.mean() * 100:.0f}%")

    alpha = (filled * 255).astype("uint8")
    rgba = np.dstack([rgb[0], rgb[1], rgb[2], alpha])
    Image.fromarray(rgba, "RGBA").save("data/naip.png")
    json.dump({"tl": [W_, N_], "tr": [E_, N_], "br": [E_, S_], "bl": [W_, S_], "date": date},
              open("data/naip_bounds.json", "w"))
    import os
    print(f"wrote data/naip.png ({os.path.getsize('data/naip.png') // 1024} KB)")


if __name__ == "__main__":
    main()
