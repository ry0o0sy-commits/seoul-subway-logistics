"""
VRP 라스트마일 순회 경로 시각화 v2 — 허브별 개별 파일, 가독성 개선
────────────────────────────────────────────────────────────
이전 버전(vrp_route_sample.png)은 3개 허브를 한 장에 몰아넣고, 왼쪽
"개별 왕복" 패널에 그 허브가 담당하는 동 전체(최대 189개)를 다 그려서
빨간 스파이크가 뭉개진 덩어리로만 보이는 문제가 있었다(발표 슬라이드에서
3초 안에 읽히지 않는다는 피드백).

이번 버전에서 바뀐 것:
  1. 허브 1개당 파일 1개로 분리(발표 슬라이드에 한 장씩 띄우는 용도).
  2. 오른쪽(VRP) 패널은 방문건수 기준 상위 5개 트럭만 그린다 — "나머지
     트럭"은 옅은 회색으로도 아예 그리지 않는다(예전엔 회색 스파게티가
     화면을 덮었음).
  3. 왼쪽(개별 왕복) 패널도 "오른쪽 상위 5대가 실제로 방문하는 동"만
     골라 그린다 — 나머지 동(상위 5대에 없는 것)은 양쪽 다 안 그려서,
     정확히 같은 동 집합을 "방사형으로 각자 왕복" vs "묶어서 순회"로
     1:1 비교할 수 있게 한다. 왼쪽 스파이크는 그 동이 속한 오른쪽 트럭과
     동일한 색으로 칠해 대응관계를 바로 보이게 한다.
  4. 배경(행정동 경계)은 alpha=0.12로 거의 안 보이게 — 경로선이 배경에
     묻히지 않게 하는 게 우선이라 지리적 맥락은 최소한만 남긴다.
  5. 각 VRP 정차 지점에 방문 순서 번호를 표기한다.
  6. 패널 하단에 큰 글씨로 요약 수치를 표기하되, "상위 5대 기준"(이
     그림에 실제로 그려진 것)과 "허브 전체 기준"(step3_vrp_lastmile.py의
     vrp_summary.csv 원본 수치)을 분리해서 함께 적는다 — 그림에 안 그린
     나머지 트럭까지 포함한 절감률을 그림만 보고 오해하지 않도록.

거리 수치(총 XX.Xkm)는 STEP 1의 dist_km.npy(역x동 도로망 최단거리)를
그대로 쓴다 — 그림에 그리는 직선은 시각화 편의를 위한 근사(실제 도로
곡선이 아님)이고, 수치 자체는 실제 계산에 쓰인 도로거리다.

STEP 3(step3_vrp_lastmile.py)가 만든 vrp_hub_routes.csv, vrp_summary.csv,
scenario_assignments.csv가 있어야 한다.

[v3 추가 — 지하철 노선 배경]
그 허브가 속한 노선 1개만(독산->1호선, 신설동->2호선, 수서->3호선) 배경에
옅게 깔아 "이 허브가 이 노선 소속"이 바로 보이게 한다. 노선 형상은 정확한
선형이 아니라 step2.py의 G_seq와 같은 방식(역간거리 CSV를 역명 순서대로
연결)으로 만든 "역을 잇는 직선"이다. 실제 노선색(서울교통공사 공식
색상)을 굵고 옅게(linewidth 5, alpha 0.35) 깔아 배경으로만 쓰고, 트럭
경로(linewidth 2.5, alpha 1.0)가 항상 위에서 더 진하고 가늘게 보이도록
선굵기·투명도 위계를 반대로 준다(굵을수록 연하게, 가늘수록 진하게).

트럭 경로 팔레트도 이번에 바꿨다 — 기존 Okabe-Ito 팔레트의 초록/주황이
2호선(초록)·3호선(주황) 배경색과 겹쳐 혼동될 수 있어, 채도를 낮춘
어두운 계열(남색/자주/갈색/검정/진회색)로 교체해 배경 노선색과 항상
구분되게 했다.
"""

import os
import re
import warnings
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams["font.family"] = "Malgun Gothic"
matplotlib.rcParams["axes.unicode_minus"] = False
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
warnings.filterwarnings("ignore")

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "output_data")

import network_common as _nc_id
SCENARIO_ID = _nc_id.REP_SCENARIO["ID"]   # 대표 시나리오 정의는 network_common 한 곳
# 담당 규모가 큰 허브 위주로 6곳 — 서부 대물량(양천구청)·동부(신답)·
# 서남(구로)·동북(신이문)·도심(서울역)·중남부(총신대입구).
# ※ 라스트마일 편도->왕복 수정으로 허브가 14 -> 18개로 바뀌면서 예전 샘플의
#   광운대·도곡·충정로는 대표성이 떨어지거나(충정로 7개동) 허브에서
#   빠져(광운대·도곡) 위 목록으로 교체했다.
SAMPLE_HUBS = [("양천구청", "1_yangcheon"), ("신답", "2_sindap"), ("구로", "3_guro"),
               ("신이문", "4_sinimun"), ("서울역", "5_seoulyeok"), ("총신대입구", "6_chongshin")]
N_HIGHLIGHT = 5   # 상위 몇 대만 그릴지

# ── 전체 경로 버전 ────────────────────────────────────────
# 상위 5대만 그리면 "나머지 동은 누가 가나"라는 질문이 남는다. 그래서 전체
# 트럭을 다 그리는 버전도 만들어 어느 쪽이 읽히는지 직접 비교할 수 있게 했다.
# 전체 버전은 선이 수십 개라 스타일을 바꾼다 — 선을 얇게, 정차 순서 번호와
# 트럭별 범례를 빼고(수십 줄이 되면 그림을 덮는다), 색은 순환 팔레트를 쓴다.
FULL_MODE = False          # draw_hub()에서 참조. main에서 모드에 따라 켠다.
FULL_LW, FULL_MS = 1.1, 3.0
FULL_PALETTE = ["#C2185B", "#6A1B9A", "#5D4037", "#212121", "#00838F",
                "#1565C0", "#2E7D32", "#EF6C00", "#4527A0", "#00695C",
                "#AD1457", "#37474F"]

# ── 노선별 대표 허브 1곳씩 (vrp_route_N호선_○○.png) ──────────────────
# 위 SAMPLE_HUBS가 1호선 2곳 + 2호선 3곳으로 편중돼 3·4호선이 아예 없었다.
# 노선별로 1곳씩 골라 4장을 따로 만든다. 선정 근거(S39 실적 기준):
#
#   호선  허브      트럭  담당동  분할동  분할비율  다중방문경로비율  거리절감률
#    1   독산       56    30     22     0.73      0.18          16.7%
#    2   신설동     55    42     23     0.55      0.20          18.8%
#    3   수서       67    31     25     0.81      0.18          10.9%
#    4   창동       53    39     31     0.79      0.21          20.9%
#
#   · 분할비율(= 여러 트럭이 나눠 가는 동 / 담당 동)이 낮을수록 선이 덜 겹쳐
#     순회 경로가 또렷하게 읽힌다. 각 호선 후보 중 낮은 쪽을 택했다.
#   · 트럭 수가 비슷해야(53~67대) 4장을 나란히 놓았을 때 밀도가 고르다.
#     같은 2호선의 양천구청(84대)은 한 장에 선이 너무 많다.
#   · 권역: 독산(서남) / 신설동(도심) / 수서(동남) / 창동(동북).
#     1호선은 서울역이 분할비율(0.48)로는 가장 깨끗하지만 신설동과 권역이
#     겹쳐 제외했다. 독산은 1호선 코레일 구간 신규역이기도 하다.
#     3호선은 오금이 다중방문비율 0.24로 가장 높지만 담당 동이 12개뿐이라
#     경로가 성기게 보여, 담당 규모(31개동)가 있는 수서를 택했다.
LINE_SAMPLE_HUBS = [("1", "독산"), ("2", "신설동"), ("3", "수서"), ("4", "창동")]

# 트럭 경로 팔레트 — v1(남색/자주/갈색/검정/진회색)은 전부 어두운 무채색
# 계열로 묶여 트럭끼리(특히 검정<->진회색, 자주<->갈색) 분간이 잘 안 된다는
# 피드백을 받아 색상환에서 고르게 벌어지도록 재선정했다: 마젠타/보라/갈색/
# 검정/틸. 노선색(1호선 파랑 #0052A4, 2호선 초록 #00A84D, 3호선 주황
# #EF7C1C, 4호선 하늘 #00A5DE)과는 명도를 어둡게 유지해 여전히 구분된다.
HL_COLORS = ["#C2185B", "#6A1B9A", "#5D4037", "#212121", "#00838F"]

# 허브가 속한 노선(배경에 옅게 깔 노선) — 서울교통공사 공식 노선색
LINE_FOR_HUB = {"충정로": "2", "광운대": "1", "구로": "1", "신답": "2", "양천구청": "2",
                "도곡": "3", "노원": "4", "독산": "1", "가락시장": "3",
                # 편도->왕복 수정 후 새로 허브가 된 역들
                "신설동": "2", "수서": "3", "창동": "4", "신이문": "1", "서울역": "1",
                "총신대입구": "4", "교대": "3", "구의": "2", "오금": "3",
                "신용산": "4", "대방": "1", "불광": "3"}
LINE_COLORS = {"1": "#0052A4", "2": "#00A84D", "3": "#EF7C1C", "4": "#00A5DE"}

# 4호선(하늘 #00A5DE) 배경일 때만 트럭5(틸 #00838F)가 색상환에서 너무
# 가까워 올리브 계열로 교체한다 — 2/3호선(초록/주황)에서는 그대로 둔다.
TRUCK5_OVERRIDE_BY_LINE = {"4": "#827717"}

print("[1] 데이터 로드")
# 1호선 코레일 구간 26개역 포함 확장 역 목록(135행) — 신규역이 허브로
# 잡힌 시나리오에서도 좌표/인덱스를 찾을 수 있어야 한다.
import network_common as nc
stations = nc.load_stations(verbose=False)
dongs = pd.read_csv(f"{OUT}/dongs.csv")
dist = np.load(f"{OUT}/dist_km.npy")            # [역 x 동] 도로망 최단거리(km)
routes_all = pd.read_csv(f"{OUT}/vrp_hub_routes.csv")
routes_all = routes_all[routes_all["ID"] == SCENARIO_ID].copy()
summary_all = pd.read_csv(f"{OUT}/vrp_summary.csv")
summary_all = summary_all[summary_all["ID"] == SCENARIO_ID].copy()

name2idx_st = {r["역명"]: i for i, r in stations.iterrows()}
name2ll = {r["역명"]: (r["경도"], r["위도"]) for _, r in stations.iterrows()}

# ★ 행정동은 이름이 유일하지 않다 — dongs.csv에 "신사동"이 관악구(idx 329)와
#   또 한 곳(idx 358) 두 번 나온다. 예전에는 이름->좌표 dict를 통째로 만들어
#   써서 나중 행이 앞 행을 덮어썼고, 독산이 담당하는 관악구 신사동이 한강
#   건너 북동쪽 좌표로 그려졌다(긴 선 2개). 거리 합계도 함께 틀어졌다.
#   vrp_hub_routes.csv에는 동 "이름"만 있으므로, 좌표는 반드시
#   scenario_assignments.csv의 행정동_idx로 풀어야 한다. 아래 맵은
#   허브별로 그 허브에 배정된 동에 한정해 이름->인덱스를 만든다.
assign_all = pd.read_csv(f"{OUT}/scenario_assignments.csv")
assign_all = assign_all[assign_all["ID"] == SCENARIO_ID]
DUP_DONGS = set(dongs["ADM_NM"].value_counts()[lambda s: s > 1].index)
if DUP_DONGS:
    print(f"[!] 동명 중복 {len(DUP_DONGS)}건: {sorted(DUP_DONGS)} — "
          f"허브별 행정동_idx로 좌표를 푼다")


def hub_dong_maps(hub_name):
    """그 허브에 배정된 동만의 이름->(인덱스, 좌표). 동명 중복을 정확히 해소."""
    sub = assign_all[assign_all["배정허브"] == hub_name]
    idx = {r["행정동"]: int(r["행정동_idx"]) for _, r in sub.iterrows()}
    ll = {n: (dongs.loc[i, "lon"], dongs.loc[i, "lat"]) for n, i in idx.items()}
    return idx, ll

import geopandas as gpd
shp = gpd.read_file(os.path.join(BASE, "행정동.shp"), encoding="utf-8")
shp["ADM_CD"] = shp["ADM_CD"].astype(str)
geo_dong = shp[shp["ADM_CD"].str.startswith("11")].to_crs(epsg=4326)

# 자치구 경계 — ADM_CD 8자리 중 앞 5자리(시도 2 + 자치구 3)로 dissolve.
# (step2.py의 GU_CODE = ADM_CD[2:5]와 같은 규칙, 여기서는 시도코드까지
# 포함해 [:5]로 묶는다.)
geo_dong["GU_KEY"] = geo_dong["ADM_CD"].str[:5]
geo_gu = geo_dong.dissolve(by="GU_KEY").reset_index()

# 서울 전체 외곽 — 행정동을 전부 하나로 합쳐 단일 윤곽만 남긴다.
geo_seoul = gpd.GeoDataFrame(geometry=[geo_dong.union_all()], crs=geo_dong.crs)


def draw_admin_layers(ax, xlim, ylim):
    """위계: 서울 외곽(진하게) > 자치구(중간) > 행정동(연하게). 배경에도
    옅은 채색을 깔아 "이게 지도"라는 게 흰 바탕에서도 바로 보이게 한다."""
    ax.set_facecolor("#f5f5f5")
    geo_dong.cx[xlim[0]:xlim[1], ylim[0]:ylim[1]].plot(
        ax=ax, facecolor="#f5f5f5", edgecolor="#999999", linewidth=0.4, alpha=0.45, zorder=0)
    geo_gu.cx[xlim[0]:xlim[1], ylim[0]:ylim[1]].plot(
        ax=ax, facecolor="none", edgecolor="#666666", linewidth=1.2, alpha=0.7, zorder=1)
    geo_seoul.plot(ax=ax, facecolor="none", edgecolor="#333333", linewidth=1.5, alpha=0.8, zorder=1)


# ── 노선 형상(배경용) — step2.py의 G_seq와 같은 방식: 역간거리 CSV를
#    역명 순서대로 이어 "역을 잇는 직선" 목록을 만든다(정확한 선형 아님).
def clean_name(s):
    return re.sub(r"\([^)]*\)", "", str(s)).replace("역", "").strip()

SEG_CSV = os.path.join(BASE, "서울교통공사 역간거리 및 소요시간_240810.csv")
seg = pd.read_csv(SEG_CSV, encoding="cp949")
seg["호선"] = seg["호선"].astype(str)
seg = seg[seg["호선"].isin(["1", "2", "3", "4"])].reset_index(drop=True)
seg["역명"] = seg["역명"].map(clean_name)

BRANCH_PARENT_OVERRIDE = {("2", "용답"): ("2", "성수"), ("2", "도림천"): ("2", "신도림")}

station_coords_clean = {}
for _, r in stations.iterrows():
    station_coords_clean.setdefault(clean_name(r["역명"]), (r["경도"], r["위도"]))

LINE_EDGES = {}     # 호선 -> [((lon1,lat1),(lon2,lat2)), ...]
LINE_NODE_XY = {}   # 호선 -> [(lon,lat), ...] (역 마커용)
for ln in sorted(set(LINE_FOR_HUB.values())):
    sub = seg[seg["호선"] == ln].reset_index(drop=True)
    prev_node = None
    edges, nodes_xy = [], []
    for _, row in sub.iterrows():
        node = (ln, row["역명"])
        if node[1] in station_coords_clean:
            nodes_xy.append(station_coords_clean[node[1]])
        parent = BRANCH_PARENT_OVERRIDE.get(node, prev_node)
        if parent is not None and parent != node:
            p_xy = station_coords_clean.get(parent[1])
            n_xy = station_coords_clean.get(node[1])
            if p_xy and n_xy:
                edges.append((p_xy, n_xy))
        prev_node = node
    LINE_EDGES[ln] = edges
    LINE_NODE_XY[ln] = nodes_xy


def draw_subway_layer(ax, line_code):
    """굵고 옅게(배경) — 선굵기·투명도를 트럭 경로와 반대로 줘서 항상
    트럭 경로가 더 가늘고 진하게, 지하철이 더 굵고 연하게 보이게 한다."""
    c = LINE_COLORS[line_code]
    for (x1, y1), (x2, y2) in LINE_EDGES[line_code]:
        ax.plot([x1, x2], [y1, y2], color=c, linewidth=5, alpha=0.35, zorder=1.2,
                solid_capstyle="round")
    nx_, ny_ = zip(*LINE_NODE_XY[line_code])
    ax.scatter(nx_, ny_, s=18, facecolor="white", edgecolor=c, linewidth=1.0,
              alpha=0.6, zorder=1.3)


def draw_hub_marker(ax, hx, hy, hub_name, color):
    """이중 원(지하철 환승역 표기 느낌) + 흰 바탕 뱃지 라벨 — 마커는
    "역 위치를 찾을 수 있으면 충분"한 절제된 크기로만, 주인공인 경로
    패턴(방사형 vs 루프)을 가리지 않게 한다. 라벨은 경로가 상대적으로
    적은 좌상단으로 살짝 띄워 트럭 경로 위에 얹히지 않게 한다."""
    # zorder는 경로선(4)·정차번호(6)보다 위에 둬서 마커가 묻히지 않게 한다.
    ax.scatter([hx], [hy], s=300, color="white", zorder=10)      # 흰 테두리 역할
    ax.scatter([hx], [hy], s=170, color=color, zorder=11)
    # 라벨을 마커 바로 위에 붙이되, 짧은 리더선으로 마커와 이어서 "이
    # 라벨이 이 마커의 것"이라는 소속이 흔들리지 않게 한다(이전 버전은
    # 경로를 피하려고 오프셋을 크게 줬다가 라벨이 마커에서 따로 노는
    # 문제가 있었다).
    ax.annotate(hub_name, (hx, hy), fontsize=11, fontweight="bold", color=color,
               xytext=(0, 16), textcoords="offset points", ha="center", va="bottom", zorder=12,
               bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor=color,
                        linewidth=1.8, alpha=0.97),   # 경로선 위로 확실히 뜨게
               arrowprops=dict(arrowstyle="-", color=color, linewidth=1))


def draw_hub(hub_name, out_stub, out_name=None):
    """out_name을 주면 그 파일명으로 저장한다(노선별 세트에서 사용)."""
    hub_j = name2idx_st[hub_name]
    hx, hy = name2ll[hub_name]

    name2idx_dg, dong2ll = hub_dong_maps(hub_name)   # 허브별 정확한 매핑
    hub_routes = routes_all[routes_all["허브"] == hub_name].copy()
    hub_routes["stops_list"] = hub_routes["방문순서"].str.split(" -> ")
    hub_routes["n_stops"] = hub_routes["stops_list"].apply(len)
    hub_routes = hub_routes.sort_values("n_stops", ascending=False).reset_index(drop=True)
    n_total_trucks = len(hub_routes)
    top = (hub_routes if FULL_MODE
           else hub_routes.head(N_HIGHLIGHT)).reset_index(drop=True)
    n_shown = len(top)

    srow = summary_all[summary_all["허브"] == hub_name].iloc[0]

    # ── 상위 N대가 실제로 방문하는 동 집합(트럭별 순서 유지) ──────────────
    # 같은 동이 분할배송으로 두 트럭에 나뉘어 있을 수도 있어, "동 이름"이
    # 아니라 "트럭별 방문 occurrence" 단위로 다룬다(분할이면 두 번 그려짐
    # — 실제로도 트럭 두 대가 각각 그 동에 간다는 뜻이라 정확한 표현이다).
    subset_occurrences = []   # (dong_name, truck_idx)
    for ti, r in top.iterrows():
        for dong_name in r["stops_list"]:
            if dong_name in name2idx_dg:
                subset_occurrences.append((dong_name, ti))

    subset_km_individual = sum(2 * dist[hub_j, name2idx_dg[d]] for d, _ in subset_occurrences)
    subset_trucks_individual = len(subset_occurrences)
    subset_km_vrp = top["경로거리_km"].sum()
    subset_pct = 1 - subset_km_vrp / subset_km_individual if subset_km_individual > 0 else 0.0

    print(f"  {hub_name}: 전체 {n_total_trucks}대 중 상위 {n_shown}대 표시 "
          f"(상위{n_shown}대 개별{subset_km_individual:.1f}km -> VRP{subset_km_vrp:.1f}km, "
          f"절감 {subset_pct:.0%} / 허브전체 절감 {srow['거리절감률']:.0%})")

    # ── 확대범위: 상위 N대가 방문하는 동 + 허브, 15% 여유 ──────────────
    all_xy = [dong2ll[d] for d, _ in subset_occurrences] + [(hx, hy)]
    all_x = np.array([p[0] for p in all_xy])
    all_y = np.array([p[1] for p in all_xy])
    # 서비스권역 중심으로 자르되(여백을 너무 남기지 않되), 자치구 몇 개는
    # 걸쳐 보일 만큼은 남겨 "서울 어디쯤인지" 맥락이 유지되게 25% 여유를 둔다.
    pad_x = (all_x.max() - all_x.min()) * 0.25 or 0.02
    pad_y = (all_y.max() - all_y.min()) * 0.25 or 0.02
    xlim = (all_x.min() - pad_x, all_x.max() + pad_x)
    ylim = (all_y.min() - pad_y, all_y.max() + pad_y)

    line_code = LINE_FOR_HUB[hub_name]
    line_color = LINE_COLORS[line_code]
    truck_colors = HL_COLORS.copy()
    if line_code in TRUCK5_OVERRIDE_BY_LINE:
        truck_colors[4] = TRUCK5_OVERRIDE_BY_LINE[line_code]
    if FULL_MODE:
        truck_colors = FULL_PALETTE
    LW = FULL_LW if FULL_MODE else 2.5
    MS = FULL_MS if FULL_MODE else 6

    # 패널 크기를 데이터 종횡비에 맞춘다 — 고정 figsize(16x8)를 쓰면 aspect
    # 보정 때문에 축 "안쪽"에 흰 여백이 생겨, wspace를 줄여도 좌우가 벌어져
    # 보였다. 데이터 폭/높이 비율로 패널 너비를 정하면 그 여백이 사라진다.
    PANEL_H = 8.0
    _aspect = 1 / np.cos(np.radians(37.5))
    _data_w = xlim[1] - xlim[0]
    _data_h = (ylim[1] - ylim[0]) * _aspect
    panel_w = PANEL_H * (_data_w / _data_h)
    fig, axes = plt.subplots(1, 2, figsize=(panel_w * 2 + 0.8, PANEL_H))
    fig.subplots_adjust(wspace=0.06)      # 좌우 패널을 붙여 비교가 쉽게

    # 담당 권역이 세로로 긴 허브(가락시장 등)는 패널이 좁아져서, 하단 요약
    # 문구를 고정 15pt로 쓰면 패널 폭을 넘어 좌우가 겹쳐 읽힌다.
    # 폭에 맞춰 글자 크기를 줄인다(대략 45자 x 0.6em 이 패널 폭에 들어가게).
    fs_main = float(np.clip(panel_w * 2.6, 8.5, 15))
    fs_sub = float(np.clip(panel_w * 1.9, 7.0, 10))

    for ax in axes:
        draw_admin_layers(ax, xlim, ylim)
        draw_subway_layer(ax, line_code)
        ax.set_xlim(*xlim); ax.set_ylim(*ylim)
        ax.set_aspect(1 / np.cos(np.radians(37.5)))
        ax.set_xticks([]); ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)

    # ── 분할배송으로 같은 행정동을 여러 트럭이 담당하는 경우 처리 ──────────
    #   수요가 트럭 적재량을 넘는 동은 방문 노드가 여러 개로 쪼개져 서로 다른
    #   트럭에 배정된다. 그대로 그리면 선·점이 완전히 겹쳐 나중에 그린 것만
    #   보이고, 범례엔 트럭이 5개인데 화면엔 3개만 있는 것처럼 된다.
    #   그래서 겹치는 동은 허브->동 방향의 수직 방향으로 조금씩 벌려 그린다.
    from collections import Counter
    occ_count = Counter(d for d, _ in subset_occurrences)
    _order = {}
    for d, ti in subset_occurrences:
        _order.setdefault(d, []).append(ti)
    split_dongs = {d for d, k in occ_count.items() if k > 1}
    SPREAD = (xlim[1] - xlim[0]) * 0.010     # 벌리는 폭(가로 화면폭의 1%)

    def dong_xy(dong_name, ti):
        """분할배송 동은 트럭별로 살짝 벌린 좌표를 준다(겹침 방지)."""
        x, y = dong2ll[dong_name]
        k = occ_count.get(dong_name, 1)
        if k <= 1:
            return x, y
        idx = _order[dong_name].index(ti) if ti in _order[dong_name] else 0
        vx, vy = x - hx, y - hy
        L = float(np.hypot(vx, vy)) or 1.0
        px, py = -vy / L, vx / L             # 허브->동 방향의 수직 단위벡터
        s = (idx - (k - 1) / 2) * SPREAD
        return x + px * s, y + py * s

    subway_legend = Line2D([0], [0], color=line_color, lw=5, alpha=0.35,
                           label=f"{line_code}호선 (배경, {hub_name} 소속 노선)")
    split_legend = Line2D([0], [0], color="#888888", lw=0, marker="o", markersize=7,
                          markerfacecolor="none", markeredgecolor="#888888",
                          label=f"동일 행정동 분할배송 {len(split_dongs)}곳 (겹침 방지로 벌려 표시)")

    # ── 왼쪽: 개별 왕복(방사형) — 상위 N대가 방문하는 동만, 같은 색 매칭 ──
    axL = axes[0]
    legend_L = [subway_legend]
    for dong_name, ti in subset_occurrences:
        dx, dy = dong_xy(dong_name, ti)
        c = truck_colors[ti % len(truck_colors)]
        axL.plot([hx, dx], [hy, dy], color=c, linewidth=LW, alpha=1.0, zorder=2)
        axL.scatter([dx], [dy], s=(18 if FULL_MODE else 55), color=c,
                    edgecolor="white", linewidth=0.5, zorder=3)
    if FULL_MODE:
        # 트럭이 수십 대라 개별 범례를 넣으면 그림을 덮는다 — 한 줄로 요약
        legend_L.append(Line2D([0], [0], color="#555555", lw=LW,
                               label=f"트럭 {n_shown}대 전체 (색은 구분용)"))
    else:
        for ti in range(n_shown):
            legend_L.append(Line2D([0], [0], color=truck_colors[ti % len(truck_colors)], lw=2.5,
                                   label=f"트럭{ti+1} 담당 동 (개별 왕복)"))
    if split_dongs:
        legend_L.append(split_legend)
    draw_hub_marker(axL, hx, hy, hub_name, line_color)
    axL.set_title("개별 왕복 (허브 <-> 동, 방사형)" +
                  ("" if FULL_MODE else " — 상위 5대분"),
                  fontsize=14, fontweight="bold")
    axL.legend(handles=legend_L, loc="upper left", fontsize=8, framealpha=0.9)
    axL.text(0.5, -0.06,
            (f"전체 {n_shown}대 기준: {subset_km_individual:,.1f}km" if FULL_MODE else
             f"상위 {n_shown}대 기준: {subset_km_individual:,.1f}km / {subset_trucks_individual}대(회)"),
            transform=axL.transAxes, ha="center", va="top", fontsize=fs_main, fontweight="bold")
    axL.text(0.5, -0.11,
            f"(허브 전체 {int(srow['방문건수'])}개 동 기준: {srow['기존_거리km']:,.1f}km / "
            f"{int(srow['기존_트럭대수'])}대)",
            transform=axL.transAxes, ha="center", va="top", fontsize=fs_sub, color="#555555")

    # ── 오른쪽: VRP 순회(루프) — 상위 N대만, 방문순서 번호 표기 ──────────
    axR = axes[1]
    legend_R = [subway_legend]
    for ti, r in top.iterrows():
        c = truck_colors[ti % len(truck_colors)]
        stops = r["stops_list"]
        # 좌측과 동일한 오프셋을 적용해 분할배송 구간이 겹쳐 사라지지 않게 한다
        pts = [(hx, hy)] + [dong_xy(s, ti) for s in stops if s in dong2ll] + [(hx, hy)]
        xs, ys = zip(*pts)
        axR.plot(xs, ys, color=c, linewidth=LW, alpha=1.0, zorder=4, marker="o", markersize=MS,
                markerfacecolor=c, markeredgecolor="white", markeredgewidth=0.6)
        if not FULL_MODE:
            # 정차 순서 번호는 전체 버전에서 빼야 한다 — 수백 개가 겹쳐 읽히지 않는다
            for si, s in enumerate(stops, 1):
                if s in dong2ll:
                    sx, sy = dong_xy(s, ti)
                    axR.annotate(str(si), (sx, sy), fontsize=8, fontweight="bold", color="white",
                                ha="center", va="center", zorder=6,
                                bbox=dict(boxstyle="circle,pad=0.15", fc=c, ec="white", lw=0.6))
            legend_R.append(Line2D([0], [0], color=c, lw=2.5,
                                   label=f"트럭{ti+1} ({r['n_stops']}개동, {r['경로거리_km']:.1f}km)"))
    if FULL_MODE:
        multi = int((top["n_stops"] >= 2).sum())
        legend_R.append(Line2D([0], [0], color="#555555", lw=LW,
                               label=f"트럭 {n_shown}대 전체 · 2개동 이상 순회 {multi}대"))
    if split_dongs:
        legend_R.append(split_legend)
    draw_hub_marker(axR, hx, hy, hub_name, line_color)
    axR.set_title(f"VRP 순회 (루프) — 전체 {n_total_trucks}개 경로" if FULL_MODE else
                  f"VRP 순회 (루프) — 상위 {n_shown}개 경로만 표시 (전체 {n_total_trucks}대 중)",
                 fontsize=14, fontweight="bold")
    axR.legend(handles=legend_R, loc="upper left", fontsize=8, framealpha=0.9)
    axR.text(0.5, -0.06,
            (f"전체 {n_shown}대 기준: {subset_km_vrp:,.1f}km (절감 {subset_pct:.0%})" if FULL_MODE else
             f"상위 {n_shown}대 기준: {subset_km_vrp:,.1f}km / {n_shown}대 (절감 {subset_pct:.0%}, 왼쪽 상위{n_shown}대 대비)"),
            transform=axR.transAxes, ha="center", va="top", fontsize=fs_main, fontweight="bold")
    axR.text(0.5, -0.11,
            f"(허브 전체 {int(srow['VRP_트럭대수'])}대 기준: {srow['VRP_거리km']:,.1f}km, "
            f"전체 절감률 {srow['거리절감률']:.0%} — vrp_summary.csv)",
            transform=axR.transAxes, ha="center", va="top", fontsize=fs_sub, color="#555555")

    fig.suptitle(f"{hub_name} 허브 라스트마일 — 개별 왕복(좌) vs VRP 순회(우)  [{SCENARIO_ID}]"
                 + ("  · 전체 경로" if FULL_MODE else ""),
                fontsize=16, fontweight="bold", y=1.0)
    plt.tight_layout(rect=[0, 0.05, 1, 0.97])
    out_path = f"{OUT}/{out_name or f'vrp_route_{hub_name}'}.png"
    nc.savefig_retry(plt, out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"    저장: {out_path}")


import sys
_which = sys.argv[1] if len(sys.argv) > 1 else "all"

if _which in ("all", "samples"):
    print(f"[2] 샘플 {len(SAMPLE_HUBS)}개 허브 개별 파일 생성")
    for hub_name, stub in SAMPLE_HUBS:
        draw_hub(hub_name, stub)

if _which in ("all", "lines"):
    print(f"[3] 노선별 대표 허브 {len(LINE_SAMPLE_HUBS)}장 생성")
    for line_code, hub_name in LINE_SAMPLE_HUBS:
        assert LINE_FOR_HUB[hub_name] == line_code, f"{hub_name} 노선 불일치"
        draw_hub(hub_name, None, out_name=f"vrp_route_{line_code}호선_{hub_name}")

if _which in ("all", "full"):
    # 전체 경로 버전 — 상위 5대 버전과 나란히 놓고 어느 쪽이 읽히는지 비교용
    FULL_MODE = True
    print(f"[4] 전체 경로 버전 {len(LINE_SAMPLE_HUBS)}장 생성")
    for line_code, hub_name in LINE_SAMPLE_HUBS:
        draw_hub(hub_name, None, out_name=f"vrp_route_{line_code}호선_{hub_name}_전체")
    FULL_MODE = False

print("\n완료.")
