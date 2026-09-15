# -*- coding: utf-8 -*-
"""
STEP 2c. 허브 설치비 민감도
────────────────────────────────────────────────────────────
현재 모델의 허브 고정비는 "지하상가 임대료 기반 일 환산액"뿐이고,
하역장·수직이송 설비 등 초기 설치비(CAPEX)가 빠져 있다.

면적 산정 근거가 없으므로 면적을 추정하지 않고, **허브당 총 설치비 P**를
파라미터로 두고 내용연수 20년 정액 감가상각으로 일 단위 환산해 고정비에 더한다.

    일 설치비 = P(억원) x 1e8 / (20 x 365)
    허브 고정비 = 기존 임대료 일 환산액 + 일 설치비

설치비는 허브를 열 때만 드는 비용이라 rent_daily에 그대로 더하면 되고,
solve_hub_location은 rent_daily를 인자로 받으므로 모듈 수정이 필요 없다.

[의도적으로 균일 적용한 부분 — 결과 보고 차등화 판단]
  · 심도가 깊을수록 엘리베이터 설치비가 커질 텐데 균일로 둔다.
  · 1호선 코레일 구간은 지상역이라 수직이송 설비가 덜 필요할 수 있으나
    역시 균일로 둔다.
  -> 즉 이 분석은 "심도가 싼 지상역에 유리하게 기울지 않은" 보수적 기준이다.

실행: python step2_install_cost.py
출력: output_data/diag_install_cost.csv
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
P_LIST_EOK = [0, 1, 3, 5, 10, 20]        # 허브당 총 설치비(억원)

COST = dict(BOX_PER_CAR=1_500, COST_PER_KM=1_500, TRUCK_CAP=200,
            ALPHA_LABOR=270, ALPHA_RAIL=700, UNLOAD_RATE=450,
            ELEV_SPEED_MPM=30, ELEV_CAPACITY=50)

print("[1] 네트워크/수요 로드")
net = nc.load_all(verbose=False)
name = list(net["stations"]["역명"])
dist = np.load(f"{OUT}/dist_km.npy")
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

rent = net["rent_daily"]
res_csv = pd.read_csv(f"{OUT}/scenario_results.csv").query("ID == @REP['ID']").iloc[0]
cur_hub_idx = [name.index(h) for h in
               sorted(set(pd.read_csv(f"{OUT}/scenario_assignments.csv")
                          .query("ID == @REP['ID']")["배정허브"]))]
cur_rent = float(sum(rent[j] for j in cur_hub_idx))
print(f"    현행 허브 {len(cur_hub_idx)}곳 임대료 합계 {cur_rent:,.0f}원/일 "
      f"(허브당 평균 {cur_rent/len(cur_hub_idx):,.0f}원/일)")
print(f"    후보역 임대료 중앙값 {np.median(rent):,.0f}원/일\n")

print(f"[2] 설치비별 재최적화 ({REP['cars']}칸x{REP['trips']}회, 분담률 {REP['share']:.0%}, "
      f"gapRel={GAP})")
rows = []
for P in P_LIST_EOK:
    daily = P * 1e8 / (YEARS * DAYS)
    r = nc.solve_hub_location(
        W, REP["cars"], REP["trips"], N_MAX,
        dist=dist, OK=net["OK"], hub_dir=net["hub_dir"], rail_t=net["rail_t"],
        DIRECTIONS=net["DIRECTIONS"], DIR_ROUND_TRIP=net["DIR_ROUND_TRIP"],
        station_depth=net["station_depth"], rent_daily=rent + daily,
        exact=False, cost=COST, time_limit=TL, gap_rel=GAP)
    if r is None:
        print(f"  P={P:>2}억: 해 없음/시간초과", flush=True)
        rows.append(dict(설치비_억=P, 일설치비=round(daily), 실행가능=False))
        continue
    hubs = sorted(name[j] for j in r["hubs"])
    install_total = r["n"] * daily          # 설치비 감가상각분(일)
    rent_only = r["고정비"] - install_total  # 순수 임대료분
    rows.append(dict(
        설치비_억=P, 일설치비=round(daily), 실행가능=True, n=r["n"],
        총비용=r["Z"], 단위비용=r["Z"] / TOT,
        고정비=r["고정비"], 임대료분=rent_only, 설치비분=install_total,
        설치비비중=install_total / r["Z"],
        총사업비_억=r["n"] * P, 허브=", ".join(hubs)))
    print(f"  P={P:>2}억 (일 {daily:>7,.0f}원): n={r['n']:2d}, "
          f"{r['Z']:>12,.0f}원 {r['Z']/TOT:6.2f}원/박스 | "
          f"고정비 {r['고정비']:>9,.0f} (임대 {rent_only:>9,.0f} + 설치 {install_total:>9,.0f}) | "
          f"총사업비 {r['n']*P:>3d}억", flush=True)

df = pd.DataFrame(rows)
df.to_csv(f"{OUT}/diag_install_cost.csv", index=False, encoding="utf-8-sig")

ok = df[df["실행가능"]]
if len(ok) > 1:
    n0 = int(ok.iloc[0]["n"])
    shrink = ok[ok["n"] < n0]
    print(f"\n[3] 허브 수 {n0}개에서 줄기 시작하는 임계점: ", end="")
    print(f"P={int(shrink.iloc[0]['설치비_억'])}억 (n={int(shrink.iloc[0]['n'])})"
          if len(shrink) else "관측 범위(P<=20억) 안에서는 줄지 않음")
    base = ok.iloc[0]
    for _, x in ok.iloc[1:].iterrows():
        prev = set(base["허브"].split(", ")); cur = set(x["허브"].split(", "))
        print(f"    P={int(x['설치비_억']):>2}억: 단위비용 {x['단위비용']:.2f}원 "
              f"({x['단위비용']/base['단위비용']-1:+.1%}), 설치비 비중 {x['설치비비중']:.1%}, "
              f"빠짐 {sorted(prev-cur) or '없음'}")
print(f"\n저장: {OUT}\\diag_install_cost.csv")
