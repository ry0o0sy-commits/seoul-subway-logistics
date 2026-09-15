"""
STEP 4. VKT(주행거리) 및 CO2 배출량 분석 — 두 시나리오 비교
────────────────────────────────────────────────────────────
연구의 최종 KPI를 "비용"에서 "도심 화물트럭 주행거리 감소·탄소배출 저감"
으로 전환하기 위한 분석. 아래 두 시나리오를 나란히 비교한다.

  · 비용효율 최적 : S39  (4칸x5회, 분담률 12%, 145,222박스/일, 14허브)
  · 환경효과 최대 : SMAX (실행가능 최대 분담률 — step2_max_feasible_share_v2.py
    로 이분탐색해 확정)

  ※ 1호선 코레일 구간 26개역 확장 + 심도 절댓값 수정 + 임대료 재설계 이후
    단위비용 최소 시나리오가 S25(3칸x5회, 4%) -> S39로 바뀌어 기준을 옮겼다.
    수치는 scenario_results.csv에서 직접 읽으므로 이 주석이 낡아도 결과는
    항상 최신 값을 따른다.

[비교 구조 — 두 시나리오 각각에 대해 동일하게 적용]
  (A) 기존 방식(지하철 미도입): 외곽 물류센터 -> 트럭 간선 -> 도심 진입
      -> 트럭 라스트마일 -> 행정동. 지하철이 담당했을 물량을 전부 트럭이
      외곽에서 직접 배송한다고 가정.
  (B) 지하철 도입(현재 모델): 차량기지 -> 지하철(트럭 주행 0) -> 허브역
      -> 트럭 라스트마일(VRP 순회) -> 행정동.

라스트마일 거리는 두 방식 모두 STEP 3(step3_vrp_lastmile.py)의
vrp_summary.csv를 재사용한다 — (A)는 "기존_거리km"(허브<->동 개별 왕복),
(B)는 "VRP_거리km"(트럭이 실제로 순회 최적화한 거리)를 쓴다.

[근거를 남겨야 하는 가정값 — 전부 아래 각주에 상세 기재]
  1. 간선거리(D_TRUNK) — 20/30/40/50km 민감도 (특정 물류센터 위치를 가정할
     근거가 없어 범위로 처리)
  2. 경유 CO2 배출계수 — 국가법령정보센터 별표12 (법정 국가고유 배출계수)
  3. 전력 배출계수 — 온실가스종합정보센터 2023년 확정 전력배출계수
  4. 1톤 화물차 연비 — 실측 도심주행 데이터
  5. 전동차 견인 에너지 원단위 — 서울메트로 실측치(2009), 여기서 화물
     적재분의 "한계" 전력만 질량비로 근사(아래 상세)
  6. 박스 평균 중량, 전동차 자중 — 공식 출처 없는 가정값(명시)

[★ 기준선 (A)의 성격 — 절감률을 인용하기 전에 반드시 함께 읽을 것]
  (A)는 "현행 택배 시스템"이 아니라 **외곽 직배송 가정**이다. 배송 1건
  (200박스 단위 방문노드)마다 트럭 한 대가 외곽에서 D_TRUNK만큼 들어왔다
  나간다고 본다(대표 시나리오에서 933건 x 왕복 60km = 55,980km/일).
  이 때문에 다음 두 가지를 반드시 함께 밝혀야 한다.

  (1) 절감의 98%는 간선 제거에서 나온다.
      D_TRUNK=30km에서 총 절감 56,984km 중 간선 55,980km(98.2%),
      라스트마일 개선은 1,004km(1.8%)뿐이다. 즉 이 분석의 91%라는 숫자는
      VRP 최적화 성과가 아니라 "간선 트럭이 사라진다"는 가정의 산물이다.

  (2) (B)에는 물류센터 -> 차량기지 반입 트럭이 계산에 없다.
      화물은 차량기지에 이미 있다고 보고 지하철 구간부터 센다. 실제로는
      차량기지(구로·이문·군자·신정·수서·창동 등)가 서울 안이라 그 반입
      주행이 존재한다. 대형트럭(1,500박스/대) 간선을 가정하면 97대 x
      왕복 60km = 5,820km/일이 (B)에 추가되어야 하고, 이 경우 VKT 절감률은
      90.6% -> 81.3%로 내려간다.

  현행 시스템은 대형트럭 간선 + 서브터미널 환적 + 1톤 배송차 구조라
  (A)보다 간선 VKT가 훨씬 작다. 따라서 (A) 대비 절감률은 "지하철 도입으로
  줄어드는 양"의 상한이며, 현행 대비 개선폭은 이보다 작다.
  발표에서는 반드시 "외곽 직배송 대비"라는 조건을 붙여 인용할 것.

[주의 — 정직성]
  SMAX는 분담률이 더 높아 VKT/CO2 절감 "절대량"이 크게 나오지만 단위비용도
  같이 오른다 — "환경효과가 크다"와 "경제적으로 효율적이다"는 별개 축이라는
  점을 그대로 드러내는 게 이 비교의 목적이지, SMAX가 더 낫다고 주장하려는
  게 아니다. 절감률/절감량은 어디까지나 "그 분담률 물량 안에서"의 값이다.
  절감률은 지하철 담당 물량(대표 시나리오 12%) 내부 기준이므로, 서울 전체
  택배 물동량 대비로 환산하면 VKT 10.9% / CO2 10.7%다(= 내부절감률 x 분담률).
"""

import os
import re
import numpy as np
import pandas as pd
import networkx as nx
import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams["font.family"] = "Malgun Gothic"
matplotlib.rcParams["axes.unicode_minus"] = False
import matplotlib.pyplot as plt

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "output_data")

AVAILABLE_MIN, TURNAROUND_MIN = 180, 10
DAYS_PER_YEAR = 365
D_TRUNK_LIST_KM = [20, 30, 40, 50]
D_TRUNK_MAIN = 30   # 대표 시각화·요약에 쓸 값(민감도 범위의 중간)

# ══════════════════════════════════════════════════════════
# 0. 배출계수·원단위 (전부 출처/가정 근거 명시)
# ══════════════════════════════════════════════════════════

# ── 1. 간선거리(D_TRUNK) 민감도 ─────────────────────────────
# 정의: "외곽 물류센터 -> 배송 행정동"의 편도 도로거리. (A)에서는 배송 1건
#       (=200박스 단위 방문노드)마다 트럭이 이 거리를 왕복한다고 본다.
#       즉 간선 VKT = 2 x D_TRUNK x 방문노드수.
#
# 근거(2026-09 보강): 수도권 택배 간선의 실제 기점 좌표로 역산했다.
#   CJ대한통운의 수도권 허브터미널은 군포복합물류단지(군포B HUB·부곡콘솔)에
#   있다. 이 지점에서 대표 시나리오 허브 18곳까지의 직선거리에 도로 우회계수
#   1.3을 적용하면:
#       물량가중평균 31.0km (단순평균 30.9km, 범위 18.4~47.2km)
#         가까운 쪽: 독산 18.4 / 총신대입구 21.9 / 구로 23.8
#         먼 쪽    : 불광 38.9 / 신이문 41.1 / 창동 47.2
#   -> D_TRUNK=30km는 임의값이 아니라 수도권 최대 택배 허브 기준의
#      물량가중평균에 해당한다(31.0km를 보수적으로 내림).
#      허브가 14 -> 18개로 바뀌어도 평균이 31.2 -> 31.0km로 거의 안 변해,
#      이 근거는 허브 구성에 민감하지 않다.
#
#   상한 범위의 근거: 이커머스 대형 물류센터가 몰린 이천(호법 일대) 70.8km,
#   용인 처인구 51.3km. 발송지가 이쪽이면 40~50km 구간이 해당한다.
#   -> 20/30/40/50km 민감도는 "군포 허브 ~ 이천·용인 물류센터" 범위를 덮는다.
#
#   ※ 좌표는 단지 대표점 근사이고 우회계수 1.3도 통상값(1.2~1.4)이라
#     ±10% 수준의 오차가 있다. 그래서 단일값이 아니라 민감도로 남긴다.
#     산출: scratchpad/dtrunk.py (허브별 거리표 포함)

# ── 2. 경유(디젤) CO2 배출계수 ─────────────────────────────
# 출처: 국가법령정보센터, "온실가스 배출권거래제 배출량 보고 및 인증에
# 관한 지침" [별표12] 연료별 국가 고유 발열량 및 배출계수
#   경유 순발열량 = 35.2 MJ/L, 경유(등유와 공유) CO2 배출계수 = 73,200 kgCO2/TJ
#   -> 35.2 MJ/L x 73,200 kgCO2/TJ / 1,000,000(MJ/TJ) = 2.577 kgCO2/L
DIESEL_MJ_PER_L = 35.2
DIESEL_KGCO2_PER_TJ = 73_200
DIESEL_KGCO2_PER_L = DIESEL_MJ_PER_L * DIESEL_KGCO2_PER_TJ / 1_000_000   # = 2.577

# ── 3. 전력 배출계수 ────────────────────────────────────────
# 출처: 기후에너지환경부 온실가스종합정보센터, 2023년 확정(공표) 전력배출계수
#   0.4173 tCO2eq/MWh = 0.4173 kgCO2eq/kWh
GRID_KGCO2_PER_KWH = 0.4173

# ── 4. 1톤 소형 경유 화물차(택배용, 포터/봉고급) 연비 ──────────
# 출처: 국토교통부는 최대적재량 1톤 초과 화물차를 에너지소비효율 표시
# 대상에서 제외해 "공인연비"가 없다. 실측/제조사 자료 기준 포터2·봉고3
# 디젤의 도심주행 연비는 8~10km/L로 보고된다. 배송 특성상(정차·재출발
# 반복, 적재 상태) 하단값인 8km/L을 보수적으로 채택한다.
TRUCK_KM_PER_L = 8.0
TRUCK_KGCO2_PER_KM = DIESEL_KGCO2_PER_L / TRUCK_KM_PER_L   # = 0.322 kgCO2/km

# ── 5~6. 전동차 화물 적재분 한계 전력 ──────────────────────────
# 원단위 출처: 서울메트로(現 서울교통공사) 1~4호선 실측, "2.42 kWh/차량-km"
# (2009년 11월 기준, 전기신문 "등촌광장" 칼럼 인용). 이는 전동차 1량이
# 1km 운행하는 데 드는 "전체" 에너지(공차 포함)이므로, 화물칸 적재로
# 늘어난 "한계"분만 반영하려면 (화물 중량)/(전동차 자중+화물 중량) 비율로
# 근사한다(견인 에너지가 대략 총중량에 비례한다는 단순화).
#   - 박스 평균 중량: 공식 통계 없음 — 택배 표준 규격(중소형 다수)을
#     감안해 5kg/박스로 가정(가정값, 검증 필요)
#   - 전동차 1량 자중: 공식 수치를 찾지 못함 — 국내 스테인리스 통근형
#     전동차 1량 자중이 통상 28~32톤 수준으로 알려져 있어 30톤으로 가정
#     (가정값, 검증 필요)
CAR_ENERGY_KWH_PER_CAR_KM = 2.42
BOX_WEIGHT_KG = 5.0
EMPTY_CAR_WEIGHT_TON = 30.0
BOX_PER_CAR = 1_500   # step2.py와 동일
CARGO_WEIGHT_TON = BOX_PER_CAR * BOX_WEIGHT_KG / 1000
MARGINAL_RATIO = CARGO_WEIGHT_TON / (EMPTY_CAR_WEIGHT_TON + CARGO_WEIGHT_TON)
MARGINAL_KWH_PER_CAR_KM = CAR_ENERGY_KWH_PER_CAR_KM * MARGINAL_RATIO

# ── 직관적 환산 상수 ────────────────────────────────────────
# 출처: 국립산림과학원 — 30년생 소나무 1그루 연간 CO2 흡수량 6.6kg,
# 승용차 1대 연간 CO2 배출량 2.4톤(관련 보도자료에서 함께 인용되는 통계)
#
# ★ 발표에는 승용차 환산만 쓴다. 소나무는 그루당 흡수량(6.6kg)이 작아
#   그루 수가 100만 단위로 커 보이는 착시가 있고, 심사에서 역산하면
#   부풀리기로 읽힐 수 있다. 승용차 환산이 더 정직하고 직관적이다.
#   소나무 값은 CSV 컬럼(소나무_환산_그루)으로만 남기고 콘솔 요약에서는 뺐다.
PINE_KGCO2_PER_YEAR = 6.6
CAR_TON_CO2_PER_YEAR = 2.4

print("[0] 배출계수/원단위")
print(f"    경유 CO2 배출계수      : {DIESEL_KGCO2_PER_L:.3f} kgCO2/L (법정 국가고유 배출계수)")
print(f"    전력 배출계수          : {GRID_KGCO2_PER_KWH} kgCO2/kWh (2023년 확정, 온실가스종합정보센터)")
print(f"    1톤 화물차 연비        : {TRUCK_KM_PER_L} km/L -> {TRUCK_KGCO2_PER_KM*1000:.0f} gCO2/km")
print(f"    화물칸 적재중량        : {CARGO_WEIGHT_TON:.1f}톤 (박스 {BOX_WEIGHT_KG}kg 가정 x {BOX_PER_CAR}박스)")
print(f"    한계 전력비율          : {MARGINAL_RATIO:.1%} (화물중량/(전동차자중{EMPTY_CAR_WEIGHT_TON}톤+화물중량))")
print(f"    한계 전력원단위        : {MARGINAL_KWH_PER_CAR_KM:.3f} kWh/차량-km "
      f"(전체 {CAR_ENERGY_KWH_PER_CAR_KM} kWh/차량-km x 한계비율)")


# ══════════════════════════════════════════════════════════
# 1. 노선망 재구축 — 방향별 편도 실거리(km) 산출용
#    1호선 코레일 구간 확장/기점 교체까지 포함해 network_common이 담당한다
#    (예전엔 이 보일러플레이트를 스크립트마다 복붙했는데, 1호선 확장 때
#    5곳을 똑같이 고쳐야 해서 공용 모듈로 뺐다).
#    시나리오와 무관하게 한 번만 구축 — 어느 역이 어느 방향에 몇 km
#    지점인지는 노선망 고유의 값이라 시나리오(허브 목록)가 바뀌어도 안 바뀐다.
# ══════════════════════════════════════════════════════════
import network_common as nc

print("\n[1] 노선망 재구축")
stations = nc.load_stations()
seg = nc.load_seg()
net = nc.build_network(stations, seg)
rail_km, hub_dir = net["rail_km"], net["hub_dir"]
DIR_ROUND_TRIP, MAX_TRIPS = net["DIR_ROUND_TRIP"], net["MAX_TRIPS"]
N_ST = len(stations)
name2idx = {n: i for i, n in enumerate(stations["역명"])}

results_all = pd.read_csv(f"{OUT}/scenario_results.csv")
hubs_all = pd.read_csv(f"{OUT}/scenario_hubs.csv")
vrp_summary_all = pd.read_csv(f"{OUT}/vrp_summary.csv")

REP_ID = nc.REP_SCENARIO["ID"]   # 비용효율 최적(대표 시나리오) — 정의는 network_common
MAX_ID = nc.MAX_SCENARIO_ID      # 환경효과 최대(실행가능 최대 분담률)
SCENARIO_LABELS = {REP_ID: f"비용효율 최적({REP_ID})", MAX_ID: f"환경효과 최대({MAX_ID})"}
SCENARIO_COLORS = {REP_ID: "#0072B2", MAX_ID: "#009E73"}


# ══════════════════════════════════════════════════════════
# 2. 시나리오 1개를 분석하는 함수 — 방향별 편도거리/전력CO2 + VKT/CO2 산출
# ══════════════════════════════════════════════════════════
def analyze_scenario(rep_id):
    srow = results_all[results_all["ID"] == rep_id].iloc[0]
    rep_cars, rep_trips, rep_share = int(srow["칸"]), int(srow["운행"]), float(srow["분담률"])
    hub_names = sorted(h.strip() for h in hubs_all[hubs_all["ID"] == rep_id].iloc[0]["선정역사"].split(","))

    print(f"\n[2-{rep_id}] {rep_cars}칸x{rep_trips}회, 분담률 {rep_share:.1%}, 허브 {len(hub_names)}개: {hub_names}")

    hub_dirs_used = sorted(set(hub_dir[name2idx[n]] for n in hub_names))
    dir_farthest_km = {}
    for dkey in hub_dirs_used:
        kms = [rail_km[name2idx[n]] for n in hub_names if hub_dir[name2idx[n]] == dkey]
        dir_farthest_km[dkey] = max(kms)

    total_train_km_per_day = 0.0
    for dkey in hub_dirs_used:
        eff = min(rep_trips, MAX_TRIPS[dkey])
        one_way_km = dir_farthest_km[dkey]
        train_km_per_day = eff * 2 * one_way_km
        total_train_km_per_day += train_km_per_day
        print(f"    {dkey:<28} 편도 {one_way_km:6.2f}km x 왕복 x {eff}회 = {train_km_per_day:8.1f} 편성-km/일")

    print(f"    합계 일일 편성-km: {total_train_km_per_day:,.1f} km/일")

    daily_kwh = total_train_km_per_day * rep_cars * MARGINAL_KWH_PER_CAR_KM
    daily_subway_co2_kg = daily_kwh * GRID_KGCO2_PER_KWH
    print(f"    일일 화물칸 전력량(한계분): {daily_kwh:,.1f} kWh/일 (편성-km x 화물칸수{rep_cars} x {MARGINAL_KWH_PER_CAR_KM:.3f})")
    print(f"    일일 지하철 화물 전력 CO2: {daily_subway_co2_kg:,.1f} kgCO2/일")

    vs = vrp_summary_all[vrp_summary_all["ID"] == rep_id]
    lastmile_A_km = vs["기존_거리km"].sum()
    trucks_A_lastmile = vs["기존_트럭대수"].sum()
    lastmile_B_km = vs["VRP_거리km"].sum()
    trucks_B = vs["VRP_트럭대수"].sum()
    print(f"    라스트마일(STEP 3) — 개별왕복 {lastmile_A_km:,.0f}km({trucks_A_lastmile}대), "
          f"VRP순회 {lastmile_B_km:,.0f}km({trucks_B}대)")

    rows = []
    for D_TRUNK in D_TRUNK_LIST_KM:
        trunk_A_km = 2 * D_TRUNK * trucks_A_lastmile
        vkt_A = lastmile_A_km + trunk_A_km
        vkt_B = lastmile_B_km

        vkt_saved = vkt_A - vkt_B
        vkt_saved_pct = vkt_saved / vkt_A

        co2_truck_A = vkt_A * TRUCK_KGCO2_PER_KM
        co2_truck_B = vkt_B * TRUCK_KGCO2_PER_KM
        co2_B_total = co2_truck_B + daily_subway_co2_kg
        co2_saved = co2_truck_A - co2_B_total
        co2_saved_pct = co2_saved / co2_truck_A

        yr_vkt_saved = vkt_saved * DAYS_PER_YEAR
        yr_co2_saved_kg = co2_saved * DAYS_PER_YEAR
        yr_co2_saved_ton = yr_co2_saved_kg / 1000

        cars_equiv = yr_co2_saved_ton / CAR_TON_CO2_PER_YEAR
        pine_equiv = yr_co2_saved_kg / PINE_KGCO2_PER_YEAR

        rows.append(dict(
            시나리오=rep_id, D_TRUNK_km=D_TRUNK,
            VKT_A_km_일=round(vkt_A), VKT_B_km_일=round(vkt_B),
            VKT_절감_km_일=round(vkt_saved), VKT_절감률=round(vkt_saved_pct, 4),
            CO2_A_kg_일=round(co2_truck_A), CO2_B_kg_일=round(co2_B_total),
            CO2_절감_kg_일=round(co2_saved), CO2_절감률=round(co2_saved_pct, 4),
            연간_VKT_절감_km=round(yr_vkt_saved), 연간_CO2_절감_톤=round(yr_co2_saved_ton, 2),
            승용차_환산_대=round(cars_equiv, 1), 소나무_환산_그루=round(pine_equiv),
            간선진입트럭_감소_대_일=round(trucks_A_lastmile),
        ))

    return dict(srow=srow, rep_cars=rep_cars, rep_trips=rep_trips, rep_share=rep_share,
               hub_names=hub_names, rows=rows,
               daily_subway_co2_kg=daily_subway_co2_kg)


SCENARIOS = [REP_ID, MAX_ID]
analysis = {sid: analyze_scenario(sid) for sid in SCENARIOS}

summary_rows_all = [r for sid in SCENARIOS for r in analysis[sid]["rows"]]
summary_df = pd.DataFrame(summary_rows_all)
summary_df.to_csv(f"{OUT}/emission_summary.csv", index=False, encoding="utf-8-sig")
print(f"\n저장: {OUT}\\emission_summary.csv")

for sid in SCENARIOS:
    print(f"\n{'='*70}\n[{sid}] D_TRUNK별 상세")
    for D_TRUNK in D_TRUNK_LIST_KM:
        row = next(r for r in analysis[sid]["rows"] if r["D_TRUNK_km"] == D_TRUNK)
        print(f"  D_TRUNK={D_TRUNK}km | VKT (A){row['VKT_A_km_일']:,}->({row['VKT_B_km_일']:,})km/일 "
              f"절감 {row['VKT_절감률']:.0%} | CO2 (A){row['CO2_A_kg_일']:,}->({row['CO2_B_kg_일']:,})kg/일 "
              f"절감 {row['CO2_절감률']:.0%} | 연간 CO2 {row['연간_CO2_절감_톤']:,.1f}톤")


# ══════════════════════════════════════════════════════════
# 3. 전체 스펙 비교표 (대표 vs SMAX) — 칸수·운행횟수·분담률·허브·비용·비중
# ══════════════════════════════════════════════════════════
spec_rows = []
for sid in SCENARIOS:
    a = analysis[sid]
    srow = a["srow"]
    spec_rows.append(dict(
        시나리오=SCENARIO_LABELS[sid], ID=sid,
        칸=a["rep_cars"], 운행=a["rep_trips"], 분담률=f"{a['rep_share']:.1%}",
        필요물량_박스일=round(srow["필요물량"]),
        허브개수=int(srow["n"]),
        허브목록=", ".join(a["hub_names"]),
        총비용_원일=round(srow["총비용"]),
        단위비용_원박스=round(srow["단위비용"], 1),
        라스트마일비중=f"{srow['라스트마일비중']:.1%}",
        철도비중=f"{srow['철도비중']:.1%}",
        심도비중=f"{srow['심도비중']:.1%}",
        고정비비중=f"{srow['고정비중']:.1%}",
    ))
spec_df = pd.DataFrame(spec_rows)
print("\n" + "=" * 70)
print(f"[{REP_ID} vs {MAX_ID} 전체 스펙 비교표]")
print(spec_df.drop(columns=["허브목록"]).to_string(index=False))
print(f"\n{REP_ID} 허브: {analysis[REP_ID]['hub_names']}")
print(f"{MAX_ID} 허브: {analysis[MAX_ID]['hub_names']}")
spec_df.to_csv(f"{OUT}/scenario_spec_comparison.csv", index=False, encoding="utf-8-sig")
print(f"\n저장: {OUT}\\scenario_spec_comparison.csv")


# ══════════════════════════════════════════════════════════
# 4. 시각화 — D_TRUNK=30km(민감도 범위 중간) 기준, 두 시나리오 나란히
# ══════════════════════════════════════════════════════════
fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))
x = np.arange(len(SCENARIOS))
width = 0.35

def get_main(sid, key):
    return next(r for r in analysis[sid]["rows"] if r["D_TRUNK_km"] == D_TRUNK_MAIN)[key]

ax = axes[0]
vkt_a = [get_main(s, "VKT_A_km_일") for s in SCENARIOS]
vkt_b = [get_main(s, "VKT_B_km_일") for s in SCENARIOS]
ax.bar(x - width/2, vkt_a, width, label="(A) 기존(트럭 전량)", color="#D55E00")
ax.bar(x + width/2, vkt_b, width, label="(B) 지하철 도입", color="#0072B2")
ax.set_xticks(x); ax.set_xticklabels([f"{SCENARIO_LABELS[s]}\n분담률 {analysis[s]['rep_share']:.1%}" for s in SCENARIOS])
ax.set_ylabel("VKT (km/일)")
ax.set_title(f"일일 주행거리(VKT) 비교 (D_TRUNK={D_TRUNK_MAIN}km 가정)")
ax.legend(); ax.grid(alpha=.3, axis="y")
for i, s in enumerate(SCENARIOS):
    pct = get_main(s, "VKT_절감률")
    ax.annotate(f"-{pct:.0%}", (x[i], vkt_b[i]), textcoords="offset points",
               xytext=(0, 8), ha="center", fontsize=9, color="#0072B2")

ax = axes[1]
co2_a = [get_main(s, "CO2_A_kg_일") for s in SCENARIOS]
co2_b = [get_main(s, "CO2_B_kg_일") for s in SCENARIOS]
ax.bar(x - width/2, co2_a, width, label="(A) 기존(트럭 전량)", color="#D55E00")
ax.bar(x + width/2, co2_b, width, label="(B) 지하철 도입(트럭+전력)", color="#0072B2")
ax.set_xticks(x); ax.set_xticklabels([f"{SCENARIO_LABELS[s]}\n분담률 {analysis[s]['rep_share']:.1%}" for s in SCENARIOS])
ax.set_ylabel("CO2 (kg/일)")
ax.set_title(f"일일 CO2 배출량 비교 (D_TRUNK={D_TRUNK_MAIN}km 가정)")
ax.legend(); ax.grid(alpha=.3, axis="y")
for i, s in enumerate(SCENARIOS):
    pct = get_main(s, "CO2_절감률")
    ax.annotate(f"-{pct:.0%}", (x[i], co2_b[i]), textcoords="offset points",
               xytext=(0, 8), ha="center", fontsize=9, color="#0072B2")

plt.suptitle(f"비용효율 최적({REP_ID}, {analysis[REP_ID]['rep_share']:.0%}) vs "
            f"환경효과 최대({MAX_ID}, {analysis[MAX_ID]['rep_share']:.1%}) — "
            "분담률이 커지는 만큼 절감 절대량도 비례해 커지지만, 단위비용도 함께 오른다",
            fontsize=10, y=1.02)
plt.tight_layout()
nc.savefig_retry(plt, f"{OUT}/emission_comparison.png", dpi=150, bbox_inches="tight")
plt.close(fig)
print(f"저장: {OUT}\\emission_comparison.png")


# ══════════════════════════════════════════════════════════
# 5. 콘솔 요약 (D_TRUNK=30km 기준) — 부풀리지 않고 조건부로 정직하게 보고
# ══════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print(f"요약 (D_TRUNK={D_TRUNK_MAIN}km 기준, 중간값)")
for sid in SCENARIOS:
    a = analysis[sid]
    row = next(r for r in a["rows"] if r["D_TRUNK_km"] == D_TRUNK_MAIN)
    srow = a["srow"]
    print(f"\n  [{SCENARIO_LABELS[sid]}] 분담률 {a['rep_share']:.1%}, "
          f"단위비용 {srow['단위비용']:.1f}원/박스, 허브 {int(srow['n'])}개")
    print(f"    VKT 절감: 일 {row['VKT_절감_km_일']:,}km ({row['VKT_절감률']:.0%}), "
          f"연간 {row['연간_VKT_절감_km']:,}km")
    print(f"    CO2 절감: 일 {row['CO2_절감_kg_일']:,}kg, 연간 {row['연간_CO2_절감_톤']:,.1f}톤")
    print(f"    환산: 승용차 {row['승용차_환산_대']}대분/년  (소나무 환산은 발표에서 쓰지 않음 — 위 상수 주석 참고)")
    print(f"    도심 진입 트럭: {row['간선진입트럭_감소_대_일']:,}대/일 -> 0대/일")

rep_co2 = next(r for r in analysis[REP_ID]["rows"] if r["D_TRUNK_km"] == D_TRUNK_MAIN)["연간_CO2_절감_톤"]
smax_co2 = next(r for r in analysis[MAX_ID]["rows"] if r["D_TRUNK_km"] == D_TRUNK_MAIN)["연간_CO2_절감_톤"]
smax_unit = analysis[MAX_ID]["srow"]["단위비용"]
rep_unit = analysis[REP_ID]["srow"]["단위비용"]
print(f"\n  ※ {MAX_ID}는 {REP_ID} 대비 물량이 "
      f"{analysis[MAX_ID]['rep_share']/analysis[REP_ID]['rep_share']:.1f}배라 "
      f"연간 CO2 절감량도 {smax_co2/rep_co2:.1f}배({rep_co2:,.0f}->{smax_co2:,.0f}톤/년)로 커진다.")
print(f"  ※ 그러나 단위비용은 {rep_unit:.1f}->{smax_unit:.1f}원/박스로 {(smax_unit/rep_unit-1):+.0%} 변한다 —")
print(f"    분담률을 올릴수록 환경효과와 비용효율이 트레이드오프 관계에 있음을 그대로 보여준다.")
print("=" * 70)
