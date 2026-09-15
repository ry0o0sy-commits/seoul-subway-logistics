"""
지하철 화물수송 허브 입지 최적화 — 코드 검증용 통합본
════════════════════════════════════════════════════════════════════════════
외부 리뷰를 위해 실제 계산 로직만 한 파일로 모은 것이다. 시각화·파일 저장·
로그 출력·일회성 검증 코드는 전부 뺐다. 실행용이 아니라 **읽고 검증받기 위한
파일**이다(실제 파이프라인은 step1~step5 + network_common.py로 나뉘어 있다).

────────────────────────────────────────────────────────────────────────────
연구 목적
  서울 지하철 1~4호선의 심야 유휴 시간대에 택배 화물을 실어, 도심 진입
  화물트럭의 주행거리(VKT)와 CO2 배출을 줄이는 방안을 평가한다.
  결정할 것: (1) 어느 역을 화물 허브로 쓸 것인가 (2) 각 행정동을 어느
  허브가 담당할 것인가. 목표: 총 물류비 최소화.

물류 흐름
  차량기지(기점) --지하철--> 허브역 --엘리베이터--> 지상 --트럭--> 행정동
  즉 간선은 지하철이 대신하고, 트럭은 허브~행정동 라스트마일만 담당한다.

주요 데이터 (서울 426개 행정동, 지하철 135개역)
  · 행정동별 일평균 택배 물동량 (총 121만 박스/일)
  · 역x동 / 동x동 도로망 최단거리 (OSMnx, Dijkstra)
  · 역간 소요시간·거리 (서울교통공사) + 1호선 코레일 구간(국토부 시각표 역산)
  · 역사 심도, 지하상가 임대료, 코레일 상업시설 매출

핵심 모델링 판단 (검증 시 중점적으로 봐주면 좋은 부분)
  1. 철도 운행비를 "방향(레이)별 레이끝 왕복시간"으로 계산 — 열차가 선로를
     따라 순차 정차하므로 허브별 개별 직통이 아니고, 그 레이에 허브가 하나라도
     열리면 열차는 회차 지점까지 갔다 와야 한다. T[dir] >= DIR_ROUND_TRIP*h[j]
     로 두어 레이당 고정비처럼 작동시킨다(허브 위치는 철도비에 무영향).
     시간 제약이 이미 DIR_ROUND_TRIP을 쓰고 있어 비용/시간 기준이 일치한다.
  2. 하역비에는 운행횟수를 곱하지 않는다 — q[j]는 하루 총 물량이라 몇 번에
     나눠 오든 총 작업량은 같다. 반면 주행비에는 곱한다(실제로 그만큼 왕복).
  3. 심야 가용시간(180분) 안에 "주행+회차+하역"이 모두 끝나야 한다는 시간
     제약. 이게 실질적 병목이며, 단순 적재량 상한보다 훨씬 타이트하다.
  4. 엘리베이터 처리량도 같은 시간 제약을 받는다(왕복 기준).
  5. 라스트마일은 2단계로 계산 — MILP에서는 "개별 왕복" 근사로 입지를 정하고,
     그 배정에 대해 별도로 VRP(순회)를 풀어 실제 주행거리를 구한다.
  6. 대표 시나리오의 허브 개수 18개는 엘보우 분석(n=1~25)에서 총비용
     곡선의 최저점이다 — n=16(10.669) > n=17(10.657) > n=18(10.640)까지
     내려가다 n=19(10.644)에서 반등한다. 격자 탐색이 n<=n_max 자유 조건으로
     고른 값과도 일치한다.
     ★ 단, 이 구간은 매우 평탄하다(n=15~22가 1.5% 안). 그래서 격자 탐색의
       기본 허용오차 gapRel=0.02(2%)로는 최저점이 실행마다 튄다(한때 n=20이
       최저로 나오고 n=21에서 급등하는 곡선이 나왔다). 엘보우와 대표 시나리오
       확정은 gapRel=0.002로 조여서 푼다(step2_refine_rep.py).

알려진 한계 (검증자가 감안해야 할 부분)
  A. 배정 경성화로 인한 시간 제약 소폭 초과
     MILP의 z[j][d]는 연속변수라 한 행정동이 여러 허브에 쪼개져 배정될 수
     있다. 후속 VRP가 "동 하나 = 허브 하나"를 요구해 사후에 최대 비율
     허브로 몰아주는데(경성화), 이때 물량이 이동하면서 일부 방향이 심야
     가용시간을 넘긴다. 사후 점검 결과 451건(시나리오x방향) 중 25건에서
     초과가 확인됐다.
     — MILP 해 자체는 제약을 만족한다(모델 오류가 아니라 경성화의 대가).
     — 대표 시나리오(S39)는 시간 제약은 방향 14개 전부 충족한다(최대
       179.9분/180분, 4호선 창동차량기지->쌍문). 위 25건은 다른 시나리오
       (운행 10~15회 등)에서 나온 것.
     — 단, S39도 적재량·엘리베이터 상한은 일부 초과한다:
         적재량   불광 +2.8%, 대방 +0.7%
         엘리베이터 오금 +0.9%, 양천구청 +0.6%
       같은 경성화에서 나온 같은 성격의 초과다. 허브가 14 -> 18개로 늘며
       물량이 분산돼 이전(적재량 4건)보다 줄었다. 특히 신답 한 곳이 90개 동
       30,377박스를 떠안던 편중이 37개 동 14,698박스로 해소됐다.
     — 실운영에서는 초과분을 분할배송(다음 편성으로 이월)으로 흡수 가능한
       수준이라 보정 로직은 넣지 않고 한계로 명시한다.
  B. 코레일 구간 임대료는 실제 계약이 아니라 상업시설 매출 x 수수료율로
     환산한 추정치다(아래 4번 블록 참고).
  C. 1호선 코레일 구간의 역간 거리(km)는 시각표에서 얻은 소요시간에
     전체 노선 평균 표정속도를 곱해 환산한 값이다(직접 실측이 아님).
  D. 차량기지 인입선 시간 0분 가정
     차량기지와 접속역을 동일 노드로 처리해, 기지에서 승강장까지의 인입선
     주행시간을 0분으로 가정했다.
     — 접속역 선정의 견고성: 인입선 편도 3분·5분을 넣어 재검증한 결과
       구로·수서·양천구청은 모두 허브로 유지된다. 세 레이는 왕복이 6~10분으로
       늘어도 심야 180분 내 희망 운행횟수(5회)를 그대로 채우므로 용량이
       깎이지 않으며, 접속역의 입지 우위(수요 밀집지 근접, 지상역으로
       엘리베이터 비용 없음)를 뒤집지 못한다.
     — 영향은 허브 18개 개정으로 크게 줄었다: 인입선 시간은 접속역만이 아니라
       모든 레이의 왕복에 +2L로 붙고 이를 운행횟수만큼 반복하므로, 하역
       가능시간이 (운행횟수 x 2L)만큼 줄어든다. 허브 14개 시절에는 이 때문에
       L=0의 허브 조합이 L=3·5분에서 실행불가였으나(유효 처리량 143,155 /
       141,505박스로 수요 145,222박스에 미달), 18개로 늘며 사용 레이가 많아져
       이제는 성립한다(188,993 / 196,943박스).
       ※ 허브를 줄이는 방향의 변경을 검토할 때는 이 제약이 다시 살아난다.
     — 실측값이 없어 0분으로 두었으므로, 본 결과는 인입선 시간이 무시할 수
       있는 수준일 때의 해로 읽어야 한다.
     — 검증: output_data/diag_access_line_sensitivity.csv
       (재현: python step2_diagnostics.py access_line)
  E. ALPHA_RAIL(700원/분)이 승무 인건비와 견인 전력 증가분을 한 계수로 묶고
     있다. 승무는 왕복 전체에 발생하지만 견인 전력은 화물이 실린 구간에만
     드는데, 둘을 분해할 비율 근거가 없어 단일 계수를 유지했다.
     현재는 레이끝 왕복(DIR_ROUND_TRIP) 기준이라 승무 쪽에 맞춰져 있고
     전력분은 과대 계상된다. 철도비는 총비용의 2% 수준이라 영향은 작다.
     (편도/왕복 비교: output_data/diag_oneway_roundtrip.csv)
════════════════════════════════════════════════════════════════════════════
"""

import re
import datetime
import numpy as np
import pandas as pd
import networkx as nx
import pulp
from ortools.constraint_solver import routing_enums_pb2, pywrapcp


# ════════════════════════════════════════════════════════════════════════════
# 0. 파라미터 — 원단위와 가정값
#    ★ 검증 포인트: 이 값들의 근거가 타당한지, 결과가 여기에 얼마나 민감한지
# ════════════════════════════════════════════════════════════════════════════
BOX_PER_CAR    = 1_500   # 박스/칸 — 롤테이너 적재 기준
COST_PER_KM    = 1_500   # 원/km  — 트럭 운행(감가상각+유류+인건비)
TRUCK_CAP      = 200     # 박스/대 — 라스트마일 탑차 적재량

ALPHA_LABOR    = 270     # 원/분 — 하역 인건비
                         #   물류 상하차 시급 10,780원 x 1.5(야간 50% 가산) / 60분
ALPHA_RAIL     = 700     # 원/분 — 열차 운행 "한계비용"(승무 인건비 + 견인 전력 증가분)
                         #   심야 유휴 편성 활용 전제. 서울교통공사 수송원가
                         #   1,817원/인은 여객 만차 기준 총원가라 화물엔 과대평가.
UNLOAD_RATE    = 450     # 박스/분 — 역당 하역속도(편측 문 4개 중 3개 병렬 = 150 x 3)
AVAILABLE_MIN  = 180     # 분 — 방향당 심야 가용시간
                         #   막차~첫차 간격은 240~300분이나 안전점검·방역·선로보수
                         #   시간을 침범하지 않는 값으로 180분 채택
TURNAROUND_MIN = 10      # 분 — 종점 회차 오버헤드
ELEV_SPEED_MPM = 30      # m/분 — 엘리베이터 속도
ELEV_CAPACITY  = 50      # 박스/회 — 엘리베이터 1회 운반량 (1대 가정)
DEFAULT_DEPTH  = 15.0    # m — 심도 정보 없는 역 기본값

SHARES = [0.04, 0.08, 0.12, 0.16]   # 지하철 분담률(전체 물동량 대비)
TRIPS  = [5, 10, 15]                # 방향당 야간 운행 편성 수(희망치)
CARS   = [1, 2, 3, 4]               # 화물 전용 칸 수
N_MAX  = 30                         # 허브 개수 상한(격자 탐색용)

# 대표 시나리오 — 격자 탐색에서 단위비용이 가장 낮은 조합.
# 허브 개수 18개는 엘보우 곡선의 최저점과도 일치해 별도 고정이 필요 없다.
# ※ 이 파일은 외부 코드검증용 단일 파일이라 network_common을 import하지 않고
#   값을 그대로 적어 둔다. 정본은 network_common.REP_SCENARIO이며,
#   그쪽을 바꾸면 여기도 같이 고쳐야 한다(운영 스크립트는 전부 정본을 참조).
REP_SCENARIO = dict(cars=4, trips=5, share=0.12, n_hubs=18, exact=False)

# 차량기지 -> (접속역, 담당 노선). 화물은 여기서 출발한다.
# ★ 한계 D: 기지와 접속역을 같은 노드로 본다 — 기지 인입선 주행시간이 0분이다.
#   그래서 기점 레이(접속역 자신)는 DIR_ROUND_TRIP=0이 되고, 시간 소모가
#   회차시간(TURNAROUND_MIN x 운행횟수)만 남는다.
#   편도 3·5분을 넣어 재검증한 결과 구로·수서·양천구청은 그대로 허브로
#   유지된다(세 레이는 왕복이 6~10분이어도 운행 5회를 다 채워 용량이 안 깎임).
#   다만 인입선은 모든 레이의 왕복에 +2L로 붙어 하역 가능시간을
#   (운행횟수 x 2L)만큼 줄이므로, 나머지 허브 구성과 총비용에는 영향이 있다.
#   자세한 내용은 위 "알려진 한계 D" 참고.
DEPOTS = {
    "구로차량사업소":      ("구로",     "1"),
    "이문차량사업소":      ("신이문",   "1"),
    "군자차량기지(2호선)": ("용답",     "2"),
    "신정차량기지":        ("양천구청", "2"),
    "지축차량기지":        ("지축",     "3"),
    "수서차량기지":        ("수서",     "3"),
    "창동차량기지":        ("창동",     "4"),
}

# 연구 범위가 서울이므로 서울 밖 역은 허브 후보에서 뺀다(기점 역할은 유지).
# 전 역을 서울 경계 폴리곤에 point-in-polygon 판정한 결과 지축만 해당(336m 밖).
SEOUL_EXCLUDED_STATIONS = {"지축"}


# ════════════════════════════════════════════════════════════════════════════
# 1. 역 목록 — 서울교통공사 1~4호선 110개역 + 1호선 코레일 구간 26개역
#    서울교통공사 데이터의 1호선은 서울역~청량리 10개역(지하구간)뿐이라
#    구로·영등포·용산 등 서남부/동북부가 통째로 빠져 있었다. 한국철도공사
#    역사정보에서 서울 구간만 골라 채운다.
# ════════════════════════════════════════════════════════════════════════════
LINE1_KORAIL_TARGETS = [
    "가산디지털단지", "개봉", "광운대", "구로", "구일", "금천구청", "남영", "노량진", "녹천",
    "대방", "도봉", "도봉산", "독산", "방학", "석계", "신길", "신도림", "신이문", "영등포",
    "오류동", "온수", "외대앞", "용산", "월계", "창동", "회기",
]
# 경원선 표에 같이 실려 있지만 실제로는 경의중앙선인 역들 — 제외
LINE1_EXCLUDE = {"서빙고", "옥수", "응봉", "이촌", "한남", "왕십리"}


def clean_name(s):
    """역명 정규화 — 원천 데이터 5개가 표기가 제각각이라 통일한다.
    ('서울역' / '서울' / '서울(1)역' -> '서울')"""
    return re.sub(r"\([^)]*\)", "", str(s)).replace("역", "").strip()


def load_stations(stations_csv, korail_xlsx):
    stations = pd.read_csv(stations_csv)          # 역명, 노선, 위도, 경도
    master = pd.read_excel(korail_xlsx)
    master["역사명_clean"] = master["역사명"].map(clean_name)

    cand = master[master["노선명"].isin(["경부선", "경인선", "경원선"])]
    cand = cand[cand["역사도로명주소"].astype(str).str.startswith("서울")]   # 서울 구간만
    cand = cand[~cand["역사명_clean"].isin(LINE1_EXCLUDE)]
    cand = cand[cand["역사명_clean"].isin(LINE1_KORAIL_TARGETS)]
    cand = cand.drop_duplicates(subset="역사명_clean")

    stations["노선"] = stations["노선"].astype(str)
    # 창동은 이미 4호선 역으로 존재하는 환승역 — 새 행 대신 노선에 "1"만 추가
    cd = stations.index[stations["역명"] == "창동"]
    stations.loc[cd, "노선"] = stations.loc[cd, "노선"] + "1"

    new_rows = pd.DataFrame({"역명": cand["역사명_clean"].values, "노선": "1",
                             "위도": cand["역위도"].values, "경도": cand["역경도"].values})
    new_rows = new_rows[new_rows["역명"] != "창동"]
    stations = pd.concat([stations, new_rows], ignore_index=True)
    stations["역명_clean"] = stations["역명"].map(clean_name)
    return stations


# ════════════════════════════════════════════════════════════════════════════
# 2. 역간 소요시간 — 1호선 코레일 구간은 실제 열차 시각표에서 역산
#    서울교통공사 역간거리 CSV에 없는 구간이므로, 국토부 시각표 엑셀에서
#    인접역 통과시각 차이를 열차별로 구해 중앙값을 쓴다.
#    ★ 검증 포인트: 이상치 필터(0~20분)와 최소 표본수(3) 기준이 적절한지
# ════════════════════════════════════════════════════════════════════════════
TT_ABBREV = {   # 시각표의 축약 역명 -> 모델 역명
    "지하서": "서울", "1종로": "종로3가", "종로5": "종로5가", "1동대": "동대문",
    "1지청": "청량리", "가산디": "가산디지털단지", "금천구": "금천구청",
}


def timetable_pair_times(df):
    """시각표 시트에서 인접역 쌍의 소요시간(분) 중앙값을 뽑는다.
    구조: 0열=역명(3행부터), 1열 이후가 열차별 통과 시각(datetime.time)."""
    seq = []
    for idx in range(3, df.shape[0]):
        v = df.iat[idx, 0]
        if isinstance(v, str) and v.strip():
            nm = v.strip()
            seq.append((TT_ABBREV.get(nm, nm), idx))

    pair_times = {}
    for i in range(len(seq) - 1):
        (na, ra), (nb, rb) = seq[i], seq[i + 1]
        diffs = []
        for c in range(1, df.shape[1]):
            va, vb = df.iat[ra, c], df.iat[rb, c]
            if isinstance(va, datetime.time) and isinstance(vb, datetime.time):
                ta = va.hour * 60 + va.minute + va.second / 60
                tb = vb.hour * 60 + vb.minute + vb.second / 60
                d = tb - ta
                if d < 0:
                    d += 24 * 60          # 자정 넘어가는 경우
                diffs.append(d)
        diffs = [d for d in diffs if 0 < d < 20]      # 이상치 제거
        if len(diffs) >= 3:                            # 표본 3개 이상만 채택
            pair_times[(na, nb)] = float(np.median(diffs))
    return pair_times


# 1호선 물리적 역 순서. 구로에서 경부선/경인선 두 갈래로 갈라진다.
LINE1_EXT_CHAINS = [
    ["서울", "남영", "용산", "노량진", "대방", "신길", "영등포", "신도림", "구로"],
    ["구로", "가산디지털단지", "독산", "금천구청"],          # 경부선 방향
    ["구로", "구일", "개봉", "오류동", "온수"],              # 경인선 방향
    ["청량리", "회기", "외대앞", "신이문", "석계", "광운대", "월계",
     "녹천", "창동", "방학", "도봉", "도봉산"],              # 경원선 방향
]

# 순차 연결만으로는 지선 분기가 틀어지는 지점 — 부모를 직접 지정한다.
# (원본 CSV가 역명 등장 순서대로만 나열돼 있어 생기는 문제)
BRANCH_PARENT_OVERRIDE = {
    ("2", "용답"):   ("2", "성수"),    # 2호선 성수지선 분기점
    ("2", "도림천"): ("2", "신도림"),  # 2호선 신정지선 분기점
    ("1", "남영"):   ("1", "서울"),    # 1호선 서쪽 분기
    ("1", "구일"):   ("1", "구로"),    # 1호선 경인선 분기
    ("1", "회기"):   ("1", "청량리"),  # 1호선 동쪽 분기
}


# ════════════════════════════════════════════════════════════════════════════
# 3. 노선망 구축 + 방향(레이) 분리
#    화물열차는 자기 노선 선로만 달리므로 환승 엣지를 만들지 않는다.
#    기점 노드를 제거했을 때 갈라지는 연결요소를 그 기점의 "방향"으로 정의한다.
#    (예: 신설동이 노선 중간이면 서울역쪽/청량리쪽 2방향)
#    ★ 검증 포인트: 이 방향 분리가 "열차 1편성이 한 번에 담당하는 구간"을
#      제대로 표현하는지. 특히 2호선 순환선을 여러 기점이 나눠 맡는 처리.
# ════════════════════════════════════════════════════════════════════════════
def build_network(stations, seg):
    """seg: 호선/역명/분/km 컬럼. 반환: 방향별 주행시간, 역별 기점 도달시간 등."""
    G_time, G_dist = nx.Graph(), nx.Graph()
    for ln in ["1", "2", "3", "4"]:
        sub = seg[seg["호선"] == ln].reset_index(drop=True)
        prev = None
        for _, row in sub.iterrows():
            node = (ln, row["역명"])
            G_time.add_node(node); G_dist.add_node(node)
            parent = BRANCH_PARENT_OVERRIDE.get(node, prev)
            if parent is not None and parent != node:
                wt, wd = row["분"], row["km"]
                if G_time.has_edge(parent, node):      # 중복 등장 시 짧은 쪽
                    wt = min(wt, G_time[parent][node]["weight"])
                    wd = min(wd, G_dist[parent][node]["weight"])
                G_time.add_edge(parent, node, weight=wt)
                G_dist.add_edge(parent, node, weight=wd)
            prev = node

    line_nodes = {ln: [n for n in G_time.nodes if n[0] == ln] for ln in "1234"}
    depot_data = {}
    for label, (nm, ln) in DEPOTS.items():
        onode = (ln, clean_name(nm))
        if onode not in line_nodes[ln]:
            continue
        H = G_time.subgraph(line_nodes[ln])
        dist_t = nx.single_source_dijkstra_path_length(H, onode, weight="weight")
        dist_d = nx.single_source_dijkstra_path_length(
            G_dist.subgraph(line_nodes[ln]), onode, weight="weight")

        # 기점 제거 -> 연결요소 = 방향(레이)
        # 접속역 자신은 "기점" 레이가 되고 dist_t[onode]=0이다(위 한계 D).
        H_minus = H.copy(); H_minus.remove_node(onode)
        comps = list(nx.connected_components(H_minus))
        dir_of = {onode: f"{ln}_{label}_기점"}
        for nb in H.neighbors(onode):
            comp = next(c for c in comps if nb in c)
            dkey = f"{ln}_{label}_{nb[1]}"       # 방향 태그 = 그쪽 첫 이웃역
            for n in comp:
                dir_of[n] = dkey
        depot_data[(ln, label)] = {"t": dist_t, "d": dist_d, "dir": dir_of}

    # 역별: 자기가 속한 노선 안에서 가장 가까운 기점으로 배정
    #   (환승역은 소속 노선 각각을 따져 최단인 쪽을 택한다.
    #    다른 노선 기점에서 환승으로 빨리 닿는다고 그 노선 소속으로 보지 않는다.)
    N_ST = len(stations)
    rail_t = np.full(N_ST, np.inf)      # 기점->그 역 주행시간(분)
    rail_km = np.full(N_ST, np.inf)     # 기점->그 역 거리(km)
    hub_dir = [None] * N_ST
    for j in range(N_ST):
        own = [c for c in str(stations.loc[j, "노선"]) if c in "1234"]
        name = stations.loc[j, "역명_clean"]
        for ln in own:
            node = (ln, name)
            for (dln, label), dd in depot_data.items():
                if dln == ln and node in dd["t"] and dd["t"][node] < rail_t[j]:
                    rail_t[j] = dd["t"][node]
                    rail_km[j] = dd["d"].get(node, np.inf)
                    hub_dir[j] = dd["dir"][node]

    OK = np.isfinite(rail_t)            # 허브 후보 = 기점 도달 가능
    for j in range(N_ST):               # 서울 밖 역 제외
        if OK[j] and stations.loc[j, "역명_clean"] in SEOUL_EXCLUDED_STATIONS:
            OK[j] = False
    DIRECTIONS = sorted(set(hub_dir[j] for j in range(N_ST) if OK[j]))

    # 방향별 왕복 주행시간 = 그 방향 "물리적 끝"까지 (개설 허브가 아니라
    # 노선 끝/회차 지점까지 가야 하므로)
    DIR_ROUND_TRIP = {}
    for (dln, label), dd in depot_data.items():
        by_dir = {}
        for node, dkey in dd["dir"].items():
            by_dir.setdefault(dkey, []).append(dd["t"][node])
        for dkey, ts in by_dir.items():
            DIR_ROUND_TRIP[dkey] = 2 * max(ts)

    # 심야에 물리적으로 가능한 최대 운행횟수
    MAX_TRIPS = {dk: int(AVAILABLE_MIN // (DIR_ROUND_TRIP[dk] + TURNAROUND_MIN))
                 for dk in DIR_ROUND_TRIP}
    return dict(rail_t=rail_t, rail_km=rail_km, hub_dir=hub_dir, OK=OK,
                DIRECTIONS=DIRECTIONS, DIR_ROUND_TRIP=DIR_ROUND_TRIP,
                MAX_TRIPS=MAX_TRIPS, G_time=G_time)


# ════════════════════════════════════════════════════════════════════════════
# 4. 역별 심도 / 임대료
#    심도: "정거장깊이" = 지반고-레일면고라 고가역은 음수 -> 절댓값을 쓴다
#          (지상/지하 방향만 다를 뿐 수직 이동거리·시간은 동일하게 발생).
#    임대료: 관측값이 있으면 그대로, 없으면 인접역 ㎡당 단가로 보간한다.
#    ★ 검증 포인트: 코레일 구간은 임대 계약 데이터가 없어 상업시설 매출에
#      수수료율 15.5%를 곱해 환산했다. 이 환산이 타당한지.
#      (검증: 환산 중앙값 304만원 vs 서울교통공사 실제 중앙값 299만원)
# ════════════════════════════════════════════════════════════════════════════
DEPTH_ALIAS = {"구로디지털": "구로디지털단지", "을지3가": "을지로3가",
               "을지4가": "을지로4가", "미아삼거리": "미아사거리"}
FEE_RATE = 0.155      # 코레일유통 매출 -> 임대료 상당액 환산 수수료율


def load_depth(stations, depth_df):
    depth_df = depth_df[depth_df["호선"].astype(str).isin(["1", "2", "3", "4"])]
    depth_df = depth_df.assign(
        역명_clean=depth_df["역명"].map(clean_name).replace(DEPTH_ALIAS))
    # 호선 필터가 없으면 노원처럼 4호선(-13.69)·7호선(22.46)이 섞여
    # median이 4.39 같은 엉뚱한 값이 된다.
    depth_map = depth_df.groupby("역명_clean")["정거장깊이"].median().abs()

    d = stations["역명_clean"].map(depth_map).values.astype(float)
    for i, nm in enumerate(stations["역명_clean"]):
        if nm in LINE1_KORAIL_TARGETS and np.isnan(d[i]):
            d[i] = 0.0        # 1호선 코레일 구간은 전 구간 지상 승강장
    return np.where(np.isnan(d), DEFAULT_DEPTH, d)


def load_rent(stations, rent_df, retail_df, G_time):
    """반환: 역별 일임대료(원/일). 관측값 우선, 없으면 인접역 단가로 보간."""
    rent_df = rent_df.assign(역명_clean=rent_df["역명"].map(clean_name))
    rent_df["단가"] = rent_df["월임대료"] / rent_df["면적(제곱미터)"]
    # 월임대료가 NaN인 행(미계약 공실)은 미리 제거 — 안 그러면 그 역이
    # "행은 있는데 값은 전부 NaN"이라 관측값 있음으로 잘못 분류된다.
    unit_price = rent_df.dropna(subset=["단가"]).groupby("역명_clean")["단가"].median()
    rent_direct = rent_df.dropna(subset=["월임대료"]).groupby("역명_clean")["월임대료"].median()
    med_unit = unit_price.median()                    # ~93,310원/㎡
    med_daily = (rent_direct / 30.0).median()         # ~99,542원/일

    # 코레일 구간: 상업시설 매출 x 수수료율로 임대료 상당액 환산
    korail = {nm: sales * FEE_RATE / 30.0
              for nm, sales in retail_df.items()
              if nm in LINE1_KORAIL_TARGETS and nm not in rent_direct.index}
    daily_direct = {nm: v / 30.0 for nm, v in rent_direct.items()}
    daily_direct.update(korail)

    def eff_unit(name):
        """단가. 코레일 구간은 면적 데이터가 없어 절대 임대료의 중앙값 대비
        비율을 단가 비율로 간주하는 프록시를 쓴다(근사 — 한계)."""
        if name in unit_price.index:
            return unit_price[name]
        if name in daily_direct:
            return daily_direct[name] / med_daily * med_unit
        return None

    rent_daily = np.zeros(len(stations))
    for i, nm in enumerate(stations["역명_clean"]):
        if nm in daily_direct:
            rent_daily[i] = daily_direct[nm]
            continue
        # 보간: 선로상 인접역들의 단가 평균. 단, 노선 중앙값보다 낮게 나오면
        # 중앙값을 쓴다(보수적 — 임대료를 과소평가해 지하철을 유리하게
        # 만들지 않기 위함). 환승역은 양쪽 노선 이웃을 모두 본다.
        vals = [v for node in G_time.nodes if node[1] == nm
                for v in [eff_unit(nb[1]) for nb in G_time.neighbors(node)]
                if v is not None]
        interp = max(float(np.mean(vals)), med_unit) if vals else med_unit
        rent_daily[i] = med_daily * (interp / med_unit)
    return rent_daily


# ════════════════════════════════════════════════════════════════════════════
# 5. MILP — 허브 입지 + 행정동 배정
#
#    결정변수
#      h[j] ∈ {0,1}   역 j를 허브로 개설하는가
#      z[j][d] ∈ [0,1] 행정동 d의 물량 중 허브 j가 담당하는 비율
#      q[j] >= 0       허브 j의 하루 처리량(박스)
#      T[dir] >= 0     방향 dir에서 기점->최원 개설허브 주행시간(분)
#
#    목적함수(원/일) = 라스트마일 + 철도주행 + 철도하역 + 엘리베이터 + 고정비
#
#    ★ 검증 포인트
#      (a) T[dir] >= rail_t[j]*h[j] 로 "최원 허브"를 선형화한 것이 맞는지
#          (목적함수에서 T에 양의 계수가 걸려 있어 최소화 과정에서 자연히
#           개설된 허브 중 최댓값으로 수렴한다는 논리)
#      (b) 하역비에 trips를 곱하지 않고 주행비에만 곱한 것이 맞는지
#      (c) 시간 제약 Σq <= (가용시간 - 주행시간) x 하역속도 의 타당성
#      (d) z를 연속변수로 두고 사후에 최대비율 허브로 경성화하는 것의 영향
#          (실제로 이 때문에 확정 배정에서 일부 방향이 시간 제약을 최대
#           1.4% 초과하는 것이 확인됨 — 알려진 한계)
# ════════════════════════════════════════════════════════════════════════════
def solve_hub_location(w, cars, trips, n_max, *, dist, OK, hub_dir, rail_t,
                       DIRECTIONS, DIR_ROUND_TRIP, station_depth, rent_daily,
                       exact=False, alpha_rail=ALPHA_RAIL, unload_rate=UNLOAD_RATE,
                       available_min=AVAILABLE_MIN):
    """w: 행정동별 처리 물량(박스/일). exact=True면 허브 수를 정확히 n_max로 고정."""
    ar, ur, am = alpha_rail, unload_rate, available_min

    # 방향별 실제 운행횟수 = min(희망, 심야에 물리적으로 가능한 횟수)
    eff_trips = {dk: min(trips, int(am // (DIR_ROUND_TRIP[dk] + TURNAROUND_MIN)))
                 for dk in DIRECTIONS}
    cap_dir = {dk: BOX_PER_CAR * cars * eff_trips[dk] for dk in DIRECTIONS}

    J = [j for j in range(len(OK)) if OK[j]]     # 허브 후보
    D = range(len(w))                             # 행정동

    p = pulp.LpProblem("hub", pulp.LpMinimize)
    h = pulp.LpVariable.dicts("h", J, cat="Binary")
    z = pulp.LpVariable.dicts("z", (J, D), 0, 1)
    q = pulp.LpVariable.dicts("q", J, 0)
    T = pulp.LpVariable.dicts("T", DIRECTIONS, 0)

    # --- 목적함수 ---
    # 라스트마일: 허브<->동 왕복거리 x 물량/트럭적재량 x km당 비용
    #   트럭은 배송 후 허브로 복귀하므로 2*dist가 맞다. 편도로 두면 이 항이
    #   함의하는 주행거리가 STEP 3 VRP 실측의 46%에 그쳤고, 왕복으로 고치면
    #   91%가 되어 실제에 부합한다(VRP의 "개별 왕복" 기준선과도 통일).
    last = pulp.lpSum(2 * COST_PER_KM * dist[j][d] * w[d] / TRUCK_CAP * z[j][d]
                      for j in J for d in D)
    # 철도 주행: 방향별 레이끝 왕복시간 x 운행횟수 x 분당 한계비용
    rail_travel = pulp.lpSum(ar * eff_trips[dk] * T[dk] for dk in DIRECTIONS)
    # 철도 하역: 총 물량 / 하역속도 x 분당 인건비 (운행횟수 곱하지 않음)
    rail_unload = pulp.lpSum(ALPHA_LABOR * (q[j] / ur) for j in J)
    # 엘리베이터: 왕복시간(2*심도/속도) x 운반 횟수(q/1회 운반량) x 분당 인건비
    elev_rt = 2 * station_depth / ELEV_SPEED_MPM
    elev = pulp.lpSum(ALPHA_LABOR * elev_rt[j] * (q[j] / ELEV_CAPACITY) for j in J)
    # 고정비: 허브 개설 시 그 역의 일임대료
    fixed = pulp.lpSum(rent_daily[j] * h[j] for j in J)
    p += last + rail_travel + rail_unload + elev + fixed

    # 엘리베이터 처리량 상한 — 지상역(심도 0)은 엘리베이터가 없으므로 무제한
    safe = np.where(elev_rt > 0, elev_rt, 1.0)
    elev_cap = np.where(elev_rt > 0, am * ELEV_CAPACITY / safe, 1e7)

    # --- 제약 ---
    for d in D:
        p += pulp.lpSum(z[j][d] for j in J) == 1          # 수요 100% 배정
    for j in J:
        p += q[j] == pulp.lpSum(w[d] * z[j][d] for d in D)
        p += q[j] <= cap_dir[hub_dir[j]] * h[j]           # 미개설 역 배정 금지
        p += q[j] <= elev_cap[j] * h[j]                   # 엘리베이터 처리량
    for dk in DIRECTIONS:
        Jd = [j for j in J if hub_dir[j] == dk]
        if not Jd:
            continue
        p += pulp.lpSum(q[j] for j in Jd) <= cap_dir[dk]  # 열차 적재량 상한
        # 시간 제약: 주행+회차로 쓰고 남은 시간만큼만 하역 가능 (실질 병목)
        travel = eff_trips[dk] * (DIR_ROUND_TRIP[dk] + TURNAROUND_MIN)
        p += pulp.lpSum(q[j] for j in Jd) <= max(0.0, am - travel) * ur
        for j in Jd:
            # 그 레이에 허브가 하나라도 열리면 열차는 레이 끝(회차 지점)까지
            # 왕복해야 한다. ALPHA_RAIL에 승무 인건비가 들어 있고 승무는 왕복
            # 전체에 발생하므로, 기점->최원허브 편도(rail_t)로 잡으면 과소평가다.
            # T[dk]는 레이 사용 여부에 따라 0 또는 DIR_ROUND_TRIP이 되어
            # 레이당 고정비처럼 작동한다(같은 레이 안 허브 위치는 철도비에
            # 영향을 주지 않으며, 이는 시간 제약과도 정합한다).
            p += T[dk] >= DIR_ROUND_TRIP[dk] * h[j]
    p += (pulp.lpSum(h[j] for j in J) == n_max) if exact else \
         (pulp.lpSum(h[j] for j in J) <= n_max)

    p.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=60, gapRel=0.02))
    if pulp.LpStatus[p.status] != "Optimal":
        return None

    hubs = [j for j in J if h[j].value() > 0.5]
    # 배정 경성화: z는 연속이라 한 동이 여러 허브에 쪼개질 수 있는데,
    # 후속 VRP는 "동 하나 = 허브 한 곳"이 필요하므로 최대 비율 허브로 확정.
    # ★ 이 단계에서 물량이 이동해 시간 제약을 소폭 넘길 수 있다(알려진 한계).
    assign = [max(hubs, key=lambda j: z[j][d].value() or 0.0) for d in D]

    return {"Z": pulp.value(p.objective), "hubs": hubs, "n": len(hubs),
            "assign": assign,
            "라스트마일": pulp.value(last), "철도_운행": pulp.value(rail_travel),
            "철도_하역": pulp.value(rail_unload), "심도": pulp.value(elev),
            "고정비": pulp.value(fixed)}


def run_scenarios(W, dist, net, station_depth, rent_daily):
    """분담률 x 운행횟수 x 칸수 격자를 전부 풀고 단위비용 최소 조합을 찾는다."""
    results = []
    for cars in CARS:
        for trips in TRIPS:
            # 총 수송능력 = Σ(방향별 칸당 적재량 x 실제 운행횟수)
            cap_tot = sum(BOX_PER_CAR * cars * min(trips, net["MAX_TRIPS"][dk])
                          for dk in net["DIRECTIONS"])
            for share in SHARES:
                w = W * share
                if w.sum() > cap_tot:        # 적재량만으로도 불가능
                    continue
                r = solve_hub_location(
                    w, cars, trips, N_MAX,
                    dist=dist, OK=net["OK"], hub_dir=net["hub_dir"],
                    rail_t=net["rail_t"], DIRECTIONS=net["DIRECTIONS"],
                    DIR_ROUND_TRIP=net["DIR_ROUND_TRIP"],
                    station_depth=station_depth, rent_daily=rent_daily)
                if r is None:                # 시간 제약 등으로 해 없음
                    continue
                results.append(dict(칸=cars, 운행=trips, 분담률=share,
                                    필요물량=w.sum(), n=r["n"], 총비용=r["Z"],
                                    단위비용=r["Z"] / w.sum(), hubs=r["hubs"],
                                    assign=r["assign"]))
    return results


# ════════════════════════════════════════════════════════════════════════════
# 6. VRP — 라스트마일 실제 주행거리 재계산 (2단계 분리)
#    MILP는 라스트마일을 "허브<->동 개별 왕복"으로 근사한다. 실제로는 트럭
#    한 대가 여러 동을 순회하므로 거리가 과대평가된다. MILP 안에 VRP를 넣으면
#    계산량이 감당이 안 돼, 확정된 배정에 대해서만 사후에 VRP를 푼다.
#
#    분할 배송 처리: 행정동 수요가 트럭 적재량(200박스)을 넘는 경우가 많아
#    "동 하나를 트럭 하나가 담당"이 성립하지 않는다. 그래서 수요를 200박스
#    단위 방문 노드로 쪼갠다(같은 위치, 거리 0). 방문 노드 하나는 항상 트럭
#    하나가 온전히 담당하므로 분할 배송 없음 요구는 유지된다.
#
#    ★ 검증 포인트: 비교 기준. MILP도 VRP도 이제 왕복(2*dist) 기준이라
#      계수가 통일됐다(2026-09 개정 전에는 MILP만 편도였다). 방문지가
#      1곳뿐이면 두 방식이 정확히 같은 값이 나와야 정상이다.
#      대표 시나리오에서 MILP 라스트마일 항이 함의하는 거리는 5,381km로
#      VRP 실측 5,929km의 90.8%다(개정 전에는 46%였다). 남는 9%는 VRP
#      순회로 줄어드는 몫과, MILP가 물량을 분수로 싣는 반면 VRP는 방문노드를
#      올림(ceil)해 나누는 차이에서 온다.
# ════════════════════════════════════════════════════════════════════════════
def split_visits(dong_indices, demands, cap=TRUCK_CAP):
    """수요가 트럭 적재량을 넘는 동을 여러 방문 노드로 쪼갠다."""
    visits = []
    for d, w in zip(dong_indices, demands):
        remaining = w
        while remaining > 1e-6:
            take = min(remaining, cap)
            visits.append((d, take))
            remaining -= take
    return visits


def solve_vrp_for_hub(hub_idx, visits, dist, dong_dist, time_limit=45):
    """허브 하나의 CVRP. 반환: (트럭별 경로, 총 주행거리 km)"""
    n_visits = len(visits)
    n_nodes = n_visits + 1                    # 0번 = 허브(디포)

    # 거리행렬(m, 정수) — 허브<->동은 역x동 행렬, 동<->동은 동x동 행렬
    M = np.zeros((n_nodes, n_nodes), dtype=np.int64)
    for i, (di, _) in enumerate(visits):
        M[0, i + 1] = M[i + 1, 0] = round(dist[hub_idx, di] * 1000)
    for i, (di, _) in enumerate(visits):
        for j, (dj, _) in enumerate(visits):
            if i != j:
                M[i + 1, j + 1] = round(dong_dist[di, dj] * 1000) if di != dj else 0

    demands = [0] + [round(v[1]) for v in visits]
    min_vehicles = max(1, -(-sum(demands) // TRUCK_CAP))     # ceil

    def try_solve(num_vehicles):
        mgr = pywrapcp.RoutingIndexManager(n_nodes, num_vehicles, 0)
        routing = pywrapcp.RoutingModel(mgr)
        transit = routing.RegisterTransitCallback(
            lambda a, b: int(M[mgr.IndexToNode(a), mgr.IndexToNode(b)]))
        routing.SetArcCostEvaluatorOfAllVehicles(transit)
        dem = routing.RegisterUnaryTransitCallback(
            lambda a: demands[mgr.IndexToNode(a)])
        routing.AddDimensionWithVehicleCapacity(
            dem, 0, [TRUCK_CAP] * num_vehicles, True, "Capacity")
        params = pywrapcp.DefaultRoutingSearchParameters()
        params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        params.time_limit.FromSeconds(time_limit)
        return mgr, routing, routing.SolveWithParameters(params)

    # 최소 대수 + 여유부터 시도, 실패하면 "방문 1개당 트럭 1대"(항상 실행가능)
    buffer = max(5, int(min_vehicles * 0.3))
    mgr, routing, sol = try_solve(min(min_vehicles + buffer, n_visits))
    if sol is None:
        mgr, routing, sol = try_solve(n_visits)
    if sol is None:
        return None, None

    routes, total_km = [], 0.0
    for v in range(routing.vehicles()):
        idx = routing.Start(v)
        if routing.IsEnd(sol.Value(routing.NextVar(idx))):
            continue                                    # 미사용 차량
        nodes, meters = [], 0
        while not routing.IsEnd(idx):
            node = mgr.IndexToNode(idx)
            if node != 0:
                nodes.append(visits[node - 1][0])
            nxt = sol.Value(routing.NextVar(idx))
            meters += routing.GetArcCostForVehicle(idx, nxt, v)
            idx = nxt
        routes.append((nodes, meters / 1000.0))
        total_km += meters / 1000.0
    return routes, total_km


def recompute_lastmile(scenario, dist, dong_dist, demands_by_dong):
    """확정 배정에 대해 허브별 VRP를 풀어 개별왕복 대비 절감을 구한다."""
    out = []
    for hub_idx in sorted(set(scenario["assign"])):
        dongs = [d for d, j in enumerate(scenario["assign"]) if j == hub_idx]
        visits = split_visits(dongs, [demands_by_dong[d] for d in dongs])
        baseline_km = sum(2 * dist[hub_idx, d] for d, _ in visits)   # 개별 왕복
        routes, vrp_km = solve_vrp_for_hub(hub_idx, visits, dist, dong_dist)
        if routes is None:
            routes, vrp_km = [([d], 2 * dist[hub_idx, d]) for d, _ in visits], baseline_km
        out.append(dict(허브=hub_idx, 방문건수=len(visits),
                        기존_거리km=baseline_km, 기존_트럭대수=len(visits),
                        VRP_거리km=vrp_km, VRP_트럭대수=len(routes),
                        거리절감률=1 - vrp_km / baseline_km if baseline_km else 0.0))
    return out


# ════════════════════════════════════════════════════════════════════════════
# 7. 전체 흐름 (실제로는 step1~step5 스크립트로 나뉘어 실행된다)
# ════════════════════════════════════════════════════════════════════════════
def main(paths):
    # (1) 역 목록 — 서울교통공사 110개 + 1호선 코레일 26개
    stations = load_stations(paths["stations_csv"], paths["korail_xlsx"])

    # (2) 역간 소요시간/거리 — 기존 CSV + 1호선은 시각표에서 역산
    seg = pd.read_csv(paths["seg_csv"], encoding="cp949")
    seg = seg[seg["호선"].astype(str).isin(["1", "2", "3", "4"])].copy()
    seg["역명"] = seg["역명"].map(clean_name)
    seg["분"] = seg["소요시간"].map(
        lambda x: int(str(x).split(":")[0]) + int(str(x).split(":")[1]) / 60.0)
    seg["km"] = seg["역간거리(km)"].astype(float)

    pt = {}
    for sheet in ["경인_평일_상", "경부장항_평일_상"]:
        pt.update(timetable_pair_times(
            pd.read_excel(paths["timetable_xlsx"], sheet_name=sheet, header=None)))
    avg_speed = seg["km"].sum() / seg["분"].sum()      # 거리 환산용 표정속도

    rows = []
    for chain in LINE1_EXT_CHAINS:
        for u, v in zip(chain, chain[1:]):
            t = pt.get((u, v)) or pt.get((v, u))
            if t is not None:
                rows.append({"호선": "1", "역명": v, "분": t, "km": t * avg_speed})
    seg = pd.concat([seg, pd.DataFrame(rows)], ignore_index=True)

    # (3) 노선망 + 방향 분리
    net = build_network(stations, seg)

    # (4) 심도 / 임대료
    station_depth = load_depth(stations, pd.read_csv(paths["depth_csv"], encoding="cp949"))
    retail = pd.read_excel(paths["retail_xls"], header=None).iloc[4:, [0, 10]]
    retail = dict(zip(retail.iloc[:, 0].astype(str).str.strip(), retail.iloc[:, 1]))
    rent_daily = load_rent(stations, pd.read_csv(paths["rent_csv"], encoding="cp949"),
                           retail, net["G_time"])

    # (5) 수요·거리행렬
    W = paths["demand_by_dong"]                # 행정동별 일평균 물동량
    dist = np.load(paths["dist_km_npy"])       # [역 x 동] 도로망 최단거리
    dong_dist = np.load(paths["dong_dist_npy"])  # [동 x 동]

    # (6) MILP 시나리오 격자 -> 단위비용 최소 조합이 대표 시나리오
    #     (4칸x5회, 분담률 12%, 허브 18개 — 엘보우 곡선 최저점과 일치)
    results = run_scenarios(W, dist, net, station_depth, rent_daily)
    rep = min(results, key=lambda r: r["단위비용"])

    # (7) 확정된 배정의 라스트마일을 VRP로 재계산
    lastmile = recompute_lastmile(rep, dist, dong_dist, W * rep["분담률"])

    return rep, lastmile
