"""
허브 후보역 전수 감사 — 서울 밖에 있는 역 찾기
────────────────────────────────────────────────────────────
연구 범위는 서울 426개 행정동인데, 노선이 서울 경계를 넘어가는 구간
(3호선 지축, 4호선 남태령/과천 방면, 2호선 까치산 등)의 역이 허브 후보에
섞여 들어가 있었다. 경기도에 허브를 두면 라스트마일이 비효율적이고
연구 범위와도 안 맞는다.

판정 방법: 행정동.shp의 서울 전체 폴리곤(union)에 역 좌표가 실제로
들어가는지 point-in-polygon으로 본다(주소 문자열 매칭보다 확실).
경계에 걸친 역을 놓치지 않도록 완충거리 0m(엄격) 기준으로 판정하고,
경계에서 얼마나 떨어져 있는지 거리도 같이 뽑아 애매한 케이스를 보여준다.
"""

import os
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
import network_common as nc

BASE, OUT = nc.BASE, nc.OUT

print("[1] 역 목록 + 서울 경계 로드")
stations = nc.load_stations(verbose=False)
print(f"    역 {len(stations)}개")

shp = gpd.read_file(os.path.join(BASE, "행정동.shp"), encoding="utf-8")
shp["ADM_CD"] = shp["ADM_CD"].astype(str)
seoul = shp[shp["ADM_CD"].str.startswith("11")].to_crs(epsg=4326)
seoul_poly = seoul.union_all()

# 거리 계산은 미터 좌표계(EPSG:5179)에서
seoul_m = gpd.GeoDataFrame(geometry=[seoul_poly], crs="EPSG:4326").to_crs(epsg=5179)
seoul_poly_m = seoul_m.geometry.iloc[0]

print("\n[2] 점-in-폴리곤 판정")
gdf = gpd.GeoDataFrame(
    stations.copy(),
    geometry=[Point(xy) for xy in zip(stations["경도"], stations["위도"])],
    crs="EPSG:4326")
gdf["서울내"] = gdf.geometry.within(seoul_poly)

gdf_m = gdf.to_crs(epsg=5179)
gdf["경계까지_m"] = [
    (0.0 if p.within(seoul_poly_m) else p.distance(seoul_poly_m))
    for p in gdf_m.geometry]
gdf["경계에서_안쪽_m"] = [
    (p.distance(seoul_poly_m.boundary) if p.within(seoul_poly_m) else -p.distance(seoul_poly_m))
    for p in gdf_m.geometry]

outside = gdf[~gdf["서울내"]].sort_values("경계까지_m", ascending=False)
print(f"    서울 밖 역: {len(outside)}개")
if len(outside):
    print(f"    {'역명':<12}{'노선':>5}{'경계 밖 거리(m)':>16}")
    for _, r in outside.iterrows():
        print(f"    {r['역명']:<12}{r['노선']:>5}{r['경계까지_m']:>16,.0f}")

print("\n[3] 경계 근처(안쪽 1km 이내) 역 — 판정이 애매할 수 있는 케이스")
near = gdf[(gdf["서울내"]) & (gdf["경계에서_안쪽_m"] < 1000)].sort_values("경계에서_안쪽_m")
print(f"    {'역명':<12}{'노선':>5}{'경계에서 안쪽(m)':>18}")
for _, r in near.iterrows():
    print(f"    {r['역명']:<12}{r['노선']:>5}{r['경계에서_안쪽_m']:>18,.0f}")

# 사용자가 지목한 역들 개별 확인
print("\n[4] 지목된 역 확인")
for nm in ["지축", "남태령", "까치산", "구파발", "연신내", "온수", "도봉산", "금천구청", "독산"]:
    row = gdf[gdf["역명"] == nm]
    if len(row):
        r = row.iloc[0]
        state = "서울 내" if r["서울내"] else "★ 서울 밖"
        print(f"    {nm:<8} {state:<8} (경계 기준 {r['경계에서_안쪽_m']:+,.0f}m)")
    else:
        print(f"    {nm:<8} (역 목록에 없음)")

out_df = gdf[["역명", "노선", "위도", "경도", "서울내", "경계에서_안쪽_m"]].copy()
out_df.to_csv(f"{OUT}/station_seoul_audit.csv", index=False, encoding="utf-8-sig")
print(f"\n저장: {OUT}\\station_seoul_audit.csv")

excluded = sorted(outside["역명"].tolist())
print(f"\n[결론] 허브 후보에서 제외해야 할 역 {len(excluded)}개: {excluded}")
