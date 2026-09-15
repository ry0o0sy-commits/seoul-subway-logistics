"""
검증·진단 스크립트 통합본
────────────────────────────────────────────────────────────
원래 아래 5개 스크립트로 흩어져 있던 일회성 검증들을 하나로 합쳤다.
각자 데이터 로드·노선망 구축 보일러플레이트를 100줄씩 복붙하고 있었고,
그 사본들이 전부 구버전 기점(군자차량기지->신설동)이라 1호선 확장·지축
제외 이후로는 돌려도 틀린 결과가 나오는 상태였다. network_common을 쓰게
바꿔 최신 네트워크·최신 대표 시나리오 기준으로 되살린다.

  step2_alpha_rail_sensitivity.py   -> --mode sensitivity
  step2_policy_unload_available.py  -> --mode policy
  step2_trips_feasibility_check.py  -> --mode trips
  step2_unload_time_check.py        -> --mode unload
  step2_adjacent_hub_analysis.py    -> --mode adjacent

사용법:
  python step2_diagnostics.py sensitivity
  python step2_diagnostics.py policy
  python step2_diagnostics.py trips
  python step2_diagnostics.py unload
  python step2_diagnostics.py adjacent
  python step2_diagnostics.py all        # 전부(오래 걸림 — MILP 다수 실행)

대표 시나리오는 하드코딩하지 않고 scenario_results.csv에서 단위비용 최소
조합을 매번 다시 뽑는다(현재 S39: 4칸x5회, 분담률 12%).
"""

import os
import re
import sys
import numpy as np
import pandas as pd
import network_common as nc

OUT, BASE = nc.OUT, nc.BASE

# 원단위 — step2.py Section 0과 동일해야 한다.
COST = dict(BOX_PER_CAR=1_500, COST_PER_KM=1_500, TRUCK_CAP=200,
            ALPHA_LABOR=270, ALPHA_RAIL=700, UNLOAD_RATE=450,
            ELEV_SPEED_MPM=30, ELEV_CAPACITY=50)
N_MAX = 30

ALPHA_RAIL_SENSITIVITY = [500, 700, 1_000, 2_000]      # 원/분
UNLOAD_RATE_SENSITIVITY = [150, 300, 450, 600]         # 박스/분
AVAILABLE_MIN_SENSITIVITY = [120, 180, 240]            # 분
POLICY_UNLOAD_RATES = [50, 150, 300, 450, 600, 1000]   # 박스/분
POLICY_AVAILABLE_MINS = [120, 180, 240, 300]           # 분
ACCESS_LINE_MINS = [0.0, 3.0, 5.0]                     # 기지 인입선 편도(분)

# ★ 비용 비교형 진단(sensitivity/adjacent)은 허용오차를 조여야 한다.
#   라스트마일을 왕복으로 고친 뒤 비용 곡선이 매우 평탄해져(n=15~22가 1.5% 안),
#   gapRel=0.02로는 차선해가 최적으로 잡힌다. 실제로 adjacent에서 "허브를
#   제외했더니 비용이 -0.79% 싸지는" 행이 나왔는데, 제외는 제약 추가라
#   비용이 낮아질 수 없으므로 기준해가 차선해였다는 뜻이다.
#   (policy/stress는 실행가능 여부만 보므로 이 영향을 받지 않는다.)
TIGHT_GAP, TIGHT_TL = 0.002, 300


# ══════════════════════════════════════════════════════════
# 공통 준비 — 네트워크 + 수요 + 대표 시나리오
# ══════════════════════════════════════════════════════════
def prepare():
    net = nc.load_all()
    stations = net["stations"]

    dongs = pd.read_csv(f"{OUT}/dongs.csv")
    dist = np.load(f"{OUT}/dist_km.npy")
    demand = pd.read_csv(os.path.join(BASE, "반출_행정동별_일평균수요.xls"), encoding="utf-8-sig")

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
    assert dist.shape[0] == len(stations), \
        f"dist_km.npy({dist.shape[0]}) != 역 수({len(stations)}) — step1c를 먼저 실행하세요"

    results = pd.read_csv(f"{OUT}/scenario_results.csv")
    ok = results[(results["실행가능"] == True) & (results["ID"] != nc.MAX_SCENARIO_ID)]
    rep = ok.loc[ok["단위비용"].idxmin()]
    print(f"    대표 시나리오: {rep['ID']} ({int(rep['칸'])}칸x{int(rep['운행'])}회, "
          f"분담률 {rep['분담률']:.0%}, {rep['단위비용']:.1f}원/박스)")

    return dict(net=net, stations=stations, dongs=dongs, dist=dist, W=W,
                rep=rep, results=results)


def make_solver(ctx):
    net, dist = ctx["net"], ctx["dist"]

    def solve(w, cars, trips, n_max, exact=False, alpha_rail=None,
              unload_rate=None, available_min=None, exclude=None,
              time_limit=40, gap_rel=0.03):
        OK = net["OK"].copy()
        if exclude:
            name2idx = {n: i for i, n in enumerate(ctx["stations"]["역명"])}
            for nm in exclude:
                if nm in name2idx:
                    OK[name2idx[nm]] = False
        return nc.solve_hub_location(
            w, cars, trips, n_max,
            dist=dist, OK=OK, hub_dir=net["hub_dir"], rail_t=net["rail_t"],
            DIRECTIONS=net["DIRECTIONS"], DIR_ROUND_TRIP=net["DIR_ROUND_TRIP"],
            station_depth=net["station_depth"], rent_daily=net["rent_daily"],
            exact=exact, alpha_rail=alpha_rail, unload_rate=unload_rate,
            available_min=available_min, cost=COST,
            time_limit=time_limit, gap_rel=gap_rel)
    return solve


def max_feasible_share(solve, W, cars, trips, unload_rate=None, available_min=None,
                       hi=60.0, iters=7):
    """이분탐색으로 최대 실행가능 분담률(%)을 찾는다."""
    lo = 0.0
    for _ in range(iters):
        mid = (lo + hi) / 2
        if solve(W * (mid / 100.0), cars, trips, N_MAX,
                 unload_rate=unload_rate, available_min=available_min) is not None:
            lo = mid
        else:
            hi = mid
    return lo


# ══════════════════════════════════════════════════════════
# [sensitivity] ALPHA_RAIL / UNLOAD_RATE / AVAILABLE_MIN 민감도
#   근거가 상대적으로 약한 가정값 3개가 결과(단위비용·허브수)에 얼마나
#   영향을 주는지 본다. 대표 시나리오 조건을 고정하고 한 번에 하나씩 바꾼다.
# ══════════════════════════════════════════════════════════
def run_sensitivity(ctx, solve):
    rep, W = ctx["rep"], ctx["W"]
    cars, trips, share = int(rep["칸"]), int(rep["운행"]), float(rep["분담률"])
    w = W * share
    total = w.sum()
    rows = []
    for label, key, values in [("ALPHA_RAIL", "alpha_rail", ALPHA_RAIL_SENSITIVITY),
                               ("UNLOAD_RATE", "unload_rate", UNLOAD_RATE_SENSITIVITY),
                               ("AVAILABLE_MIN", "available_min", AVAILABLE_MIN_SENSITIVITY)]:
        for v in values:
            r = solve(w, cars, trips, N_MAX, **{key: v},
                      time_limit=TIGHT_TL, gap_rel=TIGHT_GAP)
            base = COST.get(label, nc.AVAILABLE_MIN if label == "AVAILABLE_MIN" else None)
            if r is None:
                print(f"  {label}={v}: 해 없음")
                rows.append(dict(파라미터=label, 값=v, 실행가능=False))
                continue
            unit = r["Z"] / total
            print(f"  {label}={v:<6}: n*={r['n']:2d}, {r['Z']:,.0f}원/일, {unit:.2f}원/박스"
                  + ("  <- 기본값" if v == base else ""))
            rows.append(dict(파라미터=label, 값=v, 실행가능=True, n=r["n"],
                             총비용=r["Z"], 단위비용=unit, 기본값여부=(v == base)))
    df = pd.DataFrame(rows)
    df.to_csv(f"{OUT}/diag_sensitivity.csv", index=False, encoding="utf-8-sig")
    print(f"저장: {OUT}\\diag_sensitivity.csv")


# ══════════════════════════════════════════════════════════
# [policy] 하역속도·심야 가용시간별 최대 실행가능 분담률
#   "무엇을 개선하면 분담률을 얼마나 올릴 수 있는가"를 보여주는 정책 제언 표.
# ══════════════════════════════════════════════════════════
def run_policy_a(ctx, solve):
    """하역속도별 상한. 이분탐색 7회 x 6단계라 A/B를 따로 돌릴 수 있게 나눠 뒀다
    (한쪽만 다시 필요할 때 나머지를 재계산하지 않기 위해)."""
    rep, W = ctx["rep"], ctx["W"]
    cars, trips = int(rep["칸"]), int(rep["운행"])
    print(f"  [A] UNLOAD_RATE별 (AVAILABLE_MIN={nc.AVAILABLE_MIN} 고정, {cars}칸x{trips}회)")
    rows_a = []
    for ur in POLICY_UNLOAD_RATES:
        s = max_feasible_share(solve, W, cars, trips, unload_rate=ur)
        print(f"    {ur:>5}박스/분 -> 최대 분담률 {s:.2f}%", flush=True)
        rows_a.append(dict(UNLOAD_RATE=ur, 최대분담률_pct=round(s, 2)))
    pd.DataFrame(rows_a).to_csv(f"{OUT}/diag_policy_unload_rate.csv",
                                index=False, encoding="utf-8-sig")
    print(f"저장: {OUT}\\diag_policy_unload_rate.csv")


def run_policy_b(ctx, solve):
    """심야 가용시간별 상한."""
    rep, W = ctx["rep"], ctx["W"]
    cars, trips = int(rep["칸"]), int(rep["운행"])
    print(f"  [B] AVAILABLE_MIN별 (UNLOAD_RATE={COST['UNLOAD_RATE']} 고정, {cars}칸x{trips}회)")
    rows_b = []
    for am in POLICY_AVAILABLE_MINS:
        s = max_feasible_share(solve, W, cars, trips, available_min=am)
        print(f"    {am:>5}분      -> 최대 분담률 {s:.2f}%", flush=True)
        rows_b.append(dict(AVAILABLE_MIN=am, 최대분담률_pct=round(s, 2)))
        # 단계마다 저장 — 중간에 끊겨도 여기까지는 남는다.
        pd.DataFrame(rows_b).to_csv(f"{OUT}/diag_policy_available_min.csv",
                                    index=False, encoding="utf-8-sig")
    print(f"저장: {OUT}\\diag_policy_available_min.csv")


def run_policy(ctx, solve):
    run_policy_a(ctx, solve)
    run_policy_b(ctx, solve)


# ══════════════════════════════════════════════════════════
# [trips] 방향별 TRIPS 물리적 실행가능성
#   희망 trips를 방향마다 그대로 적용하면 긴 방향은 심야에 물리적으로
#   불가능하다. 방향별 왕복시간으로 최대 가능 trips를 계산해 확인한다.
#   (이 점검 결과는 이미 step2.py의 MAX_TRIPS/eff_trips로 반영돼 있다 —
#    여기서는 "그 상한이 실제로 어디에 걸리는지"를 표로 남긴다.)
# ══════════════════════════════════════════════════════════
def run_trips(ctx, solve=None):
    net = ctx["net"]
    rows = []
    for dk in sorted(net["DIRECTIONS"], key=lambda k: -net["DIR_ROUND_TRIP"][k]):
        rt = net["DIR_ROUND_TRIP"][dk]
        cycle = rt + nc.TURNAROUND_MIN
        max_trips = net["MAX_TRIPS"][dk]
        caps = {t: min(t, max_trips) for t in (5, 10, 15, 20)}
        rows.append(dict(방향=dk, 왕복주행_분=round(rt, 1), 왕복회차_분=round(cycle, 1),
                         최대trips=max_trips,
                         **{f"희망{t}회_실제": caps[t] for t in (5, 10, 15, 20)}))
    df = pd.DataFrame(rows)
    print(df.to_string(index=False))
    n_capped = {t: sum(1 for r in rows if r[f"희망{t}회_실제"] < t) for t in (5, 10, 15, 20)}
    print(f"\n  희망 trips별 캡핑되는 방향 수 (전체 {len(rows)}개): {n_capped}")
    df.to_csv(f"{OUT}/diag_trips_feasibility.csv", index=False, encoding="utf-8-sig")
    print(f"저장: {OUT}\\diag_trips_feasibility.csv")


# ══════════════════════════════════════════════════════════
# [unload] 하역시간이 심야 가용시간 안에 실제로 들어가는지 사후 검증
#   확정된 배정(scenario_assignments.csv)의 실제 q[j]로
#   "주행+회차 + 하역"이 AVAILABLE_MIN을 넘지 않는지 방향별로 확인한다.
#   step2.py에 시간 제약이 들어간 뒤라 위반이 0이어야 정상이다.
# ══════════════════════════════════════════════════════════
def run_unload(ctx, solve=None):
    net, stations = ctx["net"], ctx["stations"]
    assign = pd.read_csv(f"{OUT}/scenario_assignments.csv")
    results = ctx["results"]
    name2idx = {n: i for i, n in enumerate(stations["역명"])}

    rows, violations = [], []
    for sid, g in assign.groupby("ID"):
        srow = results[results["ID"] == sid]
        if not len(srow):
            continue
        srow = srow.iloc[0]
        trips = int(srow["운행"])
        q_by_hub = g.groupby("배정허브")["수요"].sum()
        by_dir = {}
        for hub, q in q_by_hub.items():
            if hub not in name2idx:
                continue
            dk = net["hub_dir"][name2idx[hub]]
            by_dir[dk] = by_dir.get(dk, 0.0) + q
        for dk, q_tot in by_dir.items():
            eff = min(trips, net["MAX_TRIPS"][dk])
            travel = eff * (net["DIR_ROUND_TRIP"][dk] + nc.TURNAROUND_MIN)
            unload = q_tot / COST["UNLOAD_RATE"]
            used = travel + unload
            ratio = used / nc.AVAILABLE_MIN
            rec = dict(ID=sid, 방향=dk, 물량=round(q_tot), 주행회차_분=round(travel, 1),
                       하역_분=round(unload, 1), 합계_분=round(used, 1),
                       가용대비=round(ratio, 3))
            rows.append(rec)
            if ratio > 1.0 + 1e-6:
                violations.append(rec)

    df = pd.DataFrame(rows)
    df.to_csv(f"{OUT}/diag_unload_time.csv", index=False, encoding="utf-8-sig")
    print(f"  검사 대상 {len(df)}건(시나리오x방향), 위반 {len(violations)}건")
    if violations:
        vdf = pd.DataFrame(violations).sort_values("가용대비", ascending=False)
        print(vdf.head(15).to_string(index=False))
        vdf.to_csv(f"{OUT}/diag_unload_violations.csv", index=False, encoding="utf-8-sig")
        print(f"  ! 위반 발견 — 시간 제약이 제대로 안 걸리고 있을 수 있음")
    else:
        print("  ✓ 위반 없음 — 심야 가용시간 제약이 정상 작동")
    print(f"저장: {OUT}\\diag_unload_time.csv")


# ══════════════════════════════════════════════════════════
# [adjacent] 인접한 두 허브가 함께 선정된 이유
#   가까운 허브 쌍을 찾고, 한쪽을 강제 제외해 다시 풀었을 때 비용이
#   얼마나 나빠지는지로 "정말 둘 다 필요한가"를 확인한다.
# ══════════════════════════════════════════════════════════
def run_adjacent(ctx, solve):
    rep, W, stations = ctx["rep"], ctx["W"], ctx["stations"]
    cars, trips, share = int(rep["칸"]), int(rep["운행"]), float(rep["분담률"])
    w = W * share
    total = w.sum()

    hubs_csv = pd.read_csv(f"{OUT}/scenario_hubs.csv")
    hub_names = [h.strip() for h in
                 hubs_csv[hubs_csv["ID"] == rep["ID"]].iloc[0]["선정역사"].split(",")]
    coord = {r["역명"]: (r["위도"], r["경도"]) for _, r in stations.iterrows()}

    def hav(a, b):
        R = 6371.0
        (la1, lo1), (la2, lo2) = coord[a], coord[b]
        la1, lo1, la2, lo2 = map(np.radians, [la1, lo1, la2, lo2])
        x = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
        return 2 * R * np.arcsin(np.sqrt(x))

    pairs = sorted(((hav(a, b), a, b)
                    for i, a in enumerate(hub_names) for b in hub_names[i + 1:]),
                   key=lambda t: t[0])[:5]
    print(f"  {rep['ID']} 허브 {len(hub_names)}개 중 가장 가까운 쌍 5개:")
    for d, a, b in pairs:
        print(f"    {a} - {b}: {d:.2f}km")

    base = solve(w, cars, trips, N_MAX, time_limit=TIGHT_TL, gap_rel=TIGHT_GAP)
    base_unit = base["Z"] / total
    print(f"\n  기준(전체 후보): {base['Z']:,.0f}원/일, {base_unit:.2f}원/박스, n={base['n']}")

    rows = []
    for d, a, b in pairs:
        for drop in (a, b):
            r = solve(w, cars, trips, N_MAX, exclude=[drop],
                      time_limit=TIGHT_TL, gap_rel=TIGHT_GAP)
            if r is None:
                print(f"    {drop} 제외 -> 해 없음(그 역이 필수)")
                rows.append(dict(쌍=f"{a}-{b}", 거리km=round(d, 2), 제외역=drop, 실행가능=False))
                continue
            unit = r["Z"] / total
            delta = r["Z"] - base["Z"]
            print(f"    {drop} 제외 -> {r['Z']:,.0f}원/일 ({unit:.2f}원/박스), "
                  f"기준 대비 {delta:+,.0f}원/일 ({delta/base['Z']:+.2%}), n={r['n']}")
            rows.append(dict(쌍=f"{a}-{b}", 거리km=round(d, 2), 제외역=drop, 실행가능=True,
                             총비용=r["Z"], 단위비용=unit, 기준대비_원=delta,
                             기준대비_pct=delta / base["Z"], n=r["n"]))
    pd.DataFrame(rows).to_csv(f"{OUT}/diag_adjacent_hub.csv", index=False, encoding="utf-8-sig")
    print(f"저장: {OUT}\\diag_adjacent_hub.csv")


# ══════════════════════════════════════════════════════════
# [access_line] 기지 인입선 시간 민감도 — 알려진 한계 D의 검증 근거
#   모델은 차량기지와 접속역을 같은 노드로 봐서 인입선 주행시간이 0분이다.
#   편도 L분을 넣으면 모든 운행이 그 구간을 왕복하므로:
#     rail_t[j] += L        (접속역 자신도 0 -> L. 지금은 "기점" 레이가 공짜다)
#     DIR_ROUND_TRIP += 2L  -> 하역 가용시간이 eff_trips x 2L 만큼 줄어든다
#   둘 다 solve_hub_location의 인자라 원본 모듈을 고치지 않고 값만 바꿔 넣는다.
#
#   확인하는 것 두 가지:
#     (1) 접속역 허브(구로·수서·양천구청)가 L을 넣어도 선정되는가
#     (2) L=0의 허브 조합이 L>0에서도 성립하는가 — 각 레이의 유효 처리량
#         min(적재상한, 하역시간상한, 엘리베이터상한)을 더해 수요와 비교한다.
#         부족하면 그 조합은 실행불가이고, 허브 교체는 축퇴가 아니라 강제다.
# ══════════════════════════════════════════════════════════
ACCESS_WATCH = ["구로", "수서", "양천구청"]     # 차량기지 접속역이자 현재 허브


def _lay_capacity(ctx, hubs, L, cars, trips):
    """L분일 때 주어진 허브 조합의 유효 처리 가능량(박스). 레이당 허브 1곳 기준."""
    net, stations = ctx["net"], ctx["stations"]
    n2i = {n: i for i, n in enumerate(stations["역명"])}
    tot, rows = 0.0, []
    for h in hubs:
        if h not in n2i:
            continue
        j = n2i[h]
        dk = net["hub_dir"][j]
        drt = net["DIR_ROUND_TRIP"][dk] + 2 * L
        eff = min(trips, int(nc.AVAILABLE_MIN // (drt + nc.TURNAROUND_MIN)))
        cap = COST["BOX_PER_CAR"] * cars * eff
        tcap = max(0.0, nc.AVAILABLE_MIN - eff * (drt + nc.TURNAROUND_MIN)) * COST["UNLOAD_RATE"]
        ert = 2 * net["station_depth"][j] / COST["ELEV_SPEED_MPM"]
        ecap = (nc.AVAILABLE_MIN * COST["ELEV_CAPACITY"] / ert) if ert > 0 \
            else nc.UNLIMITED_ELEV_CAP
        lim = min(cap, tcap, ecap)
        tot += lim
        rows.append(dict(허브=h, eff=eff, 적재상한=cap, 하역시간상한=round(tcap),
                         엘리베이터상한=round(min(ecap, 9e6)), 유효=round(lim)))
    return tot, pd.DataFrame(rows).sort_values("유효")


def run_access_line(ctx, solve):
    net, stations, rep, W = ctx["net"], ctx["stations"], ctx["rep"], ctx["W"]
    cars, trips, share = int(rep["칸"]), int(rep["운행"]), float(rep["분담률"])
    w = W * share
    total = w.sum()
    name = list(stations["역명"])

    base_hubs, rows = None, []
    for L in ACCESS_LINE_MINS:
        rail_t = net["rail_t"] + L
        drt = {k: v + 2 * L for k, v in net["DIR_ROUND_TRIP"].items()}
        r = nc.solve_hub_location(
            w, cars, trips, N_MAX,
            dist=ctx["dist"], OK=net["OK"], hub_dir=net["hub_dir"], rail_t=rail_t,
            DIRECTIONS=net["DIRECTIONS"], DIR_ROUND_TRIP=drt,
            station_depth=net["station_depth"], rent_daily=net["rent_daily"],
            exact=False, cost=COST, time_limit=180, gap_rel=0.005)
        if r is None:
            print(f"  L={L:.0f}분: 해 없음")
            rows.append(dict(인입선_편도분=L, 실행가능=False))
            continue
        hubs = sorted(name[j] for j in r["hubs"])
        if base_hubs is None:
            base_hubs = hubs
        unit = r["Z"] / total
        keep = " ".join(f"{h}{'O' if h in hubs else 'X'}" for h in ACCESS_WATCH)
        # L=0 허브 조합이 이 L에서도 성립하는지(용량 기준)
        cap_tot, cap_df = _lay_capacity(ctx, base_hubs, L, cars, trips)
        ok = cap_tot >= total
        print(f"  L={L:.0f}분: n*={r['n']}, {r['Z']:,.0f}원/일, {unit:.2f}원/박스 | {keep}")
        print(f"        L=0 허브 조합 유효 처리량 {cap_tot:,.0f} vs 수요 {total:,.0f}"
              f" -> {'성립' if ok else '실행불가'}")
        if not ok:
            print("        병목 레이: " + ", ".join(
                f"{r2['허브']}({r2['유효']:,.0f})" for _, r2 in cap_df.head(3).iterrows()))
        rows.append(dict(인입선_편도분=L, 실행가능=True, n=r["n"], 총비용=r["Z"],
                         단위비용=unit, 허브=", ".join(hubs),
                         **{f"{h}_선정": (h in hubs) for h in ACCESS_WATCH},
                         L0허브조합_유효처리량=round(cap_tot),
                         L0허브조합_성립=ok, 수요=round(total)))
    pd.DataFrame(rows).to_csv(f"{OUT}/diag_access_line_sensitivity.csv",
                              index=False, encoding="utf-8-sig")
    print(f"저장: {OUT}\\diag_access_line_sensitivity.csv")


# ══════════════════════════════════════════════════════════
# [stress] 보수 가정 복합 스트레스 — 한꺼번에 불리하게 잡아도 성립하는가
#   개별 민감도는 한 번에 하나씩만 바꿔서, "여러 가정이 동시에 틀렸을 때"를
#   보지 못한다. 근거가 약한 가정 4개를 동시에 보수적으로 잡고 2^4=16개
#   조합 각각의 최대 실행가능 분담률을 구한다.
#
#   보수 가정 4개와 모델 반영 방식:
#     L (인입선 편도 3분)  rail_t += L, DIR_ROUND_TRIP += 2L   -> 한계 D
#     상차 (기지 상차 포함) 하역과 같은 속도로 한 번 더 처리한다는 뜻이므로
#                          유효 처리속도를 절반으로 둔다. 시간 제약과 인건비가
#                          동시에 2배가 되어 "박스당 2회 취급"과 정확히 같다.
#     하역속도 150박스/분  현행 450 = 출입문 3개 병렬. 150은 문 1개만 쓸 때.
#     가용시간 150분       현행 180분에서 30분 축소(막차/첫차 여유 축소 상정).
#   상차와 하역속도는 곱해진다(둘 다면 유효 75박스/분).
# ══════════════════════════════════════════════════════════
STRESS_ACCESS_MIN = 3.0      # 인입선 편도(분)
STRESS_UNLOAD_RATE = 150     # 박스/분 (현행 450)
STRESS_AVAILABLE_MIN = 150   # 분 (현행 180)
STRESS_BISECT_ITERS = 7
STRESS_HI = 40.0             # 분담률 탐색 상한(%)


def run_stress(ctx, solve):
    import itertools
    net, rep, W = ctx["net"], ctx["rep"], ctx["W"]
    cars, trips = int(rep["칸"]), int(rep["운행"])
    rep_share = float(rep["분담률"]) * 100
    name = list(ctx["stations"]["역명"])

    def max_share(L, load, slow, short):
        """해당 조합의 최대 실행가능 분담률(%). 이분탐색."""
        rail_t = net["rail_t"] + L
        drt = {k: v + 2 * L for k, v in net["DIR_ROUND_TRIP"].items()}
        ur = (STRESS_UNLOAD_RATE if slow else COST["UNLOAD_RATE"]) / (2 if load else 1)
        am = STRESS_AVAILABLE_MIN if short else nc.AVAILABLE_MIN
        lo, hi, best = 0.0, STRESS_HI, None
        for _ in range(STRESS_BISECT_ITERS):
            mid = (lo + hi) / 2
            r = nc.solve_hub_location(
                W * (mid / 100.0), cars, trips, N_MAX,
                dist=ctx["dist"], OK=net["OK"], hub_dir=net["hub_dir"], rail_t=rail_t,
                DIRECTIONS=net["DIRECTIONS"], DIR_ROUND_TRIP=drt,
                station_depth=net["station_depth"], rent_daily=net["rent_daily"],
                exact=False, unload_rate=ur, available_min=am, cost=COST,
                time_limit=60, gap_rel=0.02)
            if r is not None:
                lo, best = mid, r
            else:
                hi = mid
        return lo, best, ur, am

    rows = []
    for load, slow, short, L_on in itertools.product([False, True], repeat=4):
        L = STRESS_ACCESS_MIN if L_on else 0.0
        s, r, ur, am = max_share(L, load, slow, short)
        n_on = sum([L_on, load, slow, short])
        tag = "+".join([t for t, on in
                        [("인입선", L_on), ("상차", load), ("저속하역", slow), ("단축시간", short)]
                        if on]) or "현행(기준)"
        ok_rep = s >= rep_share
        hubs = ", ".join(sorted(name[j] for j in r["hubs"])) if r else ""
        # 조합당 수 분씩 걸리므로 진행이 바로 보이게 flush한다(버퍼링되면
        # 백그라운드 실행 시 끝날 때까지 아무 출력도 안 보인다).
        print(f"  [{n_on}개] {tag:<34} 최대 분담률 {s:5.2f}%"
              f"  (유효하역 {ur:5.1f}박스/분, 가용 {am:3.0f}분)"
              f"  대표 {rep_share:.0f}% {'성립' if ok_rep else '★불가'}", flush=True)
        rows.append(dict(보수가정수=n_on, 조합=tag, 인입선분=L, 상차포함=load,
                         유효하역속도=ur, 가용시간=am, 최대분담률_pct=round(s, 2),
                         대표분담률_성립=ok_rep, n=(r["n"] if r else None),
                         허브=hubs))
    df = pd.DataFrame(rows).sort_values(["보수가정수", "최대분담률_pct"],
                                        ascending=[True, False])
    df.to_csv(f"{OUT}/diag_stress_combinations.csv", index=False, encoding="utf-8-sig")
    worst = df.iloc[-1] if len(df) else None
    print(f"\n  기준(현행) 최대 분담률 {df.iloc[0]['최대분담률_pct']:.2f}%")
    if worst is not None:
        print(f"  전부 보수적으로: {worst['최대분담률_pct']:.2f}% "
              f"(대표 {rep_share:.0f}% {'성립' if worst['대표분담률_성립'] else '불가'})")
    bad = df[~df["대표분담률_성립"]]
    print(f"  대표 분담률 {rep_share:.0f}%가 불가능한 조합: {len(bad)}/{len(df)}개")
    for _, r2 in bad.iterrows():
        print(f"    - {r2['조합']} -> 최대 {r2['최대분담률_pct']:.2f}%")
    print(f"저장: {OUT}\\diag_stress_combinations.csv")


MODES = {
    "sensitivity": ("ALPHA_RAIL/UNLOAD_RATE/AVAILABLE_MIN 민감도", run_sensitivity, True),
    "access_line": ("기지 인입선 시간 민감도(한계 D 검증)", run_access_line, True),
    "stress":      ("보수 가정 4개 복합 스트레스(2^4 조합)", run_stress, True),
    "policy":      ("하역속도·심야시간별 최대 분담률(정책 제언)", run_policy, True),
    "policy_a":    ("  └ 하역속도별만", run_policy_a, True),
    "policy_b":    ("  └ 심야 가용시간별만", run_policy_b, True),
    "trips":       ("방향별 TRIPS 물리적 실행가능성", run_trips, False),
    "unload":      ("하역시간 심야 가용시간 제약 사후검증", run_unload, False),
    "adjacent":    ("인접 허브 쌍이 둘 다 필요한지", run_adjacent, True),
}


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode not in MODES and mode != "all":
        print("사용법: python step2_diagnostics.py <mode>")
        print("  mode:")
        for k, (desc, _, milp) in MODES.items():
            print(f"    {k:<12} {desc}" + ("  (MILP 실행 — 오래 걸림)" if milp else ""))
        print(f"    {'all':<12} 전부 실행")
        return

    print("[준비] 네트워크/수요 로드")
    ctx = prepare()
    solve = make_solver(ctx)

    # policy_a/b는 policy의 부분집합이라 all에서는 제외(중복 실행 방지)
    targets = [m for m in MODES if m not in ("policy_a", "policy_b")] if mode == "all" else [mode]
    for m in targets:
        desc, fn, _ = MODES[m]
        print(f"\n{'='*70}\n[{m}] {desc}\n{'='*70}")
        fn(ctx, solve)


if __name__ == "__main__":
    main()
