"""
STEP 1c. dist_km.npy(역x동 도로망 거리행렬)에 1호선 신규 26개역 추가
────────────────────────────────────────────────────────────
step2.py에서 1호선을 코레일 관할 구간까지 확장하면서 26개역이 새로
후보역에 들어왔는데, dist_km.npy는 step1.py가 원래 110개역 기준으로
만든 행렬이라 이 26개역의 행이 없다. step1.py와 같은 방법(캐싱된
seoul_drive.graphml, Dijkstra 최단경로)으로 이 26개역만 추가 계산해서
행렬을 확장한다 — 새 역도 haversine 근사가 아니라 원래와 동일한 실제
도로망 최단거리를 쓴다.

한 번만 실행하면 되고, 결과는 dist_km.npy를 덮어쓴다(실행 전 자동 백업).
"""

import os
import re
import warnings
import numpy as np
import pandas as pd
import osmnx as ox
import networkx as nx
from tqdm import tqdm

warnings.filterwarnings("ignore")

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "output_data")


def clean_name(s):
    return re.sub(r"\([^)]*\)", "", str(s)).replace("역", "").strip()


TARGET_26 = ["가산디지털단지", "개봉", "광운대", "구로", "구일", "금천구청", "남영", "노량진", "녹천",
            "대방", "도봉", "도봉산", "독산", "방학", "석계", "신길", "신도림", "신이문", "영등포",
            "오류동", "온수", "외대앞", "용산", "월계", "창동", "회기"]
EXCLUDE_JUNGANG = {"서빙고", "옥수", "응봉", "이촌", "한남", "왕십리"}

print("[1] 신규 26개역 좌표 로드")
master = pd.read_excel(os.path.join(BASE, "한국철도공사_도시광역철도_역사정보_20260228.xlsx"))
master["역사명_clean"] = master["역사명"].map(clean_name)
cand = master[master["노선명"].isin(["경부선", "경인선", "경원선"])].copy()
cand = cand[cand["역사도로명주소"].astype(str).str.startswith("서울")]
cand = cand[~cand["역사명_clean"].isin(EXCLUDE_JUNGANG)]
cand = cand[cand["역사명_clean"].isin(TARGET_26)].drop_duplicates(subset="역사명_clean")
new_stations = cand[["역사명_clean", "역위도", "역경도"]].rename(
    columns={"역사명_clean": "역명", "역위도": "위도", "역경도": "경도"}).reset_index(drop=True)
print(f"    {len(new_stations)}/{len(TARGET_26)}개역 좌표 확보")
assert len(new_stations) == 26, "26개역이 모두 확보돼야 함 — step2.py의 1호선 확장 로직과 불일치"

stations_orig = pd.read_csv(f"{OUT}/stations.csv")
dist_orig = np.load(f"{OUT}/dist_km.npy")
print(f"    기존 dist_km.npy: {dist_orig.shape} (역 {len(stations_orig)}개 x 동 {dist_orig.shape[1]}개)")
assert dist_orig.shape[0] == len(stations_orig)

dongs = pd.read_csv(f"{OUT}/dongs.csv")
print(f"    동 {len(dongs)}개")

print("\n[2] 도로망 그래프 로드(캐시)")
GRAPH = os.path.join(OUT, "seoul_drive.graphml")
G = ox.load_graphml(GRAPH)
print(f"    노드 {len(G.nodes):,} / 엣지 {len(G.edges):,}")

print("\n[3] 좌표 -> 도로 노드 매핑")
new_st_nodes = ox.distance.nearest_nodes(G, X=new_stations["경도"].values, Y=new_stations["위도"].values)
dong_nodes = ox.distance.nearest_nodes(G, X=dongs["lon"].values, Y=dongs["lat"].values)

print(f"\n[4] 최단거리 계산 (신규 {len(new_stations)} x 동 {len(dongs)})")
D_new = np.full((len(new_stations), len(dongs)), np.inf)
for i, sn in enumerate(tqdm(new_st_nodes, desc="    역별")):
    try:
        L = nx.single_source_dijkstra_path_length(G, sn, weight="length")
        for j, dn in enumerate(dong_nodes):
            D_new[i, j] = L.get(dn, np.inf)
    except Exception as e:
        print(f"    실패: {new_stations.iloc[i]['역명']} — {e}")

D_new = D_new / 1000.0
n_inf = np.isinf(D_new).sum()
if n_inf:
    print(f"    ! 도달 불가 {n_inf}쌍 -> 100km로 대체 (step1.py와 동일 규칙)")
    D_new = np.where(np.isinf(D_new), 100.0, D_new)

print(f"    신규역 평균 거리: {D_new.mean():.2f}km")

# ── stations.csv와 정확히 같은 순서로 합치기 ────────────────────────
# step2.py가 station augmentation에서 "TARGET_26 순서대로, 창동 제외 후
# concat"하는 것과 동일한 순서로 맞춰야 행 인덱스가 어긋나지 않는다.
new_stations_no_changdong = new_stations[new_stations["역명"] != "창동"].reset_index(drop=True)
name_to_row = {nm: D_new[i] for i, nm in enumerate(new_stations["역명"])}
ordered_rows = np.array([name_to_row[nm] for nm in new_stations_no_changdong["역명"]])
print(f"    창동 제외 신규행 {ordered_rows.shape[0]}개 (stations.csv 확장 순서와 일치해야 함)")

backup_path = f"{OUT}/dist_km_backup_전1호선확장.npy"
if not os.path.exists(backup_path):
    np.save(backup_path, dist_orig)
    print(f"\n저장(백업): {backup_path}")

dist_extended = np.vstack([dist_orig, ordered_rows])
np.save(f"{OUT}/dist_km.npy", dist_extended)
print(f"저장: {OUT}\\dist_km.npy (확장 후 {dist_extended.shape})")

new_stations_no_changdong.to_csv(f"{OUT}/dist_km_new_station_order.csv", index=False, encoding="utf-8-sig")
print(f"저장: {OUT}\\dist_km_new_station_order.csv (검증용 — step2.py 확장 순서와 대조)")
