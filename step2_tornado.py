# -*- coding: utf-8 -*-
"""
전체 변수 민감도 통합 — 토네이도 차트
────────────────────────────────────────────────────────────
대표 시나리오(S39)를 기준으로 8개 원단위·운영 변수를 각각 ±30% 흔들어
단위비용과 최적 허브 수가 얼마나 움직이는지 한 그림으로 보인다.
"어느 변수가 결과를 가장 좌우하는가"가 목적이므로, 모든 변수를 같은
±30% 폭으로 맞춰 서로 비교 가능하게 했다.

[변수 전달 경로 — solve_hub_location의 인자 구조가 달라 주의]
  cost dict로 전달 : COST_PER_KM, TRUCK_CAP, BOX_PER_CAR, UNLOAD_RATE,
                     ALPHA_RAIL, ALPHA_LABOR
  별도 인자로 전달 : AVAILABLE_MIN(available_min), TURNAROUND(turnaround_min)
                     — 이 둘은 network_common의 모듈 상수를 보므로 cost dict에
                       넣어도 반영되지 않는다.

[해상도]
비용 곡선이 평탄해(n=17~20이 0.2% 안) gapRel을 0.002로 조인다. 그래도
허브 수는 인접 값과 구분이 어려울 수 있어, n 변화는 "경향"으로만 읽어야 한다.

실행: python step2_tornado.py
출력: output_data/tornado_sensitivity.png, diag_tornado.csv
"""
import os
import re
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams["font.family"] = "Malgun Gothic"
matplotlib.rcParams["axes.unicode_minus"] = False
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import network_common as nc

OUT, BASE = nc.OUT, nc.BASE
REP = nc.REP_SCENARIO
PCT = 0.30
N_MAX, GAP, TL = 30, 0.002, 300
CACHE = f"{OUT}/diag_tornado.csv"

BASE_COST = dict(BOX_PER_CAR=1_500, COST_PER_KM=1_500, TRUCK_CAP=200,
                 ALPHA_LABOR=270, ALPHA_RAIL=700, UNLOAD_RATE=450,
                 ELEV_SPEED_MPM=30, ELEV_CAPACITY=50)

# (표시명, 기준값, 단위, 전달방식)  kind: "cost" | "am" | "tm"
VARS = [
    ("COST_PER_KM",   1_500, "원/km",  "cost"),
    ("TRUCK_CAP",       200, "박스/대", "cost"),
    ("BOX_PER_CAR",   1_500, "박스/칸", "cost"),
    ("UNLOAD_RATE",     450, "박스/분", "cost"),
    ("AVAILABLE_MIN",   180, "분",     "am"),
    ("ALPHA_RAIL",      700, "원/분",  "cost"),
    ("ALPHA_LABOR",     270, "원/분",  "cost"),
    ("TURNAROUND",       10, "분",     "tm"),
]

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


def run(cost=None, am=None, tm=None):
    r = nc.solve_hub_location(
        W, REP["cars"], REP["trips"], N_MAX,
        dist=dist, OK=net["OK"], hub_dir=net["hub_dir"], rail_t=net["rail_t"],
        DIRECTIONS=net["DIRECTIONS"], DIR_ROUND_TRIP=net["DIR_ROUND_TRIP"],
        station_depth=net["station_depth"], rent_daily=net["rent_daily"],
        exact=False, cost=cost or BASE_COST, available_min=am, turnaround_min=tm,
        time_limit=TL, gap_rel=GAP)
    if r is None:
        return None, None
    return r["Z"] / TOT, r["n"]


done = {}
if os.path.exists(CACHE):
    for _, r in pd.read_csv(CACHE).iterrows():
        done[(str(r["변수"]), str(r["방향"]))] = (r["단위비용"], r["n"])
    print(f"    이전 계산 {len(done)}건 재사용")

rows = [dict(변수=k[0], 방향=k[1], 단위비용=v[0], n=v[1]) for k, v in done.items()]


def save():
    pd.DataFrame(rows).to_csv(CACHE, index=False, encoding="utf-8-sig")


print(f"\n[2] 기준 + 8개 변수 x ±{PCT:.0%} (gapRel={GAP})")
if ("기준", "기준") in done:
    base_u, base_n = done[("기준", "기준")]
else:
    base_u, base_n = run()
    rows.append(dict(변수="기준", 방향="기준", 단위비용=base_u, n=base_n)); save()

# ★ 비용 곡선이 평탄해 같은 조건을 다시 풀어도 solver가 0.4%쯤 나쁜 해를
#   잡을 때가 있다(실제로 여기서 73.56원이 나왔는데 정본은 73.27원).
#   scenario_results.csv에 저장된 값은 더 오래 돌려 검증한 실행가능해이므로,
#   더 낮은 쪽을 기준선으로 삼는다. 막대는 기준선과의 차이로 그리므로
#   기준이 흔들리면 모든 막대가 함께 틀어진다.
_res = pd.read_csv(f"{OUT}/scenario_results.csv").query("ID == @REP['ID']")
if len(_res):
    stored_u, stored_n = float(_res.iloc[0]["단위비용"]), int(_res.iloc[0]["n"])
    if stored_u < base_u - 1e-9:
        print(f"  기준 보정: 재계산 {base_u:.2f}원 -> 저장값 {stored_u:.2f}원 "
              f"(n {int(base_n)} -> {stored_n})")
        base_u, base_n = stored_u, stored_n
print(f"  기준: {base_u:.2f}원/박스, n={int(base_n)}\n")

for vname, v0, unit, kind in VARS:
    for sign, lbl in [(-1, "-30%"), (+1, "+30%")]:
        if (vname, lbl) in done:
            u, n = done[(vname, lbl)]
            print(f"  {vname:<14}{lbl:>5} (캐시) {u:>7.2f}원  n={int(n)}")
            continue
        v = v0 * (1 + sign * PCT)
        c, am, tm = dict(BASE_COST), None, None
        if kind == "cost":
            c[vname] = v
        elif kind == "am":
            am = v
        else:
            tm = v
        u, n = run(cost=c, am=am, tm=tm)
        rows.append(dict(변수=vname, 방향=lbl, 단위비용=u, n=n)); save()
        if u is None:
            print(f"  {vname:<14}{lbl:>5} ({v:>8.1f} {unit:<6}) 해 없음/시간초과", flush=True)
        else:
            print(f"  {vname:<14}{lbl:>5} ({v:>8.1f} {unit:<6}) "
                  f"{u:>7.2f}원  ({u-base_u:+6.2f})  n={int(n)}", flush=True)

# ── 토네이도 차트 ──────────────────────────────────────────
df = pd.DataFrame(rows)
df = df[df["변수"] != "기준"].dropna(subset=["단위비용"])
piv = df.pivot(index="변수", columns="방향", values="단위비용")
npv = df.pivot(index="변수", columns="방향", values="n")
piv["swing"] = (piv.max(axis=1) - piv.min(axis=1))
piv = piv.sort_values("swing")          # 아래에서 위로 커지게
order = list(piv.index)

fig, ax = plt.subplots(figsize=(13, 7.2))
C_LOW, C_HIGH = "#1565C0", "#C62828"
for y, v in enumerate(order):
    for lbl, col in [("-30%", C_LOW), ("+30%", C_HIGH)]:
        u = piv.loc[v, lbl]
        if pd.isna(u):
            continue
        left, width = min(base_u, u), abs(u - base_u)
        ax.barh(y, width, left=left, height=0.62, color=col, alpha=0.88,
                edgecolor="white", linewidth=0.8, zorder=3)
        nn = npv.loc[v, lbl]
        tag = f"{u:.1f}원" + (f" · n={int(nn)}" if not pd.isna(nn) else "")
        ax.annotate(tag, (u, y), fontsize=9, fontweight="bold", color=col,
                    va="center", ha="left" if u > base_u else "right",
                    xytext=(5 if u > base_u else -5, 0),
                    textcoords="offset points", zorder=5)

ax.axvline(base_u, color="#212121", linewidth=2.0, zorder=4)
# 기준 라벨은 맨 위 막대와 겹치므로 아래쪽 여백에 둔다
ax.annotate(f"기준 {base_u:.2f}원 (n={int(base_n)})", (base_u, -0.62),
            fontsize=10.5, fontweight="bold", ha="center", va="bottom",
            bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#212121", lw=1.2),
            zorder=6)

unit_of = {v: u for v, _, u, _ in VARS}
base_of = {v: b for v, b, _, _ in VARS}
ax.set_yticks(range(len(order)))
ax.set_yticklabels([f"{v}\n({base_of[v]:,} {unit_of[v]})" for v in order], fontsize=10)
ax.set_xlabel("단위비용 (원/박스)", fontsize=12)
ax.grid(axis="x", alpha=0.3, zorder=0)
ax.set_axisbelow(True)
lo, hi = piv[["-30%", "+30%"]].min().min(), piv[["-30%", "+30%"]].max().max()
pad = (hi - lo) * 0.16
ax.set_xlim(lo - pad, hi + pad)
ax.set_ylim(-0.7, len(order) - 0.1)
# 범례에 U+2212(−)를 쓰면 Malgun Gothic에 없어 네모로 깨진다 — ASCII 하이픈 사용
ax.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=C_LOW, label="변수 -30%"),
                   plt.Rectangle((0, 0), 1, 1, color=C_HIGH, label="변수 +30%"),
                   Line2D([0], [0], color="#212121", lw=2, label="기준(대표 시나리오)")],
          loc="lower right", fontsize=10, framealpha=0.95)
top = piv.index[-1]
ax.set_title(f"변수 민감도 토네이도 — {REP['ID']} "
             f"({REP['cars']}칸x{REP['trips']}회, 분담률 {REP['share']:.0%}, 허브 {int(base_n)}개)\n"
             f"각 변수를 ±30% 흔들었을 때 단위비용 변화 — 영향이 가장 큰 변수는 {top}",
             fontsize=14, fontweight="bold", pad=12)
fig.text(0.5, 0.012,
         "막대 끝의 n = 그 조건에서 다시 최적화한 허브 수 · "
         "비용 곡선이 평탄해(n=17~20이 0.2% 안) n 변화는 경향으로만 읽을 것 · "
         f"gapRel={GAP}",
         ha="center", fontsize=9, color="#555555")
plt.tight_layout(rect=[0, 0.035, 1, 1])
nc.savefig_retry(plt, f"{OUT}/tornado_sensitivity.png", dpi=180)
plt.close(fig)

print("\n[3] 영향 큰 순")
for v in reversed(order):
    lo_, hi_ = piv.loc[v, "-30%"], piv.loc[v, "+30%"]
    print(f"  {v:<14} 변동폭 {piv.loc[v,'swing']:5.2f}원 "
          f"({min(lo_,hi_):.2f} ~ {max(lo_,hi_):.2f}) "
          f"| n {int(npv.loc[v,'-30%'])} ~ {int(npv.loc[v,'+30%'])}")
print(f"\n저장: {OUT}\\tornado_sensitivity.png, {CACHE}")
