# -*- coding: utf-8 -*-
"""
발표용 그림 3종
  [1] demand_density_hubs.png  — 행정동 수요밀도(박스/km2) 코로플레스 + 허브 위치
  [2] policy_sensitivity.png   — 정책 변수(하역속도/심야 가용시간)별 최대 분담률
  [3] night_window_gantt.png   — 심야 가용시간(180분) 안에서 방향별 시간 소모 간트

시나리오 ID·허브 개수는 network_common.REP_SCENARIO 하나만 참조한다(하드코딩 금지).
"""
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

import network_common as nc

plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False

BASE, OUT = nc.BASE, nc.OUT
REP = nc.REP_SCENARIO
REP_ID = REP["ID"]
SUB = f'{REP_ID} ({REP["cars"]}칸x{REP["trips"]}회, 분담률 {REP["share"]:.0%}, 허브 {REP["n_hubs"]}개)'


# ══════════════════════════════════════════════════════════
# 0. 공통 — 행정구역 도형 / 노선 형상
#    elbow·VRP 그림과 동일한 배경 스타일을 쓴다(발표 자료 톤 통일).
# ══════════════════════════════════════════════════════════
import geopandas as gpd

print("[0] 배경 도형 로드")
_shp = gpd.read_file(os.path.join(BASE, "행정동.shp"), encoding="utf-8")
_shp["ADM_CD"] = _shp["ADM_CD"].astype(str)
geo_dong = _shp[_shp["ADM_CD"].str.startswith("11")].to_crs(epsg=4326)
geo_dong["GU_KEY"] = geo_dong["ADM_CD"].str[:5]
geo_gu = geo_dong.dissolve(by="GU_KEY").reset_index()
geo_seoul = gpd.GeoDataFrame(geometry=[geo_dong.union_all()], crs=geo_dong.crs)

st, net = None, None


def ensure_network():
    """지도 그림에서만 필요하므로 지연 로드."""
    global st, net
    if st is None:
        net = nc.load_all(verbose=False)      # stations/seg가 net dict에 합쳐져 반환된다
        st = net["stations"]
    return st, net


def line_edges(stations, seg):
    """역 좌표를 노선 순서대로 이어 노선 형상을 만든다(분기는 override로 부모 지정)."""
    coords = {}
    for _, r in stations.iterrows():
        coords.setdefault(r["역명_clean"], (r["경도"], r["위도"]))
    out = {}
    for ln in ["1", "2", "3", "4"]:
        sub = seg[seg["호선"] == ln].reset_index(drop=True)
        prev, edges = None, []
        for _, row in sub.iterrows():
            node = (ln, row["역명"])
            parent = nc.BRANCH_PARENT_OVERRIDE.get(node, prev)
            if parent is not None and parent != node:
                p, q = coords.get(parent[1]), coords.get(node[1])
                if p and q:
                    edges.append((p, q))
            prev = node
        out[ln] = edges
    return out


# ══════════════════════════════════════════════════════════
# 1. demand_density_hubs.png — 수요밀도 + 허브
#    "허브가 왜 저기 놓였나"를 한 장으로 설명하는 그림.
#    수요 총량이 아니라 면적당 밀도로 그린다(면적이 큰 외곽 동이
#    총량만으로는 과대 표현되기 때문).
# ══════════════════════════════════════════════════════════
def fig_demand_density():
    print(f"\n[1] demand_density_hubs.png ({REP_ID})")
    stations, net = ensure_network()

    asg = pd.read_csv(f"{OUT}/scenario_assignments.csv")
    asg = asg[asg["ID"] == REP_ID]
    if asg.empty:
        print(f"  ! scenario_assignments.csv에 {REP_ID} 없음 — 건너뜀")
        return
    # 제출용 저장소의 배정표에는 원자료 보호를 위해 수요 열이 빠져 있다
    asg = nc.attach_demand(asg, REP["share"], verbose=True)
    # ★ 행정동 "이름"으로 조인하면 안 된다 — dongs.csv에 같은 이름이 두 번
    #   나오는 동이 있어(신사동: 관악구 idx329 / idx358), 이름 기준 merge는
    #   한 동의 물량을 엉뚱한 동에도 복제한다. scenario_assignments.csv의
    #   행정동_idx가 dongs.csv의 행 번호이므로 그것으로 ADM_CD를 얻어
    #   ADM_CD로 조인한다(서비스 권역도 step5와 같은 방식).
    dongs = pd.read_csv(f"{OUT}/dongs.csv")
    dongs["ADM_CD"] = dongs["ADM_CD"].astype(str)
    dup = dongs["ADM_NM"].value_counts()
    dup = sorted(dup[dup > 1].index)
    if dup:
        print(f"  (동명 중복 {len(dup)}건: {dup} — 행정동_idx로 조인)")

    asg = asg.copy()
    asg["ADM_CD"] = dongs.loc[asg["행정동_idx"].astype(int), "ADM_CD"].values
    dem = asg.groupby("ADM_CD", as_index=False)["수요"].sum()
    dem = dem.merge(dongs[["ADM_CD", "ADM_NM", "면적_km2"]], on="ADM_CD", how="left")
    dem["밀도"] = dem["수요"] / dem["면적_km2"]

    gdf = geo_dong.merge(dem[["ADM_CD", "수요", "면적_km2", "밀도"]], on="ADM_CD", how="left")

    hub_names = sorted(set(asg["배정허브"]))
    hubs = stations[stations["역명"].isin(hub_names)].drop_duplicates("역명")

    fig, ax = plt.subplots(figsize=(13, 11))
    ax.set_facecolor("#f5f5f5")

    # 밀도 상위 5%가 색을 다 먹어버리지 않도록 상한을 95분위로 자른다.
    vmax = float(np.nanpercentile(gdf["밀도"].dropna(), 95))
    gdf.plot(column="밀도", ax=ax, cmap="YlOrRd", vmin=0, vmax=vmax,
             edgecolor="#999999", linewidth=0.3, alpha=0.9, zorder=1,
             missing_kwds=dict(color="#e8e8e8", edgecolor="#bbbbbb", linewidth=0.3))
    geo_gu.plot(ax=ax, facecolor="none", edgecolor="#666666", linewidth=0.9, alpha=0.8, zorder=2)
    geo_seoul.plot(ax=ax, facecolor="none", edgecolor="#222222", linewidth=1.6, zorder=3)

    for ln, edges in line_edges(stations, net["seg"]).items():
        for (x1, y1), (x2, y2) in edges:
            ax.plot([x1, x2], [y1, y2], color=nc.LINE_COLORS[ln], linewidth=1.6,
                    alpha=0.35, zorder=4, solid_capstyle="round")

    # 허브 — VRP/elbow 그림과 같은 이중 원 스타일
    ax.scatter(hubs["경도"], hubs["위도"], s=260, color="white", zorder=6)
    ax.scatter(hubs["경도"], hubs["위도"], s=150, color="#1A237E", zorder=7)
    # 서울역-충정로처럼 0.9km 떨어진 쌍은 라벨이 겹친다. 앞서 배치한 라벨과
    # 가까우면 아래쪽으로 내려 붙여 겹침을 피한다(마커 위치는 그대로).
    placed = []
    span = float(hubs["경도"].max() - hubs["경도"].min())
    for _, r in hubs.sort_values("위도", ascending=False).iterrows():
        x, y = r["경도"], r["위도"]
        below = any(np.hypot(x - px, y - py) < span * 0.035 for px, py in placed)
        ax.annotate(r["역명"], (x, y), fontsize=10, fontweight="bold",
                    color="white", ha="center", va="top" if below else "bottom",
                    xytext=(0, -14 if below else 14), textcoords="offset points", zorder=8,
                    bbox=dict(boxstyle="round,pad=0.25", fc="#1A237E", ec="none", alpha=0.92))
        placed.append((x, y))

    sm = plt.cm.ScalarMappable(cmap="YlOrRd", norm=plt.Normalize(vmin=0, vmax=vmax))
    cb = fig.colorbar(sm, ax=ax, fraction=0.030, pad=0.01)
    cb.set_label("수요밀도 (박스/km²/일)", fontsize=12)
    cb.ax.set_title(f"상한 {vmax:,.0f}\n(95분위)", fontsize=9, color="#555555", pad=8)

    top = dem.nlargest(3, "밀도")
    note = " · ".join(f"{r['ADM_NM']} {r['밀도']:,.0f}" for _, r in top.iterrows())
    ax.set_title(f"행정동별 심야 화물 수요밀도와 허브 입지 — {SUB}\n"
                 f"밀도 상위: {note} (박스/km²)",
                 fontsize=15, fontweight="bold", pad=14)
    ax.legend(handles=[
        Line2D([0], [0], marker="o", color="none", markerfacecolor="#1A237E",
               markeredgecolor="white", markeredgewidth=1.5, markersize=12,
               label=f"허브 {len(hubs)}개"),
        Patch(facecolor="#e8e8e8", edgecolor="#bbbbbb", label="배정 수요 없음"),
    ], loc="upper left", fontsize=11, framealpha=0.92)
    ax.set_xticks([]); ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_visible(False)
    plt.tight_layout()
    nc.savefig_retry(plt, f"{OUT}/demand_density_hubs.png", dpi=200)
    plt.close(fig)
    print(f"  저장: demand_density_hubs.png (동 {gdf['밀도'].notna().sum()}개, 허브 {len(hubs)}개)")


# ══════════════════════════════════════════════════════════
# 2. policy_sensitivity.png — 정책 변수별 최대 분담률
#    step2_diagnostics.py policy 산출물(diag_policy_*.csv)을 그림으로.
#    "무엇을 바꾸면 분담률 상한이 얼마나 오르는가" = 정책 제언의 근거.
# ══════════════════════════════════════════════════════════
def fig_policy_sensitivity():
    print("\n[2] policy_sensitivity.png")
    pa = f"{OUT}/diag_policy_unload_rate.csv"
    pb = f"{OUT}/diag_policy_available_min.csv"
    if not os.path.exists(pa):
        print("  ! diag_policy_unload_rate.csv 없음 — 건너뜀")
        return
    A = pd.read_csv(pa)
    B = pd.read_csv(pb) if os.path.exists(pb) else None
    if B is None:
        print("  ! diag_policy_available_min.csv 없음 — A패널만 그림")

    ncol = 2 if B is not None else 1
    fig, axes = plt.subplots(1, ncol, figsize=(7.5 * ncol, 6.2))
    axes = np.atleast_1d(axes)

    def panel(ax, df, xcol, xlabel, cur_x, title, color, marker):
        x, y = df[xcol].values, df["최대분담률_pct"].values
        ax.plot(x, y, "-", color=color, linewidth=2.8, zorder=3)
        ax.plot(x, y, marker, color=color, markersize=9, zorder=4,
                markeredgecolor="white", markeredgewidth=1.2)
        for xi, yi in zip(x, y):
            ax.annotate(f"{yi:.1f}%", (xi, yi), fontsize=10, fontweight="bold",
                        xytext=(0, 10), textcoords="offset points", ha="center", zorder=5)
        # 현행 운영점과 대표 시나리오 분담률 — 여유가 얼마나 남았는지 보이게
        if cur_x in set(x):
            cy = float(y[list(x).index(cur_x)])
            ax.axvline(cur_x, color="#B71C1C", linestyle="--", linewidth=1.6, alpha=0.8, zorder=2)
            ax.scatter([cur_x], [cy], s=210, facecolor="none", edgecolor="#B71C1C",
                       linewidth=2.4, zorder=6)
        ax.axhline(REP["share"] * 100, color="#1A237E", linestyle=":", linewidth=1.8,
                   alpha=0.85, zorder=2)
        ax.set(xlabel=xlabel, ylabel="실행 가능 최대 분담률 (%)", title=title)
        ax.set_xticks(x)
        ax.set_ylim(0, max(y) * 1.22)
        ax.grid(alpha=0.3, zorder=0)
        ax.title.set_fontsize(13)
        ax.title.set_fontweight("bold")

    panel(axes[0], A, "UNLOAD_RATE", "하역속도 (박스/분)", 450,
          f"(A) 하역속도별 상한  ─ 심야 {nc.AVAILABLE_MIN}분 고정",
          "#D84315", "o")
    if B is not None:
        panel(axes[1], B, "AVAILABLE_MIN", "심야 작업 가용시간 (분)", nc.AVAILABLE_MIN,
              "(B) 심야 가용시간별 상한  ─ 하역 450박스/분 고정",
              "#00695C", "s")

    handles = [
        Line2D([0], [0], marker="o", color="none", markerfacecolor="none",
               markeredgecolor="#B71C1C", markeredgewidth=2.2, markersize=13, label="현행 운영 조건"),
        Line2D([0], [0], color="#1A237E", linestyle=":", linewidth=2,
               label=f'대표 시나리오 분담률 {REP["share"]:.0%}'),
    ]
    axes[0].legend(handles=handles, loc="lower right", fontsize=10, framealpha=0.92)
    plt.suptitle(f"정책 변수별 실행 가능 최대 분담률 — {SUB} 기준 모델",
                 fontsize=15, fontweight="bold")
    plt.tight_layout(rect=[0, 0, 1, 0.95])
    nc.savefig_retry(plt, f"{OUT}/policy_sensitivity.png", dpi=200)
    plt.close(fig)
    print("  저장: policy_sensitivity.png")


# ══════════════════════════════════════════════════════════
# 3. night_window_gantt.png — 심야 가용시간 소모 구조
#    방향(레이)별로 "열차 주행+회차"와 "하역"이 180분을 어떻게 쓰는지.
#    한계로 명시한 확정배정 시간 초과 건도 이 그림에서 그대로 드러난다.
# ══════════════════════════════════════════════════════════
def fig_night_gantt():
    print("\n[3] night_window_gantt.png")
    p = f"{OUT}/diag_unload_time.csv"
    if not os.path.exists(p):
        print("  ! diag_unload_time.csv 없음 — 건너뜀")
        return
    df = pd.read_csv(p)
    df = df[df["ID"] == REP_ID].copy()
    if df.empty:
        print(f"  ! diag_unload_time.csv에 {REP_ID} 없음 — 건너뜀")
        return

    # 방향 라벨: "3수서차량기지가락시장" -> 앞 숫자는 호선, 뒤는 기점/말단역
    df["호선"] = df["방향"].str[0]
    df["라벨"] = df["호선"] + "호선 · " + df["방향"].str[1:]
    df = df.sort_values("합계_분").reset_index(drop=True)

    AM = nc.AVAILABLE_MIN
    over = df["합계_분"] > AM
    h = max(5.5, 0.42 * len(df) + 2.2)
    fig, ax = plt.subplots(figsize=(13, h))

    y = np.arange(len(df))
    ax.barh(y, df["주행회차_분"], color="#5C6BC0", edgecolor="white",
            linewidth=0.6, label="열차 주행 + 회차", zorder=3)
    ax.barh(y, df["하역_분"], left=df["주행회차_분"], color="#FFB300", edgecolor="white",
            linewidth=0.6, label="하역", zorder=3)
    # 초과분은 테두리로만 표시 — 막대 색을 바꾸면 구성비가 안 읽힌다.
    for i in np.where(over)[0]:
        ax.barh(i, df.loc[i, "합계_분"], facecolor="none", edgecolor="#C62828",
                linewidth=2.0, zorder=4)

    ax.axvline(AM, color="#C62828", linewidth=2.4, zorder=5)
    ax.text(AM, len(df) - 0.2, f" 가용 {AM}분", color="#C62828",
            fontsize=12, fontweight="bold", va="top")

    for i, r in df.iterrows():
        ax.text(r["합계_분"] + 2, i, f"{r['합계_분']:.0f}분 ({r['가용대비']*100:.0f}%)",
                va="center", fontsize=9,
                color="#C62828" if r["합계_분"] > AM else "#444444",
                fontweight="bold" if r["합계_분"] > AM else "normal")

    ax.set_yticks(y)
    ax.set_yticklabels(df["라벨"], fontsize=9)
    ax.set_xlim(0, max(df["합계_분"].max(), AM) * 1.22)
    ax.set_xlabel("소요 시간 (분)", fontsize=12)
    ax.grid(axis="x", alpha=0.3, zorder=0)
    ax.set_axisbelow(True)

    n_over = int(over.sum())
    worst = df["가용대비"].max()
    all_over = int((pd.read_csv(p)["합계_분"] > AM).sum())
    all_n = len(pd.read_csv(p))
    if n_over:
        sub2 = (f"방향(레이) {len(df)}개 중 초과 {n_over}개 · 최대 {worst*100:.1f}% "
                f"— 확정 배정 하드닝에 따른 한계(본문 기재)")
    else:
        sub2 = (f"방향(레이) {len(df)}개 전부 가용시간 내 · 최대 {worst*100:.1f}%"
                f"  (전 시나리오 기준으로는 {all_n}건 중 {all_over}건 초과 — 하드닝 한계)")
    ax.set_title(f"심야 작업창({AM}분) 소모 구조 — {SUB}\n{sub2}",
                 fontsize=14, fontweight="bold", pad=12)
    handles, labels = ax.get_legend_handles_labels()
    if n_over:      # 초과가 없으면 범례에 넣지 않는다(없는 항목을 설명하면 오해를 부른다)
        handles.append(Patch(facecolor="none", edgecolor="#C62828", linewidth=2,
                             label="가용시간 초과"))
    ax.legend(handles=handles, loc="lower right", fontsize=11, framealpha=0.92)
    plt.tight_layout()
    nc.savefig_retry(plt, f"{OUT}/night_window_gantt.png", dpi=200)
    plt.close(fig)
    print(f"  저장: night_window_gantt.png (방향 {len(df)}개, 초과 {n_over}개)")


# ══════════════════════════════════════════════════════════
# 4. night_window_timeline.png — 심야 180분을 시간축으로 펼친 간트
#    night_window_gantt.png가 "총량"이라면 이건 "순서"다.
#    한 방향의 1회 운행 사이클을 [상차/회차]-[주행]-[하역]-[주행]... 으로
#    펼쳐, 회차를 eff_trips만큼 이어 붙인다.
#
#    모델과의 대응(그림이 모델을 벗어나지 않게 하는 부분):
#      · 1회 사이클 = TURNAROUND_MIN + DIR_ROUND_TRIP + (그 회차의 하역시간)
#      · 전체 = eff x (DIR_ROUND_TRIP + TURNAROUND_MIN) + 총하역시간
#        -> diag_unload_time.csv의 주행회차_분 / 하역_분과 정확히 일치한다.
#      · DIR_ROUND_TRIP은 "기점 -> 그 레이의 최말단역 -> 기점"이다(개설 허브가
#        아니라 레이 끝까지). 그래서 마지막 허브 뒤에도 주행 구간이 남는다.
#      · 하역은 회차마다 균등 분할했다(q_j / eff / UNLOAD_RATE). 모델은 하루
#        총량만 제약하므로 회차별 배분은 이 그림을 위한 표현이다.
#      · 상차 시간은 모델에 따로 없다 — 회차시간(10분) 블록에 함께 표기한다.
# ══════════════════════════════════════════════════════════
NIGHT_START_MIN = 30      # 00:30 시작으로 병기


def _clock(m):
    t = NIGHT_START_MIN + m
    return f"{int(t // 60) % 24:02d}:{int(round(t % 60)):02d}"


def _pick_directions(df):
    """대비가 드러나는 방향 3개 — 가장 빡빡한 / 하역이 지배적인 / 가장 여유로운."""
    picks = []
    for key in [df["가용대비"].idxmax(), df["하역_분"].idxmax(), df["가용대비"].idxmin()]:
        if key not in picks:
            picks.append(key)
    return df.loc[picks]


def fig_night_timeline():
    print("\n[4] night_window_timeline.png")
    p = f"{OUT}/diag_unload_time.csv"
    if not os.path.exists(p):
        print("  ! diag_unload_time.csv 없음 — 건너뜀")
        return
    tdf = pd.read_csv(p)
    tdf = tdf[tdf["ID"] == REP_ID].copy().reset_index(drop=True)
    if tdf.empty:
        print(f"  ! diag_unload_time.csv에 {REP_ID} 없음 — 건너뜀")
        return

    stations, net = ensure_network()
    name2idx = {n: i for i, n in enumerate(stations["역명"])}
    asg = pd.read_csv(f"{OUT}/scenario_assignments.csv")
    asg = asg[asg["ID"] == REP_ID]
    asg = nc.attach_demand(asg, REP["share"])      # 수요 열 없으면 원자료에서 복원
    q_by_hub = asg.groupby("배정허브")["수요"].sum()

    UR = 450.0        # UNLOAD_RATE — step2_diagnostics.COST와 동일
    AM = nc.AVAILABLE_MIN
    TM = nc.TURNAROUND_MIN
    trips_want = int(REP["trips"])

    sel = _pick_directions(tdf)
    C_RUN, C_UNLOAD, C_TURN = "#3949AB", "#FB8C00", "#9E9E9E"

    # 방향별 사이클 수만큼 패널 높이를 나눠 준다(회차가 많으면 더 높게).
    plans = []
    for _, row in sel.iterrows():
        dk = row["방향"]
        rt = net["DIR_ROUND_TRIP"][dk]
        eff = min(trips_want, net["MAX_TRIPS"][dk])
        hubs = [(h, float(q)) for h, q in q_by_hub.items()
                if h in name2idx and net["hub_dir"][name2idx[h]] == dk]
        hubs.sort(key=lambda t: net["rail_t"][name2idx[t[0]]])
        plans.append(dict(row=row, dk=dk, rt=rt, eff=eff, hubs=hubs))

    heights = [max(1.6, 0.62 * pl["eff"] + 1.1) for pl in plans]
    fig, axes = plt.subplots(len(plans), 1, figsize=(15, sum(heights) + 2.0),
                             gridspec_kw=dict(height_ratios=heights))
    axes = np.atleast_1d(axes)

    for ax, pl in zip(axes, plans):
        row, dk, rt, eff, hubs = pl["row"], pl["dk"], pl["rt"], pl["eff"], pl["hubs"]
        t = 0.0
        for k in range(eff):
            y = eff - 1 - k                      # 1회차가 위로 오게
            # ── 회차·상차 (모델의 TURNAROUND_MIN)
            ax.barh(y, TM, left=t, height=0.62, color=C_TURN,
                    edgecolor="white", linewidth=0.8, zorder=3)
            t += TM
            # ── 출발 -> 각 허브(주행 + 하역) -> 레이 끝
            prev = 0.0
            for hub, q in hubs:
                leg = float(net["rail_t"][name2idx[hub]]) - prev
                if leg > 1e-9:
                    ax.barh(y, leg, left=t, height=0.62, color=C_RUN,
                            edgecolor="white", linewidth=0.8, zorder=3)
                    t += leg
                dwell = q / eff / UR
                ax.barh(y, dwell, left=t, height=0.62, color=C_UNLOAD,
                        edgecolor="white", linewidth=0.8, zorder=3)
                ax.annotate(f"{hub}\n{q/eff:,.0f}박스", (t + dwell / 2, y + 0.34),
                            ha="center", va="bottom", fontsize=8, fontweight="bold",
                            color="#5D4037", zorder=6)
                t += dwell
                prev = float(net["rail_t"][name2idx[hub]])
            tail = rt / 2 - prev                 # 마지막 허브 -> 레이 끝
            if tail > 1e-9:
                ax.barh(y, tail, left=t, height=0.62, color=C_RUN,
                        edgecolor="white", linewidth=0.8, zorder=3)
                t += tail
            if rt / 2 > 1e-9:                    # 복귀
                ax.barh(y, rt / 2, left=t, height=0.62, color=C_RUN,
                        edgecolor="white", linewidth=0.8, zorder=3)
                t += rt / 2
            ax.annotate(f"{t:.0f}분", (t + 1.5, y), va="center", fontsize=8, color="#555555")

        ax.axvline(AM, color="#C62828", linewidth=2.4, zorder=5)
        ax.set_yticks(range(eff))
        ax.set_yticklabels([f"{eff - i}회차" for i in range(eff)], fontsize=10)
        ax.set_ylim(-0.6, eff - 0.4)
        ax.set_xlim(0, AM * 1.13)
        ax.grid(axis="x", alpha=0.25, zorder=0)
        ax.set_axisbelow(True)
        pct = row["가용대비"] * 100
        ax.set_title(f'{dk[0]}호선 · {dk[1:]}   —   {row["합계_분"]:.0f}분 / {AM}분 ({pct:.0f}%)'
                     f'   ·   주행+회차 {row["주행회차_분"]:.0f}분 + 하역 {row["하역_분"]:.0f}분'
                     f'   ·   허브 {len(hubs)}개 · {eff}회차',
                     fontsize=12, fontweight="bold", loc="left", pad=6,
                     color="#B71C1C" if pct > 95 else "#333333")

    # x축은 맨 아래 패널에만 — 분 + 실제 시각 병기
    for ax in axes[:-1]:
        ax.set_xticklabels([])
    ticks = np.arange(0, AM + 1, 30)
    axes[-1].set_xticks(ticks)
    axes[-1].set_xticklabels([f"{int(m)}분\n{_clock(m)}" for m in ticks], fontsize=10)
    axes[-1].set_xlabel(f"심야 작업창 경과시간 (00:30 기준, 가용 {AM}분)", fontsize=12)
    axes[0].legend(handles=[
        Patch(facecolor=C_TURN, label=f"회차·상차 ({TM}분)"),
        Patch(facecolor=C_RUN, label="주행 (기점↔레이 끝)"),
        Patch(facecolor=C_UNLOAD, label="허브 정차·하역"),
        Line2D([0], [0], color="#C62828", linewidth=2.4, label=f"가용 {AM}분"),
    ], loc="upper right", ncol=4, fontsize=10, framealpha=0.95)

    plt.suptitle(f"심야 운행 사이클 타임라인 — {SUB}\n"
                 f"빡빡한 방향과 여유 있는 방향의 시간 구조 비교",
                 fontsize=15, fontweight="bold")
    plt.tight_layout(rect=[0, 0, 1, 0.955])
    nc.savefig_retry(plt, f"{OUT}/night_window_timeline.png", dpi=200)
    plt.close(fig)
    for pl in plans:
        print(f"  {pl['dk']}: {pl['eff']}회차, 허브 {len(pl['hubs'])}개, "
              f"왕복 {pl['rt']:.0f}분")
    print("  저장: night_window_timeline.png")


if __name__ == "__main__":
    import sys
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("all", "demand"):
        fig_demand_density()
    if which in ("all", "policy"):
        fig_policy_sensitivity()
    if which in ("all", "gantt"):
        fig_night_gantt()
    if which in ("all", "timeline"):
        fig_night_timeline()
    print("\n완료")
