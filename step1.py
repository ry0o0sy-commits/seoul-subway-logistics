"""
STEP 1. 서울 도로망 기반 [지하철역 x 행정동] 최단거리 행렬 구축
────────────────────────────────────────────────────────────
한 번만 실행하면 됩니다. 결과는 ./output_data 에 저장되고
STEP 2에서 계속 재사용합니다.

로컬 실행용으로 경로만 /content -> 프로젝트 폴더로 변경.

[수정 사항]
  · 행정동.shp 인코딩: cp949 -> utf-8 (.cpg 파일 확인 결과 UTF-8)
  · 호선 필터: str.contains("1호선|2호선|3호선|4호선") -> 정확히 일치(isin)
    (원래 contains 방식은 "인천1호선"/"인천2호선"/"공항철도1호선"까지
     부분일치로 딸려 들어오는 버그가 있었음 — 194건 중 74건이 오염)
  · 단, "신이문"(경원선)/"구로"(경부선)처럼 코레일 선로명으로 표기된
    실제 1호선 직결 구간 역은 이 필터로는 여전히 잡히지 않음.
    -> STEP 2의 DEPOTS는 이문/구로 차량기지 대신 신설동(군자차량사업소가
       담당하는 1호선 입고 경로)을 1호선 기점으로 사용하도록 수정됨.
  · osmnx 2.x 대응: ox.nearest_nodes -> ox.distance.nearest_nodes
"""

import os
import warnings
import numpy as np
import pandas as pd
import geopandas as gpd
import osmnx as ox
import networkx as nx
from tqdm import tqdm

warnings.filterwarnings("ignore")

BASE = os.path.dirname(os.path.abspath(__file__))
STATION_CSV = os.path.join(BASE, "서울시 역사마스터 정보 (1).csv")
DONG_SHP    = os.path.join(BASE, "행정동.shp")
OUT         = os.path.join(BASE, "output_data")
os.makedirs(OUT, exist_ok=True)


# ══════════════════════════════════════════════════════════
# 1. 지하철역 — 1~4호선 필터 + 환승역 중복 제거
# ══════════════════════════════════════════════════════════
print("[1] 지하철역 로드")
st = pd.read_csv(STATION_CSV, encoding="cp949")
st = st[st["호선"].isin(["1호선", "2호선", "3호선", "4호선"])].copy()
print(f"    1~4호선 행: {len(st)}개")

# 역명에서 괄호 제거 ('용두(동대문구청)' -> '용두')
st["역명"] = st["역사명"].str.replace(r"\(.*?\)", "", regex=True).str.strip()

# 호선 번호만 추출
def line_no(s):
    for k in "1234":
        if f"{k}호선" == str(s):
            return k
    return None

st["노선"] = st["호선"].apply(line_no)

# ★ 환승역 중복 제거: 역사마스터는 호선별로 행이 나뉘어 있어
#   시청역이 1호선·2호선 두 행으로 존재 -> 물리적으로 같은 역이므로 통합
stations = (st.groupby("역명")
              .agg(노선=("노선", lambda s: "".join(sorted(set(x for x in s if x)))),
                   위도=("위도", "mean"),
                   경도=("경도", "mean"))
              .reset_index())
print(f"    중복 제거 후: {len(stations)}개 (환승역 {len(st)-len(stations)}개 통합)")


# ══════════════════════════════════════════════════════════
# 2. 행정동 — 서울시만 + 중심점 추출
# ══════════════════════════════════════════════════════════
print("[2] 행정동 SHP 로드")
dongs = gpd.read_file(DONG_SHP, encoding="utf-8")
dongs["ADM_CD"] = dongs["ADM_CD"].astype(str)
dongs = dongs[dongs["ADM_CD"].str.startswith("11")].copy()   # 서울 = 11

# 면적 계산 및 정확한 중심점 추출을 위해 미터 좌표계로 변환
dongs = dongs.to_crs(epsg=5179)
dongs["면적_km2"] = dongs.geometry.area / 1e6
dongs["centroid"] = dongs.geometry.centroid

# OSMnx 사용을 위해 다시 위경도로
dongs = dongs.set_geometry("centroid").to_crs(epsg=4326)
dongs["lon"] = dongs.geometry.x
dongs["lat"] = dongs.geometry.y
dongs = dongs.reset_index(drop=True)
print(f"    서울 행정동: {len(dongs)}개")


# ══════════════════════════════════════════════════════════
# 3. 도로망 그래프
# ══════════════════════════════════════════════════════════
GRAPH = os.path.join(OUT, "seoul_drive.graphml")
if os.path.exists(GRAPH):
    print("[3] 저장된 도로망 불러오는 중")
    G = ox.load_graphml(GRAPH)
else:
    print("[3] 서울 도로망 다운로드 (5~10분)")
    G = ox.graph_from_place("Seoul, South Korea", network_type="drive")
    ox.save_graphml(G, GRAPH)
print(f"    노드 {len(G.nodes):,} / 엣지 {len(G.edges):,}")


# ══════════════════════════════════════════════════════════
# 4. 최근접 도로 노드 매핑
# ══════════════════════════════════════════════════════════
print("[4] 좌표 -> 도로 노드 매핑")
st_nodes   = ox.distance.nearest_nodes(G, X=stations["경도"].values, Y=stations["위도"].values)
dong_nodes = ox.distance.nearest_nodes(G, X=dongs["lon"].values,     Y=dongs["lat"].values)


# ══════════════════════════════════════════════════════════
# 5. 최단거리 행렬 [역 x 행정동]
# ══════════════════════════════════════════════════════════
print(f"[5] 최단거리 계산 ({len(stations)} x {len(dongs)})")
D = np.full((len(stations), len(dongs)), np.inf)

for i, sn in enumerate(tqdm(st_nodes, desc="    역별")):
    try:
        L = nx.single_source_dijkstra_path_length(G, sn, weight="length")
        for j, dn in enumerate(dong_nodes):
            D[i, j] = L.get(dn, np.inf)
    except Exception as e:
        print(f"    실패: {stations.iloc[i]['역명']} — {e}")

D = D / 1000.0                       # m -> km
n_inf = np.isinf(D).sum()
if n_inf:
    print(f"    ! 도달 불가 {n_inf}쌍 -> 100km로 대체")
    D = np.where(np.isinf(D), 100.0, D)


# ══════════════════════════════════════════════════════════
# 6. 저장
# ══════════════════════════════════════════════════════════
np.save(os.path.join(OUT, "dist_km.npy"), D)
stations.to_csv(os.path.join(OUT, "stations.csv"), index=False, encoding="utf-8-sig")
dongs.drop(columns=["geometry", "centroid"], errors="ignore").to_csv(
    os.path.join(OUT, "dongs.csv"), index=False, encoding="utf-8-sig")

print(f"\n완료 — 행렬 {D.shape}, 평균 거리 {D[D < 100].mean():.2f} km")
print(f"저장: {OUT}\\dist_km.npy, stations.csv, dongs.csv")
