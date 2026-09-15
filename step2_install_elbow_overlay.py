# -*- coding: utf-8 -*-
"""
추가 분석 — 구축비별 엘보우 곡선 겹쳐 그리기
────────────────────────────────────────────────────────────
"구축비가 커지면 허브 개수 곡선의 모양과 최적점이 어떻게 바뀌는가"를
한 장으로 보여준다. 추가 분석 꼭지의 메인 그림.

구축비는 시나리오 축이 아니다 — P가 커질수록 단위비용은 단조증가라
극점이 없고, 경제성 분석(운영기간·할인율)이 필요해 본 연구 범위를 벗어난다.
그래서 대표 시나리오는 P=0(운영비 기준)을 유지하고, 여기서는 "P를 넣으면
결론이 어떻게 이동하는지"만 별도로 보인다.

  일 구축비 = P(억) x 1e8 / (20년 x 365일)     — 전 역 균일(보수적)
  허브 고정비 = 임대료 일 환산액 + 일 구축비

P=0 곡선은 step2_elbow_s39.py가 만든 elbow_results.csv를 그대로 쓰고,
P>0 곡선만 여기서 계산한다(같은 gapRel=0.002).

실행: python step2_install_elbow_overlay.py
출력: output_data/install_elbow_overlay.png, diag_install_elbow.csv
"""
import os
import re
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams["font.family"] = "Malgun Gothic"
matplotlib.rcParams["axes.unicode_minus"] = False
import matplotlib.pyplot as plt
import network_common as nc

OUT, BASE = nc.OUT, nc.BASE
REP = nc.REP_SCENARIO
GAP, TL = 0.002, 180
YEARS, DAYS = 20, 365
P_LIST = [0, 1, 3, 5]                 # 억원
N_RANGE = range(10, 29)               # P>0에서 계산할 구간(P=0은 CSV 재사용)
COLORS = {0: "#1A237E", 1: "#00838F", 3: "#EF6C00", 5: "#B71C1C"}

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

curves = {}
# ── P=0: 엘보우 결과 재사용 ────────────────────────────────
e0 = pd.read_csv(f"{OUT}/elbow_results.csv")
curves[0] = {int(r["n"]): float(r["단위비용"]) for _, r in e0.iterrows()}
print(f"    P=0: elbow_results.csv 재사용 (n={min(curves[0])}~{max(curves[0])})")

CACHE = f"{OUT}/diag_install_elbow.csv"
done = {}
if os.path.exists(CACHE):
    prev = pd.read_csv(CACHE)
    for _, r in prev.iterrows():
        done[(int(r["P억"]), int(r["n"]))] = float(r["단위비용"])
    print(f"    이전 계산 {len(done)}건 재사용")

rows = [dict(P억=p, n=n, 단위비용=v) for (p, n), v in done.items()]
print(f"\n[2] P>0 곡선 계산 (gapRel={GAP}, n={N_RANGE.start}~{N_RANGE.stop-1})")
for P in [p for p in P_LIST if p > 0]:
    daily = P * 1e8 / (YEARS * DAYS)
    curves[P] = {}
    for n in N_RANGE:
        if (P, n) in done:
            curves[P][n] = done[(P, n)]
            continue
        r = nc.solve_hub_location(
            W, REP["cars"], REP["trips"], n,
            dist=dist, OK=net["OK"], hub_dir=net["hub_dir"], rail_t=net["rail_t"],
            DIRECTIONS=net["DIRECTIONS"], DIR_ROUND_TRIP=net["DIR_ROUND_TRIP"],
            station_depth=net["station_depth"], rent_daily=rent + daily,
            exact=True, cost=COST, time_limit=TL, gap_rel=GAP)
        if r is None:
            continue
        u = r["Z"] / TOT
        curves[P][n] = u
        rows.append(dict(P억=P, n=n, 단위비용=u))
        pd.DataFrame(rows).to_csv(CACHE, index=False, encoding="utf-8-sig")
        print(f"    P={P}억 n={n:2d}: {u:6.2f}원/박스", flush=True)

# ── 그림 ───────────────────────────────────────────────────
print("\n[3] 그림")
fig, ax = plt.subplots(figsize=(11, 7))
summary = []
for P in P_LIST:
    c = {n: v for n, v in curves.get(P, {}).items() if n in N_RANGE or P == 0}
    if P == 0:
        c = {n: v for n, v in curves[0].items() if n >= N_RANGE.start}
    if not c:
        continue
    ns = sorted(c)
    ys = [c[n] for n in ns]
    col = COLORS[P]
    lbl = "구축비 미반영 (본 연구)" if P == 0 else f"허브당 {P}억"
    ax.plot(ns, ys, "-o", color=col, linewidth=2.4, markersize=4.5,
            label=lbl, zorder=3)
    bn = min(c, key=c.get)
    ax.scatter([bn], [c[bn]], s=210, facecolor="white", edgecolor=col,
               linewidth=2.6, zorder=5)
    # P=0 곡선은 그림 맨 아래라 라벨을 아래로 빼면 축 밖으로 잘린다 — 위로 붙인다
    # P=0은 그림 맨 아래라 라벨을 아래로 빼면 잘리고, 위로 올리면 P=1억
    # 라벨과 겹친다 — 오른쪽으로 밀어 붙인다.
    if P == 0:
        kw = dict(ha="left", va="center", xytext=(26, -4))
    else:
        kw = dict(ha="center", va="top", xytext=(0, -16))
    ax.annotate(f"n={bn}  {c[bn]:.1f}원", (bn, c[bn]), fontsize=10.5,
                fontweight="bold", color=col, textcoords="offset points",
                zorder=6,
                bbox=dict(boxstyle="round,pad=0.22", fc="white", ec=col,
                          lw=1.0, alpha=0.92), **kw)
    summary.append((P, bn, c[bn]))
    print(f"    P={P}억 -> 최저 n={bn} ({c[bn]:.2f}원/박스)")

ax.set_xlabel("허브 개수 n", fontsize=12)
ax.set_ylabel("단위비용 (원/박스)", fontsize=12)
ax.set_xticks(list(N_RANGE)[::2])
ax.grid(alpha=0.3)
ax.set_axisbelow(True)
ax.legend(fontsize=11, title="허브 구축비", title_fontsize=11, framealpha=0.95)
note = " · ".join(f"{p}억→n={b}" for p, b, _ in summary)
ax.set_title(f"허브 구축비별 비용 곡선과 최적 허브 수 — {REP['ID']} "
             f"({REP['cars']}칸x{REP['trips']}회, 분담률 {REP['share']:.0%})\n"
             f"구축비가 커질수록 곡선이 들리고 최적 규모가 작아진다: {note}",
             fontsize=14, fontweight="bold", pad=12)
# 캡션은 축 안에 넣으면 P=0 곡선과 겹친다 — figure 하단으로 뺀다
fig.text(0.5, 0.005,
         "구축비 = 허브당 P를 20년 정액 감가상각으로 일 환산해 고정비에 가산"
         " (전 역 균일 적용 — 지상역 수직이송 설비 절감분 미반영, 보수적 기준)\n"
         "각 n은 정확히 n개로 고정해 푼 값. 최저점 부근은 곡선이 평탄해 "
         "인접 n과의 차이가 solver 허용오차(0.2%) 수준이다",
         ha="center", va="bottom", fontsize=9, color="#555555", linespacing=1.5)
plt.tight_layout(rect=[0, 0.07, 1, 1])
nc.savefig_retry(plt, f"{OUT}/install_elbow_overlay.png", dpi=180)
plt.close(fig)
print(f"\n저장: {OUT}\\install_elbow_overlay.png, {CACHE}")
