"""
STEP 5. 허브별 서비스 권역 choropleth — "어느 허브가 서울 어디를 커버하는가"
────────────────────────────────────────────────────────────
대표 시나리오 S39(4칸x5회, 분담률 12%, 허브 18개) 기준, scenario_assignments.csv의
행정동->허브 배정을 그대로 써서 각 행정동을 담당 허브 색으로 채색한다.
MILP를 다시 풀지 않는다.

허브 색 — Okabe-Ito 색약 안전 팔레트 8색을 먼저 쓰고, 허브가 그보다 많으면
(S39는 18개) 명도가 충분히 다른 색을 이어붙인다. 허브명 가나다순으로 고정
배정이라 매 실행 동일한 역이 항상 동일한 색을 받는다.

배경(자치구 경계 흰 선, 지하철 1~4호선 옅게)은 step3_vrp_route_viz.py /
step2.py 섹션7과 같은 스타일 요소를 재사용한다.
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
import matplotlib.colors as mcolors
from matplotlib.patches import Patch
import geopandas as gpd

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "output_data")

import network_common as _nc_id
SCENARIO_ID = _nc_id.REP_SCENARIO["ID"]   # 대표 시나리오 정의는 network_common 한 곳

# 허브가 18개로 늘어 Okabe-Ito 8색으로는 부족하다. 8색을 먼저 쓰고(색약
# 안전), 모자란 만큼 tab20에서 명도가 충분히 다른 색을 이어붙인다.
# (라스트마일 편도->왕복 수정으로 14 -> 18개가 되면서 색을 4개 더 늘렸다.)
OKABE_ITO = ["#E69F00", "#56B4E9", "#009E73", "#F0E442",
            "#0072B2", "#D55E00", "#CC79A7", "#000000"]
EXTRA_COLORS = ["#8C564B", "#7F7F7F", "#17BECF", "#9467BD", "#2CA02C", "#BCBD22",
                "#AEC7E8", "#FFBB78", "#C5B0D5", "#98DF8A", "#FF9896", "#5254A3"]
PALETTE = OKABE_ITO + EXTRA_COLORS


def clean_name(s):
    return re.sub(r"\([^)]*\)", "", str(s)).replace("역", "").strip()

def mmss_to_min(x):
    try:
        m, s = str(x).split(":")
        return int(m) + int(s) / 60.0
    except Exception:
        return 0.0

def darken(hex_color, factor=0.62):
    r, g, b = mcolors.to_rgb(hex_color)
    return (r * factor, g * factor, b * factor)


def label_ink(hex_color, max_lum=0.42):
    """라벨 글씨·테두리 색. darken()만 쓰면 원색이 옅은 허브(수서=회색)는
    같은 색 권역 위에서 대비가 부족해 라벨이 묻힌다. 밝기(휘도) 상한을 걸어
    어떤 권역 색이든 글씨가 충분히 진하게 나오도록 한 번 더 눌러 준다."""
    r, g, b = darken(hex_color)
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b      # 상대휘도(sRGB 근사)
    if lum > max_lum:
        k = max_lum / lum
        r, g, b = r * k, g * k, b * k
    return (r, g, b)


print("[1] 데이터 로드")
# 1호선 코레일 구간 26개역이 포함된 확장 역 목록(135행)을 써야 신규역이
# 허브로 잡힌 시나리오에서도 좌표를 찾을 수 있다.
import network_common as nc
stations = nc.load_stations(verbose=False)
dongs = pd.read_csv(f"{OUT}/dongs.csv")
assign = pd.read_csv(f"{OUT}/scenario_assignments.csv")
assign = assign[assign["ID"] == SCENARIO_ID].copy()
_srow = pd.read_csv(f"{OUT}/scenario_results.csv").query("ID == @SCENARIO_ID").iloc[0]
# 제출용 저장소의 배정표에는 원자료 보호를 위해 수요 열이 빠져 있다 — 원자료가
# 있으면 되살리고, 있는 경우에는 그대로 쓴다.
assign = _nc_id.attach_demand(assign, _srow["분담률"], verbose=True)

name2ll = {r["역명"]: (r["경도"], r["위도"]) for _, r in stations.iterrows()}

hub_names = sorted(assign["배정허브"].unique())
print(f"    {SCENARIO_ID} 허브 {len(hub_names)}개: {hub_names}")
if len(hub_names) > len(PALETTE):
    raise ValueError(f"허브 수({len(hub_names)})가 팔레트 색상 수({len(PALETTE)})를 초과합니다.")
HUB_COLOR = {h: PALETTE[i] for i, h in enumerate(hub_names)}

# 허브별 담당 동 수 / 담당 물량(범례용)
hub_stats = assign.groupby("배정허브").agg(동수=("행정동", "count"), 물량=("수요", "sum")).reindex(hub_names)


# ══════════════════════════════════════════════════════════
# 2. 행정동 폴리곤에 배정허브 붙이기 (ADM_CD로 조인 — 이름 중복 문제 회피)
# ══════════════════════════════════════════════════════════
print("[2] 행정동 폴리곤 조인")
shp = gpd.read_file(os.path.join(BASE, "행정동.shp"), encoding="utf-8")
shp["ADM_CD"] = shp["ADM_CD"].astype(str)
geo_dong = shp[shp["ADM_CD"].str.startswith("11")].to_crs(epsg=4326)

dongs["ADM_CD"] = dongs["ADM_CD"].astype(str)
assign_cd = assign.merge(dongs[["ADM_CD"]].reset_index().rename(columns={"index": "행정동_idx"}),
                         on="행정동_idx", how="left")
geo_assigned = geo_dong.merge(assign_cd[["ADM_CD", "배정허브"]], on="ADM_CD", how="left")
n_missing = geo_assigned["배정허브"].isna().sum()
print(f"    매칭 {len(geo_assigned) - n_missing}/{len(geo_assigned)}개 동" +
      (f" (미매칭 {n_missing}개 — 회색 처리)" if n_missing else ""))
geo_assigned["color"] = geo_assigned["배정허브"].map(HUB_COLOR)

geo_gu = geo_dong.copy()
geo_gu["GU_KEY"] = geo_gu["ADM_CD"].str[:5]
geo_gu = geo_gu.dissolve(by="GU_KEY").reset_index()


# ══════════════════════════════════════════════════════════
# 3. 지하철 1~4호선 노선(배경 오버레이용)
# ══════════════════════════════════════════════════════════
print("[3] 지하철 노선 형상 구축")
SEG_CSV = os.path.join(BASE, "서울교통공사 역간거리 및 소요시간_240810.csv")
seg = pd.read_csv(SEG_CSV, encoding="cp949")
seg["호선"] = seg["호선"].astype(str)
seg = seg[seg["호선"].isin(["1", "2", "3", "4"])].reset_index(drop=True)
seg["역명"] = seg["역명"].map(clean_name)
BRANCH_PARENT_OVERRIDE = {("2", "용답"): ("2", "성수"), ("2", "도림천"): ("2", "신도림")}
LINE_COLORS_ALL = {"1": "#0052A4", "2": "#00A84D", "3": "#EF7C1C", "4": "#00A5DE"}

station_coords_clean = {}
for _, r in stations.iterrows():
    station_coords_clean.setdefault(clean_name(r["역명"]), (r["경도"], r["위도"]))

ALL_LINE_EDGES = {}
for ln in ["1", "2", "3", "4"]:
    sub = seg[seg["호선"] == ln].reset_index(drop=True)
    prev_node, edges = None, []
    for _, row in sub.iterrows():
        node = (ln, row["역명"])
        parent = BRANCH_PARENT_OVERRIDE.get(node, prev_node)
        if parent is not None and parent != node:
            p_xy = station_coords_clean.get(parent[1])
            n_xy = station_coords_clean.get(node[1])
            if p_xy and n_xy:
                edges.append((p_xy, n_xy))
        prev_node = node
    ALL_LINE_EDGES[ln] = edges

# ── 1호선 연장(코레일 관할 구간) ──────────────────────────────────
# 서울교통공사 역간거리 CSV는 서울역~청량리 10개 역만 담고 있다(그
# 서쪽/동쪽은 한국철도공사 관할이라 그 데이터셋에 없음). "서울시 역사마스터
# 정보" CSV(호선 카테고리가 경부선/경인선/경원선/중앙선 등으로 세분돼
# 있음)에서 해당 구간 역 좌표를 가져와 물리적 실제 순서대로 이어붙인다.
# (마스터 CSV의 행 순서가 항상 노선 순서와 일치하진 않아 순서는 직접
# 지정 — 통상적으로 알려진 역 순서.)
master_df = pd.read_csv(os.path.join(BASE, "서울시 역사마스터 정보 (1).csv"), encoding="cp949")
master_coords = {}
for _, r in master_df.iterrows():
    master_coords.setdefault(clean_name(r["역사명"]), (r["경도"], r["위도"]))

def coord_lookup(name):
    name = clean_name(name)
    return station_coords_clean.get(name) or master_coords.get(name)

LINE1_EXT_CHAINS = [
    ["서울역", "남영", "용산", "노량진", "대방", "신길", "영등포", "신도림", "구로"],
    ["구로", "가산디지털단지", "금천구청", "석수", "관악", "안양"],       # 경부선 방향
    ["구로", "구일", "개봉", "오류동", "온수"],                          # 경인선 방향
    ["청량리", "회기", "외대앞", "신이문", "석계", "광운대", "월계",
     "녹천", "창동", "방학", "도봉", "도봉산", "망월사"],                 # 경원선 방향
]
n_ext = 0
for chain in LINE1_EXT_CHAINS:
    coords = [coord_lookup(n) for n in chain]
    for i in range(len(coords) - 1):
        if coords[i] and coords[i + 1]:
            ALL_LINE_EDGES["1"].append((coords[i], coords[i + 1]))
            n_ext += 1
        else:
            missing = chain[i] if not coords[i] else chain[i + 1]
            print(f"    ! 좌표 없음: {missing} — 이 구간 생략")
print(f"    1호선 연장 {n_ext}개 구간 추가(코레일 관할 포함)")


# ══════════════════════════════════════════════════════════
# 4. 그리기
# ══════════════════════════════════════════════════════════
print("[4] 시각화")
fig, ax = plt.subplots(figsize=(11, 11))
ax.set_facecolor("#fafafa")

geo_assigned.plot(ax=ax, color=geo_assigned["color"].fillna("#DDDDDD"),
                  alpha=0.55, edgecolor="white", linewidth=0.25, zorder=1)

# 1호선을 코레일 관할 구간까지 이어붙였으니 이제 굳이 다른 노선보다
# 강조할 필요 없이 나머지 노선과 동일한 스타일로 그린다.
for ln, edges in ALL_LINE_EDGES.items():
    c = LINE_COLORS_ALL[ln]
    for (x1, y1), (x2, y2) in edges:
        ax.plot([x1, x2], [y1, y2], color=c, linewidth=1.5, alpha=0.25, zorder=2,
                solid_capstyle="round")

geo_gu.plot(ax=ax, facecolor="none", edgecolor="white", linewidth=0.8, zorder=3)
geo_gu.plot(ax=ax, facecolor="none", edgecolor="#999999", linewidth=0.5, alpha=0.6, zorder=3)

# ── 허브 마커 + 라벨 ────────────────────────────────────────
# 서울역-충정로는 0.91km 거리라 기본 오프셋(0,14)으로는 라벨이 완전히 겹쳐
# 뒤쪽(서울역)이 안 보였다. 후보 위치를 순서대로 시도해 이미 배치된 라벨과
# 겹치지 않는 첫 자리에 놓고, 마커에서 멀어지면 arrowprops의 지시선(leader
# line)이 자연스럽게 드러나 어느 마커의 라벨인지 알 수 있게 한다.
LABEL_FS = 11
CAND_OFFSETS = [(0, 14), (0, -16), (54, 10), (-54, 10),
                (54, -12), (-54, -12), (0, 34), (0, -36), (76, 26), (-76, 26)]

fig.canvas.draw()                      # transData 확정 후 화면좌표 계산
_pt = fig.dpi / 72.0                   # 픽셀/포인트 — 전부 포인트 단위로 맞춘다


def _label_box(name, cx, cy):
    """라벨 대략 크기(포인트). 한글은 폭이 글자당 약 1.05em."""
    w = len(name) * LABEL_FS * 1.05 + 8
    h = LABEL_FS * 1.7
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def _overlap(a, b, pad=3):
    return not (a[2] + pad < b[0] or b[2] + pad < a[0] or
                a[3] + pad < b[1] or b[3] + pad < a[1])


placed_boxes = []
# 위쪽부터 배치하면 남는 자리가 아래로 밀려 결과가 안정적이다.
for h in sorted(hub_names, key=lambda n: -name2ll[n][1]):
    hx, hy = name2ll[h]
    dark = label_ink(HUB_COLOR[h])     # 권역 색 위에서도 묻히지 않게 밝기 상한 적용
    ax.scatter([hx], [hy], s=260, color="white", zorder=5)
    ax.scatter([hx], [hy], s=160, color=dark, zorder=6)

    mx, my = ax.transData.transform((hx, hy)) / _pt      # 마커 위치(포인트)
    chosen = CAND_OFFSETS[0]
    for dx, dy in CAND_OFFSETS:
        # va가 bottom/top이라 라벨 중심은 오프셋 방향으로 반 높이만큼 더 간다
        cy = my + dy + (LABEL_FS * 0.85 if dy >= 0 else -LABEL_FS * 0.85)
        box = _label_box(h, mx + dx, cy)
        if not any(_overlap(box, b) for b in placed_boxes):
            chosen = (dx, dy)
            placed_boxes.append(box)
            break
    else:
        dx, dy = CAND_OFFSETS[0]
        placed_boxes.append(_label_box(h, mx + dx, my + dy + LABEL_FS * 0.85))

    dx, dy = chosen
    ax.annotate(h, (hx, hy), fontsize=LABEL_FS, fontweight="bold", color=dark,
               xytext=(dx, dy), textcoords="offset points",
               ha="center", va="bottom" if dy >= 0 else "top", zorder=7,
               bbox=dict(boxstyle="round,pad=0.25", facecolor="white", edgecolor=dark,
                        linewidth=1.6, alpha=0.92),
               arrowprops=dict(arrowstyle="-", color=dark, linewidth=1,
                               shrinkA=0, shrinkB=6))

legend_handles = [
    Patch(facecolor=HUB_COLOR[h], edgecolor=darken(HUB_COLOR[h]), alpha=0.85,
         label=f"{h} ({int(hub_stats.loc[h, '동수'])}개동, {hub_stats.loc[h, '물량']:,.0f}박스/일)")
    for h in hub_names
]
ax.legend(handles=legend_handles, loc="upper left", fontsize=9.5, framealpha=0.95,
         title=f"허브 서비스 권역 ({SCENARIO_ID})", title_fontsize=10.5)

ax.set_xticks([]); ax.set_yticks([])
for spine in ax.spines.values():
    spine.set_visible(False)
ax.set_title(f"허브별 서비스 권역 — {SCENARIO_ID} "
            f"({int(_srow['칸'])}칸x{int(_srow['운행'])}회, 분담률 {_srow['분담률']:.0%}, 허브 {len(hub_names)}개)",
            fontsize=15, fontweight="bold")

plt.tight_layout()
nc.savefig_retry(plt, f"{OUT}/hub_service_area.png", dpi=150, bbox_inches="tight")
plt.close(fig)
print(f"저장: {OUT}\\hub_service_area.png")
