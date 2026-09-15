"""
scenario.png 재설계 — x축(총 수송능력)에 서로 다른 (칸,운행) 조합이 뒤섞여
꺾은선이 톱니처럼 튀는 문제 해결
────────────────────────────────────────────────────────────
기존 scenario.png는 "총 수송능력"을 x축으로 두고 분담률별로 선을 이었는데,
예컨대 2칸x15회와 3칸x10회처럼 비용구조가 전혀 다른 조합이 총 수송능력만
비슷해 x축상 인접해버려 선으로 이으면 의미 없는 지그재그가 된다. 애초에
이산적인 (칸,운행,분담률) 조합 집합이라 "연속 곡선"으로 그리는 것 자체가
잘못된 인코딩이었다.

대신 두 가지를 새로 그린다(교수님 피드백의 대안2/3 — 발표에 더 적합하다고
판단해 둘 다 만듦, 선 연결형인 대안1은 채택하지 않음):
  1. scenario_heatmap.png — 분담률별 (칸 x 운행) 그리드에 단위비용을
     색으로 표시. "어떤 조합이 유리한가"를 한눈에 보여준다. 실행불가
     조합은 회색 해칭으로 표시(값이 없다는 뜻이지 0이 아님을 명확히).
  2. scenario_ranked.png — 실행가능 시나리오를 단위비용 오름차순으로
     정렬한 가로 막대. "왜 그 시나리오가 뽑혔나"(가장 단위비용이 낮은 실행가능
     조합)를 가장 직관적으로 보여준다.

MILP를 다시 풀지 않는다 — 이미 저장된 scenario_results.csv를 그대로 쓴다.
SMAX(대표 시나리오와 비교용으로 별도 탐색된, 더 높은 분담률의
시나리오)는 이 두 그림이 다루는 "SHARES=[4,8,12,16%] x TRIPS x CARS 정례
스윕"의 일부가 아니므로 제외한다(emission 비교에서 이미 별도로 다룸).
"""

import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams["font.family"] = "Malgun Gothic"
matplotlib.rcParams["axes.unicode_minus"] = False
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.lines import Line2D
import network_common as nc   # savefig 재시도 래퍼만 사용

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "output_data")

df = pd.read_csv(f"{OUT}/scenario_results.csv")
# 정례 스윕(SHARES x TRIPS x CARS)만 남긴다. SMAX(최대 분담률 탐색)는 항상
# 격자 밖이고, 대표 시나리오는 격자 결과를 그대로 쓰는 경우(ID == base_id)와
# 별도로 다시 푼 경우가 있어 후자일 때만 제외한다.
#   — 예전에 대표 ID를 무조건 제외했다가, 대표가 격자 안 시나리오(S39)가 된
#     뒤로 정작 그 행이 그림에서 빠지고 2위가 대표로 표시되는 버그가 났다.
_drop = {nc.MAX_SCENARIO_ID}
if nc.REP_SCENARIO["ID"] != nc.REP_SCENARIO["base_id"]:
    _drop.add(nc.REP_SCENARIO["ID"])
df = df[~df["ID"].isin(_drop)].copy()
ok = df[df["실행가능"] == True].copy()

SHARES = sorted(df["분담률"].unique())
CARS = [1, 2, 3, 4]
TRIPS = [5, 10, 15]

# ★ ID를 박아두지 않는다. 대표 시나리오의 "축"(칸/운행/분담률)은
#   network_common.REP_SCENARIO에서 가져오고, 이 격자에서 그 축에 해당하는
#   행을 찾아 강조한다. 예전엔 REP_ID="S25"로 박아뒀다가 최적 조합이 바뀌자
#   그림 제목("왜 S25가 뽑혔나")과 실제 1위가 어긋나는 사고가 났다.
_R = nc.REP_SCENARIO
_match = ok[(ok["칸"] == _R["cars"]) & (ok["운행"] == _R["trips"]) &
            (np.isclose(ok["분담률"], _R["share"]))]
_rep = _match.iloc[0] if len(_match) else ok.loc[ok["단위비용"].idxmin()]
REP_ID = _rep["ID"]
REP_DESC = f"{int(_rep['칸'])}칸x{int(_rep['운행'])}회, 분담률 {_rep['분담률']:.0%}"
REP_NOTE = f"허브 {int(_rep['n'])}개"
print(f"대표 시나리오: {REP_ID} ({REP_DESC}, {REP_NOTE}, {_rep['단위비용']:.2f}원/박스)")

# 분담률 카테고리 색 — Okabe-Ito 색약 안전 팔레트, 고정 순서(이 저장소의
# 다른 그림들과 동일 팔레트 사용)
SHARE_COLORS = {SHARES[i]: c for i, c in enumerate(
    ["#0072B2", "#D55E00", "#009E73", "#E69F00"][:len(SHARES)])}


# ══════════════════════════════════════════════════════════
# 1. 히트맵 — 분담률별 (칸 x 운행) 그리드, 색=단위비용
# ══════════════════════════════════════════════════════════
vmin, vmax = ok["단위비용"].min(), ok["단위비용"].max()
cmap = plt.cm.OrRd   # 단일 색상(주황) 순차 팔레트 — 값이 클수록 진하게(비쌈)

fig, axes = plt.subplots(1, len(SHARES), figsize=(4.2 * len(SHARES), 4.6))
if len(SHARES) == 1:
    axes = [axes]

for ax, share in zip(axes, SHARES):
    grid = np.full((len(CARS), len(TRIPS)), np.nan)
    for i, cars in enumerate(CARS):
        for j, trips in enumerate(TRIPS):
            row = df[(df["칸"] == cars) & (df["운행"] == trips) & (df["분담률"] == share) & (df["실행가능"] == True)]
            if len(row):
                grid[i, j] = row["단위비용"].values[0]

    im = ax.imshow(grid, cmap=cmap, vmin=vmin, vmax=vmax, aspect="auto")

    # 실행불가/데이터없음 칸 — 회색 해칭(색만으로 구분하지 않음)
    for i in range(len(CARS)):
        for j in range(len(TRIPS)):
            if np.isnan(grid[i, j]):
                ax.add_patch(Rectangle((j - 0.5, i - 0.5), 1, 1, facecolor="#DADADA",
                                       edgecolor="white", hatch="//", linewidth=0.5, zorder=2))
            else:
                ax.text(j, i, f"{grid[i, j]:.0f}", ha="center", va="center",
                       fontsize=11, fontweight="bold",
                       color="white" if grid[i, j] > (vmin + vmax) / 2 else "#333333")

    # 대표 시나리오 강조 — 굵은 테두리
    rep_row = df[df["ID"] == REP_ID]
    if len(rep_row) and rep_row["분담률"].values[0] == share:
        ri = CARS.index(int(rep_row["칸"].values[0]))
        rj = TRIPS.index(int(rep_row["운행"].values[0]))
        ax.add_patch(Rectangle((rj - 0.5, ri - 0.5), 1, 1, facecolor="none",
                               edgecolor="#DC3220", linewidth=3.5, zorder=3))
        ax.text(rj, ri + 0.38, REP_ID, ha="center", va="top", fontsize=9,
               fontweight="bold", color="#DC3220", zorder=4)

    ax.set_xticks(range(len(TRIPS))); ax.set_xticklabels([f"{t}회" for t in TRIPS])
    ax.set_yticks(range(len(CARS))); ax.set_yticklabels([f"{c}칸" for c in CARS])
    ax.set_xlabel("운행횟수"); ax.set_title(f"분담률 {share:.0%}", fontsize=13, fontweight="bold")
    ax.set_xticks(np.arange(-0.5, len(TRIPS), 1), minor=True)
    ax.set_yticks(np.arange(-0.5, len(CARS), 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=1.5)
    ax.tick_params(which="minor", length=0)
axes[0].set_ylabel("칸수")

cbar = fig.colorbar(im, ax=axes, shrink=0.85, pad=0.02)
cbar.set_label("단위비용 (원/박스)")

hatch_legend = Line2D([0], [0], marker="s", color="none", markerfacecolor="#DADADA",
                     markeredgecolor="white", markersize=14, label="실행불가/해당없음")
rep_legend = Line2D([0], [0], marker="s", color="none", markerfacecolor="none",
                   markeredgecolor="#DC3220", markeredgewidth=2.5, markersize=14,
                   label=f"대표 시나리오({REP_ID})")
fig.legend(handles=[hatch_legend, rep_legend], loc="lower center", ncol=2,
          bbox_to_anchor=(0.5, -0.06), fontsize=10, frameon=False)

fig.suptitle("분담률별 (칸수 x 운행횟수) 단위비용 — 어떤 조합이 유리한가", fontsize=14, fontweight="bold", y=1.03)
nc.savefig_retry(plt, f"{OUT}/scenario_heatmap.png", dpi=150, bbox_inches="tight")
plt.close(fig)
print(f"저장: {OUT}\\scenario_heatmap.png")


# ══════════════════════════════════════════════════════════
# 2. 정렬 막대 — 실행가능 시나리오를 단위비용 오름차순, 대표 시나리오 강조
# ══════════════════════════════════════════════════════════
ok_sorted = ok.sort_values("단위비용", ascending=True).reset_index(drop=True)
labels = [f"{int(r.칸)}칸x{int(r.운행)}회, {r.분담률:.0%}" for r in ok_sorted.itertuples()]
colors = [SHARE_COLORS[r.분담률] for r in ok_sorted.itertuples()]
is_rep = ok_sorted["ID"] == REP_ID

fig, ax = plt.subplots(figsize=(10, 0.42 * len(ok_sorted) + 1.5))
y = np.arange(len(ok_sorted))
bars = ax.barh(y, ok_sorted["단위비용"], color=colors, edgecolor="none", height=0.65, zorder=2)

for i, (rep, bar) in enumerate(zip(is_rep, bars)):
    if rep:
        bar.set_edgecolor("#000000")
        bar.set_linewidth(2.5)
        ax.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2,
               f"★ 대표 시나리오({REP_ID}) — {bar.get_width():.1f}원/박스",
               va="center", fontsize=10, fontweight="bold", color="#000000")

ax.set_yticks(y); ax.set_yticklabels(labels, fontsize=9)
ax.invert_yaxis()
ax.set_xlabel("단위비용 (원/박스)")
ax.set_title(f"실행가능 시나리오 — 단위비용 오름차순 "
            f"(대표 시나리오 {REP_ID}: {REP_DESC}, {REP_NOTE})",
            fontsize=13, fontweight="bold")
ax.grid(axis="x", alpha=.3, zorder=0)
for spine in ["top", "right"]:
    ax.spines[spine].set_visible(False)

shares_shown = sorted(ok_sorted["분담률"].unique())
legend_handles = [Line2D([0], [0], marker="s", color="none", markerfacecolor=SHARE_COLORS[s],
                        markersize=12, label=f"분담률 {s:.0%}") for s in shares_shown]
ax.legend(handles=legend_handles, loc="lower right", fontsize=9, title="분담률", framealpha=0.9)

plt.tight_layout()
nc.savefig_retry(plt, f"{OUT}/scenario_ranked.png", dpi=150, bbox_inches="tight")
plt.close(fig)
print(f"저장: {OUT}\\scenario_ranked.png")


# ══════════════════════════════════════════════════════════
# 3. 필요물량 vs 총 수송능력 — 실행불가 조합이 왜 불가능한지 보여주는 그림
#    (원래 step2.py 섹션 5에 있었는데, step2.py는 MILP 재실행 없이는 못 돌려서
#     같은 CSV만 읽으면 되는 이 스크립트로 옮겼다. 실행가능 여부와 무관하게
#     전 시나리오를 그린다.)
# ══════════════════════════════════════════════════════════
fig, ax = plt.subplots(figsize=(11, 5.5))
g = df.sort_values(["칸", "운행", "분담률"]).reset_index(drop=True)
x = np.arange(len(g))
width = 0.35
ax.bar(x - width / 2, g["필요물량"], width, label="필요물량", color="#D55E00")
ax.bar(x + width / 2, g["총능력"], width, label="총능력(공급가능)", color="#0072B2")
ax.set_xticks(x)
ax.set_xticklabels([f"{int(r.칸)}칸x{int(r.운행)}회\n{r.분담률:.0%}" for r in g.itertuples()],
                   fontsize=6, rotation=90)
ax.set_ylabel("박스/일")
ax.set_title("시나리오별 필요물량 vs 총 수송능력 (전체) — 막대가 역전된 구간이 물리적 불가능")
ax.legend()
ax.grid(axis="y", alpha=.3)
plt.tight_layout()
nc.savefig_retry(plt, f"{OUT}/capacity_gap.png", dpi=150, bbox_inches="tight")
plt.close(fig)
print(f"저장: {OUT}\\capacity_gap.png")
