"""GeoJSON intermediates -> Hilbert-sorted GeoParquet 1.1 (canonical cloud-native store).

ZSTD columnar compression, a `bbox` covering column, and Hilbert spatial sort with small
row groups so a reader (DuckDB / parquet-wasm) prunes to just the row groups covering the
viewport — i.e. stream only the area in view. Host these on Source Cooperative.
"""
import json
import geopandas as gpd
import shapely.geometry as sg

ROW_GROUP = 2000  # small groups + spatial sort => tight bbox stats => good range pruning


def build(src, ts_col=False):
    g = json.load(open(src))
    geoms, props = [], []
    for f in g["features"]:
        p = dict(f["properties"])
        if ts_col:
            ts = p.pop("_lst_ts", None)
            if ts:
                p["_ts"] = json.dumps(ts, separators=(",", ":"))
        props.append(p)
        geoms.append(sg.shape(f["geometry"]))
    gdf = gpd.GeoDataFrame(props, geometry=geoms, crs="EPSG:4326")
    gdf = gdf.iloc[gdf.hilbert_distance().argsort()].reset_index(drop=True)  # spatial sort
    return gdf


def write(gdf, out):
    gdf.to_parquet(out, compression="zstd", schema_version="1.1.0",
                   write_covering_bbox=True, row_group_size=ROW_GROUP, index=False)
    import os
    print(f"  {out}: {os.path.getsize(out) // 1024} KB  ({len(gdf)} features, {gdf.shape[1] - 1} cols)")


if __name__ == "__main__":
    import os
    write(build("data/buildings.geojson", ts_col=True), "public/data/buildings.parquet")
    write(build("data/gardens.geojson"), "public/data/gardens.parquet")
    if os.path.exists("data/cooling.geojson"):
        write(build("data/cooling.geojson"), "public/data/cooling.parquet")
