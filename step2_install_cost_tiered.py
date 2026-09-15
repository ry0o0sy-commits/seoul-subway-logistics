# -*- coding: utf-8 -*-
"""
STEP 2c-2. 허브 설치비 민감도 — 지상/지하 차등 버전
────────────────────────────────────────────────────────────
step2_install_cost.py는 모든 역에 동일한 설치비 P를 물렸다. 그런데 지상역은
승강장이 지면 높이라 화물 수직이송 설비가 불필요하거나 훨씬 단순하고,
지하역은 심도만큼의 엘리베이터 설치가 필요하다. 균일 적용은 지상역에
불리한 보수적 기준이므로 여기서 차등화한다.

  [A안] 지상역(심도 0): 0.5P / 지하역: 1.0P          (요청 사양)
  [B안] 지상역(심도 0): 0.5P / 지하역: 심도 비례      (A안의 정교화)
        지하역 계수 = 0.5 + 0.5 x (심도 / 지하역 심도 중앙값), 상한 1.5
        -> 심도 중앙값인 역이 정확히 1.0P가 되어 A안과 눈금이 맞는다.
           0.5는 "수직이송과 무관한 고정 설비(하역장·전원·통신)" 몫,
           나머지 0.5가 심도에 비례하는 엘리베이터 몫이라는 해석이다.

일 환산은 동일하게 내용연수 20년 정액 감가상각:
    일 설치비(j) = P(억) x 1e8 x 계수(j) / (20 x 365)

실행: python step2_install_cost_tiered.py
출력: output_data/diag_install_cost_tiered.csv
"""
import os
import re
import numpy as np
import pandas as pd
import network_common as nc

OUT, BASE = nc.OUT, nc.BASE
REP = nc.REP_SCENARIO
N_MAX, GAP, TL = 30, 0.002, 420
YEARS, DAYS = 20, 365
P_LIST_EOK = [1, 3, 5, 10, 20]
GROUND_FACTOR = 0.5          # 지상역 계수
UNDER_CAP = 1.5              # B안 지하역 계수 상한

COST = dict(BOX_PER_CAR=1_500, COST_PER_KM=1_500, TRUCK_CAP=200,
            ALPHA_LABOR=270, ALPHA_RAIL=700, UNLOAD_RATE=450,
            ELEV_SPEED_MPM=30, ELEV_CAPACITY=50)

print("[1] 네트워크/수요 로드")
net = nc.load_all(verbose=False)
stations = net["stations"]
name = list(stations["역명"])
n2i = {n: i for i, n in enumerate(name)}
dist = np.load(f"{OUT}/dist_km.npy")
depth = net["station_depth"]
rent = net["rent_daily"]

dongs = pd.read_csv(f"{OUT}/dongs.csv")
demand = pd.read_csv(os.path.join(BASE, "반출_행정동별_일평균수요.xls"), encoding="utf-8-sig")


def norm(s):
    s = str(s).replace("·", ".")
    s = re.sub(r"제([\d.]+동)", r"\1", s)
    return re.sub(r"^홍(\d+동)$", r"홍제\1", s)


demand["N"] = demand["행정동"].map(norm)
dongs["N"] = dongs["ADM_NM"].map(norm)
dongs["GU_CODE"] = dongs["ADM_CD"].astype(str).str[2:5]
dup = set(dongs["N"].value_counts()[lambda s: s > 1].index)
uq = dongs[~dongs["N"].isin(dup)].merge(demand[["N", "자치구"]], on="N", how="inner")
dongs["자치구"] = dongs["GU_CODE"].map(
    uq.groupby("GU_CODE")["자치구"].agg(lambda s: s.value_counts().index[0]))
dongs = dongs.merge(demand[["자치구", "N", "일평균_전체시장"]], on=["자치구", "N"], how="left")
W = dongs["일평균_전체시장"].fillna(0).values * REP["share"]
TOT = W.sum()

# ── 계수 산출 ──────────────────────────────────────────────
OKm = net["OK"]
is_ground = (depth <= 0.05)
und_depth = depth[OKm & ~is_ground]
med_depth = float(np.median(und_depth)) if len(und_depth) else 1.0
print(f"    허브 후보 {int(OKm.sum())}곳 중 지상역(심도 0) {int((OKm & is_ground).sum())}곳")
print(f"    지하역 심도 중앙값 {med_depth:.1f}m "
      f"(범위 {und_depth.min():.1f}~{und_depth.max():.1f}m)")

fac_A = np.where(is_ground, GROUND_FACTOR, 1.0)
fac_B = np.where(is_ground, GROUND_FACTOR,
                 np.clip(0.5 + 0.5 * depth / med_depth, GROUND_FACTOR, UNDER_CAP))

KORAIL = set(nc.LINE1_KORAIL_TARGETS)
kor_ground = [n for n in KORAIL if n in n2i and is_ground[n2i[n]]]
print(f"    1호선 코레일 구간 {len(KORAIL)}곳 중 지상역 {len(kor_ground)}곳\n")


def run(tag, fac):
    rows = []
    for P in P_LIST_EOK:
        daily = P * 1e8 * fac / (YEARS * DAYS)     # 역별 벡터
        r = nc.solve_hub_location(
            W, REP["cars"], REP["trips"], N_MAX,
            dist=dist, OK=OKm, hub_dir=net["hub_dir"], rail_t=net["rail_t"],
            DIRECTIONS=net["DIRECTIONS"], DIR_ROUND_TRIP=net["DIR_ROUND_TRIP"],
            station_depth=depth, rent_daily=rent + daily,
            exact=False, cost=COST, time_limit=TL, gap_rel=GAP)
        if r is None:
            print(f"  [{tag}] P={P:>2}억: 해 없음/시간초과", flush=True)
            continue
        hubs = sorted(name[j] for j in r["hubs"])
        g = [h for h in hubs if is_ground[n2i[h]]]
        k = [h for h in hubs if h in KORAIL]
        inst = float(sum(daily[j] for j in r["hubs"]))
        rows.append(dict(안=tag, 설치비_억=P, n=r["n"], 총비용=r["Z"], 단위비용=r["Z"] / TOT,
                         고정비=r["고정비"], 설치비분=inst, 임대료분=r["고정비"] - inst,
                         지상역수=len(g), 지상역비율=len(g) / r["n"],
                         코레일1호선수=len(k), 허브=", ".join(hubs)))
        print(f"  [{tag}] P={P:>2}억: n={r['n']:2d}, {r['Z']:>12,.0f}원 "
              f"{r['Z']/TOT:6.2f}원/박스 | 지상역 {len(g):2d}/{r['n']:2d} "
              f"({len(g)/r['n']:5.1%}) | 1호선코레일 {len(k):2d} | "
              f"설치비 {inst:>9,.0f}원/일", flush=True)
        pd.DataFrame(rows).to_csv(f"{OUT}/diag_install_cost_tiered_{tag}.csv",
                                  index=False, encoding="utf-8-sig")
    return rows


print(f"[2] A안 (지상 {GROUND_FACTOR}P / 지하 1.0P)")
rows_a = run("A", fac_A)
print(f"\n[3] B안 (지상 {GROUND_FACTOR}P / 지하 심도비례 {GROUND_FACTOR}~{UNDER_CAP}P)")
rows_b = run("B", fac_B)

df = pd.DataFrame(rows_a + rows_b)
df.to_csv(f"{OUT}/diag_install_cost_tiered.csv", index=False, encoding="utf-8-sig")
print(f"\n저장: {OUT}\\diag_install_cost_tiered.csv")

# ── 균일 적용본과 비교 ─────────────────────────────────────
u = f"{OUT}/diag_install_cost.csv"
if os.path.exists(u):
    U = pd.read_csv(u)
    U = U[U["실행가능"] == True].set_index("설치비_억")
    print("\n[4] 균일 적용 대비")
    print(f"  {'P':>3} {'균일 n':>7} {'A안 n':>6} {'B안 n':>6} | "
          f"{'균일 단위':>9} {'A안':>8} {'B안':>8} | {'A안 지상역':>10}")
    for P in P_LIST_EOK:
        ra = next((x for x in rows_a if x["설치비_억"] == P), None)
        rb = next((x for x in rows_b if x["설치비_억"] == P), None)
        if P not in U.index or ra is None:
            continue
        print(f"  {P:>3} {int(U.loc[P,'n']):>7} {ra['n']:>6} "
              f"{(rb['n'] if rb else 0):>6} | {U.loc[P,'단위비용']:>9.2f} "
              f"{ra['단위비용']:>8.2f} {(rb['단위비용'] if rb else 0):>8.2f} | "
              f"{ra['지상역수']:>4}/{ra['n']} ({ra['지상역비율']:.0%})")
        uh = set(str(U.loc[P, "허브"]).split(", "))
        for nm in ["독산", "대방"]:
            print(f"      {nm}: 균일 {'O' if nm in uh else 'X'} / "
                  f"A안 {'O' if nm in ra['허브'] else 'X'} / "
                  f"B안 {'O' if rb and nm in rb['허브'] else 'X'}")
