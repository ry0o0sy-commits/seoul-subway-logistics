# -*- coding: utf-8 -*-
"""
STEP 2b. 대표 시나리오 정밀 재계산 (격자 탐색 후처리)
────────────────────────────────────────────────────────────
격자 탐색(step2.py)은 48개 조합을 훑어야 해서 solver 허용오차를
gapRel=0.02(2%)로 느슨하게 둔다. 그런데 라스트마일을 왕복으로 고친 뒤
허브 개수에 따른 비용 곡선이 매우 평탄해져(n=15~22가 1.5% 안), 허용오차가
곡선의 기복보다 커졌다. 그 결과:

  · 같은 n=18인데 격자는 10,759,949원, 정밀 계산은 10,640,332원
  · 허브 18곳 중 4곳이 다름
  · 예전에도 같은 이유로 도곡/교대가 0.0085% 차이로 뒤집힌 적 있음

그래서 상위 후보 조합만 골라 허용오차를 조여 다시 풀고, 진짜 최적을
scenario_results/hubs/assignments의 해당 행에 덮어쓴다. 후속 단계
(VRP·배출량·그림)가 차선해 위에서 만들어지는 것을 막는 게 목적이다.

실행: python step2_refine_rep.py [상위N개=5]
"""
import os
import re
import sys
import numpy as np
import pandas as pd
import network_common as nc

OUT, BASE = nc.OUT, nc.BASE
TOP_N = int(sys.argv[1]) if len(sys.argv) > 1 else 5
GAP, TIME_LIMIT = 0.002, 600
N_MAX = 30

COST = dict(BOX_PER_CAR=1_500, COST_PER_KM=1_500, TRUCK_CAP=200,
            ALPHA_LABOR=270, ALPHA_RAIL=700, UNLOAD_RATE=450,
            ELEV_SPEED_MPM=30, ELEV_CAPACITY=50)

print("[1] 네트워크/수요 로드")
net = nc.load_all(verbose=False)
stations = net["stations"]
name = list(stations["역명"])
dist = np.load(f"{OUT}/dist_km.npy")
dongs = pd.read_csv(f"{OUT}/dongs.csv")
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

results = pd.read_csv(f"{OUT}/scenario_results.csv")
hubs_df = pd.read_csv(f"{OUT}/scenario_hubs.csv")
assign_df = pd.read_csv(f"{OUT}/scenario_assignments.csv")

ok = results[results["실행가능"] == True]
ok = ok[ok["ID"] != nc.MAX_SCENARIO_ID]
cand = ok.sort_values("단위비용").head(TOP_N)
print(f"\n[2] 상위 {len(cand)}개 조합 정밀 재계산 (gapRel={GAP}, {TIME_LIMIT}초)")
print(f"    {'ID':<5} {'조합':<18} {'격자(gap2%)':>14} {'정밀(gap0.2%)':>14} {'개선':>8}")

refined = {}
for _, row in cand.iterrows():
    sid = row["ID"]
    cars, trips, share = int(row["칸"]), int(row["운행"]), float(row["분담률"])
    w = W * share
    tot = w.sum()
    r = nc.solve_hub_location(
        w, cars, trips, N_MAX,
        dist=dist, OK=net["OK"], hub_dir=net["hub_dir"], rail_t=net["rail_t"],
        DIRECTIONS=net["DIRECTIONS"], DIR_ROUND_TRIP=net["DIR_ROUND_TRIP"],
        station_depth=net["station_depth"], rent_daily=net["rent_daily"],
        exact=False, cost=COST, time_limit=TIME_LIMIT, gap_rel=GAP)
    if r is None:
        print(f"    {sid:<5} 해 없음/시간초과")
        continue
    unit = r["Z"] / tot
    imp = (row["총비용"] - r["Z"]) / row["총비용"]
    refined[sid] = dict(row=row, res=r, unit=unit, tot=tot, w=w)
    print(f"    {sid:<5} {cars}칸x{trips}회 분담률{share:.0%}   "
          f"{row['단위비용']:>10.2f}원 {unit:>13.2f}원 {imp:>7.2%}  n={r['n']}", flush=True)
    # 조합당 수 분씩 걸린다. 한 번 끊기면 전부 날아가지 않도록 진행분을 남긴다
    # (실제로 5개 중 4개까지 계산한 상태에서 죽어 결과를 통째로 잃은 적 있다).
    pd.DataFrame([dict(ID=k, n=v["res"]["n"], 총비용=v["res"]["Z"], 단위비용=v["unit"],
                       허브=", ".join(sorted(name[j] for j in v["res"]["hubs"])))
                  for k, v in refined.items()]).to_csv(
        f"{OUT}/diag_refine_progress.csv", index=False, encoding="utf-8-sig")

if not refined:
    raise SystemExit("정밀 재계산 실패 — 중단")

best_id = min(refined, key=lambda k: refined[k]["unit"])
b = refined[best_id]
best_hubs = sorted(name[j] for j in b["res"]["hubs"])
print(f"\n[3] 정밀 기준 최적: {best_id}  n={b['res']['n']}  "
      f"{b['res']['Z']:,.0f}원/일  {b['unit']:.2f}원/박스")
print(f"    허브 {len(best_hubs)}개: {', '.join(best_hubs)}")

prev = hubs_df[hubs_df["ID"] == best_id]
if len(prev):
    old_h = set(x.strip() for x in prev.iloc[0]["선정역사"].split(","))
    print(f"    격자 대비 — 빠짐 {sorted(old_h - set(best_hubs)) or '없음'} / "
          f"들어옴 {sorted(set(best_hubs) - old_h) or '없음'}")

# ── 정밀해로 세 파일의 해당 행을 교체 ──────────────────────
print(f"\n[4] 산출물 갱신 — {list(refined)} 행 교체")
for sid, d in refined.items():
    res, row, w = d["res"], d["row"], d["w"]
    hub_names = sorted(name[j] for j in res["hubs"])

    m = results["ID"] == sid
    results.loc[m, "n"] = res["n"]
    results.loc[m, "총비용"] = res["Z"]
    results.loc[m, "단위비용"] = d["unit"]
    for col, key in [("라스트마일", "라스트마일"), ("철도", "철도"),
                     ("심도", "심도"), ("고정비", "고정비")]:
        if col in results.columns and key in res:
            results.loc[m, col] = res[key]

    hubs_df.loc[hubs_df["ID"] == sid, "선정역사"] = ", ".join(hub_names)

    new_rows = []
    for d_idx, j in enumerate(res["assign"]):
        if w[d_idx] <= 0:
            continue
        new_rows.append(dict(ID=sid, 행정동=dongs.loc[d_idx, "ADM_NM"], 행정동_idx=d_idx,
                             배정허브=name[j], 허브_idx=j, 수요=w[d_idx]))
    assign_df = assign_df[assign_df["ID"] != sid]
    assign_df = pd.concat([assign_df, pd.DataFrame(new_rows)], ignore_index=True)

results.to_csv(f"{OUT}/scenario_results.csv", index=False, encoding="utf-8-sig")
hubs_df.to_csv(f"{OUT}/scenario_hubs.csv", index=False, encoding="utf-8-sig")
assign_df.to_csv(f"{OUT}/scenario_assignments.csv", index=False, encoding="utf-8-sig")
print(f"    저장: scenario_results.csv / scenario_hubs.csv / scenario_assignments.csv")

rep = nc.REP_SCENARIO
if best_id != rep["ID"] or b["res"]["n"] != rep["n_hubs"]:
    print(f"\n★ network_common.REP_SCENARIO 갱신 필요: "
          f"ID={best_id}, n_hubs={b['res']['n']} "
          f"(현재 {rep['ID']}, {rep['n_hubs']})")
else:
    print(f"\n대표 시나리오 정의와 일치: {rep['ID']}, n_hubs={rep['n_hubs']}")
