# -*- coding: utf-8 -*-
"""
시나리오 3차원 곡면 — 칸수·운행횟수·분담률 x 단위비용 (발표·전시용)
────────────────────────────────────────────────────────────
설계 변수가 3개(칸수·운행횟수·분담률)라 단위비용까지 넣으면 4차원이 된다.
변수를 2개씩 묶고 나머지 하나를 대표 시나리오 값으로 고정해 3장으로 나눈다.

  (A) x=칸수,     y=운행횟수, z=단위비용   — 분담률 12% 고정
  (B) x=칸수,     y=분담률,   z=단위비용   — 운행 5회 고정
  (C) x=운행횟수, y=분담률,   z=단위비용   — 칸수 4 고정

[보간 — 반드시 캡션에 명시할 것]
원본 격자가 4x3 / 4x4 수준이라 그대로 그리면 각진 다면체가 된다. 발표·전시용
완성도를 위해 scipy.interpolate.griddata로 120x120까지 세밀화한다(cubic,
실패 시 linear 폴백). **곡면은 실측값이 아니라 실측 격자점을 보간한 것**이므로
실제로 계산한 지점은 검은 점으로 곡면 위에 그대로 찍어 구분할 수 있게 한다.

[구멍 처리 — 별도 마스킹을 하지 않는다]
griddata는 입력점의 볼록껍질(convex hull) 바깥을 NaN으로 남긴다. 이 격자에서
값이 없는 조합(1칸x분담률 12% 등)은 전부 격자 가장자리에 몰려 있어, 별도
마스킹 없이도 자연히 곡면 밖으로 빠진다. 인위적으로 원형 구멍을 뚫으면
매끄러움만 해치고 정보는 늘지 않으므로 그렇게 하지 않았고, 대신 바닥면에
회색 X로 "여기에 값이 없다"를 표시한다.

실행: python step2_scenario_surface3d.py
출력: output_data/scenario_surface3d.png
"""
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams["font.family"] = "Malgun Gothic"
matplotlib.rcParams["axes.unicode_minus"] = False
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401
from scipy.interpolate import griddata
import network_common as nc

OUT = nc.OUT
REP = nc.REP_SCENARIO
CMAP = "viridis_r"          # 낮을수록 밝게(좋은 쪽이 눈에 먼저 들어오게)
GRID = 120                  # 보간 해상도
ELEV, AZIM = 25, -60

res = pd.read_csv(f"{OUT}/scenario_results.csv")
res = res[res["ID"] != nc.MAX_SCENARIO_ID]
ok = res[res["실행가능"] == True]

CARS = sorted(res["칸"].unique())
TRIPS = sorted(res["운행"].unique())
SHARES = sorted(res["분담률"].unique())
full = len(CARS) * len(TRIPS) * len(SHARES)
print(f"격자: 칸 {len(CARS)} x 운행 {len(TRIPS)} x 분담률 {len(SHARES)}")
print(f"  존재 {len(res)}행 / 완전격자 {full} "
      f"(미계산 {full - len(res)}, 실행불가 {len(res) - len(ok)})")

REPV = dict(칸=REP["cars"], 운행=REP["trips"], 분담률=REP["share"])
PANELS = [
    ("(A) 분담률 12% 고정", "칸", "운행", "분담률", REPV["분담률"],
     "화물 전용 칸수", "야간 운행횟수"),
    ("(B) 운행 5회 고정", "칸", "분담률", "운행", REPV["운행"],
     "화물 전용 칸수", "지하철 분담률"),
    ("(C) 칸수 4 고정", "운행", "분담률", "칸", REPV["칸"],
     "야간 운행횟수", "지하철 분담률"),
]

vmin, vmax = ok["단위비용"].min(), ok["단위비용"].max()
span = vmax - vmin
fig = plt.figure(figsize=(20, 6.8))
n_hole_total, used_cubic = 0, True

for pi, (title, xk, yk, fixk, fixv, xlab, ylab) in enumerate(PANELS, 1):
    ax = fig.add_subplot(1, 3, pi, projection="3d")
    sub = res[np.isclose(res[fixk], fixv)]
    xs = sorted(res[xk].unique())
    ys = sorted(res[yk].unique())

    pts, vals, holes = [], [], []
    for j, yv in enumerate(ys):
        for i, xv in enumerate(xs):
            m = sub[np.isclose(sub[xk], xv) & np.isclose(sub[yk], yv)]
            if len(m) and bool(m.iloc[0]["실행가능"]):
                pts.append((i, j)); vals.append(float(m.iloc[0]["단위비용"]))
            else:
                holes.append((i, j))
    n_hole_total += len(holes)
    P = np.array(pts, dtype=float)
    V = np.array(vals, dtype=float)

    gx = np.linspace(0, len(xs) - 1, GRID)
    gy = np.linspace(0, len(ys) - 1, GRID)
    GX, GY = np.meshgrid(gx, gy)
    Z = griddata(P, V, (GX, GY), method="cubic")
    if np.all(np.isnan(Z)):                      # 점이 적으면 cubic이 실패한다
        Z = griddata(P, V, (GX, GY), method="linear")
        used_cubic = False
    else:                                        # cubic이 남긴 가장자리 NaN만 보강
        lin = griddata(P, V, (GX, GY), method="linear")
        Z = np.where(np.isnan(Z), lin, Z)

    zfloor = vmin - span * 0.28
    # 바닥 등고선 — 곡면 아래 그림자처럼 깔려 입체감을 준다
    if np.isfinite(Z).any():
        ax.contourf(GX, GY, Z, levels=18, zdir="z", offset=zfloor,
                    cmap=CMAP, vmin=vmin, vmax=vmax, alpha=0.45)
    ax.plot_surface(GX, GY, Z, cmap=CMAP, vmin=vmin, vmax=vmax,
                    rstride=1, cstride=1, edgecolor="none", linewidth=0,
                    alpha=0.9, antialiased=True, shade=True, zorder=3)

    # 실측 격자점 — 곡면이 보간이라는 사실을 눈으로 구분할 수 있게
    ax.scatter(P[:, 0], P[:, 1], V, s=22, color="#111111",
               depthshade=False, zorder=6)
    for i, j in holes:
        ax.scatter([i], [j], [zfloor], s=52, marker="x", color="#8A8A8A",
                   linewidth=1.8, depthshade=False, zorder=7)

    # 대표 시나리오 — 후광 + 수직 지시선 + 뱃지
    rx = xs.index(REPV[xk]) if REPV[xk] in xs else None
    ry = ys.index(REPV[yk]) if REPV[yk] in ys else None
    if rx is not None and ry is not None:
        hit = [v for (a, b), v in zip(pts, vals) if a == rx and b == ry]
        if hit:
            zv = hit[0]
            ztop = vmax + span * 0.10
            for s, al in [(430, 0.10), (300, 0.16), (200, 0.26)]:   # 후광
                ax.scatter([rx], [ry], [zv], s=s, color="#D32F2F",
                           alpha=al, depthshade=False, zorder=8)
            ax.plot([rx, rx], [ry, ry], [zv, ztop], color="#D32F2F",
                    linewidth=1.0, linestyle=":", zorder=9)
            ax.scatter([rx], [ry], [zv], s=130, color="#D32F2F",
                       edgecolor="white", linewidth=1.5,
                       depthshade=False, zorder=10)
            ax.text(rx, ry, ztop, f"{REP['ID']} {zv:.1f}원", color="#D32F2F",
                    fontsize=10.5, fontweight="bold", ha="center", va="bottom",
                    bbox=dict(boxstyle="round,pad=0.25", fc="white",
                              ec="#D32F2F", lw=1.0, alpha=0.95), zorder=11)

    ax.set_xticks(range(len(xs)))
    ax.set_xticklabels([f"{v:.0%}" if xk == "분담률" else f"{int(v)}" for v in xs],
                       fontsize=9.5)
    ax.set_yticks(range(len(ys)))
    ax.set_yticklabels([f"{v:.0%}" if yk == "분담률" else f"{int(v)}" for v in ys],
                       fontsize=9.5)
    ax.set_xlabel(xlab, fontsize=10.5, labelpad=7)
    ax.set_ylabel(ylab, fontsize=10.5, labelpad=7)
    ax.set_zlabel("단위비용 (원/박스)", fontsize=10.5, labelpad=5)
    ax.set_zlim(zfloor, vmax + span * 0.20)
    ax.set_title(title + (f"   (값 없음 {len(holes)}칸)" if holes else ""),
                 fontsize=13.5, fontweight="bold", pad=-2)
    ax.view_init(elev=ELEV, azim=AZIM)
    ax.tick_params(labelsize=9.5)

    # 배경 패널·격자선을 연하게 — 곡면이 주인공이 되도록
    for pane, axis in [(ax.xaxis, "x"), (ax.yaxis, "y"), (ax.zaxis, "z")]:
        pane.set_pane_color((0.985, 0.985, 0.99, 1.0))
        pane._axinfo["grid"].update(color="#D8D8DD", linewidth=0.6)

# 컬러바는 전용 축에 따로 둔다 — ax=fig.axes로 붙이면 3D 축의 z라벨 위에
# 겹쳐 눈금이 읽히지 않았다.
sm = plt.cm.ScalarMappable(cmap=CMAP, norm=plt.Normalize(vmin=vmin, vmax=vmax))
cax = fig.add_axes([0.955, 0.24, 0.010, 0.50])
cb = fig.colorbar(sm, cax=cax)
cb.set_label("단위비용 (원/박스)", fontsize=11, labelpad=10)
cb.ax.set_title("낮을수록\n유리", fontsize=9, color="#555555", pad=8)
cb.outline.set_linewidth(0.4)

fig.suptitle(f"시나리오 3차원 곡면 — 설계변수 2개씩 x 단위비용 "
             f"(고정값은 대표 시나리오 {REP['ID']}: "
             f"{REP['cars']}칸x{REP['trips']}회, 분담률 {REP['share']:.0%})",
             fontsize=15.5, fontweight="bold", y=0.985)
fig.text(0.5, 0.015,
         f"곡면은 실측 격자점을 보간한 것(griddata "
         f"{'cubic' if used_cubic else 'linear'}, {GRID}x{GRID}) — 격자 사이 값은 계산값이 아니다 · "
         "검은 점 = 실제로 계산한 격자점 · "
         f"회색 X = 값이 없는 조합(수송능력 부족으로 미계산 또는 실행불가, 3개 패널 합계 {n_hole_total}칸) "
         "— 보간 영역이 실측점의 볼록껍질로 한정돼 곡면에서 자연히 제외됨 · 빨간 점 = 대표 시나리오",
         ha="center", fontsize=9.5, color="#555555")
plt.subplots_adjust(left=0.01, right=0.935, top=0.86, bottom=0.06, wspace=0.03)
nc.savefig_retry(plt, f"{OUT}/scenario_surface3d.png", dpi=180)
plt.close(fig)
print(f"보간: griddata {'cubic' if used_cubic else 'linear'} ({GRID}x{GRID})")
print(f"저장: {OUT}\\scenario_surface3d.png")
