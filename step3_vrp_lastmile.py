"""
STEP 3. VRP 기반 라스트마일 재계산 (사후 평가, 2단계 분리 방식)
────────────────────────────────────────────────────────────
STEP 2의 MILP는 라스트마일 비용을 "허브 -> 행정동 개별 왕복"으로 근사한다
(2 * COST_PER_KM * dist[hub][dong] * 물량/TRUCK_CAP). 실제로는 트럭 한 대가
허브에서 출발해 여러 행정동을 순회하고 복귀하므로 이 근사는 거리를
과대평가한다. MILP 안에 VRP를 통합하면 계산량이 감당이 안 되므로,
여기서는 최적화 자체는 건드리지 않고(2단계 분리):

  1단계(기완료, step2.py) : MILP로 허브 입지·행정동 배정 확정
  2단계(이 스크립트)       : 확정된 배정에 대해서만 허브별로 OR-Tools VRP를
                              돌려 실제 순회거리를 구하고, "개별 왕복" 방식과
                              비교한다.

[분할 배송 처리]
"한 행정동은 한 트럭이 담당"이 요구되지만, 실제 행정동 수요(최대 1.4만
박스/일)는 트럭 1대 용량(TRUCK_CAP=200박스)을 훨씬 넘는 경우가 많다.
그래서 "행정동 하나 전체를 트럭 1대가 담당"이 아니라 "트럭 1회 방문은
반드시 그 행정동 수요 중 최대 TRUCK_CAP만큼을 통째로 싣는다"로 해석해,
수요가 TRUCK_CAP을 넘는 행정동은 같은 위치(거리 0)의 방문 노드 여러 개로
쪼갠다. 방문 노드 하나는 항상 트럭 1대가 온전히 담당하므로 "분할 배송
없음" 요구를 유지하면서도 대용량 수요를 표현할 수 있다.

[비교 방식에 대한 주의]
2026-09 개정으로 STEP 2의 목적함수도 왕복(2*dist)이 됐다. 이제 STEP 2와
이 스크립트가 같은 계수를 쓰므로 두 값을 직접 비교할 수 있다.
(개정 전에는 STEP 2만 편도라, 방문지 1곳짜리 경로조차 VRP는 2*dist인데
 기존 방식은 1*dist여서 "순회해도 무조건 더 나쁨"으로 보이는 착시가 있었다.)

여기서 "개별 왕복" 기준선은 방문 노드 단위로 2*dist를 적용한다 —
방문지가 1곳뿐이면 VRP와 정확히 같은 값이 나와야 정상이고(=순회 이득 0%),
방문지가 여러 곳일 때만 절감이 나와야 한다는 sanity check다.

STEP 2의 라스트마일 항과는 아직 완전히 같지는 않다. MILP는 물량을 분수로
싣지만(w[d]/TRUCK_CAP) VRP는 방문노드를 올림(ceil)해 나누기 때문이다.
대표 시나리오 기준 MILP 라스트마일이 함의하는 거리 5,381km는
VRP 실측 5,929km의 90.8%다(개정 전에는 46%였다).

[출력]
  vrp_hub_routes.csv   : 허브별 트럭별 순회 순서, 경로거리, 적재량
  vrp_summary.csv      : 허브별 기존 방식 vs VRP 거리·트럭대수·절감률
  콘솔                  : 전체 절감률, 재계산된 라스트마일 비용/단위비용
"""

import os
import sys
# ★ ortools를 numpy/pandas보다 먼저 import 해야 한다. pandas가 내부적으로
#   pyarrow를 불러오는데, pyarrow가 번들한 re2/libprotobuf DLL이 ortools가
#   쓰는 동명의 DLL과 충돌해 (WinError 127) ortools import가 깨지는 문제가
#   Windows에서 발생한다. import 순서를 바꿔 ortools의 DLL이 먼저 로드되게
#   해서 우회한다.
from ortools.constraint_solver import routing_enums_pb2, pywrapcp
import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
OUT  = os.path.join(BASE, "output_data")

# 명령줄 인자로 시나리오 ID를 바꿀 수 있게 함 (예: python step3_vrp_lastmile.py SMAX)
# — 여러 시나리오(S25, SMAX 등)를 비교하려면 이 스크립트를 시나리오별로 반복
# 실행해야 하는데, 매번 SCENARIO_ID를 코드에서 고쳐 쓰지 않아도 되게 한다.
#   기본값은 network_common.REP_SCENARIO(대표 시나리오) — 스크립트마다 ID를
#   박아두면 대표 시나리오가 바뀔 때 산출물이 어긋나므로 한 곳만 본다.
def _default_scenario_id():
    import network_common as _nc
    return _nc.REP_SCENARIO["ID"]

SCENARIO_ID = sys.argv[1] if len(sys.argv) > 1 else _default_scenario_id()
TRUCK_CAP   = 200       # 박스/대 — step2.py의 TRUCK_CAP과 반드시 일치시킬 것
COST_PER_KM = 1_500     # 원/km — step2.py의 COST_PER_KM과 반드시 일치시킬 것
TIME_LIMIT_SEC = 45     # 허브 1개당 VRP 탐색 시간 제한 (근사해 허용)

# ══════════════════════════════════════════════════════════
# 1. 데이터 로드
# ══════════════════════════════════════════════════════════
print(f"[1] 데이터 로드 — 시나리오 {SCENARIO_ID}")
# ★ stations.csv를 직접 읽으면 안 된다 — 1호선 코레일 구간 26개역이 빠진
#   110행짜리 원본이라, scenario_assignments.csv의 허브 인덱스(최대 134)를
#   찾지 못해 KeyError가 난다. network_common이 확장한 135행 기준을 쓴다.
#   (network_common은 pandas를 import하므로 반드시 ortools 뒤에서 import)
import network_common as nc
stations = nc.load_stations(verbose=False)
dongs    = pd.read_csv(f"{OUT}/dongs.csv")
dist     = np.load(f"{OUT}/dist_km.npy")           # [역 x 동] km
dong_dist = np.load(f"{OUT}/dong_dist_km.npy")      # [동 x 동] km

assign_all = pd.read_csv(f"{OUT}/scenario_assignments.csv")
assign = assign_all[assign_all["ID"] == SCENARIO_ID].copy()
if len(assign) == 0:
    raise ValueError(f"scenario_assignments.csv에 {SCENARIO_ID} 없음 — step2.py를 먼저 실행하세요.")

results = pd.read_csv(f"{OUT}/scenario_results.csv")
srow = results[results["ID"] == SCENARIO_ID].iloc[0]
print(f"    {SCENARIO_ID}: 허브 {int(srow['n'])}개, 기존 총비용 {srow['총비용']:,.0f}원/일, "
      f"기존 단위비용 {srow['단위비용']:.0f}원/박스")
print(f"    행정동 배정 {len(assign)}건, 허브 수 {assign['허브_idx'].nunique()}개")


# ══════════════════════════════════════════════════════════
# 2. 허브별 VRP
# ══════════════════════════════════════════════════════════
def split_visits(dong_idx_list, demand_list, cap):
    """수요가 트럭 용량을 넘는 행정동을 같은 위치(거리 0)의 방문 노드 여러
    개로 쪼갠다. 방문 노드 하나 = 트럭 1대가 온전히 담당하는 1회 방문."""
    visits = []   # (행정동 idx, 이 방문의 적재량)
    for d, w in zip(dong_idx_list, demand_list):
        remaining = w
        while remaining > 1e-6:
            take = min(remaining, cap)
            visits.append((d, take))
            remaining -= take
    return visits


def solve_vrp_for_hub(hub_station_idx, visits):
    """visits: [(행정동idx, 적재량), ...]. 반환: (트럭별 경로 리스트, 총거리km)"""
    n_visits = len(visits)
    n_nodes  = n_visits + 1                     # 0번 = 허브(디포)

    # 거리행렬(m, 정수) — 허브<->동은 dist_km.npy, 동<->동은 dong_dist_km.npy
    dist_m = np.zeros((n_nodes, n_nodes), dtype=np.int64)
    for i in range(n_visits):
        di = visits[i][0]
        dist_m[0, i + 1] = round(dist[hub_station_idx, di] * 1000)
        dist_m[i + 1, 0] = dist_m[0, i + 1]
    for i in range(n_visits):
        di = visits[i][0]
        for j in range(n_visits):
            if i == j:
                continue
            dj = visits[j][0]
            dist_m[i + 1, j + 1] = round(dong_dist[di, dj] * 1000) if di != dj else 0

    demands = [0] + [round(v[1]) for v in visits]
    total_demand = sum(demands)
    min_vehicles = max(1, -(-total_demand // TRUCK_CAP))   # ceil

    def try_solve(num_vehicles, time_limit_sec):
        manager = pywrapcp.RoutingIndexManager(n_nodes, num_vehicles, 0)
        routing = pywrapcp.RoutingModel(manager)

        def dist_cb(from_i, to_i):
            return int(dist_m[manager.IndexToNode(from_i), manager.IndexToNode(to_i)])
        transit_idx = routing.RegisterTransitCallback(dist_cb)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_idx)

        def demand_cb(from_i):
            return demands[manager.IndexToNode(from_i)]
        demand_idx = routing.RegisterUnaryTransitCallback(demand_cb)
        routing.AddDimensionWithVehicleCapacity(
            demand_idx, 0, [TRUCK_CAP] * num_vehicles, True, "Capacity")

        params = pywrapcp.DefaultRoutingSearchParameters()
        params.first_solution_strategy = (
            routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC)
        params.local_search_metaheuristic = (
            routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH)
        params.time_limit.FromSeconds(time_limit_sec)

        sol = routing.SolveWithParameters(params)
        return manager, routing, sol

    # 최소 대수 근방(여유 buffer)부터 시도, 안 되면 "방문노드 1개=트럭 1대"인
    # 항상 실행가능한 상한으로 재시도한다.
    buffer = max(5, int(min_vehicles * 0.3))
    manager, routing, sol = try_solve(min(min_vehicles + buffer, n_visits), TIME_LIMIT_SEC)
    if sol is None:
        manager, routing, sol = try_solve(n_visits, TIME_LIMIT_SEC)
    if sol is None:
        return None, None

    routes, total_km = [], 0.0
    for v in range(routing.vehicles()):
        idx = routing.Start(v)
        if routing.IsEnd(sol.Value(routing.NextVar(idx))):
            continue                                        # 빈 차량(미사용)
        route_nodes, route_m = [], 0
        while not routing.IsEnd(idx):
            node = manager.IndexToNode(idx)
            if node != 0:
                route_nodes.append(visits[node - 1][0])
            nxt = sol.Value(routing.NextVar(idx))
            route_m += routing.GetArcCostForVehicle(idx, nxt, v)
            idx = nxt
        routes.append((route_nodes, route_m / 1000.0))
        total_km += route_m / 1000.0
    return routes, total_km


hub_ids = sorted(assign["허브_idx"].unique())
print(f"[2] 허브 {len(hub_ids)}개 VRP 순회 계산 (허브당 최대 {TIME_LIMIT_SEC}초)")

route_rows, summary_rows = [], []
for hi, hub_j in enumerate(hub_ids, 1):
    sub = assign[assign["허브_idx"] == hub_j]
    hub_name = stations.loc[hub_j, "역명"]
    visits = split_visits(sub["행정동_idx"].tolist(), sub["수요"].tolist(), TRUCK_CAP)

    # 기존 방식(개별 왕복) — 방문 노드 하나마다 허브<->동 왕복
    baseline_km = sum(2 * dist[hub_j, d] for d, _ in visits)
    n_baseline_trucks = len(visits)

    routes, vrp_km = solve_vrp_for_hub(hub_j, visits)
    if routes is None:
        print(f"  [{hi}/{len(hub_ids)}] {hub_name}: 해 없음 — 기존 방식 값으로 대체")
        vrp_km = baseline_km
        routes = [([d], 2 * dist[hub_j, d]) for d, _ in visits]

    n_vrp_trucks = len(routes)
    reduction = 1 - vrp_km / baseline_km if baseline_km > 0 else 0.0
    print(f"  [{hi}/{len(hub_ids)}] {hub_name:6s} | 방문 {len(visits):3d}건 | "
          f"기존 {baseline_km:8.1f}km({n_baseline_trucks:3d}대) -> "
          f"VRP {vrp_km:8.1f}km({n_vrp_trucks:3d}대) | 절감 {reduction:.0%}")

    for t, (route_dongs, route_km) in enumerate(routes, 1):
        route_rows.append(dict(
            ID=SCENARIO_ID, 허브=hub_name, 트럭번호=t,
            방문순서=" -> ".join(dongs.loc[d, "ADM_NM"] for d in route_dongs),
            방문행정동수=len(route_dongs), 경로거리_km=round(route_km, 2)))

    summary_rows.append(dict(
        ID=SCENARIO_ID, 허브=hub_name,
        방문건수=len(visits),
        기존_거리km=round(baseline_km, 1), 기존_트럭대수=n_baseline_trucks,
        VRP_거리km=round(vrp_km, 1), VRP_트럭대수=n_vrp_trucks,
        거리절감률=round(reduction, 4),
        기존_비용원=round(baseline_km * COST_PER_KM),
        VRP_비용원=round(vrp_km * COST_PER_KM),
    ))

# ── merge-save: 다른 시나리오 ID의 기존 행은 보존하고 이 SCENARIO_ID 행만 교체 ──
route_df = pd.DataFrame(route_rows)
routes_path = f"{OUT}/vrp_hub_routes.csv"
if os.path.exists(routes_path):
    old_routes = pd.read_csv(routes_path)
    old_routes = old_routes[old_routes["ID"] != SCENARIO_ID]
    route_df = pd.concat([old_routes, route_df], ignore_index=True)
route_df.to_csv(routes_path, index=False, encoding="utf-8-sig")

summary_df = pd.DataFrame(summary_rows)
summary_path = f"{OUT}/vrp_summary.csv"
summary_save = summary_df
if os.path.exists(summary_path):
    old_summary = pd.read_csv(summary_path)
    old_summary = old_summary[old_summary["ID"] != SCENARIO_ID]
    summary_save = pd.concat([old_summary, summary_df], ignore_index=True)
summary_save.to_csv(summary_path, index=False, encoding="utf-8-sig")


# ══════════════════════════════════════════════════════════
# 3. 전체 요약 — MILP 라스트마일 항 / 개별 왕복 기준선 / VRP 순회 (모두 왕복)
# ══════════════════════════════════════════════════════════
total_baseline_km  = summary_df["기존_거리km"].sum()
total_vrp_km        = summary_df["VRP_거리km"].sum()
total_baseline_cost = summary_df["기존_비용원"].sum()
total_vrp_cost       = summary_df["VRP_비용원"].sum()
total_reduction      = 1 - total_vrp_km / total_baseline_km if total_baseline_km > 0 else 0.0
total_demand         = assign["수요"].sum()

원래_총비용   = srow["총비용"]
원래_라스트마일_절대 = srow["총비용"] * srow["라스트마일비중"]
새_총비용     = 원래_총비용 - 원래_라스트마일_절대 + total_vrp_cost
새_단위비용   = 새_총비용 / total_demand

print("\n" + "=" * 80)
print(f"[{SCENARIO_ID}] VRP 라스트마일 재계산 결과")
print(f"  방문(트럭 1회분) 총 {len(assign)}개 행정동 -> {int(summary_df['기존_트럭대수'].sum())}건 방문노드")
print(f"  총 주행거리 — 개별 왕복: {total_baseline_km:,.0f}km  ->  VRP 순회: {total_vrp_km:,.0f}km "
      f"(절감 {total_reduction:.1%})")
print(f"  트럭 대수   — 개별 왕복: {summary_df['기존_트럭대수'].sum():,}대  ->  VRP 순회: "
      f"{summary_df['VRP_트럭대수'].sum():,}대")
print(f"  라스트마일 비용(왕복 기준) — 개별 왕복: {total_baseline_cost:,.0f}원/일  ->  "
      f"VRP 순회: {total_vrp_cost:,.0f}원/일")
print(f"\n  ※ STEP 2 라스트마일 항(왕복식, 연속배정): {원래_라스트마일_절대:,.0f}원/일 "
      f"— VRP 실측 대비 {원래_라스트마일_절대/total_vrp_cost:.1%}"
      f" (분수적재 vs 방문노드 올림 차이만 남음)")
print(f"\n  기존 총비용(STEP 2)         : {원래_총비용:,.0f}원/일  ({srow['단위비용']:.0f}원/박스)")
print(f"  VRP 반영 재계산 총비용       : {새_총비용:,.0f}원/일  ({새_단위비용:.0f}원/박스)")
print(f"  (라스트마일 항만 '개별왕복->VRP순회'로 교체, 허브 입지·배정은 STEP 2 그대로)")

print(f"\n저장: {OUT}\\vrp_hub_routes.csv, vrp_summary.csv")
