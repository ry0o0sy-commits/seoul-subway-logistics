"""
실행 가능한 최대 분담률 재탐색 (1호선 확장 이후)
────────────────────────────────────────────────────────────
UNLOAD_RATE=450, AVAILABLE_MIN=180 기준. 1호선 코레일 구간 26개역이
들어오면서 후보역이 109 -> 134개, 방향이 17 -> 21개로 늘었고 수송능력이
커졌으므로 이전 탐색값(15.6%)은 무효 — 처음부터 다시 이분탐색한다.

cars=4 고정: cap_dir(=BOX_PER_CAR*cars*eff_trips)에만 곱해지고 시간 제약
(remaining_min*ur, elev_cap)에는 cars가 안 들어가므로 항상 약하게 유리.
trips는 5/10/15/20 네 가지 — trips를 늘리면 왕복시간이 늘어 하역 가용시간이
줄어드는 트레이드오프가 있어 무조건 클수록 좋은 게 아니다.

찾은 시나리오는 ID="SMAX"로 scenario_results.csv 등에 추가(기존 ID 보존).
네트워크/심도/임대료는 network_common으로 step2.py와 동일하게 구축한다.
"""

import os
import numpy as np
import pandas as pd
import pulp
import network_common as nc

OUT = nc.OUT
BOX_PER_CAR = 1_500
COST_PER_KM = 1_500
TRUCK_CAP   = 200
ALPHA_LABOR = 270
ALPHA_RAIL  = 700
UNLOAD_RATE = 450
AVAILABLE_MIN = nc.AVAILABLE_MIN
TURNAROUND_MIN = nc.TURNAROUND_MIN
ELEV_SPEED_MPM = 30
ELEV_CAPACITY  = 50
N_MAX = 30
TRIPS_CANDIDATES = [5, 10, 15, 20]
CARS_FIXED = 4
REP_ID_FOR_COMPARE = nc.REP_SCENARIO["ID"]   # 대표 시나리오 정의는 network_common 한 곳

print("[1] 데이터/네트워크 로드")
net = nc.load_all()
stations, G_seq = net["stations"], net["G_seq"]
rail_t, hub_dir, OK = net["rail_t"], net["hub_dir"], net["OK"]
DIRECTIONS, DIR_ROUND_TRIP, MAX_TRIPS = net["DIRECTIONS"], net["DIR_ROUND_TRIP"], net["MAX_TRIPS"]
station_depth, rent_daily = net["station_depth"], net["rent_daily"]

dongs = pd.read_csv(f"{OUT}/dongs.csv")
dist = np.load(f"{OUT}/dist_km.npy")
demand = pd.read_csv(os.path.join(nc.BASE, "반출_행정동별_일평균수요.xls"), encoding="utf-8-sig")

import re
def norm(s):
    s = str(s).replace("·", ".")
    s = re.sub(r"제([\d.]+동)", r"\1", s)
    s = re.sub(r"^홍(\d+동)$", r"홍제\1", s)
    return s

demand["N"] = demand["행정동"].map(norm)
dongs["N"] = dongs["ADM_NM"].map(norm)
dongs["GU_CODE"] = dongs["ADM_CD"].astype(str).str[2:5]
dup = set(dongs["N"].value_counts()[lambda s: s > 1].index)
uniq = dongs[~dongs["N"].isin(dup)].merge(demand[["N", "자치구"]], on="N", how="inner")
gu_map = uniq.groupby("GU_CODE")["자치구"].agg(lambda s: s.value_counts().index[0])
dongs["자치구"] = dongs["GU_CODE"].map(gu_map)
dongs = dongs.merge(demand[["자치구", "N", "일평균_전체시장"]], on=["자치구", "N"], how="left")
dongs["일평균_전체시장"] = dongs["일평균_전체시장"].fillna(0)
W = dongs["일평균_전체시장"].values
N_ST, N_D = len(stations), len(dongs)
assert dist.shape[0] == N_ST, f"dist_km.npy({dist.shape[0]}) != 역 수({N_ST})"
print(f"    역 {N_ST} x 동 {N_D}, 수요 합계 {W.sum():,.0f}박스/일")


COST = dict(BOX_PER_CAR=BOX_PER_CAR, COST_PER_KM=COST_PER_KM, TRUCK_CAP=TRUCK_CAP,
            ALPHA_LABOR=ALPHA_LABOR, ALPHA_RAIL=ALPHA_RAIL, UNLOAD_RATE=UNLOAD_RATE,
            ELEV_SPEED_MPM=ELEV_SPEED_MPM, ELEV_CAPACITY=ELEV_CAPACITY)


def solve(w, cars, trips, n_max, time_limit=30, gap_rel=0.03):
    """MILP 본체는 network_common.solve_hub_location() 공유(step2.py와 동일 수식)."""
    return nc.solve_hub_location(
        w, cars, trips, n_max,
        dist=dist, OK=OK, hub_dir=hub_dir, rail_t=rail_t,
        DIRECTIONS=DIRECTIONS, DIR_ROUND_TRIP=DIR_ROUND_TRIP,
        station_depth=station_depth, rent_daily=rent_daily,
        exact=False, cost=COST, time_limit=time_limit, gap_rel=gap_rel)


print(f"\n[2] cars={CARS_FIXED} 고정, trips별 최대 실행가능 분담률 이분탐색 (0~60%)")
print("=" * 78)
search_rows = []
for trips in TRIPS_CANDIDATES:
    lo, hi = 0.0, 60.0
    for _ in range(8):     # 60/2^8 ≈ 0.23%p
        mid = (lo + hi) / 2
        ok = solve(W * (mid / 100.0), CARS_FIXED, trips, N_MAX) is not None
        print(f"  trips={trips:2d}회 | share={mid:6.2f}% | {'가능' if ok else '불가능'}")
        if ok:
            lo = mid
        else:
            hi = mid
    print(f"  -> trips={trips}회: 최대 실행가능 분담률 ≈ {lo:.2f}%\n")
    search_rows.append(dict(trips=trips, cars=CARS_FIXED, max_share_pct=round(lo, 2)))

search_df = pd.DataFrame(search_rows)
print("[탐색 결과]")
print(search_df.to_string(index=False))
search_df.to_csv(f"{OUT}/max_feasible_share_v2.csv", index=False, encoding="utf-8-sig")

best_row = search_df.loc[search_df["max_share_pct"].idxmax()]
BEST_TRIPS = int(best_row["trips"])
BEST_SHARE_PCT = np.floor(best_row["max_share_pct"] * 10) / 10
print(f"\n★ 최대 실행가능 분담률: {BEST_SHARE_PCT:.1f}% (trips={BEST_TRIPS}회, cars={CARS_FIXED}칸)")

print(f"\n[3] 최종 확정 solve")
w_final = W * (BEST_SHARE_PCT / 100.0)
r = solve(w_final, CARS_FIXED, BEST_TRIPS, N_MAX, time_limit=90, gap_rel=0.02)
if r is None:
    raise RuntimeError("최종 solve 실패 — BEST_SHARE_PCT를 더 낮춰야 함")

total = w_final.sum()
unit = r["Z"] / total
eff_prev = {dk: min(BEST_TRIPS, MAX_TRIPS[dk]) for dk in DIRECTIONS}
cap_tot = sum(BOX_PER_CAR * CARS_FIXED * et for et in eff_prev.values())
hub_names = stations.loc[r["hubs"], "역명"].tolist()
LINE1_NEW = set(nc.LINE1_KORAIL_TARGETS) - {"창동"}
new_hubs = sorted(set(hub_names) & LINE1_NEW)
print(f"    n*={r['n']}개, 총비용 {r['Z']:,.0f}원/일, 단위비용 {unit:.1f}원/박스")
print(f"    허브: {', '.join(sorted(hub_names))}")
print(f"    1호선 신규역 포함: {new_hubs} ({len(new_hubs)}개)")

NEW_ID = nc.MAX_SCENARIO_ID
res_path = f"{OUT}/scenario_results.csv"
old = pd.read_csv(res_path)
old = old[old["ID"] != NEW_ID]
new_row = dict(ID=NEW_ID, 칸=CARS_FIXED, 운행=BEST_TRIPS, 분담률=BEST_SHARE_PCT / 100.0,
               총능력=cap_tot, 필요물량=total, 실행가능=True, n=r["n"],
               총비용=r["Z"], 단위비용=unit,
               라스트마일비중=r["라스트마일"] / r["Z"], 철도비중=r["철도"] / r["Z"],
               철도운행비중=r["철도_운행"] / r["Z"], 철도하역비중=r["철도_하역"] / r["Z"],
               심도비중=r["심도"] / r["Z"], 고정비중=r["고정비"] / r["Z"])
pd.concat([old, pd.DataFrame([new_row])], ignore_index=True).to_csv(
    res_path, index=False, encoding="utf-8-sig")

hubs_path = f"{OUT}/scenario_hubs.csv"
oh = pd.read_csv(hubs_path)
oh = oh[oh["ID"] != NEW_ID]
pd.concat([oh, pd.DataFrame([{"ID": NEW_ID, "선정역사": ", ".join(sorted(hub_names))}])],
          ignore_index=True).to_csv(hubs_path, index=False, encoding="utf-8-sig")

asg_path = f"{OUT}/scenario_assignments.csv"
oa = pd.read_csv(asg_path)
oa = oa[oa["ID"] != NEW_ID]
rows = [dict(ID=NEW_ID, 행정동=dongs.loc[d, "ADM_NM"], 행정동_idx=d,
             배정허브=stations.loc[r["assign"][d], "역명"], 허브_idx=r["assign"][d],
             수요=w_final[d]) for d in range(N_D)]
pd.concat([oa, pd.DataFrame(rows)], ignore_index=True).to_csv(
    asg_path, index=False, encoding="utf-8-sig")
print(f"\n저장(추가): scenario_results.csv, scenario_hubs.csv, scenario_assignments.csv (ID={NEW_ID})")

# ── 스펙 저장 + S39 비교 ──────────────────────────────────────────
name2idx = {n: i for i, n in enumerate(stations["역명"])}
dirs_used = sorted(set(hub_dir[name2idx[n]] for n in hub_names))
lines = []
def p(s=""):
    print(s); lines.append(s)

p("=" * 74)
p(f"환경효과 최대 시나리오 {NEW_ID} 전체 스펙 (실행가능 최대 분담률)")
p("=" * 74)
p("[운영 조건]")
p(f"  칸 수 / 운행횟수  : {CARS_FIXED}칸 x {BEST_TRIPS}회(희망)")
p(f"  분담률            : {BEST_SHARE_PCT:.1f}%  (UNLOAD_RATE=450, AVAILABLE_MIN=180 기준 상한)")
p(f"  필요물량          : {total:,.0f}박스/일")
p(f"  총 수송능력       : {cap_tot:,.0f}박스/일")
p(f"\n[허브]")
p(f"  허브 개수         : {r['n']}개")
p(f"  선정역 목록       : {', '.join(sorted(hub_names))}")
p(f"  1호선 신규역      : {', '.join(new_hubs) if new_hubs else '-'} ({len(new_hubs)}개)")
p(f"\n[비용]")
p(f"  총비용            : {r['Z']:,.0f}원/일")
p(f"  단위비용          : {unit:.1f}원/박스")
p(f"\n[비용 구성 비중]")
p(f"  라스트마일        : {r['라스트마일']/r['Z']:.1%}")
p(f"  철도(합계)        : {r['철도']/r['Z']:.1%}  (운행 {r['철도_운행']/r['Z']:.1%} + 하역 {r['철도_하역']/r['Z']:.1%})")
p(f"  심도(엘리베이터)  : {r['심도']/r['Z']:.1%}")
p(f"  고정비(임대료)    : {r['고정비']/r['Z']:.1%}")
p(f"\n[방향별 실제 운행횟수]")
p(f"  {'방향':<30} {'왕복+회차(분)':>13} {'희망':>5} {'실제':>5}  담당 허브")
for dk in dirs_used:
    rt_ = DIR_ROUND_TRIP[dk] + TURNAROUND_MIN
    eff = min(BEST_TRIPS, MAX_TRIPS[dk])
    cap = " (캡핑)" if eff < BEST_TRIPS else ""
    hs = [n for n in hub_names if hub_dir[name2idx[n]] == dk]
    p(f"  {dk:<30} {rt_:>13.1f} {BEST_TRIPS:>5d} {eff:>5d}{cap}  <- {', '.join(hs)}")
p("=" * 74)

with open(f"{OUT}/representative_scenario_max.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
print(f"\n저장: {OUT}\\representative_scenario_max.txt")

res = pd.read_csv(res_path)
rep = res[res["ID"] == REP_ID_FOR_COMPARE].iloc[0]
comp = pd.DataFrame([
    dict(구분="비용효율 최적", ID=REP_ID_FOR_COMPARE, 칸=int(rep["칸"]), 운행=int(rep["운행"]),
         분담률=f"{rep['분담률']:.0%}", 필요물량=round(rep["필요물량"]), 허브개수=int(rep["n"]),
         총비용=round(rep["총비용"]), 단위비용=round(rep["단위비용"], 1)),
    dict(구분="환경효과 최대", ID=NEW_ID, 칸=CARS_FIXED, 운행=BEST_TRIPS,
         분담률=f"{BEST_SHARE_PCT:.1f}%", 필요물량=round(total), 허브개수=r["n"],
         총비용=round(r["Z"]), 단위비용=round(unit, 1)),
])
print(f"\n[{REP_ID_FOR_COMPARE} vs {NEW_ID}]")
print(comp.to_string(index=False))
comp.to_csv(f"{OUT}/scenario_comparison_rep_vs_SMAX.csv", index=False, encoding="utf-8-sig")
print(f"\n저장: {OUT}\\scenario_comparison_rep_vs_SMAX.csv")
