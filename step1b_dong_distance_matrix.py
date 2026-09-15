"""
STEP 1b. 행정동 x 행정동 도로망 최단거리 행렬 구축
────────────────────────────────────────────────────────────
STEP 3(VRP 라스트마일 재계산)에서 허브별 순회경로를 짜려면 행정동 간
이동거리가 필요하다. step1.py가 이미 받아 캐시해 둔 서울 도로망 그래프
(output_data/seoul_drive.graphml)를 재사용하므로 도로망을 다시 받지 않는다.

한 번만 실행하면 되고, 결과는 output_data/dong_dist_km.npy 에 저장된다
(행/열 순서는 dongs.csv 행 순서와 동일).
"""

import os
import warnings
import numpy as np
import pandas as pd
import osmnx as ox
import networkx as nx
from tqdm import tqdm

warnings.filterwarnings("ignore")

BASE  = os.path.dirname(os.path.abspath(__file__))
OUT   = os.path.join(BASE, "output_data")
GRAPH = os.path.join(OUT, "seoul_drive.graphml")

if not os.path.exists(GRAPH):
    raise FileNotFoundError(f"{GRAPH} 없음 — step1.py를 먼저 실행하세요.")

print("[1] 캐시된 서울 도로망 로드")
G = ox.load_graphml(GRAPH)
print(f"    노드 {len(G.nodes):,} / 엣지 {len(G.edges):,}")

print("[2] 행정동 로드")
dongs = pd.read_csv(os.path.join(OUT, "dongs.csv"))
N_D = len(dongs)
print(f"    행정동 {N_D}개")

print("[3] 좌표 -> 도로 노드 매핑")
dong_nodes = ox.distance.nearest_nodes(G, X=dongs["lon"].values, Y=dongs["lat"].values)

print(f"[4] 행정동 간 최단거리 계산 ({N_D} x {N_D})")
D = np.full((N_D, N_D), np.inf)

for i, sn in enumerate(tqdm(dong_nodes, desc="    동별")):
    try:
        L = nx.single_source_dijkstra_path_length(G, sn, weight="length")
        for j, dn in enumerate(dong_nodes):
            D[i, j] = L.get(dn, np.inf)
    except Exception as e:
        print(f"    실패: {dongs.iloc[i]['ADM_NM']} — {e}")

D = D / 1000.0                        # m -> km
np.fill_diagonal(D, 0.0)
n_inf = np.isinf(D).sum()
if n_inf:
    print(f"    ! 도달 불가 {n_inf}쌍 -> 100km로 대체")
    D = np.where(np.isinf(D), 100.0, D)

np.save(os.path.join(OUT, "dong_dist_km.npy"), D)
print(f"\n완료 — 행렬 {D.shape}, 평균 거리 {D[~np.eye(N_D, dtype=bool)].mean():.2f} km")
print(f"저장: {OUT}\\dong_dist_km.npy")
