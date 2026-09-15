"""
공용 네트워크 구축 모듈
────────────────────────────────────────────────────────────
step2.py의 Section 1~2(역 목록 + 1호선 코레일 확장 + 노선망/방향 분리 +
심도/임대료)를 하위 스크립트들이 공유하도록 뽑아낸 모듈.

지금까지 step2_representative_scenario_spec.py / step4_emission.py /
step5_hub_service_area.py / step2_elbow_hub_maps_v2.py /
step2_max_feasible_share_v2.py 가 이 보일러플레이트를 각자 복붙하고
있었는데, 1호선 확장처럼 데이터 구조가 바뀌면 5곳을 똑같이 고쳐야 해서
불일치가 생기기 쉬웠다. 한 곳에서만 정의하고 import해서 쓴다.

step2.py 자체는 이미 검증된 상태라 건드리지 않았다(재실행 비용이 커서
리팩터링 리스크를 지지 않음) — 대신 이 모듈이 step2.py와 동일한 로직을
갖도록 맞춰뒀다. step2.py의 Section 1x/2를 고치면 여기도 같이 고쳐야 한다.
"""

import os
import re
import datetime
import numpy as np
import pandas as pd
import networkx as nx

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "output_data")

# ── 파라미터 (step2.py와 동일해야 함) ────────────────────────────────
AVAILABLE_MIN = 180
TURNAROUND_MIN = 10
DEFAULT_DEPTH = 15.0
DEFAULT_FIXED = 500_000
FEE_RATE = 0.155

# 차량기지 -> (접속역, 담당 노선).
# ★ 알려진 한계 D: 기지와 접속역을 동일 노드로 처리해 기지 인입선 주행시간을
#   0분으로 가정했다. 그래서 "기점" 레이(접속역 자신)는 DIR_ROUND_TRIP=0이 되고
#   시간 소모가 회차시간(TURNAROUND_MIN x 운행횟수)만 남는다.
#   편도 3·5분을 넣어 재검증한 결과 접속역 허브(구로·수서·양천구청)는 모두
#   유지된다 — 세 레이는 왕복이 6~10분으로 늘어도 심야 180분 안에 희망
#   운행횟수(5회)를 그대로 채워 용량이 깎이지 않는다.
#   다만 인입선은 모든 레이의 왕복에 +2L로 붙고 그 왕복을 운행횟수만큼
#   반복하므로, 하역 가능시간이 (운행횟수 x 2L)만큼 줄어 나머지 허브 구성과
#   총비용(+2.5~2.8%)에는 영향이 있다. 실측값이 없어 0분으로 두었으므로 본
#   결과는 인입선 시간이 무시할 수준일 때의 해로 읽어야 한다.
#   검증: step2_diagnostics.py access_line -> diag_access_line_sensitivity.csv
DEPOTS = {
    "구로차량사업소":      ("구로",     "1"),
    "이문차량사업소":      ("신이문",   "1"),
    "군자차량기지(2호선)": ("용답",     "2"),
    "신정차량기지":        ("양천구청", "2"),
    "지축차량기지":        ("지축",     "3"),
    "수서차량기지":        ("수서",     "3"),
    "창동차량기지":        ("창동",     "4"),
}

LINE1_KORAIL_TARGETS = [
    "가산디지털단지", "개봉", "광운대", "구로", "구일", "금천구청", "남영", "노량진", "녹천",
    "대방", "도봉", "도봉산", "독산", "방학", "석계", "신길", "신도림", "신이문", "영등포",
    "오류동", "온수", "외대앞", "용산", "월계", "창동", "회기",
]
LINE1_EXCLUDE_JUNGANG = {"서빙고", "옥수", "응봉", "이촌", "한남", "왕십리"}

LINE1_EXT_CHAINS = [
    ["서울", "남영", "용산", "노량진", "대방", "신길", "영등포", "신도림", "구로"],
    ["구로", "가산디지털단지", "독산", "금천구청"],
    ["구로", "구일", "개봉", "오류동", "온수"],
    ["청량리", "회기", "외대앞", "신이문", "석계", "광운대", "월계",
     "녹천", "창동", "방학", "도봉", "도봉산"],
]

BRANCH_PARENT_OVERRIDE = {
    ("2", "용답"):  ("2", "성수"),
    ("2", "도림천"): ("2", "신도림"),
    ("1", "남영"):  ("1", "서울"),
    ("1", "구일"):  ("1", "구로"),
    ("1", "회기"):  ("1", "청량리"),
}

DEPTH_ALIAS = {"구로디지털": "구로디지털단지", "을지3가": "을지로3가",
              "을지4가": "을지로4가", "미아삼거리": "미아사거리"}

# ── 허브 후보에서 제외할 역 (서울 밖) ────────────────────────────────
#   연구 범위가 서울 426개 행정동이므로 서울 밖에 허브를 두면 라스트마일이
#   비효율적이고 범위와도 안 맞는다. 행정동.shp의 서울 폴리곤에 대해
#   전 역을 point-in-polygon으로 판정한 결과(step2_seoul_boundary_audit.py)
#   서울 밖은 지축(3호선, 경기 고양시 — 서울 경계 336m 밖) 하나뿐이었다.
#   남태령(서초구 안쪽 436m)·구파발·온수·도봉산·금천구청·독산 등 경계 근처
#   역은 모두 서울 안이라 후보로 유지한다.
#   ★ 지축은 "차량기지 접속역(기점)" 역할은 그대로 둔다 — 화물은 지축기지에서
#   출발하되 하역(허브)은 서울 안에서만 한다.
SEOUL_EXCLUDED_STATIONS = {"지축"}

LINE_COLORS = {"1": "#0052A4", "2": "#00A84D", "3": "#EF7C1C", "4": "#00A5DE"}

# ══════════════════════════════════════════════════════════
# 대표 시나리오 — 단일 정의
#   ★ 여기가 유일한 정본이다. 모든 스크립트가 nc.REP_SCENARIO를 참조하고,
#     스크립트마다 ID를 박아두지 않는다. 예전에 대표 시나리오가
#     S25 -> S39로 바뀌었을 때 그림 제목·VRP 대상·배출량 기준이 제각각
#     옛 ID를 가리켜 산출물이 어긋난 적이 있다.
#
#   허브 개수 18개 — 격자 탐색이 n<=n_max 자유 조건으로 고른 값.
#     ★ 라스트마일 편도->왕복 수정(2*dist)으로 14 -> 18로 늘었다.
#       라스트마일이 총비용의 75% 안팎인데 이를 2배로 제대로 계산하면
#       허브를 더 열어 평균 배송거리를 줄이는 쪽이 유리해지기 때문이다.
#       (편도로 두면 라스트마일이 절반으로 과소평가돼 허브 수도 과소 추정됐다.)
#       철도 주행비도 같은 수정에서 레이끝 왕복(DIR_ROUND_TRIP) 기준으로 바꿨다.
#       수정 전 결과는 output_data/backup_편도수정전/ 에 있다.
#     대표 시나리오 조합(4칸x5회, 분담률 12%) 자체는 수정 전후 동일하다.
REP_SCENARIO = dict(
    ID="S39",              # 격자 탐색 결과를 그대로 대표로 사용
    base_id="S39",
    cars=4,
    trips=5,
    share=0.12,
    n_hubs=18,
    exact=False,
    label="대표 시나리오(4칸x5회, 분담률 12%, 허브 18개)",
)
MAX_SCENARIO_ID = "SMAX"   # 환경효과 최대(실행가능 최대 분담률) 시나리오

_TT_ABBREV = {
    "지하서": "서울", "1종로": "종로3가", "종로5": "종로5가", "1동대": "동대문",
    "1지청": "청량리", "가산디": "가산디지털단지", "금천구": "금천구청",
}


def savefig_retry(plt_or_fig, path, retries=5, delay=1.5, **kwargs):
    """savefig 재시도 래퍼.

    이 환경에서 matplotlib savefig가 간헐적으로 OSError(errno 22)로 실패한다
    — 방금 쓴 PNG를 백신 실시간 검사가 잠깐 붙들고 있는 동안 다음 쓰기가
    거부되는 것으로 보인다(파일 자체는 몇 초 뒤 정상 접근됨). 실패하면
    잠깐 쉬었다 다시 시도하고, 그래도 안 되면 기존 파일을 지운 뒤 재시도한다.
    """
    import time
    last = None
    for i in range(retries):
        try:
            plt_or_fig.savefig(path, **kwargs)
            return
        except OSError as e:
            last = e
            time.sleep(delay)
            if i >= 1 and os.path.exists(path):
                try:
                    os.remove(path)      # 손상/잠긴 기존 파일 제거 후 재시도
                except OSError:
                    pass
    raise last


def clean_name(s):
    return re.sub(r"\([^)]*\)", "", str(s)).replace("역", "").strip()


def mmss_to_min(x):
    try:
        m, s = str(x).split(":")
        return int(m) + int(s) / 60.0
    except Exception:
        return 0.0


def load_stations(verbose=True):
    """stations.csv + 1호선 코레일 26개역 확장. step2.py Section 1x와 동일 순서."""
    stations = pd.read_csv(f"{OUT}/stations.csv")
    n_before = len(stations)

    master = pd.read_excel(os.path.join(BASE, "한국철도공사_도시광역철도_역사정보_20260228.xlsx"))
    master["역사명_clean"] = master["역사명"].map(clean_name)
    cand = master[master["노선명"].isin(["경부선", "경인선", "경원선"])].copy()
    cand = cand[cand["역사도로명주소"].astype(str).str.startswith("서울")]
    cand = cand[~cand["역사명_clean"].isin(LINE1_EXCLUDE_JUNGANG)]
    cand = cand[cand["역사명_clean"].isin(LINE1_KORAIL_TARGETS)].drop_duplicates(subset="역사명_clean")

    stations["노선"] = stations["노선"].astype(str)
    cd_idx = stations.index[stations["역명"] == "창동"]
    if len(cd_idx):
        stations.loc[cd_idx, "노선"] = stations.loc[cd_idx, "노선"] + "1"

    new_rows = pd.DataFrame({
        "역명": cand["역사명_clean"].values,
        "노선": "1",
        "위도": cand["역위도"].values,
        "경도": cand["역경도"].values,
    })
    new_rows = new_rows[new_rows["역명"] != "창동"]
    stations = pd.concat([stations, new_rows], ignore_index=True)
    stations["역명_clean"] = stations["역명"].map(clean_name)

    # ★ 역명 중복 경고 — 이름을 키로 쓰는 코드(name2idx, name2ll 등)가
    #   중복이 있으면 조용히 마지막 행을 집어 엉뚱한 좌표·레이·심도를 쓴다.
    #   현재 알려진 중복: 신도림(2호선 원본 + 1호선 코레일 신규). 창동은
    #   위에서 노선 문자열만 갱신해 병합했는데 신도림은 그러지 않아 생긴
    #   비대칭이다. 지금 대표 시나리오에는 신도림이 허브로 선정되지 않아
    #   영향이 없지만, 선정되면 이름으로 조회하는 하위 코드가 어긋난다.
    #   고치려면 stations 행 수가 바뀌어 dist_km.npy부터 다시 만들어야 하므로
    #   여기서는 경고만 남긴다.
    dup = stations["역명"].value_counts()
    dup = sorted(dup[dup > 1].index)
    if dup and verbose:
        print(f"    [!] 역명 중복 {len(dup)}건: {dup} — 이름으로 조회하는 코드 주의")

    if verbose:
        print(f"    역 수: {n_before} -> {len(stations)}개 (1호선 신규 {len(new_rows)}개 + 창동 노선 갱신)")
    return stations


def _load_pair_times(xlsx_path, sheet_name):
    df = pd.read_excel(xlsx_path, sheet_name=sheet_name, header=None)
    seq = []
    for idx in range(3, df.shape[0]):
        val = df.iat[idx, 0]
        if isinstance(val, str) and val.strip():
            nm = val.strip()
            seq.append((_TT_ABBREV.get(nm, nm), idx))
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
                    d += 24 * 60
                diffs.append(d)
        diffs = [d for d in diffs if 0 < d < 20]
        if len(diffs) >= 3:
            pair_times[(na, nb)] = float(np.median(diffs))
    return pair_times


def load_seg(verbose=True):
    """역간거리 CSV + 1호선 코레일 구간(시각표 기반 소요시간) 확장."""
    seg = pd.read_csv(os.path.join(BASE, "서울교통공사 역간거리 및 소요시간_240810.csv"),
                      encoding="cp949")
    seg["호선"] = seg["호선"].astype(str)
    seg = seg[seg["호선"].isin(["1", "2", "3", "4"])].reset_index(drop=True)
    seg["역명"] = seg["역명"].map(clean_name)
    seg["분"] = seg["소요시간"].map(mmss_to_min)
    seg["km"] = seg["역간거리(km)"].astype(float)

    tt = os.path.join(BASE, "202608281a045c6bb40560.xlsx")
    pt_in = _load_pair_times(tt, "경인_평일_상")
    pt_bu = _load_pair_times(tt, "경부장항_평일_상")

    def lookup(u, v):
        for pt in (pt_in, pt_bu):
            if (u, v) in pt:
                return pt[(u, v)]
            if (v, u) in pt:
                return pt[(v, u)]
        return None

    # 역간거리(km)는 시각표에 없으므로 표정속도로 환산한다 — 기존 1~4호선
    # 데이터에서 역산한 평균 표정속도(총거리/총시간)를 그대로 적용.
    avg_speed_km_per_min = seg["km"].sum() / seg["분"].sum()

    rows = []
    for chain in LINE1_EXT_CHAINS:
        for i in range(len(chain) - 1):
            u, v = chain[i], chain[i + 1]
            t = lookup(u, v)
            if t is None:
                print(f"    ! 1호선 신규 구간 소요시간 없음: {u}~{v}")
                continue
            rows.append({"호선": "1", "역명": v, "분": t, "km": t * avg_speed_km_per_min})
    seg = pd.concat([seg, pd.DataFrame(rows)], ignore_index=True)
    if verbose:
        print(f"    1호선 신규 구간 {len(rows)}개 추가 (표정속도 {avg_speed_km_per_min*60:.1f}km/h로 거리 환산)")
    return seg


def safe_key(*parts):
    s = "_".join(str(p) for p in parts)
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", s)


def build_network(stations, seg, verbose=True):
    """G_seq(시간) / G_km(거리) + 기점별 방향 분리 + rail_t/rail_km/hub_dir."""
    G_seq, G_km = nx.Graph(), nx.Graph()
    for ln in ["1", "2", "3", "4"]:
        sub = seg[seg["호선"] == ln].reset_index(drop=True)
        prev_node = None
        for _, row in sub.iterrows():
            node = (ln, row["역명"])
            G_seq.add_node(node); G_km.add_node(node)
            parent = BRANCH_PARENT_OVERRIDE.get(node, prev_node)
            if parent is not None and parent != node:
                wmin, wkm = row["분"], row["km"]
                if G_seq.has_edge(parent, node):
                    wmin = min(wmin, G_seq[parent][node]["weight"])
                if G_km.has_edge(parent, node):
                    wkm = min(wkm, G_km[parent][node]["weight"])
                G_seq.add_edge(parent, node, weight=wmin)
                G_km.add_edge(parent, node, weight=wkm)
            prev_node = node

    line_nodes = {ln: [n for n in G_seq.nodes if n[0] == ln] for ln in "1234"}
    depot_data = {}
    for depot_label, (nm, ln) in DEPOTS.items():
        onode = (ln, clean_name(nm))
        if onode not in line_nodes[ln]:
            print(f"    ! 기점 미발견: {depot_label}({nm}, {ln}호선)")
            continue
        H = G_seq.subgraph(line_nodes[ln])
        Hkm = G_km.subgraph(line_nodes[ln])
        dist_map = nx.single_source_dijkstra_path_length(H, onode, weight="weight")
        dist_map_km = nx.single_source_dijkstra_path_length(Hkm, onode, weight="weight")
        H_minus = H.copy(); H_minus.remove_node(onode)
        comps = list(nx.connected_components(H_minus))
        dir_of = {onode: safe_key(ln, depot_label, "기점")}
        for nb in H.neighbors(onode):
            comp = next(c for c in comps if nb in c)
            dkey = safe_key(ln, depot_label, nb[1])
            for n in comp:
                dir_of[n] = dkey
        depot_data[(ln, depot_label)] = {"dist": dist_map, "dist_km": dist_map_km, "dir": dir_of}

    N_ST = len(stations)
    rail_t = np.full(N_ST, np.inf)
    rail_km = np.full(N_ST, np.inf)
    hub_dir = [None] * N_ST
    hub_line = [None] * N_ST
    for j in range(N_ST):
        own_lines = [c for c in str(stations.loc[j, "노선"]) if c in "1234"]
        node_name = stations.loc[j, "역명_clean"]
        for ln in own_lines:
            node = (ln, node_name)
            for (dln, dlabel), dd in depot_data.items():
                if dln != ln:
                    continue
                if node in dd["dist"] and dd["dist"][node] < rail_t[j]:
                    rail_t[j] = dd["dist"][node]
                    rail_km[j] = dd["dist_km"].get(node, np.inf)
                    hub_dir[j] = dd["dir"][node]
                    hub_line[j] = ln

    OK = np.isfinite(rail_t)
    # 서울 밖 역은 기점 도달은 되지만 허브 후보에서는 뺀다(위 주석 참고).
    n_excluded = 0
    for j in range(N_ST):
        if OK[j] and stations.loc[j, "역명_clean"] in SEOUL_EXCLUDED_STATIONS:
            OK[j] = False
            n_excluded += 1
    DIRECTIONS = sorted(set(hub_dir[j] for j in range(N_ST) if OK[j]))

    DIR_ROUND_TRIP = {}
    for (dln, dlabel), dd in depot_data.items():
        by_dir = {}
        for node, dkey in dd["dir"].items():
            by_dir.setdefault(dkey, []).append(dd["dist"][node])
        for dkey, dists in by_dir.items():
            DIR_ROUND_TRIP[dkey] = 2 * max(dists)
    MAX_TRIPS = {dk: int(AVAILABLE_MIN // (DIR_ROUND_TRIP[dk] + TURNAROUND_MIN)) for dk in DIR_ROUND_TRIP}

    if verbose:
        print(f"    허브 후보 {OK.sum()}/{N_ST}개, 방향(레이) {len(DIRECTIONS)}개"
              + (f" (서울 밖 {n_excluded}개 제외: {', '.join(sorted(SEOUL_EXCLUDED_STATIONS))})"
                 if n_excluded else ""))
    return dict(G_seq=G_seq, G_km=G_km, depot_data=depot_data, rail_t=rail_t, rail_km=rail_km,
                hub_dir=hub_dir, hub_line=hub_line, OK=OK, DIRECTIONS=DIRECTIONS,
                DIR_ROUND_TRIP=DIR_ROUND_TRIP, MAX_TRIPS=MAX_TRIPS)


def load_depth_rent(stations, G_seq, verbose=True):
    """심도(절댓값·호선필터·별칭) + 임대료(㎡당 단가 보간 + 코레일 매출 환산)."""
    N_ST = len(stations)

    depth_df = pd.read_csv(os.path.join(BASE, "서울교통공사_역사심도정보_20241104.csv"), encoding="cp949")
    depth_df["호선"] = depth_df["호선"].astype(str)
    depth_df = depth_df[depth_df["호선"].isin(["1", "2", "3", "4"])]
    depth_df["역명_clean"] = depth_df["역명"].map(clean_name).replace(DEPTH_ALIAS)
    depth_map = depth_df.groupby("역명_clean")["정거장깊이"].median().abs()

    station_depth = stations["역명_clean"].map(depth_map).values.astype(float)
    for i, nm in enumerate(stations["역명_clean"]):
        if nm in LINE1_KORAIL_TARGETS and np.isnan(station_depth[i]):
            station_depth[i] = 0.0
    station_depth = np.where(np.isnan(station_depth), DEFAULT_DEPTH, station_depth)

    rent_df = pd.read_csv(os.path.join(BASE, "서울교통공사_지하상가 임대정보_20251231.csv"), encoding="cp949")
    rent_df["역명_clean"] = rent_df["역명"].map(clean_name)
    rent_df["단가"] = rent_df["월임대료"] / rent_df["면적(제곱미터)"]
    station_unit_price = rent_df.dropna(subset=["단가"]).groupby("역명_clean")["단가"].median()
    station_rent_direct = rent_df.dropna(subset=["월임대료"]).groupby("역명_clean")["월임대료"].median()
    net_med_unit = station_unit_price.median()
    net_med_daily = (station_rent_direct / 30.0).median()

    retail = pd.read_excel(
        os.path.join(BASE, "2026년+7월+역별+상업시설+이용고객+수(객수),업종별+매장+수,+매장당+평균매출.xls"),
        header=None)
    rd = retail.iloc[4:, [0, 10]].copy()
    rd.columns = ["역명", "매장당평균매출"]
    rd["역명"] = rd["역명"].astype(str).str.strip()
    rd = rd.dropna(subset=["매장당평균매출"])
    retail_map = dict(zip(rd["역명"], rd["매장당평균매출"]))

    korail_daily = {nm: s * FEE_RATE / 30.0 for nm, s in retail_map.items()
                    if nm in LINE1_KORAIL_TARGETS and nm not in station_rent_direct.index}
    rent_daily_direct = {nm: v / 30.0 for nm, v in station_rent_direct.items()}
    rent_daily_direct.update(korail_daily)

    def eff_unit(name):
        if name in station_unit_price.index:
            return station_unit_price[name]
        if name in rent_daily_direct:
            return rent_daily_direct[name] / net_med_daily * net_med_unit
        return None

    def nb_units(name):
        vals = []
        for node in G_seq.nodes:
            if node[1] == name:
                for nb in G_seq.neighbors(node):
                    v = eff_unit(nb[1])
                    if v is not None:
                        vals.append(v)
        return vals

    interp = {}
    for nm in sorted(set(stations["역명_clean"])):
        if nm not in rent_daily_direct:
            nbs = nb_units(nm)
            interp[nm] = max(float(np.mean(nbs)), net_med_unit) if nbs else net_med_unit

    rent_daily = np.zeros(N_ST)
    for i, nm in enumerate(stations["역명_clean"]):
        if nm in rent_daily_direct:
            rent_daily[i] = rent_daily_direct[nm]
        else:
            rent_daily[i] = net_med_daily * (interp[nm] / net_med_unit)

    if verbose:
        print(f"    심도 매칭 완료, 임대료 직접 {len(rent_daily_direct)}건 기준 "
              f"(중앙값 {np.median(rent_daily):,.0f}원/일)")
    return station_depth, rent_daily


# ══════════════════════════════════════════════════════════
# MILP 허브 입지 최적화 — 공통 solve()
#   원래 step2.py / step2_elbow_s39.py / step2_max_feasible_share_v2.py
#   세 곳에 같은 목적함수·제약이 복붙돼 있었다. 비용 모델을 고칠 때마다
#   세 곳을 똑같이 고쳐야 했고(지축 제외 때 실제로 그랬다) 어긋날 위험이
#   컸다. 여기 한 곳으로 모으고, 세 스크립트는 이 함수를 호출한다.
#
#   step2.py의 Section 0(파라미터)·1~2(데이터/노선망)는 검증된 상태라
#   그대로 두기로 했으므로, 이 함수는 전역에 의존하지 않고 필요한 값을
#   전부 인자로 받는다 — 호출자가 자기 상수·자기 배열을 넘긴다.
# ══════════════════════════════════════════════════════════
COST_DEFAULTS = dict(
    BOX_PER_CAR=1_500,      # 박스/칸
    COST_PER_KM=1_500,      # 원/km 트럭 운행
    TRUCK_CAP=200,          # 박스/대 라스트마일 탑차
    ALPHA_LABOR=270,        # 원/분 하역 인건비
    ALPHA_RAIL=700,         # 원/분 열차 운행 한계비용
    UNLOAD_RATE=450,        # 박스/분 역당 하역 처리속도
    ELEV_SPEED_MPM=30,      # m/분 엘리베이터 속도
    ELEV_CAPACITY=50,       # 박스/회 엘리베이터 1회 운반량
)
UNLIMITED_ELEV_CAP = 10_000_000.0   # 지상역(심도 0)은 엘리베이터 제약 사실상 없음


def solve_hub_location(w, cars, trips, n_max, *, dist, OK, hub_dir, rail_t,
                       DIRECTIONS, DIR_ROUND_TRIP, station_depth, rent_daily,
                       exact=False, alpha_rail=None, unload_rate=None,
                       available_min=None, turnaround_min=None,
                       cost=None, time_limit=60, gap_rel=0.02):
    """허브 입지 MILP. 반환: dict(비용 분해 + hubs + assign) 또는 None(해 없음).

    w            : 행정동별 처리 물량 (박스/일)
    cars, trips  : 화물 전용 칸 수 / "희망" 야간 운행 편성 수(방향당).
                   trips는 방향별 심야 가용시간 상한을 넘지 못하게 잘린다(eff_trips).
    n_max, exact : 허브 개수 상한(<=). exact=True면 정확히 n_max개로 고정(엘보우용).
    alpha_rail / unload_rate / available_min : 민감도 분석용 오버라이드.
    cost         : COST_DEFAULTS를 덮어쓸 원단위 dict(호출자가 자기 상수를 넘길 때).
    """
    import pulp

    c = dict(COST_DEFAULTS)
    if cost:
        c.update(cost)
    ar = c["ALPHA_RAIL"] if alpha_rail is None else alpha_rail
    ur = c["UNLOAD_RATE"] if unload_rate is None else unload_rate
    am = AVAILABLE_MIN if available_min is None else available_min
    tm = TURNAROUND_MIN if turnaround_min is None else turnaround_min

    N_ST, N_D = len(OK), len(w)

    # 방향별 "실제 실행가능한" trips — 희망 trips와 심야 가용시간 상한 중 작은 쪽
    eff_trips = {dk: min(trips, int(am // (DIR_ROUND_TRIP[dk] + tm))) for dk in DIRECTIONS}
    cap_dir = {dk: c["BOX_PER_CAR"] * cars * eff_trips[dk] for dk in DIRECTIONS}

    J = [j for j in range(N_ST) if OK[j]]
    D = range(N_D)

    p = pulp.LpProblem("hub", pulp.LpMinimize)
    h = pulp.LpVariable.dicts("h", J, cat="Binary")      # 허브 개설
    z = pulp.LpVariable.dicts("z", (J, D), 0, 1)         # 담당 비율(연속)
    q = pulp.LpVariable.dicts("q", J, 0)                 # 허브 처리량
    T = pulp.LpVariable.dicts("T", DIRECTIONS, 0)        # 방향별 "기점->최원허브" 주행시간

    # 목적함수 = 라스트마일 + 철도(주행+하역) + 심도(엘리베이터) + 고정비(임대료)
    #
    # 라스트마일은 왕복(2*dist)이다. 트럭은 배송 후 반드시 허브로 복귀하므로
    # 편도만 과금하면 절반으로 과소평가된다. 실제로 편도로 계산했을 때
    # 이 항이 함의하는 주행거리는 STEP 3 VRP 실측(6,468km/일)의 46%뿐이었고,
    # 왕복으로 고치면 91%가 되어 물리적 실제에 부합한다. STEP 3의 "개별 왕복"
    # 기준선도 2*dist라 MILP와 VRP의 기준이 통일된다.
    last = pulp.lpSum(2 * c["COST_PER_KM"] * dist[j][d] * w[d] / c["TRUCK_CAP"] * z[j][d]
                      for j in J for d in D)
    rail_travel = pulp.lpSum(ar * eff_trips[dk] * T[dk] for dk in DIRECTIONS)
    # 하역비에는 trips를 곱하지 않는다 — q[j]는 그 역의 하루 총 물량이라
    # 몇 번에 나눠 오든 총 하역 작업량은 같다. 반면 rail_travel의 trips는
    # 그대로 둔다(열차가 실제로 그만큼 왕복하므로 주행시간도 그 배수).
    rail_unload = pulp.lpSum(c["ALPHA_LABOR"] * (q[j] / ur) for j in J)
    # 엘리베이터는 적재 왕복(내려간 뒤 다시 올라와야 다음 회를 실음)이라
    # 왕복시간(2*depth/speed)을 쓴다.
    elev_round_trip = 2 * station_depth / c["ELEV_SPEED_MPM"]
    elev = pulp.lpSum(c["ALPHA_LABOR"] * elev_round_trip[j] * (q[j] / c["ELEV_CAPACITY"])
                      for j in J)
    fixed = pulp.lpSum(rent_daily[j] * h[j] for j in J)
    p += last + rail_travel + rail_unload + elev + fixed

    # 엘리베이터 처리량(시간 제약): 심야 가용시간 안에 q[j]를 전부 올려야 한다.
    # 지상역(심도 0)은 엘리베이터가 없으므로 사실상 무제한으로 둔다(0 나누기 회피).
    _safe = np.where(elev_round_trip > 0, elev_round_trip, 1.0)
    elev_cap = np.where(elev_round_trip > 0, am * c["ELEV_CAPACITY"] / _safe,
                        UNLIMITED_ELEV_CAP)

    for d in D:                                     # 수요 100% 배정
        p += pulp.lpSum(z[j][d] for j in J) == 1
    for j in J:
        p += q[j] == pulp.lpSum(w[d] * z[j][d] for d in D)
        p += q[j] <= cap_dir[hub_dir[j]] * h[j]     # 미개설 역 배정 금지
        p += q[j] <= elev_cap[j] * h[j]             # 그 역 엘리베이터 심야 처리량 상한
    for dk in DIRECTIONS:
        Jd = [j for j in J if hub_dir[j] == dk]
        if Jd:
            p += pulp.lpSum(q[j] for j in Jd) <= cap_dir[dk]
            # 심야 가용시간 제약: 주행+회차로 쓰고 남은 시간만큼만 하역 가능
            travel_time = eff_trips[dk] * (DIR_ROUND_TRIP[dk] + tm)
            remaining_min = max(0.0, am - travel_time)
            p += pulp.lpSum(q[j] for j in Jd) <= remaining_min * ur
            for j in Jd:
                # 철도 주행비 기준: 그 레이에 허브가 하나라도 열리면 열차는
                # 레이 끝(회차 지점)까지 왕복해야 하므로 DIR_ROUND_TRIP이 든다.
                # ALPHA_RAIL에 승무 인건비가 포함되는데 승무는 왕복 전체에
                # 발생하므로, 기점->최원허브 편도(rail_t)로 잡으면 과소평가된다.
                # 이 형태에서 T[dk]는 "레이 사용 여부"에 따라 0 또는
                # DIR_ROUND_TRIP이 되어, 레이당 고정비처럼 작동한다.
                #   ※ 그 결과 rail_t(기점->역 편도)는 목적함수에서 더 쓰이지
                #     않는다 — 같은 레이 안에서는 허브 위치가 철도비에 영향을
                #     주지 않는다는 뜻이고, 이는 시간 제약이 이미
                #     DIR_ROUND_TRIP을 쓰는 것과도 정합한다.
                #   ※ ALPHA_RAIL은 승무 인건비와 견인 전력을 한 계수로 묶고
                #     있다. 전력은 적재 구간에만 드는 게 맞지만 분해 비율의
                #     근거가 없어 단일 계수를 유지한다(한계로 명시).
                p += T[dk] >= DIR_ROUND_TRIP[dk] * h[j]
    if exact:
        p += pulp.lpSum(h[j] for j in J) == n_max
    else:
        p += pulp.lpSum(h[j] for j in J) <= n_max

    p.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=time_limit, gapRel=gap_rel))
    if pulp.LpStatus[p.status] != "Optimal":
        return None

    hubs = [j for j in J if h[j].value() > 0.5]
    # 행정동별 확정 배정(경성화): z는 연속변수라 소수 비율로 걸릴 수 있는데
    # 후속 VRP는 "동 하나 = 허브 한 곳"이 필요하므로 최대 비율 허브로 확정.
    assign = []
    for d in D:
        best_j, best_z = hubs[0], -1.0
        for j in hubs:
            zv = z[j][d].value() or 0.0
            if zv > best_z:
                best_z, best_j = zv, j
        assign.append(best_j)

    rt, ru = pulp.value(rail_travel), pulp.value(rail_unload)
    return {
        "Z": pulp.value(p.objective),
        "라스트마일": pulp.value(last),
        "철도_운행": rt, "철도_하역": ru, "철도": rt + ru,
        "심도": pulp.value(elev), "고정비": pulp.value(fixed),
        "hubs": hubs, "n": len(hubs), "assign": assign,
    }


def load_dong_demand(verbose=False):
    """행정동별 일평균 택배 물동량(박스/일) 배열 — dongs.csv 행 순서와 일치.

    step2 등 여러 스크립트에 같은 조인 코드가 복붙돼 있던 것을 한 곳으로 모았다.
    동명이 유일하지 않아(신사동) 이름만으로 조인하면 안 되고, 중복 이름을 먼저
    걸러 자치구 코드를 만든 뒤 "자치구 + 동명" 복합키로 붙인다.

    제출용 저장소의 scenario_assignments.csv에는 원자료 보호를 위해 수요 열을
    빼 두었다. 그 열이 필요한 스크립트(step5/step6)가 원자료로부터 되살릴 때 쓴다.
    """
    dongs = pd.read_csv(f"{OUT}/dongs.csv")
    demand = pd.read_csv(os.path.join(BASE, "반출_행정동별_일평균수요.xls"),
                         encoding="utf-8-sig")

    def _norm(s):
        s = str(s).replace("·", ".")
        s = re.sub(r"제([\d.]+동)", r"\1", s)
        return re.sub(r"^홍(\d+동)$", r"홍제\1", s)

    demand["N"] = demand["행정동"].map(_norm)
    dongs["N"] = dongs["ADM_NM"].map(_norm)
    dongs["GU_CODE"] = dongs["ADM_CD"].astype(str).str[2:5]
    dup = set(dongs["N"].value_counts()[lambda s: s > 1].index)
    uq = dongs[~dongs["N"].isin(dup)].merge(demand[["N", "자치구"]], on="N", how="inner")
    dongs["자치구"] = dongs["GU_CODE"].map(
        uq.groupby("GU_CODE")["자치구"].agg(lambda s: s.value_counts().index[0]))
    dongs = dongs.merge(demand[["자치구", "N", "일평균_전체시장"]],
                        on=["자치구", "N"], how="left")
    W = dongs["일평균_전체시장"].fillna(0).values.astype(float)
    if verbose:
        print(f"    수요 재구성: {len(W)}개 동, 합계 {W.sum():,.0f}박스/일")
    return W


def attach_demand(assign, share, verbose=False):
    """배정표에 수요 열이 없으면 원자료에서 되살린다(있으면 그대로 둔다)."""
    if "수요" in assign.columns:
        return assign
    W = load_dong_demand(verbose)
    assign = assign.copy()
    assign["수요"] = W[assign["행정동_idx"].astype(int).values] * float(share)
    if verbose:
        print(f"    (배정표에 수요 열이 없어 원자료에서 복원 — 분담률 {share:.0%})")
    return assign


def load_all(verbose=True):
    """가장 흔한 사용 패턴 — 역/노선망/심도/임대료를 한 번에."""
    if verbose:
        print("[network_common] 네트워크 구축")
    stations = load_stations(verbose)
    seg = load_seg(verbose)
    net = build_network(stations, seg, verbose)
    depth, rent = load_depth_rent(stations, net["G_seq"], verbose)
    net.update(stations=stations, seg=seg, station_depth=depth, rent_daily=rent)
    return net
