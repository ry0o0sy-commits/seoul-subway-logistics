"""
엘보우 분석 재실행 — S39 조건(4칸 x 5회, 분담률 12%), n 범위 확대
────────────────────────────────────────────────────────────
step2.py의 엘보우 분석은 n=1~15까지만 봤는데, S39가 자유탐색(n<=n_max)에서
n*=14를 고른 터라 "14가 진짜 엘보우인지, 아니면 평탄 구간의 한 점인지"를
15까지만으로는 판별할 수 없다. n을 1~25로 넓혀 곡선이 다시 올라가는지까지
확인한다.

곁들여 n별 허브 위치 지도(elbow_hub_maps.png)도 이 스크립트에서 같이
갱신한다 — step2.py 섹션 7과 같은 스타일(행정동/자치구/서울외곽 + 1~4호선
배경, 이중 원 마커)이되, 강조할 패널은 이번 분석 결과에서 판정한 엘보우로
바꾼다.

MILP는 다시 푼다(엘보우는 n을 정확히 고정해 매번 재최적화해야 하므로).
네트워크/심도/임대료는 network_common으로 step2.py와 동일하게 구축.
"""

import os
import re
import sys
import numpy as np
import pandas as pd
import pulp
import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams["font.family"] = "Malgun Gothic"
matplotlib.rcParams["axes.unicode_minus"] = False
import matplotlib.pyplot as plt
import network_common as nc

OUT = nc.OUT
BASE = nc.BASE

REP_ID = nc.REP_SCENARIO["base_id"]      # 시나리오 축(4칸x5회, 12%)의 자유탐색 결과
ADOPTED_N = nc.REP_SCENARIO["n_hubs"]    # 실제 채택한 허브 개수 — 이 지점을 강조
N_RANGE = range(1, 31)          # ★ 1~30 (25 -> 30으로 확대: 최저점 n=18 뒤의
                                #   상승 구간을 길게 보여줘 극소점이 시각적으로
                                #   분명해지도록. 곡선이 평탄해 짧게 자르면
                                #   "계속 내려가는 중"으로 오해될 수 있다.)
BOX_PER_CAR, COST_PER_KM, TRUCK_CAP = 1_500, 1_500, 200
ALPHA_LABOR, ALPHA_RAIL, UNLOAD_RATE = 270, 700, 450
AVAILABLE_MIN, TURNAROUND_MIN = nc.AVAILABLE_MIN, nc.TURNAROUND_MIN
ELEV_SPEED_MPM, ELEV_CAPACITY = 30, 50

print("[1] 네트워크/데이터 로드")
net = nc.load_all()
stations = net["stations"]
rail_t, hub_dir, OK = net["rail_t"], net["hub_dir"], net["OK"]
DIRECTIONS, DIR_ROUND_TRIP, MAX_TRIPS = net["DIRECTIONS"], net["DIR_ROUND_TRIP"], net["MAX_TRIPS"]
station_depth, rent_daily = net["station_depth"], net["rent_daily"]

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
N_ST, N_D = len(stations), len(dongs)

srow = pd.read_csv(f"{OUT}/scenario_results.csv").query("ID == @REP_ID").iloc[0]
REP_CARS, REP_TRIPS, REP_SHARE = int(srow["칸"]), int(srow["운행"]), float(srow["분담률"])
rep_w = W * REP_SHARE
rep_total = rep_w.sum()
print(f"    {REP_ID}: {REP_CARS}칸x{REP_TRIPS}회, 분담률 {REP_SHARE:.0%}, "
      f"필요물량 {rep_total:,.0f}박스/일, 자유탐색 n*={int(srow['n'])}")


COST = dict(BOX_PER_CAR=BOX_PER_CAR, COST_PER_KM=COST_PER_KM, TRUCK_CAP=TRUCK_CAP,
            ALPHA_LABOR=ALPHA_LABOR, ALPHA_RAIL=ALPHA_RAIL, UNLOAD_RATE=UNLOAD_RATE,
            ELEV_SPEED_MPM=ELEV_SPEED_MPM, ELEV_CAPACITY=ELEV_CAPACITY)


# ★ gap_rel을 0.02 -> 0.002로 조였다. 라스트마일을 왕복으로 고친 뒤 비용
#   곡선이 매우 평탄해져(n=15~22가 1.5% 안) 허용오차 2%가 곡선의 기복보다
#   커졌고, 그 상태에서는 최저점이 실행할 때마다 튀었다(n=20이 최저로 나오고
#   n=21에서 급등하는 등). 0.2%로 조이면 n=18을 바닥으로 하는 매끄러운
#   U자 곡선이 나온다. 대신 조합당 시간이 늘어 time_limit도 함께 키웠다.
#   ※ time_limit을 240 -> 400으로 올렸다. 240초에서는 n=18이 10.683백만으로
#     나온 적이 있는데, 같은 조건을 300·600초로 풀면 10.640백만이 나온다.
#     gapRel을 조여도 제한시간 안에 그 해를 못 찾으면 곡선이 위로 튄다.
def solve(w, cars, trips, n, exact=True, time_limit=400, gap_rel=0.002):
    """MILP 본체는 network_common.solve_hub_location() 공유(step2.py와 동일 수식)."""
    return nc.solve_hub_location(
        w, cars, trips, n,
        dist=dist, OK=OK, hub_dir=hub_dir, rail_t=rail_t,
        DIRECTIONS=DIRECTIONS, DIR_ROUND_TRIP=DIR_ROUND_TRIP,
        station_depth=station_depth, rent_daily=rent_daily,
        exact=exact, cost=COST, time_limit=time_limit, gap_rel=gap_rel)


# --skip-solve: MILP를 다시 풀지 않고 저장된 결과(elbow_results.csv,
#   elbow_hub_locations.csv)를 읽어 그림만 다시 그린다. 그림 스타일을
#   손볼 때 25회 MILP를 매번 돌리는 건 낭비라 넣어둔 옵션이다.
SKIP_SOLVE = "--skip-solve" in sys.argv

if SKIP_SOLVE:
    print("\n[2] 엘보우 분석 — 저장된 결과 재사용(--skip-solve)")
    elbow_df = pd.read_csv(f"{OUT}/elbow_results.csv")
    _loc = pd.read_csv(f"{OUT}/elbow_hub_locations.csv")
    elbow_hubs = {int(r["n"]): [x.strip() for x in r["허브목록"].split(",")]
                  for _, r in _loc.iterrows()}
    print(f"    n = {sorted(elbow_hubs)} 재사용")
else:
    print(f"\n[2] 엘보우 분석 — n = {N_RANGE.start}~{N_RANGE.stop - 1} (정확히 n개 고정)")
    rows, elbow_hubs = [], {}
    for n in N_RANGE:
        r = solve(rep_w, REP_CARS, REP_TRIPS, n)
        if r is None:
            print(f"  n={n:2d} | 해 없음(불가능)")
            continue
        unit = r["Z"] / rep_total
        elbow_hubs[n] = stations.loc[r["hubs"], "역명"].tolist()
        rows.append(dict(n=n, 총비용=r["Z"], 단위비용=unit))
        print(f"  n={n:2d} | {r['Z']/1e6:7.3f}백만원/일 | {unit:6.2f}원/박스")

    elbow_df = pd.DataFrame(rows)
    elbow_df["한계개선"] = -elbow_df["총비용"].diff()
    elbow_df.to_csv(f"{OUT}/elbow_results.csv", index=False, encoding="utf-8-sig")

# ── 엘보우 판정 ──────────────────────────────────────────────────
# "직전 n 대비 총비용 개선폭이 최저비용의 0.5% 미만으로 떨어지는 첫 지점"을
# 실무적 엘보우로 본다(그 뒤로는 허브를 더 늘려도 비용이 사실상 안 준다).
# 채택 기준은 단순하게 — 총비용 곡선의 최저점.
#   (한때 "최저비용 대비 0.5% 이내면 동률로 보고 최소 규모 채택"이라는 임의
#    기준을 썼는데, 반올림한 값을 동률로 오인한 착오였다. 군더더기 없이
#    최저점을 채택으로 삼는다.)
#   ★ 라스트마일 편도->왕복 수정 후 곡선이 매우 평탄해졌다(n=15~22가 1.5% 안).
#     그래서 위 solve()의 gap_rel을 0.002로 조여야 최저점이 안정적으로 잡힌다.
#     느슨한 2%에서는 실행마다 최저점이 튀었다(n=20이 최저로 나오고 n=21에서
#     급등하는 등). 현재 기준 최저점은 n=18이다.
best_n_row = elbow_df.loc[elbow_df["총비용"].idxmin()]
adopted_n = int(best_n_row["n"])
free_n = int(srow["n"])

print(f"\n[3] 채택 허브 개수")
print(f"  총비용 최저점 : n={adopted_n} ({best_n_row['총비용']:,.0f}원/일, "
      f"{best_n_row['단위비용']:.2f}원/박스)  <- 채택")
nb = elbow_df[elbow_df["n"].isin([adopted_n - 1, adopted_n + 1])]
for _, r in nb.iterrows():
    print(f"    비교 n={int(r['n'])}: {r['총비용']:,.0f}원/일 ({r['단위비용']:.2f}원/박스)")
if free_n != adopted_n:
    print(f"  ! 격자 자유탐색 n*={free_n}와 다름 — 확인 필요")
else:
    print(f"  격자 자유탐색 n*={free_n}와 일치")

loc_rows, prev = [], set()
for n in sorted(elbow_hubs):
    cur = set(elbow_hubs[n])
    loc_rows.append(dict(n=n, 허브목록=", ".join(sorted(cur)),
                         신규추가=", ".join(sorted(cur - prev)) or "-",
                         빠짐=", ".join(sorted(prev - cur)) or "-"))
    prev = cur
loc_df = pd.DataFrame(loc_rows)
loc_df.to_csv(f"{OUT}/elbow_hub_locations.csv", index=False, encoding="utf-8-sig")
print(f"\n저장: {OUT}\\elbow_results.csv, elbow_hub_locations.csv")


# ══════════════════════════════════════════════════════════
# 4. 비용 곡선 그래프
# ══════════════════════════════════════════════════════════
fig, ax = plt.subplots(1, 3, figsize=(17, 4.6))

ADOPT_COLOR = "#B71C1C"

ax[0].plot(elbow_df["n"], elbow_df["총비용"] / 1e6, "o-", color="#0072B2")
ax[0].axvline(adopted_n, color=ADOPT_COLOR, ls="--", lw=1.8,
             label=f"채택 n={adopted_n} (최저점)")
ax[0].plot([adopted_n], [best_n_row["총비용"] / 1e6], "o", color=ADOPT_COLOR,
          markersize=11, markerfacecolor="none", markeredgewidth=2.2)
ax[0].set(xlabel="허브 개수 n", ylabel="총비용 (백만원/일)", title="허브 개수별 총비용")
ax[0].legend(fontsize=9); ax[0].grid(alpha=.3)

ax[1].plot(elbow_df["n"], elbow_df["단위비용"], "o-", color="#D55E00")
ax[1].axvline(adopted_n, color=ADOPT_COLOR, ls="--", lw=1.8)
ax[1].plot([adopted_n], [best_n_row["단위비용"]], "o", color=ADOPT_COLOR,
          markersize=11, markerfacecolor="none", markeredgewidth=2.2)
ax[1].set(xlabel="허브 개수 n", ylabel="단위비용 (원/박스)", title="허브 개수별 단위비용")
ax[1].grid(alpha=.3)

# 한계 비용개선 — 양수면 허브를 늘려 비용이 준 것, 음수면 오히려 늘어난 것.
# 채택 지점 다음부터 음수가 우세해지는지를 본다(별도 기준선은 두지 않는다).
bars = ax[2].bar(elbow_df["n"].iloc[1:], elbow_df["한계개선"].iloc[1:] / 1e3,
                 color=["#009E73" if v > 0 else "#D55E00"
                        for v in elbow_df["한계개선"].iloc[1:]])
ax[2].axvline(adopted_n, color=ADOPT_COLOR, ls="--", lw=1.8)
ax[2].axhline(0, color="#666666", lw=0.8)
ax[2].set(xlabel="허브 개수 n", ylabel="직전 n 대비 비용개선 (천원/일)",
         title="한계 비용개선 — 채택 지점 이후 음수(비용 증가)로 전환")
ax[2].grid(alpha=.3, axis="y")

plt.suptitle(f"허브 개수 엘보우 분석 — {REP_ID} ({REP_CARS}칸x{REP_TRIPS}회, 분담률 {REP_SHARE:.0%})",
            fontsize=13, fontweight="bold")
plt.tight_layout()
nc.savefig_retry(plt, f"{OUT}/elbow.png", dpi=150, bbox_inches="tight")
plt.close(fig)
print(f"저장: {OUT}\\elbow.png")


# ══════════════════════════════════════════════════════════
# 5. n별 허브 위치 지도
# ══════════════════════════════════════════════════════════
import geopandas as gpd

feasible_ns = sorted(elbow_hubs)
show_n = sorted(set([feasible_ns[0], max(feasible_ns[0], adopted_n - 5),
                     max(feasible_ns[0], adopted_n - 2), adopted_n, feasible_ns[-1]]))
show_n = [n for n in show_n if n in elbow_hubs][:5]
print(f"\n[5] n별 허브 위치 지도: n = {show_n}")

shp = gpd.read_file(os.path.join(BASE, "행정동.shp"), encoding="utf-8")
shp["ADM_CD"] = shp["ADM_CD"].astype(str)
geo_dong = shp[shp["ADM_CD"].str.startswith("11")].to_crs(epsg=4326)
geo_dong["GU_KEY"] = geo_dong["ADM_CD"].str[:5]
geo_gu = geo_dong.dissolve(by="GU_KEY").reset_index()
geo_seoul = gpd.GeoDataFrame(geometry=[geo_dong.union_all()], crs=geo_dong.crs)

station_coords = {}
for _, r in stations.iterrows():
    station_coords.setdefault(r["역명_clean"], (r["경도"], r["위도"]))

seg = net["seg"]
ALL_LINE_EDGES = {}
for ln in ["1", "2", "3", "4"]:
    sub = seg[seg["호선"] == ln].reset_index(drop=True)
    prev_node, edges = None, []
    for _, row in sub.iterrows():
        node = (ln, row["역명"])
        parent = nc.BRANCH_PARENT_OVERRIDE.get(node, prev_node)
        if parent is not None and parent != node:
            p_xy, n_xy = station_coords.get(parent[1]), station_coords.get(node[1])
            if p_xy and n_xy:
                edges.append((p_xy, n_xy))
        prev_node = node
    ALL_LINE_EDGES[ln] = edges

def draw_bg(ax, xlim, ylim, facecolor="#f5f5f5"):
    ax.set_facecolor(facecolor)
    geo_dong.cx[xlim[0]:xlim[1], ylim[0]:ylim[1]].plot(
        ax=ax, facecolor=facecolor, edgecolor="#999999", linewidth=0.4, alpha=0.4, zorder=0)
    geo_gu.cx[xlim[0]:xlim[1], ylim[0]:ylim[1]].plot(
        ax=ax, facecolor="none", edgecolor="#999999", linewidth=0.7, alpha=0.7, zorder=1)
    geo_seoul.plot(ax=ax, facecolor="none", edgecolor="#333333", linewidth=1.2, alpha=0.8, zorder=1)
    for ln, edges in ALL_LINE_EDGES.items():
        c = nc.LINE_COLORS[ln]
        for (x1, y1), (x2, y2) in edges:
            ax.plot([x1, x2], [y1, y2], color=c, linewidth=1.8, alpha=0.25, zorder=1.2,
                    solid_capstyle="round")

fig, axes = plt.subplots(1, len(show_n), figsize=(5 * len(show_n), 5.8), sharex=True, sharey=True)
if len(show_n) == 1:
    axes = [axes]

cand_idx = [j for j in range(N_ST) if OK[j]]
cand_lon, cand_lat = stations.loc[cand_idx, "경도"], stations.loc[cand_idx, "위도"]
pad_x = (cand_lon.max() - cand_lon.min()) * 0.05
pad_y = (cand_lat.max() - cand_lat.min()) * 0.05
xlim = (cand_lon.min() - pad_x, cand_lon.max() + pad_x)
ylim = (cand_lat.min() - pad_y, cand_lat.max() + pad_y)

# 허브는 노선 구분 없이 한 가지 색으로 그린다 — 이 그림의 목적은 "n이 늘면서
# 허브가 어디로 퍼지는가"이지 어느 노선 소속인지가 아니라, 색을 나누면 오히려
# 시선이 분산된다(1호선 신규역 강조는 뺐다).
for ax, n in zip(axes, show_n):
    is_adopted = (n == adopted_n)
    draw_bg(ax, xlim, ylim, facecolor="#fffbf0" if is_adopted else "#f5f5f5")
    ax.scatter(cand_lon, cand_lat, s=5, color="lightgray", alpha=0.4, label="후보역", zorder=2)
    hub_names = set(elbow_hubs[n])
    sel = stations[stations["역명"].isin(hub_names)]
    ax.scatter(sel["경도"], sel["위도"], s=90, color="white", zorder=3)
    ax.scatter(sel["경도"], sel["위도"], s=50, color="crimson", label="허브", zorder=4)
    for _, row in sel.iterrows():
        ax.annotate(row["역명"], (row["경도"], row["위도"]), fontsize=7,
                    xytext=(3, 3), textcoords="offset points", zorder=5)
    ax.set_xlim(*xlim); ax.set_ylim(*ylim)
    unit_here = elbow_df.loc[elbow_df["n"] == n, "단위비용"].values[0]
    title = f"n = {n}  ({unit_here:.1f}원/박스)"
    if is_adopted:
        ax.set_title(title + "  ★ 채택", fontsize=12, fontweight="bold", color="#B71C1C")
        for sp in ax.spines.values():
            sp.set_visible(True); sp.set_linewidth(3); sp.set_color("#B71C1C")
    else:
        ax.set_title(title, fontsize=12, fontweight="bold")
        for sp in ax.spines.values():
            sp.set_visible(False)
    ax.set_xticks([]); ax.set_yticks([])
axes[0].legend(loc="upper left", fontsize=8)
_prev = elbow_df[elbow_df["n"] == adopted_n - 1]
_next = elbow_df[elbow_df["n"] == adopted_n + 1]
_cmp = []
if len(_prev):
    _cmp.append(f"n={adopted_n-1} {_prev.iloc[0]['총비용']/1e6:.3f}백만원")
_cmp.append(f"n={adopted_n} {best_n_row['총비용']/1e6:.3f}백만원(최저)")
if len(_next):
    _cmp.append(f"n={adopted_n+1} {_next.iloc[0]['총비용']/1e6:.3f}백만원")
fig.text(0.5, -0.02,
        f"{REP_ID}({REP_CARS}칸x{REP_TRIPS}회, 분담률 {REP_SHARE:.0%}) 기준. "
        f"총비용 곡선의 최저점을 채택: " + " < ".join(_cmp) + ".",
        ha="center", fontsize=9, color="#555555")
plt.tight_layout()
nc.savefig_retry(plt, f"{OUT}/elbow_hub_maps.png", dpi=150, bbox_inches="tight")
plt.close(fig)
print(f"저장: {OUT}\\elbow_hub_maps.png")
