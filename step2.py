"""
STEP 2. 시나리오별 허브 입지 최적화
────────────────────────────────────────────────────────────
시나리오 축 3개를 바꿔가며, 각 조건에서
  · 최적 허브 개수 n*
  · 그 위치 (역 이름)
  · 총비용 / 박스당 단위비용
을 구합니다.

  분담률   20% / 25% / 30%
  운행횟수 10 / 15 / 20회 (★ 노선 "한 방향"당 — 아래 [철도비 전면 재설계] 참고)
  칸  수   1 / 2 / 3 / 4칸
  -> 36개 시나리오

마지막에 허브 개수 엘보우 분석(대표 시나리오에서 n을 1개씩 고정해가며
비용 곡선을 그려 적정 개수를 시각적으로 확인)과 n별 허브 위치를 추가로 살펴봅니다.

[이번 단계에서 의도적으로 제외한 것]
  · 혼잡도 기반 가용 시간대 검증
  나중에 확장합니다.

로컬 실행용으로 경로만 /content -> 프로젝트 폴더로 변경.

[이전 수정 이력]
  · len(오케이) -> len(ok) NameError 수정
  · DEPOTS 재검토 — 신설동(1호선)/용답·양천구청(2호선)/지축·수서(3호선)/
    창동(4호선) 6개 기점으로 전 노선 커버
  · 심도 기반 엘리베이터 비용, 임대료 기반 역별 차등 고정비 반영 (1.py에서)
  · CARS = [1,2,3] -> [1,2,3,4]
  (직전 결과는 output_data/backup_철도비수정전/ 에 백업)

════════════════════════════════════════════════════════════
[철도비 전면 재설계] — 3가지 문제가 얽혀 있어 한 번에 고쳤다
════════════════════════════════════════════════════════════

■ 문제 1. 단위 불일치
  기존: rail = ALPHA * rail_t[j] / cap_line * q[j]
  rail_t[j](열차 편도 소요시간, 분)를 "하루 전체 수송능력"(박스/일)으로
  나누고 있어 차원이 안 맞았고, 운행횟수(trips)가 늘수록 박스당 철도비가
  과소평가돼 철도가 사실상 "공짜"로 계산되고 있었다.
  -> 아래 [순차 하역 모델]에서 시간 기반으로 전면 재계산한다.

■ 문제 2. hub_line이 "허브가 속한 노선"이 아니라 "가장 빨리 닿은 기점의 노선"
  기존에는 환승(노선 무관 전역 Floyd-Warshall)을 허용해 rail_t를 계산했기
  때문에, 예를 들어 2호선 사당역이 4호선 창동기지에서 최단이면 사당역이
  "4호선 허브"로 분류되고 사당역 물량이 4호선 수송능력에서 차감됐다.
  -> 수정: 노선 소속은 stations.csv의 "노선" 컬럼(그 역이 실제로 걸쳐 있는
  노선)만 후보로 삼는다. 환승역(여러 노선 소속)은 소속 노선들 각각에 대해
  "그 노선 자기 선로망만으로" 도달시간을 계산하고, 그중 최단인 노선으로
  배정한다(교수님 코멘트에 적힌 "결정변수로 두거나(권장), 어려우면 최단
  소속 노선으로 배정" 중 후자 — 문제 3의 방향(레이) 분리까지 결정변수로
  얹으면 이번 재설계 범위에서 감당이 안 돼 후자를 택했다. 자세한 이유는
  아래 [설계 판단: 환승역 노선 배정]).
  이 수정의 자연스러운 결과로, 기존에 있던 "환승 허용(노선 무관 전역
  Floyd-Warshall, 환승시간 0 가정)" 메커니즘은 더 이상 쓰지 않는다 — 문제
  3에서 화물열차가 "자기 노선 선로만 달리는 물리적 실체"로 모델링되는
  이상, 서로 다른 노선을 공짜로 갈아타는 경로를 철도비 계산에 쓰는 것 자체가
  모순이기 때문이다(환승역거리 소요시간 CSV도 이제 안 쓴다).

■ 문제 3. 순차 하역 미반영 (핵심 피드백)
  기존 모델은 화물이 기점에서 각 허브로 "개별 직통"한다고 가정해 rail_t를
  단순 합산했다. 실제로는 열차가 선로를 따라 순차 정차하며 짐을 나눠
  내리므로, 기점~중간역 구간이 허브 수만큼 중복 계산돼 철도비가 과대
  청구되고 있었다(허브가 많을수록 더 심해짐 -> n* 왜곡).

  [순차 운행 모델]
  지하철은 선로가 고정이라 방문 "순서"를 최적화할 필요가 없다 —
  "기점에서 가장 먼 허브까지 가는 동안 중간 허브를 자동으로 지난다"가
  물리적 사실이다. 그래서 노선(방향)별로:

    T_dir = 기점→최원 허브 주행시간  +  Σ(각 정차역 하역시간)
    하역시간_j = q[j] / UNLOAD_RATE
    비용_dir  = ALPHA_RAIL * trips * T_dir(주행 부분)
              + ALPHA_LABOR * trips * Σ(하역시간_j)   (아래 ALPHA 분리 참고)

  "최원 허브 주행시간"은 MILP에서 max를 직접 못 쓰므로 표준적인 방식으로
  선형화한다: 방향별 변수 T_travel[dir] >= (기준시간) * h[j] (그 방향의
  모든 후보 j에 대해). 목적함수에서 T_travel[dir]에 양(+)의 비용이 걸려
  있으므로, 최소화 과정에서 자연히 그 방향의 기준시간으로 수렴한다.

  ★ 2026-09 개정 — 기준시간을 rail_t[j](기점->최원허브 편도)에서
    DIR_ROUND_TRIP[dir](레이 끝까지 왕복)로 바꿨다. ALPHA_RAIL에 승무
    인건비가 포함되는데 승무는 왕복 전체에 발생하기 때문이다. 이제 T는
    "레이 사용 여부"에 따라 0 또는 DIR_ROUND_TRIP이 되어 레이당 고정비처럼
    작동하며, 같은 레이 안에서는 허브 위치가 철도비에 영향을 주지 않는다.
    시간 제약이 이미 DIR_ROUND_TRIP을 쓰고 있어 비용/시간 기준이 일치한다.
    라스트마일도 같은 개정에서 편도 -> 왕복(2*dist)으로 고쳤다.
    ※ 실제 수식은 network_common.solve_hub_location() 한 곳에만 있다.
      이 파일의 solve()는 그 함수를 호출하는 얇은 래퍼다.

  [수정: 하역비에는 trips를 곱하지 않는다]
  처음에는 T_dir 전체(주행+하역)에 trips를 곱했는데, 이러면 "trips 횟수만큼
  그 역 하루 물량 전체를 매번 하역한다"는 셈이 돼 하역 인건비가 운행횟수에
  비례해 과대 청구되는 버그가 있었다(q[j]는 하루 총 물량이라, 20번에
  나눠 오면 회당 물량만 1/20이 될 뿐 총 하역 작업량은 동일한데도 x20이
  걸렸었음). 그래서 최종 식은:
    rail_travel = ALPHA_RAIL * trips * T_travel[dir]     (주행은 trips배가 맞음 — 실제로 그만큼 왕복)
    rail_unload = ALPHA_LABOR * Σ(q[j] / UNLOAD_RATE)    (trips 없음 — 하루 총 하역 작업량은 고정)
  이렇게 분리했다. (참고: 정차당 문 개폐·대기 같은 고정 오버헤드까지
  반영하려면 ALPHA_LABOR*trips*DWELL_OVERHEAD*h[j] 항을 추가하는 방법이
  있으나, 이번 수정 범위에서는 넣지 않았다.)

  [방향 분리 — 노선을 상행/하행(및 2호선은 분기)으로 쪼갠다]
  기점이 노선 중간에 있으면 허브가 기점 양쪽으로 흩어질 수 있어, 한쪽
  최원거리만 쓰면 반대편 허브가 누락된다. "역간거리" 데이터로 만든
  노선별 전용(환승 미포함) 그래프에서, 기점 노드를 제거했을 때 갈라지는
  연결요소를 그 기점의 "방향(레이)"으로 정의한다:
    - 신설동(1호선 기점, 노선 중간) -> 서울역쪽 / 청량리쪽 2방향
    - 지축(3호선 기점, 노선 끝) -> 1방향
    - 수서(3호선 기점, 노선 중간) -> 지축쪽 / 오금쪽 2방향
    - 창동(4호선 기점, 노선 중간) -> 당고개쪽 / 남태령쪽 2방향
    - 용답(2호선 기점) -> 성수지선쪽(신답·용두·신설동) / 본선순환쪽 2방향
    - 양천구청(2호선 기점) -> 신정지선쪽(신정네거리·까치산) / 본선순환쪽 2방향
  용답과 양천구청 둘 다 "본선순환쪽" 방향을 갖지만, 이 둘은 서로 다른
  진입점(성수 vs 신도림)에서 도는 별개의 레이로 취급한다 — 실제로도
  2호선 순환선은 여러 차량기지에서 각각 편성이 투입되는 구조라 물리적
  으로도 타당한 근사다(자세한 설계 판단은 아래).

  [설계 판단: 왜 "본선순환/성수지선/신정지선" 3버킷을 손으로 나누지
  않고 그래프 알고리즘으로 도출했나]
  손으로 역 목록을 나열하면(순환선만 43개 역) 오타·누락 위험이 크다.
  대신 "기점 제거 -> 연결요소 분리 + 최단 기점 배정"을 전 노선에 동일하게
  적용하면 성수지선/신정지선은 자동으로 분리된다 — 예컨대 신정네거리·
  까치산은 용답 기점을 거쳐 순환선을 한 바퀴 돌아가는 경로도 위상적으로는
  존재하지만, 양천구청 기점에서 직접 가는 경로가 항상 훨씬 짧아 최단
  선택 과정에서 저절로 걸러진다.

  [추가 수정: 방향별 심야 가용시간 상한 (TRIPS 물리적 실행가능성)]
  처음에는 시나리오 TRIPS(10/15/20)를 "방향 하나당" 그대로 적용했는데,
  이러면 예컨대 2호선처럼 방향이 4개인 노선은 20회씩 총 80회가 되고,
  본선순환처럼 왕복 80~103분 걸리는 긴 방향까지 20회 왕복(1,600~2,060분)
  이 가능한 것처럼 계산돼 버렸다(step2_trips_feasibility_check.py로 검증
  — 짧은 지선 6개만 20회를 감당하고, 긴 방향 5개는 10회에서도 4~6배
  초과). 그래서 방향별로 "물리적으로 가능한 최대 trips"를 따로 구해 희망
  trips와 min을 취한다:

    심야 가용시간 AVAILABLE_MIN = 180분
      근거: 막차 종착(24~01시)~첫차 준비(05시)의 물리적 간격은 240~300분
      이지만, 서울교통공사가 이 시간대를 안전관리·방역·선로보수에 쓰고
      있다(2020년 심야 1시간 단축운행 공지 "심야시간대 안전관리와
      방역업무 시간 확보가 절실"; 홈페이지 "열차서행정보(선로공사)" 상시
      메뉴 운영 = 선로공사가 일상적으로 진행됨). 정비 시간을 침범하지
      않는 화물 가용시간으로 180분을 쓴다.
      ★ 민감도 분석 대상: 120 / 180 / 240분 (AVAILABLE_MIN_SENSITIVITY).
    TURNAROUND_MIN = 10분 — 종점 회차(방향전환) 오버헤드.
    max_trips[방향] = floor(AVAILABLE_MIN / (왕복주행시간[방향] + TURNAROUND_MIN))
    eff_trips[방향] = min(희망 trips, max_trips[방향])

  "왕복주행시간"은 그 방향에 속한 모든 역(개설된 허브뿐 아니라 노선의
  물리적 끝까지) 중 최원 기준이다 — 열차는 어차피 그 방향 선로 끝이나
  최소한 회차 지점까지 가야 하기 때문이다. eff_trips는 수송능력
  (cap_dir = BOX_PER_CAR*cars*eff_trips)과 철도 주행비(rail_travel =
  ALPHA_RAIL*eff_trips*T_travel) 양쪽에 모두 쓰인다.

  [추가 수정: 하역시간도 심야 가용시간 제약에 넣는다]
  위 max_trips는 "주행+회차" 시간만으로 eff_trips를 캡핑하고, 하역시간
  (q[j]/UNLOAD_RATE)은 rail_unload 비용에만 반영하고 있었다. 그런데
  eff_trips*(왕복주행+회차)가 이미 180분에 가깝게 채워진 방향(특히 rail_t=0인
  "기점 자신" 방향처럼 트래블타임이 0에 가까워 eff_trips가 최댓값(18회)까지
  차는 경우)에 하역량까지 쌓이면, 실제 총 소요시간이 180분을 크게 초과하는데도
  모델은 이를 걸러내지 못했다(step2_unload_time_check.py로 검증 — 수정 전
  27개 실행가능 시나리오 전부가 실제로는 180분을 최대 4.6배 초과했음, 주로
  "차량기지 = 허브"로 잡혀 트래블타임 0 + 사실상 무제한급 하역량이 쌓인
  경우). 그래서 방향별 수송능력 제약에 하역시간까지 반영한 항을 추가한다:

    remaining_min[방향] = AVAILABLE_MIN - eff_trips[방향]*(왕복주행시간+TURNAROUND_MIN)
    Σ(q[j] for j in 그 방향 허브들) <= remaining_min[방향] * UNLOAD_RATE

  즉 "주행+회차로 쓰고 남은 시간"만큼만 하역 물량을 실을 수 있다. 기존
  cap_dir(트럭/열차 적재량 기준 상한)과 별개로, 이 시간 기준 상한이 더
  타이트하면 그쪽이 실제 병목이 된다.

■ 엘리베이터 처리량 제약 (UNLOAD_RATE 기본값 재검토와 함께 발견)
  UNLOAD_RATE(150박스/분)를 "열차 문 1개, 롤테이너 1대 20초"로 근거를
  댔는데, 문을 3개(편측 4개 중 3개) 병렬로 쓰면 450박스/분까지 가능하다는
  지적을 받았다. 문제는 문에서 내린 물량이 지상으로 나가려면 엘리베이터를
  타야 하는데, 그 처리량이 전혀 체크가 안 되고 있었다는 점이다:
    - elev 비용항은 station_depth[j]/ELEV_SPEED_MPM(편도)만 써서 실제
      왕복(내려가서 다음 짐을 실으러 돌아옴)의 절반만 계산하고 있었다
      -> 심도 15m 기준 100박스/분으로 잡히던 게, 왕복 기준(올바른 계산)
      으로는 50박스/분이다(사용자가 제시한 수치와 일치, ELEV_CAPACITY=50
      /round_trip=1분).
    - 게다가 이 처리시간은 비용(elev)에만 들어가고, "심야 가용시간 안에
      다 실어 올려야 한다"는 제약으로는 어디에도 안 걸려 있었다 — 문제3의
      rail_unload와 정확히 같은 종류의 버그다.
  두 가지를 모두 고쳤다:
    1) elev 비용항: depth/speed -> 2*depth/speed (왕복)
    2) 엘리베이터 1대 기준 심야 처리량 상한을 새로 추가:
       elev_cap[j] = AVAILABLE_MIN * ELEV_CAPACITY / (2*station_depth[j]/ELEV_SPEED_MPM)
       q[j] <= elev_cap[j] * h[j]
  이 제약이 생기면서 UNLOAD_RATE를 450으로 올려도 "문에서 내리는 속도"만
  빨라질 뿐, 엘리베이터가 여전히 병목인 역에서는 결과가 그대로 그 한도에
  묶인다 — 즉 UNLOAD_RATE를 올리는 게 안전해졌다(이전처럼 근거 없이
  결과를 낙관적으로 부풀리지 않는다). 실제로 재실행해보면 엘리베이터
  제약만으로도(UNLOAD_RATE는 150 그대로) 실행가능 시나리오가 20/23->11/14,
  최소 단위비용이 43->46원/박스로 나빠졌다 — 엘리베이터가 이미 상당히
  타이트한 병목이었다는 뜻. UNLOAD_RATE=450으로 올린 뒤의 결과는 실행
  로그를 참고.
  ★ 엘리베이터 대수는 1대로 가정했다(실제 대수를 알면 elev_cap에 그
  대수를 곱하면 된다) — 이것도 근거가 약한 가정값이다.

■ ALPHA 이중 사용 분리
  기존 ALPHA(500원/분)를 철도 운행비·엘리베이터 하역비 양쪽에 썼는데,
  열차 1편성 운행 원가와 하역 인건비는 단가 성격이 전혀 다르다.
  (아래 두 값은 사용자가 직접 산정해 지정한 값 — 추가 표준단가 조사는
  하지 않았다.)

  ALPHA_LABOR = 270원/분 — 하역 인건비 (엘리베이터 하역, 역내 상하역 작업)
    근거: 물류 상하차(HUB) 시급 10,780원(2026년 최저임금 10,320원 대비
    가산) x 1.5(근로기준법 제56조, 22~06시 야간근로 50% 가산) / 60분
    = 269.5 -> 270원/분.

  ALPHA_RAIL = 700원/분 — 열차 운행의 "한계비용"(민감도 분석 대상)
    근거: 심야 유휴 편성을 활용한다는 전제라 화물 운행분의 한계비용만
    계상한다(승무 인건비 + 견인에 따른 전력 증가분). 서울교통공사 2025년
    원가분석의 수송원가 1,817원/인은 여객 만차를 가정한 총원가라 화물
    운행에 그대로 적용하면 과대평가된다(편성 정원 약 1,600명 환산 시
    36,000~48,000원/분이라는 비현실적 수치가 나와 미채택).
    ★ 민감도 분석 대상: 500 / 700 / 1,000 / 2,000원/분 4가지로 결과가
    어떻게 바뀌는지 별도로 확인한다 (ALPHA_RAIL_SENSITIVITY 참고,
    step2_alpha_rail_sensitivity.py에서 실행).

  UNLOAD_RATE (박스/분, 역당 하역 처리속도) — 롤테이너 1대(50박스)를
    내리는 데 20초 걸린다고 가정하면 50박스/20초 = 150박스/분. 실측치가
    아닌 가정값이라 사용자 지정으로 30/50/100/150박스/분 4가지 민감도
    분석을 병행한다 (UNLOAD_RATE_SENSITIVITY, step2_alpha_rail_sensitivity.py).
"""

import os
import re
import datetime
import numpy as np
import pandas as pd
import networkx as nx
import pulp
import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams["font.family"] = "Malgun Gothic"
matplotlib.rcParams["axes.unicode_minus"] = False
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.lines import Line2D
import network_common as nc   # MILP 본체(solve_hub_location) + savefig 재시도만 사용
                              # — 데이터 로드/노선망 구축은 이 파일 Section 1~2가 정본

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "output_data")

# ══════════════════════════════════════════════════════════
# 0. 파라미터
# ══════════════════════════════════════════════════════════
# --- 적재량 ---
BOX_PER_CAR    = 1_500      # 박스/칸 (사용자 지정 — 롤테이너 적재 기준 재산정치)

# --- 비용 원단위 ---
COST_PER_KM    = 1_500     # 원/km  트럭 운행 (감가상각+유류+인건비)
TRUCK_CAP      = 200       # 박스/대 라스트마일 탑차 적재량

# --- 시간가치 (ALPHA 이중사용 분리 — 근거는 위 docstring [ALPHA 이중 사용 분리]) ---
ALPHA_LABOR = 270    # 원/분  하역 인건비 (엘리베이터 하역, 역내 상하역 작업)
ALPHA_RAIL  = 700    # 원/분  열차 운행 한계비용 (기본값 — 민감도 분석 대상)
ALPHA_RAIL_SENSITIVITY = [500, 700, 1_000, 2_000]   # step2_alpha_rail_sensitivity.py에서 사용

# --- 순차 하역(철도) 모델 — 근거는 위 docstring [철도비 전면 재설계] ---
UNLOAD_RATE = 450   # 박스/분  역당 "열차 문" 하역 처리속도 (편측 문 4개 중 3개 병렬
                     # 사용 = 150 x 3. 엘리베이터 처리량은 별도로 elev_cap 제약에서
                     # 독립적으로 체크하므로(아래 [엘리베이터 처리량 제약] 참고),
                     # 이 값을 올려도 엘리베이터가 여전히 병목이면 결과에 반영된다.
UNLOAD_RATE_SENSITIVITY = [150, 300, 450, 600]      # step2_alpha_rail_sensitivity.py에서 사용

# --- 방향별 심야 가용시간 (TRIPS 물리적 실행가능성) ---
#   근거: 막차 종착(24~01시)~첫차 준비(05시) 물리적 간격은 240~300분이지만,
#   서울교통공사가 이 시간대를 안전관리·방역·선로보수에 쓰고 있다(2020년
#   심야 1시간 단축운행 공지 "심야시간대 안전관리와 방역업무 시간 확보가
#   절실"; 홈페이지 "열차서행정보(선로공사)" 상시 메뉴 운영). 정비 시간을
#   침범하지 않는 화물 가용시간으로 180분을 쓴다.
AVAILABLE_MIN = 180                       # 분  방향(레이)당 심야 가용시간
AVAILABLE_MIN_SENSITIVITY = [120, 180, 240]         # step2_alpha_rail_sensitivity.py에서 사용
TURNAROUND_MIN = 10                       # 분  종점 회차(방향전환) 오버헤드

# --- 심도(엘리베이터) 비용 — 1.py에서 반영 ---
ELEV_SPEED_MPM = 30        # m/분   엘리베이터 속도
ELEV_CAPACITY  = 50        # 박스/회 엘리베이터 1회 운반량
DEFAULT_DEPTH  = 15.0      # m      심도정보 없는 역 기본값

# --- 허브 고정비(임대료 기반) — 1.py에서 반영 ---
DEFAULT_FIXED  = 500_000   # 원/일  임대정보 없는 역 기본 고정비

# --- 시나리오 축 ---
# 하역시간까지 포함한 심야 가용시간 제약을 추가한 뒤 원래 축(20~30%)은
# 전부 불가능으로 나와(step2_max_feasible_share.py) 실행가능 구간으로
# 재설계했다. 이후 UNLOAD_RATE=150 기준 최대 실행가능이 16.80%로 확인돼
# (policy_unload_rate.csv) SHARES를 그 절반 수준이 아니라 근접하게 확장했다.
SHARES = [0.04, 0.08, 0.12, 0.16]  # 분담률
TRIPS  = [5, 10, 15]               # 야간 운행 편성 수 (노선 "한 방향"당, 희망치)
CARS   = [1, 2, 3, 4]              # 화물 전용 칸 수

N_MAX  = 30                      # 허브 개수 탐색 상한

# 차량기지 -> (접속역, 담당 노선)
#   군자차량기지는 2호선(용답)뿐 아니라 1호선(신설동 유령승강장 경유 입고)도
#   담당하므로 두 항목으로 나눠 등록한다.
#
#   ★ 1호선 기점 교체(신설동 -> 구로/신이문): 예전에는 1호선의 실제
#   차량사업소(구로차량사업소/이문차량사업소, 둘 다 코레일 관할)가 데이터에
#   없어서 "신설동 유령승강장 경유 입고"를 근거로 신설동을 대체 기점으로
#   썼다. 이번에 1호선을 코레일 관할 구간까지 확장하면서 구로·신이문 실제
#   좌표가 들어왔으므로, 더 이상 대체할 필요 없이 물리적으로 맞는 기점으로
#   바꾼다: 구로차량사업소(경부선/경인선 방면 담당, 구로역 인근)와
#   이문차량사업소(경원선 방면 담당, 신이문역 인근). 이문차량사업소는
#   실제 위치가 신이문역 바로 옆이라는 것만 확인했고, 현재도 운영 중인지는
#   이번 분석 범위에서 별도로 검증하지 않았다 — 위치 대체용으로만 쓴다.
DEPOTS = {
    "구로차량사업소":      ("구로",     "1"),
    "이문차량사업소":      ("신이문",   "1"),
    "군자차량기지(2호선)": ("용답",     "2"),
    "신정차량기지":        ("양천구청", "2"),
    "지축차량기지":        ("지축",     "3"),
    "수서차량기지":        ("수서",     "3"),
    "창동차량기지":        ("창동",     "4"),
}


# ══════════════════════════════════════════════════════════
# 1. 데이터 로드
# ══════════════════════════════════════════════════════════
print("[1] 데이터 로드")
stations = pd.read_csv(f"{OUT}/stations.csv")
dongs    = pd.read_csv(f"{OUT}/dongs.csv")
dist     = np.load(f"{OUT}/dist_km.npy")          # [역 x 동] km — step1c_extend_line1_stations.py로
                                                    # 1호선 신규 26개역분(도로망 실측)까지 이미 확장됨

# ══════════════════════════════════════════════════════════
# 1x. 1호선 코레일 관할 구간 26개역 추가
#   서울교통공사 역간거리 CSV는 1호선을 서울역~청량리 10개역(서울교통공사
#   관할 지하구간)만 담고 있었다 — 그 서쪽(경부선/경인선)·동쪽(경원선)은
#   한국철도공사 관할이라 데이터 자체에 없었고, 그래서 지금까지 구로·
#   영등포·용산·노량진 같은 서울 서남부 주요역이 후보에서 통째로 빠져
#   있었다. "한국철도공사_도시광역철도_역사정보" 파일(노선명이 경부선/
#   경인선/경원선으로 세분화됨)에서 서울 구간 26개역 좌표를 가져와 채운다.
#   - 경의중앙선과 겹치는 서빙고/옥수/응봉/이촌/한남/왕십리는 제외
#     (경원선 표에 같이 실려 있지만 실제로는 1호선이 그쪽으로 가지 않음)
#   - 경기도 구간(안양/의정부 이북 등)은 "역사도로명주소"가 "서울"로
#     시작하는 역만 남겨 자동으로 제외
# ══════════════════════════════════════════════════════════
print("[1x] 1호선 코레일 관할 구간 26개역 추가")
LINE1_KORAIL_TARGETS = [
    "가산디지털단지", "개봉", "광운대", "구로", "구일", "금천구청", "남영", "노량진", "녹천",
    "대방", "도봉", "도봉산", "독산", "방학", "석계", "신길", "신도림", "신이문", "영등포",
    "오류동", "온수", "외대앞", "용산", "월계", "창동", "회기",
]
LINE1_EXCLUDE_JUNGANG = {"서빙고", "옥수", "응봉", "이촌", "한남", "왕십리"}

_master = pd.read_excel(os.path.join(BASE, "한국철도공사_도시광역철도_역사정보_20260228.xlsx"))
_master["역사명_clean"] = _master["역사명"].map(lambda s: re.sub(r"\([^)]*\)", "", str(s)).replace("역", "").strip())
_cand = _master[_master["노선명"].isin(["경부선", "경인선", "경원선"])].copy()
_cand = _cand[_cand["역사도로명주소"].astype(str).str.startswith("서울")]
_cand = _cand[~_cand["역사명_clean"].isin(LINE1_EXCLUDE_JUNGANG)]
_cand = _cand[_cand["역사명_clean"].isin(LINE1_KORAIL_TARGETS)].drop_duplicates(subset="역사명_clean")
if len(_cand) != len(LINE1_KORAIL_TARGETS):
    print(f"    ! 26개역 중 {len(_cand)}개만 찾음 — 확인 필요: "
          f"{set(LINE1_KORAIL_TARGETS) - set(_cand['역사명_clean'])}")

stations["노선"] = stations["노선"].astype(str)
# 창동은 이미 4호선으로 존재하는 물리역(코레일 1호선도 지나가는 환승역) —
# 새 행을 만들지 않고 기존 행의 "노선"에 "1"만 추가한다.
_changdong_idx = stations.index[stations["역명"] == "창동"]
if len(_changdong_idx):
    stations.loc[_changdong_idx, "노선"] = stations.loc[_changdong_idx, "노선"] + "1"

_new_rows = pd.DataFrame({
    "역명": _cand["역사명_clean"].values,
    "노선": "1",
    "위도": _cand["역위도"].values,
    "경도": _cand["역경도"].values,
})
_new_rows = _new_rows[_new_rows["역명"] != "창동"]   # 창동은 위에서 이미 처리
stations = pd.concat([stations, _new_rows], ignore_index=True)
print(f"    역 수: {len(stations) - len(_new_rows)} -> {len(stations)}개 "
      f"(신규 {len(_new_rows)}개 + 창동 노선 갱신)")
assert dist.shape[0] == len(stations), (
    f"dist_km.npy 행 수({dist.shape[0]})가 확장된 역 수({len(stations)})와 다릅니다 — "
    f"step1c_extend_line1_stations.py를 먼저 실행하거나, 이 스크립트의 신규역 추가 순서가 "
    f"바뀌지 않았는지 확인하세요(그 스크립트도 동일한 필터/순서로 만들어야 행 인덱스가 맞습니다).")

demand = pd.read_csv(os.path.join(BASE, "반출_행정동별_일평균수요.xls"), encoding="utf-8-sig")
print(f"    수요 원본 {len(demand)}개 동, 합계 {demand['일평균_전체시장'].sum():,.0f} 박스/일")

# ── 수요 결합 ──────────────────────────────────────────────
# demand의 "행정동코드"는 10자리 법정동코드, dongs의 "ADM_CD"는 8자리 SGIS
# 행정동코드로 서로 다른 코드 체계라 단순 자릿수 절삭으로는 매칭되지 않는다
# (실제로 시도해보면 426개 중 32개만 우연히 일치 -> 수요 대부분이 누락됨).
# 대신 동이름 + 자치구로 결합한다. 두 파일의 동이름 표기 방식이 달라
# ("전농제1동" vs "전농1동", "종로5·6가동" vs "종로5.6가동" 등) 정규화가 필요하고,
# "신사동"처럼 서로 다른 구(강남구/관악구)에 같은 동이름이 존재하는 경우가 있어
# 자치구까지 맞춰야 정확히 구분된다.
def norm(s):
    s = str(s).replace("·", ".")
    s = re.sub(r"제([\d.]+동)", r"\1", s)          # "전농제1동" -> "전농1동"
    s = re.sub(r"^홍(\d+동)$", r"홍제\1", s)        # SHP 표기 오류 보정: "홍1동" -> "홍제1동"
    return s

demand["N"] = demand["행정동"].map(norm)
dongs["N"]  = dongs["ADM_NM"].map(norm)
dongs["GU_CODE"] = dongs["ADM_CD"].astype(str).str[2:5]   # SGIS 코드의 자치구 구간(3자리)

# 이름이 유일한 동들로 GU_CODE -> 자치구 매핑을 먼저 확보한 뒤,
# 신사동처럼 이름이 겹치는 동은 이 매핑으로 자치구를 붙여 구분한다.
dup_names = set(dongs["N"].value_counts()[lambda s: s > 1].index)
uniq = dongs[~dongs["N"].isin(dup_names)].merge(demand[["N", "자치구"]], on="N", how="inner")
gu_map = uniq.groupby("GU_CODE")["자치구"].agg(lambda s: s.value_counts().index[0])
dongs["자치구"] = dongs["GU_CODE"].map(gu_map)

dongs = dongs.merge(demand[["자치구", "N", "일평균_전체시장"]], on=["자치구", "N"], how="left")

miss = dongs["일평균_전체시장"].isna().sum()
print(f"    조인 결과: {len(dongs)-miss}/{len(dongs)}개 매칭" + (f"  ← 미매칭 {miss}개 확인 필요" if miss else "  ✓"))
dongs["일평균_전체시장"] = dongs["일평균_전체시장"].fillna(0)

W = dongs["일평균_전체시장"].values                # 행정동별 전체 물동량
N_ST, N_D = len(stations), len(dongs)
print(f"    역 {N_ST}개 x 동 {N_D}개, 매칭된 수요 합계 {W.sum():,.0f} 박스/일")


# ══════════════════════════════════════════════════════════
# 2. 기점(차량기지) 및 철도 소요시간 — 노선별 전용 네트워크 + 방향(레이) 분리
#    (환승을 포함한 전역 Floyd-Warshall은 더 이상 쓰지 않는다 — 위 docstring
#    [철도비 전면 재설계] 문제2 참고)
# ══════════════════════════════════════════════════════════
def clean_name(s):
    """역명 정규화: 괄호 제거 + '역' 글자 제거. 역간거리/환승/심도/임대료
    4개 원천 데이터마다 역명 표기가 제각각이라("서울역" vs "서울" vs
    "서울(1)역") 이 규칙으로 통일해서 station.csv의 역명과 맞춘다."""
    return re.sub(r"\([^)]*\)", "", str(s)).replace("역", "").strip()

def mmss_to_min(x):
    try:
        m, s = str(x).split(":")
        return int(m) + int(s) / 60.0
    except Exception:
        return 0.0

SEG_CSV      = os.path.join(BASE, "서울교통공사 역간거리 및 소요시간_240810.csv")
DEPTH_CSV    = os.path.join(BASE, "서울교통공사_역사심도정보_20241104.csv")
RENT_CSV     = os.path.join(BASE, "서울교통공사_지하상가 임대정보_20251231.csv")

stations["역명_clean"] = stations["역명"].map(clean_name)

# ── 2-1. 노선별 전용(환승 미포함) 순차 네트워크 (호선, 역명) 노드 ────────
#   문제2/3 대응: 화물열차는 자기 노선 선로만 달릴 수 있어, 여기서는
#   노선 간 환승 엣지를 아예 만들지 않는다(예전 "환승 허용" 로직 제거).
seg = pd.read_csv(SEG_CSV, encoding="cp949")
seg["호선"] = seg["호선"].astype(str)
seg = seg[seg["호선"].isin(["1", "2", "3", "4"])].reset_index(drop=True)
seg["역명"] = seg["역명"].map(clean_name)
seg["분"] = seg["소요시간"].map(mmss_to_min)

# ── 1호선 코레일 구간 26개역의 역간 소요시간 — 서울교통공사 역간거리
#   CSV에는 당연히 이 구간이 없으므로, 국토교통부 철도 실시간 시각표
#   엑셀("202608281a045c6bb40560.xlsx")에서 실제 열차 통과시각을 읽어
#   인접역 간 시각차의 "열차별 중앙값"으로 역간 소요시간을 역산한다.
#   시트가 두 개 필요하다 — "경인_평일_상"은 구로~인천 방향(구일/개봉/
#   오류동/온수 포함)과 서울역~청량리~도봉산 공통 구간을, "경부장항_평일_상"은
#   구로~수원 방향(가산디지털단지/독산/금천구청 포함)을 담고 있다. 이상치는
#   0~20분 범위만, 표본 3개 이상인 구간만 채택(그 미만은 신뢰 못 해 버림).
def _load_pair_times(xlsx_path, sheet_name, abbrev_map):
    df = pd.read_excel(xlsx_path, sheet_name=sheet_name, header=None)
    seq = []
    for idx in range(3, df.shape[0]):
        val = df.iat[idx, 0]
        if isinstance(val, str) and val.strip():
            nm = val.strip()
            nm = abbrev_map.get(nm, nm)
            seq.append((nm, idx))
    pair_times = {}
    for i in range(len(seq) - 1):
        (na, ra), (nb, rb) = seq[i], seq[i + 1]
        diffs = []
        for c in range(1, df.shape[1]):
            va, vb = df.iat[ra, c], df.iat[rb, c]
            if isinstance(va, datetime.time) and isinstance(vb, datetime.time):
                ta = va.hour * 60 + va.minute + va.second / 60
                tb = vb.hour * 60 + vb.minute + vb.second / 60
                d = tb - ta
                if d < 0:
                    d += 24 * 60
                diffs.append(d)
        diffs = [d for d in diffs if 0 < d < 20]
        if len(diffs) >= 3:
            pair_times[(na, nb)] = float(np.median(diffs))
    return pair_times

_TT_XLSX = os.path.join(BASE, "202608281a045c6bb40560.xlsx")
_TT_ABBREV = {   # 시각표 파일의 축약 역명 -> 우리 모델 역명
    "지하서": "서울", "1종로": "종로3가", "종로5": "종로5가", "1동대": "동대문",
    "1지청": "청량리", "가산디": "가산디지털단지", "금천구": "금천구청",
}
_pt_gyeongin = _load_pair_times(_TT_XLSX, "경인_평일_상", _TT_ABBREV)
_pt_gyeongbu = _load_pair_times(_TT_XLSX, "경부장항_평일_상", _TT_ABBREV)

def _lookup_travel_min(u, v):
    for pt in (_pt_gyeongin, _pt_gyeongbu):
        if (u, v) in pt:
            return pt[(u, v)]
        if (v, u) in pt:
            return pt[(v, u)]
    return None

# 실제 물리적 역 순서(서울역 core -> 서쪽 구로 방향 -> 구로에서 두 갈래,
# 청량리 core -> 동쪽 도봉산 방향). BRANCH_PARENT_OVERRIDE와 짝지어 아래
# G_seq 구축 루프에서 정확한 위상으로 이어붙는다.
LINE1_EXT_CHAINS = [
    ["서울", "남영", "용산", "노량진", "대방", "신길", "영등포", "신도림", "구로"],
    ["구로", "가산디지털단지", "독산", "금천구청"],
    ["구로", "구일", "개봉", "오류동", "온수"],
    ["청량리", "회기", "외대앞", "신이문", "석계", "광운대", "월계",
     "녹천", "창동", "방학", "도봉", "도봉산"],
]
_line1_new_seg_rows = []
for _chain in LINE1_EXT_CHAINS:
    for _i in range(len(_chain) - 1):
        _u, _v = _chain[_i], _chain[_i + 1]
        _t = _lookup_travel_min(_u, _v)
        if _t is None:
            print(f"    ! 1호선 신규 구간 소요시간 없음: {_u}~{_v} — 확인 필요")
        else:
            _line1_new_seg_rows.append({"호선": "1", "역명": _v, "분": _t})
seg = pd.concat([seg, pd.DataFrame(_line1_new_seg_rows)], ignore_index=True)
print(f"    1호선 신규 구간 {len(_line1_new_seg_rows)}개 추가(시각표 기반 소요시간)")

# ★ 2호선 지선 분기점 보정: 원본 CSV는 역명이 등장한 순서대로만 나열돼 있어
#   그냥 순차연결하면 성수지선이 (순환선이 닫히는 지점인) 두 번째 "시청"에서,
#   신정지선이 "신설동"에서 갈라지는 것처럼 잘못 이어진다.
#   실제로는 성수지선은 성수역, 신정지선은 신도림역에서 분기한다.
#   1호선도 같은 이유로 3곳 보정이 필요하다 — seg에 신규 구간을 그냥
#   순서대로 이어붙였더니 "구로"에서 두 번(가산디지털단지 방향/구일 방향),
#   "청량리"에서 한 번(회기 방향) 분기가 생기는데, 자연스러운 "이전 행"
#   연결로는 그중 하나(가산디지털단지)만 맞고 나머지 둘은 어긋난다.
BRANCH_PARENT_OVERRIDE = {
    ("2", "용답"):  ("2", "성수"),    # 성수지선 분기점
    ("2", "도림천"): ("2", "신도림"),  # 신정지선 분기점
    ("1", "남영"):  ("1", "서울"),    # 1호선 서쪽 분기(서울역 기준)
    ("1", "구일"):  ("1", "구로"),    # 1호선 경인선 분기(구일 기준)
    ("1", "회기"):  ("1", "청량리"),  # 1호선 동쪽 분기(청량리 기준)
}

G_seq = nx.Graph()
for ln in ["1", "2", "3", "4"]:
    sub = seg[seg["호선"] == ln].reset_index(drop=True)
    prev_node = None
    for _, row in sub.iterrows():
        node = (ln, row["역명"])
        G_seq.add_node(node)
        parent = BRANCH_PARENT_OVERRIDE.get(node, prev_node)
        if parent is not None and parent != node:
            w = row["분"]
            if G_seq.has_edge(parent, node):
                w = min(w, G_seq[parent][node]["weight"])
            G_seq.add_edge(parent, node, weight=w)
        prev_node = node

print(f"[2] 노선별 전용 네트워크: 노드 {G_seq.number_of_nodes()}개, 엣지 {G_seq.number_of_edges()}개 "
      f"(환승 엣지 없음 — 노선별 독립 그래프)")

# ── 2-2. 기점(차량기지)별 방향(레이) 분리 + 노선 전용 최단시간 ───────────
#   기점 노드를 그래프에서 제거했을 때 갈라지는 연결요소를 그 기점의
#   "방향(레이)"으로 정의한다(자세한 설명은 상단 docstring [철도비 전면
#   재설계] 참고). 레이 태그는 pulp 변수명에 그대로 쓰이므로 특수문자를
#   제거해 안전한 문자열로 만든다.
def safe_key(*parts):
    s = "_".join(str(p) for p in parts)
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", s)

line_nodes = {ln: [n for n in G_seq.nodes if n[0] == ln] for ln in "1234"}

depot_data = {}   # (ln, depot_label) -> {"dist": {node: 분}, "dir": {node: dir_key}}
for depot_label, (nm, ln) in DEPOTS.items():
    onode = (ln, clean_name(nm))
    if onode not in line_nodes[ln]:
        print(f"    ! 기점 미발견: {depot_label}({nm}, {ln}호선) — 역간거리 데이터에 없음")
        continue
    H = G_seq.subgraph(line_nodes[ln])
    dist_map = nx.single_source_dijkstra_path_length(H, onode, weight="weight")

    H_minus_O = H.copy()
    H_minus_O.remove_node(onode)
    components = list(nx.connected_components(H_minus_O))

    dir_of = {onode: safe_key(ln, depot_label, "기점")}
    for nb in H.neighbors(onode):
        comp = next(c for c in components if nb in c)
        dkey = safe_key(ln, depot_label, nb[1])   # 방향 태그 = 그쪽 첫 이웃역 이름
        for n in comp:
            dir_of[n] = dkey

    depot_data[(ln, depot_label)] = {"dist": dist_map, "dir": dir_of}

n_dirs_by_depot = {k: len(set(v["dir"].values())) for k, v in depot_data.items()}
print(f"    기점 {len(depot_data)}개, 기점별 방향 수: {n_dirs_by_depot}")

# ── 2-3. 물리역별 소속 노선(stations.csv "노선" 컬럼) 안에서만 최단 배정 ──
#   여러 노선에 걸친 환승역은 "소속된 노선들 각각의 자기 선로망 최단시간"
#   중 가장 짧은 쪽으로 배정한다(문제2 수정 — 더 이상 다른 노선 기점에서
#   환승으로 빨리 닿는다고 그 노선 소속으로 잘못 분류하지 않는다).
rail_t    = np.full(N_ST, np.inf)
rail_from = [None] * N_ST     # 어느 기점에서 왔는지
hub_line  = [None] * N_ST     # 그 역이 실제로 속한 노선 (stations.csv 기준)
hub_dir   = [None] * N_ST     # 방향(레이) 키 — 목적함수의 T_travel[dir] 그룹핑에 사용

for j in range(N_ST):
    own_lines = [c for c in str(stations.loc[j, "노선"]) if c in "1234"]
    node_name = stations.loc[j, "역명_clean"]
    for ln in own_lines:
        node = (ln, node_name)
        for (dln, dlabel), dd in depot_data.items():
            if dln != ln:
                continue
            if node in dd["dist"]:
                t = dd["dist"][node]
                if t < rail_t[j]:
                    rail_t[j], rail_from[j], hub_line[j] = t, dlabel, ln
                    hub_dir[j] = dd["dir"][node]

OK = np.isfinite(rail_t)                          # 기점 도달 가능 역 (자기 노선망 안에서)

# ── 서울 밖 역은 허브 후보에서 제외 ────────────────────────────────
#   연구 범위가 서울 426개 행정동이라 서울 밖에 허브를 두면 라스트마일이
#   비효율적이고 범위와도 안 맞는다. 행정동.shp 서울 폴리곤에 대해 전 역을
#   point-in-polygon으로 판정한 결과(step2_seoul_boundary_audit.py) 서울
#   밖은 지축(3호선, 경기 고양시 — 경계 336m 밖) 하나뿐이었다. 남태령
#   (서초구 안쪽 436m)·구파발·온수·도봉산·금천구청·독산 등 경계 근처 역은
#   전부 서울 안이라 후보로 유지한다.
#   ★ 지축은 차량기지 접속역(기점) 역할은 그대로 유지 — 화물은 지축기지에서
#   출발하되 하역(허브)은 서울 안에서만 이뤄진다.
SEOUL_EXCLUDED_STATIONS = {"지축"}
_n_excluded = 0
for j in range(N_ST):
    if OK[j] and stations.loc[j, "역명_clean"] in SEOUL_EXCLUDED_STATIONS:
        OK[j] = False
        _n_excluded += 1
if _n_excluded:
    print(f"    서울 밖 역 {_n_excluded}개 허브 후보 제외: {', '.join(sorted(SEOUL_EXCLUDED_STATIONS))} "
          f"(기점 역할은 유지)")

DIRECTIONS = sorted(set(hub_dir[j] for j in range(N_ST) if OK[j]))
N_DIRECTIONS = len(DIRECTIONS)
print(f"    허브 후보 {OK.sum()}/{N_ST}개, 방향(레이) {N_DIRECTIONS}개")
print("    노선별 후보 수:", pd.Series([hub_line[j] for j in range(N_ST) if OK[j]]).value_counts().to_dict())

# ── 2-3b. 방향별 왕복 소요시간 -> 심야 가용시간 안에서 물리적으로 가능한
#   최대 trips (교수님 피드백: TRIPS=20을 방향 17개에 그대로 적용하면
#   본선순환처럼 긴 방향은 물리적으로 불가능 — step2_trips_feasibility_check.py
#   참고). "방향 전체 물리적 길이"(그 방향에 속한 모든 역 중 최원) 기준으로
#   계산한다 — 열차는 개설된 허브가 아니라 노선 끝(또는 회차 지점)까지
#   가야 하므로.
DIR_ROUND_TRIP = {}    # dkey -> 왕복 주행시간(분)
for (dln, dlabel), dd in depot_data.items():
    by_dir = {}
    for node, dkey in dd["dir"].items():
        by_dir.setdefault(dkey, []).append(dd["dist"][node])
    for dkey, dists in by_dir.items():
        DIR_ROUND_TRIP[dkey] = 2 * max(dists)

MAX_TRIPS = {dkey: int(AVAILABLE_MIN // (DIR_ROUND_TRIP[dkey] + TURNAROUND_MIN))
             for dkey in DIRECTIONS}
print(f"    방향별 왕복시간(분)/심야 최대 trips: " +
      ", ".join(f"{k}={DIR_ROUND_TRIP[k]:.0f}분(최대{MAX_TRIPS[k]}회)"
                for k in sorted(DIRECTIONS, key=lambda k: -DIR_ROUND_TRIP[k])[:5]) +
      " 등")

# ── 2-4. 심도(엘리베이터) ──────────────────────────────────────────
#   [버그1] "정거장깊이" = 지반고-레일면고라 고가역은 음수로 나오는데,
#   예전 코드가 그대로 써서 그 역들의 엘리베이터 비용이 음수(=수입)가
#   되고 있었다. 지상/고가역은 아래로, 지하역은 위로 방향만 다를 뿐
#   수직 이동거리·소요시간은 동일하게 발생하므로 abs()로 고친다.
#   발견 당시 대표 시나리오였던 S25의 허브 중 노원(4호선, 원래 -13.69m)·
#   창동(4호선, 원래 -10.57m)이 이 버그의 영향을 받고 있었다 — 부당하게
#   유리했을 수 있다(현재 대표 시나리오는 network_common.REP_SCENARIO 참조).
#   [버그2] 위 median 계산이 호선 필터 없이(1~9호선 전부) 이뤄지고
#   있었다 — 노원처럼 4호선(-13.69)·7호선(22.46) 둘 다 잡히는 환승역은
#   median([-13.69, 22.46])=4.39처럼 이 프로젝트와 무관한 값으로
#   오염된다. 1~4호선만 남기고 계산한다.
#   [역명 매칭] 심도 파일의 "구로디지털"(모델은 "구로디지털단지"),
#   "을지3가"/"을지4가"(모델은 "을지로3가"/"을지로4가"), "미아삼거리"
#   (모델은 "미아사거리")처럼 표기가 달라 결측 처리되던 4곳을 별칭
#   테이블로 보완한다.
depth_df = pd.read_csv(DEPTH_CSV, encoding="cp949")
depth_df["호선"] = depth_df["호선"].astype(str)
depth_df = depth_df[depth_df["호선"].isin(["1", "2", "3", "4"])]
depth_df["역명_clean"] = depth_df["역명"].map(clean_name)
DEPTH_ALIAS = {"구로디지털": "구로디지털단지", "을지3가": "을지로3가",
              "을지4가": "을지로4가", "미아삼거리": "미아사거리"}
depth_df["역명_clean"] = depth_df["역명_clean"].replace(DEPTH_ALIAS)
depth_map = depth_df.groupby("역명_clean")["정거장깊이"].median().abs()

station_depth = stations["역명_clean"].map(depth_map).values.astype(float)
# 1호선 코레일 구간 26개역은 전 구간 지상 승강장이다(종로선 구간, 즉
# 서울교통공사가 관할하는 서울역~청량리만 지하 — 그 서쪽/동쪽은 개통 당시
# 부터 전 구간 지상/고가. "수도권1호선_역구조.xlsx"로 확인). 녹천·영등포는
# 심도 파일에 "지상"/"지하" 행이 둘 다 있으나 이는 역 건물 층수 표기이지
# 승강장 깊이가 아니고, 석계의 "지하 1층" 기록도 6호선 쪽이라 1호선 승강장
# 깊이와는 무관하다고 판단해 0으로 둔다.
for _i, _nm in enumerate(stations["역명_clean"]):
    if _nm in LINE1_KORAIL_TARGETS and np.isnan(station_depth[_i]):
        station_depth[_i] = 0.0
n_depth_matched = int((~np.isnan(station_depth)).sum())
station_depth = np.where(np.isnan(station_depth), DEFAULT_DEPTH, station_depth)
print(f"    심도 매칭 {n_depth_matched}/{N_ST}개 (나머지 기본값 {DEFAULT_DEPTH}m)")

# ── 2-5. 임대료(허브 고정비) ────────────────────────────────────────
#   [문제] 결측역이 DEFAULT_FIXED(50만원/일)로 채워지는데, 이는 실제
#   관측 분포 중앙값(약 10만원/일)의 5배라 결측역이 부당하게 불리했다.
#   [재설계] ㎡당 단가(월임대료/면적) 기반으로 바꾼다 — 역별 단가의
#   중앙값을 구하고, 결측역은 "선로상 인접역 단가 평균"으로 보간하되
#   그 평균이 노선 전체 중앙값보다 낮으면(더 싸게 나오면) 중앙값을
#   채택한다(보수적 — 임대료를 과소평가해 지하철을 유리하게 만들지
#   않기 위함). 인접역 탐색은 G_seq(순차 노선망, 2호선 지선의
#   BRANCH_PARENT_OVERRIDE 포함)를 그대로 재사용하므로 성수지선/신정지선
#   구조가 자동 반영되고, 신설동처럼 여러 노선에 걸친 역은 양쪽 노선의
#   이웃을 모두 살펴 더 큰 쪽을 쓴다.
#   [계약 없는 상가 제외] 월임대료가 NaN인 행(예: 신정네거리 — 상가는
#   있지만 미계약 공실)을 먼저 제거한다 — 안 그러면 그 역이 "행은
#   있는데 값이 전부 NaN"이라 median이 NaN이 되어 "직접관측값 있음"으로
#   잘못 분류된다.
rent_df = pd.read_csv(RENT_CSV, encoding="cp949")
rent_df["역명_clean"] = rent_df["역명"].map(clean_name)
rent_df["단가"] = rent_df["월임대료"] / rent_df["면적(제곱미터)"]
station_unit_price = rent_df.dropna(subset=["단가"]).groupby("역명_clean")["단가"].median()
station_rent_direct = rent_df.dropna(subset=["월임대료"]).groupby("역명_clean")["월임대료"].median()
network_median_unit_price = station_unit_price.median()
network_median_rent_daily = (station_rent_direct / 30.0).median()
print(f"    ㎡당 단가 네트워크 중앙값: {network_median_unit_price:,.0f}원/㎡")
print(f"    절대 임대료 네트워크 중앙값: {network_median_rent_daily:,.0f}원/일 "
      f"({network_median_rent_daily*30:,.0f}원/월)")

#   [1호선 코레일역 임대료] 코레일유통 소관이라 서울교통공사 임대정보에는
#   없다. 코레일유통 "역별 상업시설 이용고객수·업종별 매장수·매장당
#   평균매출" 공개자료의 "매장당 평균매출"에 수수료율을 곱해 월임대료
#   상당액으로 환산한다. 수수료율 15.5%는 코레일유통 회기역 실제 모집공고
#   (편의점 33.83㎡, 예상수수료 월 4,339,000원)와 같은 자료의 회기역
#   매장당 평균매출(28,044,024원)을 역산해 얻었다(코레일유통 공시
#   수수료율 17~50% 범위의 최저 수준과 부합). 이렇게 환산한 절대값은
#   서울교통공사 월임대료 중앙값과 스케일이 거의 같다(검증: 코레일 17개역
#   환산 중앙값이 서울교통공사 네트워크 중앙값과 오차 0.2% 수준 — 같은
#   모델에 그대로 합쳐도 된다는 근거).
#   단, 가산디지털단지·도봉산·석계·신길·신도림(7/6/6/5/2호선으로 이미
#   서울교통공사 임대정보가 있음)·온수(7호선)는 그 실측 계약 데이터가
#   더 직접적인 근거이므로 코레일 매출 방식 대신 그쪽을 그대로 쓴다.
RETAIL_XLS = os.path.join(BASE, "2026년+7월+역별+상업시설+이용고객+수(객수),업종별+매장+수,+매장당+평균매출.xls")
FEE_RATE = 0.155
_retail_df = pd.read_excel(RETAIL_XLS, header=None)
_retail_data = _retail_df.iloc[4:, [0, 10]].copy()
_retail_data.columns = ["역명", "매장당평균매출"]
_retail_data["역명"] = _retail_data["역명"].astype(str).str.strip()
_retail_data = _retail_data.dropna(subset=["매장당평균매출"])
_retail_map = dict(zip(_retail_data["역명"], _retail_data["매장당평균매출"]))

station_rent_korail_daily = {
    nm: sales * FEE_RATE / 30.0
    for nm, sales in _retail_map.items()
    if nm in LINE1_KORAIL_TARGETS and nm not in station_rent_direct.index
}
print(f"    코레일 매출 기반 임대료 적용역({len(station_rent_korail_daily)}개): "
      f"{sorted(station_rent_korail_daily.keys())}")

rent_daily_direct = {nm: v / 30.0 for nm, v in station_rent_direct.items()}
rent_daily_direct.update(station_rent_korail_daily)

def _effective_unit_price(name):
    """실측 단가 있으면 그대로. 코레일 절대값만 있는 역은 면적 데이터가
    없어 단가를 직접 못 구하므로, 그 역의 절대 일임대료가 네트워크
    중앙값 대비 몇 배인지를 단가의 배율로도 같다고 가정해 프록시로 쓴다
    (면적 정보 부재로 인한 근사 — 한계로 남겨둔다)."""
    if name in station_unit_price.index:
        return station_unit_price[name]
    if name in rent_daily_direct:
        return rent_daily_direct[name] / network_median_rent_daily * network_median_unit_price
    return None

def _neighbor_unit_prices(name):
    vals = []
    for node in G_seq.nodes:
        if node[1] == name:
            for nb in G_seq.neighbors(node):
                v = _effective_unit_price(nb[1])
                if v is not None:
                    vals.append(v)
    return vals

_all_names = sorted(set(stations["역명_clean"]))
_gap_names = [nm for nm in _all_names if nm not in rent_daily_direct]
_interp_unit_price = {}
for nm in _gap_names:
    nbs = _neighbor_unit_prices(nm)
    if nbs:
        _interp_unit_price[nm] = max(float(np.mean(nbs)), network_median_unit_price)
    else:
        _interp_unit_price[nm] = network_median_unit_price

rent_daily = np.zeros(N_ST)
_rent_source = [""] * N_ST
for _i, _nm in enumerate(stations["역명_clean"]):
    if _nm in rent_daily_direct:
        rent_daily[_i] = rent_daily_direct[_nm]
        _rent_source[_i] = "직접"
    else:
        _w = _interp_unit_price[_nm] / network_median_unit_price
        rent_daily[_i] = network_median_rent_daily * _w
        _rent_source[_i] = "보간"
print(f"    임대료: 직접관측 {_rent_source.count('직접')}개 / 보간 {_rent_source.count('보간')}개 "
      f"(중앙값 {np.median(rent_daily):,.0f}원/일)")



# ══════════════════════════════════════════════════════════
# 3. 최적화 함수
#    exact=True로 부르면 허브 개수를 정확히 n_max개로 고정 (엘보우 분석용).
#    기본값(exact=False)은 상한(<=)만 건다.
# ══════════════════════════════════════════════════════════
def solve(w, cars, trips, n_max, exact=False, alpha_rail=None, unload_rate=None, available_min=None):
    """
    w           : 행정동별 처리 물량 (박스/일)
    cars        : 화물 전용 칸 수
    trips       : "희망" 야간 운행 편성 수 (노선 "한 방향"당) — 방향마다 물리적으로
                  가능한 상한(MAX_TRIPS)을 넘지 못하게 잘린다 (아래 eff_trips)
    n_max       : 허브 개수 상한 (exact=True면 정확히 이 개수)
    alpha_rail, unload_rate, available_min : 기본값(ALPHA_RAIL, UNLOAD_RATE,
                  AVAILABLE_MIN) 대신 민감도 분석에서 다른 값을 넣어보고 싶을 때 지정
                  (step2_alpha_rail_sensitivity.py)
    """
    # ★ MILP 본체는 network_common.solve_hub_location()으로 옮겼다.
    #   원래 이 목적함수·제약이 step2.py / step2_elbow_s39.py /
    #   step2_max_feasible_share_v2.py 세 곳에 복붙돼 있어서, 비용 모델을
    #   고칠 때마다 세 곳을 똑같이 고쳐야 했다(지축 제외 때 실제로 그랬다).
    #   여기서는 이 파일의 Section 0 상수와 Section 1~2에서 만든 배열을
    #   그대로 넘겨주기만 한다 — 즉 데이터·파라미터의 정본은 여전히 이 파일이고,
    #   MILP 수식만 공유한다.
    return nc.solve_hub_location(
        w, cars, trips, n_max,
        dist=dist, OK=OK, hub_dir=hub_dir, rail_t=rail_t,
        DIRECTIONS=DIRECTIONS, DIR_ROUND_TRIP=DIR_ROUND_TRIP,
        station_depth=station_depth, rent_daily=rent_daily,
        exact=exact, alpha_rail=alpha_rail, unload_rate=unload_rate,
        available_min=available_min, turnaround_min=TURNAROUND_MIN,
        cost=dict(BOX_PER_CAR=BOX_PER_CAR, COST_PER_KM=COST_PER_KM,
                  TRUCK_CAP=TRUCK_CAP, ALPHA_LABOR=ALPHA_LABOR,
                  ALPHA_RAIL=ALPHA_RAIL, UNLOAD_RATE=UNLOAD_RATE,
                  ELEV_SPEED_MPM=ELEV_SPEED_MPM, ELEV_CAPACITY=ELEV_CAPACITY),
        time_limit=60, gap_rel=0.02)


# ══════════════════════════════════════════════════════════
# 4. 시나리오 실행
# ══════════════════════════════════════════════════════════
rows, detail, assign_rows = [], {}, []
sid = 0
print(f"\n[3] 시나리오 {len(SHARES)*len(TRIPS)*len(CARS)}개 실행\n" + "="*95)

for cars in CARS:
    for trips in TRIPS:
        # 방향별로 심야 가용시간 안에서 실제 가능한 trips가 다르므로(MAX_TRIPS),
        # 전체 수송능력은 방향별 상한을 적용해 합산한다.
        eff_trips_preview = {dkey: min(trips, MAX_TRIPS[dkey]) for dkey in DIRECTIONS}
        cap_tot = sum(BOX_PER_CAR * cars * et for et in eff_trips_preview.values())
        for share in SHARES:
            sid += 1
            w = W * share
            total = w.sum()
            tag = f"S{sid:02d} {cars}칸x{trips}회 {share:.0%}"

            if total > cap_tot:                        # 물리적으로 불가능
                print(f"{tag} | 불가능 (필요 {total:,.0f} > 능력 {cap_tot:,.0f})")
                rows.append(dict(ID=f"S{sid:02d}", 칸=cars, 운행=trips, 분담률=share,
                                 총능력=cap_tot, 필요물량=total,
                                 실행가능=False, n=None, 총비용=None, 단위비용=None))
                continue

            r = solve(w, cars, trips, N_MAX)
            if r is None:
                print(f"{tag} | 해 없음")
                continue

            unit = r["Z"] / total
            detail[f"S{sid:02d}"] = stations.loc[r["hubs"], "역명"].tolist()
            rows.append(dict(ID=f"S{sid:02d}", 칸=cars, 운행=trips, 분담률=share,
                             총능력=cap_tot, 필요물량=total,
                             실행가능=True, n=r["n"],
                             총비용=r["Z"], 단위비용=unit,
                             라스트마일비중=r["라스트마일"]/r["Z"],
                             철도비중=r["철도"]/r["Z"],
                             철도운행비중=r["철도_운행"]/r["Z"],
                             철도하역비중=r["철도_하역"]/r["Z"],
                             심도비중=r["심도"]/r["Z"],
                             고정비중=r["고정비"]/r["Z"]))
            print(f"{tag} | n*={r['n']:2d} | {r['Z']/1e6:7.1f}백만원/일 | "
                  f"{unit:6.0f}원/박스 | 라스트마일 {r['라스트마일']/r['Z']:.0%} | "
                  f"철도 {r['철도']/r['Z']:.0%} | 심도 {r['심도']/r['Z']:.0%}")

            # 행정동별 확정 배정 — STEP 3(VRP 라스트마일 재계산)에서 재사용
            for d in range(N_D):
                j = r["assign"][d]
                assign_rows.append(dict(
                    ID=f"S{sid:02d}",
                    행정동=dongs.loc[d, "ADM_NM"],
                    행정동_idx=d,
                    배정허브=stations.loc[j, "역명"],
                    허브_idx=j,
                    수요=w[d],
                ))

# ★ 격자 밖 시나리오(REP=대표 시나리오, SMAX=최대 분담률)는 다른 스크립트가
#   같은 파일에 추가해 둔 것이라, 여기서 통째로 덮어쓰면 지워진다.
#   실제로 step2.py를 재실행했다가 SMAX가 사라져 배출량 분석이 깨진 적이 있다.
#   이 스윕이 만들지 않는 ID는 보존한 채 스윕 결과만 교체한다.
PRESERVE_IDS = {nc.REP_SCENARIO["ID"], nc.MAX_SCENARIO_ID}


def _merge_save(new_df, path):
    if os.path.exists(path):
        old = pd.read_csv(path)
        # ★ "격자 밖" 판정은 PRESERVE_IDS만으로 하면 안 된다. 대표 시나리오가
        #   격자 안 조합(예: S39)이면 이번에 새로 계산한 행과 예전 행이 둘 다
        #   남아 ID가 중복되고, 낡은 행이 최적으로 뽑히는 사고가 난다.
        #   이번 스윕이 실제로 만든 ID는 제외하고 보존한다.
        produced = set(new_df["ID"])
        keep = old[old["ID"].isin(PRESERVE_IDS - produced)]
        if len(keep):
            new_df = pd.concat([new_df, keep], ignore_index=True)
            print(f"    (격자 밖 시나리오 {sorted(set(keep['ID']))} 보존)")
    new_df.to_csv(path, index=False, encoding="utf-8-sig")


df = pd.DataFrame(rows)
_merge_save(df, f"{OUT}/scenario_results.csv")
_merge_save(pd.DataFrame([(k, ", ".join(v)) for k, v in detail.items()],
                         columns=["ID", "선정역사"]),
            f"{OUT}/scenario_hubs.csv")
_merge_save(pd.DataFrame(assign_rows), f"{OUT}/scenario_assignments.csv")


# ══════════════════════════════════════════════════════════
# 5. 요약
# ══════════════════════════════════════════════════════════
ok = df[df["실행가능"]]
print("\n" + "="*95)
print(f"실행가능 {len(ok)}/{len(df)}개")

if len(ok):
    best = ok.loc[ok["단위비용"].idxmin()]
    print(f"\n★ 단위비용 최소: {best['ID']} "
          f"({best['칸']}칸 x {best['운행']}회, 분담률 {best['분담률']:.0%})")
    print(f"   {best['단위비용']:.0f}원/박스, 허브 {best['n']}개")
    print(f"   {', '.join(detail[best['ID']])}")

    print("\n[단위비용 표 — 원/박스]")
    print(ok.pivot_table(index=["칸", "운행"], columns="분담률",
                         values="단위비용").round(0).to_string())
    print("\n[최적 허브 수]")
    print(ok.pivot_table(index=["칸", "운행"], columns="분담률",
                         values="n").to_string())

    # ── 그래프 ──────────────────────────────────────────────────────
    # 예전엔 x축을 "총 수송능력"으로 두고 분담률별로 선을 이었는데,
    # 2칸x15회와 3칸x10회처럼 비용구조가 전혀 다른 조합이 총 수송능력만
    # 비슷해 x축상 인접해버려 선으로 이으면 의미 없는 지그재그가 됐다
    # (애초에 이산적인 (칸,운행,분담률) 조합 집합이라 "연속 곡선"으로
    # 그리는 것 자체가 잘못된 인코딩). 대신 두 그림으로 대체한다:
    #   1) 히트맵 — 분담률별 (칸 x 운행) 그리드에 단위비용을 색으로.
    #      "어떤 조합이 유리한가"를 한눈에 보여준다.
    #   2) 정렬 막대 — 실행가능 시나리오를 단위비용 오름차순으로.
    #      "왜 대표 시나리오가 뽑혔나"를 가장 직관적으로 보여준다.
    REP_ID_VIZ = best["ID"]
    SHARE_COLORS = {s: c for s, c in zip(SHARES, ["#0072B2", "#D55E00", "#009E73", "#E69F00"])}

    vmin, vmax = ok["단위비용"].min(), ok["단위비용"].max()
    cmap = plt.cm.OrRd
    fig, axes = plt.subplots(1, len(SHARES), figsize=(4.2 * len(SHARES), 4.6))
    if len(SHARES) == 1:
        axes = [axes]
    for ax, share in zip(axes, SHARES):
        grid = np.full((len(CARS), len(TRIPS)), np.nan)
        for i, cars in enumerate(CARS):
            for j, trips in enumerate(TRIPS):
                row = df[(df["칸"] == cars) & (df["운행"] == trips) & (df["분담률"] == share) & (df["실행가능"])]
                if len(row):
                    grid[i, j] = row["단위비용"].values[0]
        im = ax.imshow(grid, cmap=cmap, vmin=vmin, vmax=vmax, aspect="auto")
        for i in range(len(CARS)):
            for j in range(len(TRIPS)):
                if np.isnan(grid[i, j]):
                    ax.add_patch(Rectangle((j - 0.5, i - 0.5), 1, 1, facecolor="#DADADA",
                                           edgecolor="white", hatch="//", linewidth=0.5, zorder=2))
                else:
                    ax.text(j, i, f"{grid[i, j]:.0f}", ha="center", va="center", fontsize=11,
                           fontweight="bold", color="white" if grid[i, j] > (vmin + vmax) / 2 else "#333333")
        if best["분담률"] == share:
            ri, rj = CARS.index(int(best["칸"])), TRIPS.index(int(best["운행"]))
            ax.add_patch(Rectangle((rj - 0.5, ri - 0.5), 1, 1, facecolor="none",
                                   edgecolor="#DC3220", linewidth=3.5, zorder=3))
            ax.text(rj, ri + 0.38, REP_ID_VIZ, ha="center", va="top", fontsize=9,
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
                       label=f"대표 시나리오({REP_ID_VIZ})")
    fig.legend(handles=[hatch_legend, rep_legend], loc="lower center", ncol=2,
              bbox_to_anchor=(0.5, -0.06), fontsize=10, frameon=False)
    fig.suptitle("분담률별 (칸수 x 운행횟수) 단위비용 — 어떤 조합이 유리한가",
                fontsize=14, fontweight="bold", y=1.03)
    nc.savefig_retry(plt, f"{OUT}/scenario_heatmap.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    ok_sorted = ok.sort_values("단위비용", ascending=True).reset_index(drop=True)
    labels = [f"{int(r.칸)}칸x{int(r.운행)}회, {r.분담률:.0%}" for r in ok_sorted.itertuples()]
    colors = [SHARE_COLORS[r.분담률] for r in ok_sorted.itertuples()]
    is_rep = ok_sorted["ID"] == REP_ID_VIZ
    fig, ax = plt.subplots(figsize=(10, 0.42 * len(ok_sorted) + 1.5))
    y = np.arange(len(ok_sorted))
    bars = ax.barh(y, ok_sorted["단위비용"], color=colors, edgecolor="none", height=0.65, zorder=2)
    for rep, bar in zip(is_rep, bars):
        if rep:
            bar.set_edgecolor("#000000"); bar.set_linewidth(2.5)
            ax.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2,
                   f"★ 대표 시나리오({REP_ID_VIZ}) — {bar.get_width():.1f}원/박스",
                   va="center", fontsize=10, fontweight="bold", color="#000000")
    ax.set_yticks(y); ax.set_yticklabels(labels, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("단위비용 (원/박스)")
    ax.set_title(f"실행가능 시나리오 — 단위비용 오름차순 (왜 {REP_ID_VIZ}가 뽑혔나)",
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
else:
    print("실행가능한 시나리오가 없어 단위비용 히트맵/정렬막대 그래프는 생략합니다.")

# 실행가능 여부와 무관하게: 시나리오별 "필요물량 vs 총능력" 격차는 항상 기록해둔다
fig, ax = plt.subplots(figsize=(11, 5.5))
g = df.sort_values(["칸", "운행", "분담률"]).reset_index(drop=True)
x = np.arange(len(g))
width = 0.35
ax.bar(x - width/2, g["필요물량"], width, label="필요물량", color="crimson")
ax.bar(x + width/2, g["총능력"], width, label="총능력(공급가능)", color="steelblue")
ax.set_xticks(x)
ax.set_xticklabels([f"{r.칸}칸x{r.운행}회\n{r.분담률:.0%}" for r in g.itertuples()], fontsize=6, rotation=90)
ax.set_ylabel("박스/일")
ax.set_title("시나리오별 필요물량 vs 총 수송능력 (전체)")
ax.legend()
plt.tight_layout()
nc.savefig_retry(plt, f"{OUT}/capacity_gap.png", dpi=150, bbox_inches="tight")
plt.close(fig)

print(f"\n저장: {OUT}\\scenario_results.csv, scenario_hubs.csv, scenario_heatmap.png, scenario_ranked.png, capacity_gap.png")


# ══════════════════════════════════════════════════════════
# 6. 허브 개수 엘보우 분석
#    대표 시나리오 하나를 골라 허브 개수 n을 1개부터 순서대로 정확히 고정해서
#    반복적으로 풀고, 총비용/단위비용이 n에 따라 어떻게 줄어드는지 본다.
#    감소폭이 급격히 완만해지는 지점(엘보우)이 적정 허브 개수의 근거가 된다.
#    대표 시나리오: 실행가능한 조합 중 단위비용이 가장 낮은 것 (섹션 5의 best)
# ══════════════════════════════════════════════════════════
elbow_rows, elbow_hubs = [], {}
if len(ok) == 0:
    print("\n[4] 엘보우 분석 — 실행가능한 시나리오가 없어 대표 시나리오를 고를 수 없습니다. 생략합니다.")
    REP_SHARE = REP_CARS = REP_TRIPS = None
else:
    REP_SHARE, REP_CARS, REP_TRIPS = float(best["분담률"]), int(best["칸"]), int(best["운행"])
    rep_eff_trips = {dkey: min(REP_TRIPS, MAX_TRIPS[dkey]) for dkey in DIRECTIONS}
    rep_cap_tot = sum(BOX_PER_CAR * REP_CARS * et for et in rep_eff_trips.values())
    rep_w = W * REP_SHARE
    rep_total = rep_w.sum()
    n_candidates = int(OK.sum())
    N_RANGE = range(1, min(16, n_candidates + 1))

    print(f"\n[4] 엘보우 분석 — 대표 시나리오 {best['ID']}({REP_CARS}칸x{REP_TRIPS}회, "
          f"분담률 {REP_SHARE:.0%}, 단위비용 최소) 총능력({N_DIRECTIONS}개 방향, 심야가용시간 상한 반영) "
          f"{rep_cap_tot:,}박스/일, 필요물량 {rep_total:,.0f}박스/일, 허브 후보 {n_candidates}개")

    for n in N_RANGE:
        r = solve(rep_w, REP_CARS, REP_TRIPS, n, exact=True)
        if r is None:
            print(f"  n={n:2d} | 해 없음(불가능)")
            continue
        unit = r["Z"] / rep_total
        elbow_hubs[n] = stations.loc[r["hubs"], "역명"].tolist()
        elbow_rows.append(dict(n=n, 총비용=r["Z"], 단위비용=unit))
        print(f"  n={n:2d} | {r['Z']/1e6:7.2f}백만원/일 | {unit:6.0f}원/박스")

elbow_df = pd.DataFrame(elbow_rows)
elbow_df.to_csv(f"{OUT}/elbow_results.csv", index=False, encoding="utf-8-sig")

if len(elbow_df) == 0:
    print("엘보우 데이터가 없어 그래프를 생략합니다.")
else:
    fig, ax = plt.subplots(1, 2, figsize=(13, 4.5))

    ax[0].plot(elbow_df["n"], elbow_df["총비용"]/1e6, "o-", color="tab:blue")
    ax[0].set(xlabel="허브 개수 n", ylabel="총비용 (백만원/일)", title="허브 개수별 총비용 (엘보우)")
    ax[0].grid(alpha=.3)

    ax[1].plot(elbow_df["n"], elbow_df["단위비용"], "o-", color="tab:orange")
    ax[1].set(xlabel="허브 개수 n", ylabel="단위비용 (원/박스)", title="허브 개수별 단위비용")
    ax[1].grid(alpha=.3)

    plt.tight_layout()
    nc.savefig_retry(plt, f"{OUT}/elbow.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    # 한계개선폭(직전 n 대비 비용 감소분) -> 이 값이 급격히 작아지는 지점이 엘보우
    elbow_df["한계개선"] = -elbow_df["총비용"].diff()
    print("[n별 한계 비용개선(원/일) — 감소폭이 확 줄어드는 지점을 확인]")
    print(elbow_df.round(0).to_string())


# ══════════════════════════════════════════════════════════
# 7. n별 허브 위치
#    n이 늘어날 때 어떤 역이 새로 허브로 추가되는지, 몇 개 n 값에서
#    실제 위치가 지도상 어디인지 본다. 배경은 step3_vrp_route_viz.py와
#    같은 스타일(행정동/자치구/서울외곽 경계 + 지하철 노선)을 써서 좌표만
#    있는 산점도가 아니라 "서울 어디인지"가 바로 보이게 한다 — 이 그림은
#    특정 허브가 아니라 "n이 늘 때 허브가 어디로 퍼지는가"를 보는 전체
#    조망용이라, VRP 그림과 달리 노선은 1~4호선을 전부 깔고(역 점은 생략
#    — 후보역 회색 점과 겹쳐 지저분해짐), 허브 마커 색도 노선별로 나누지
#    않고 빨강으로 통일한다(나누면 오히려 분산 패턴이 안 보임).
# ══════════════════════════════════════════════════════════
if not elbow_hubs:
    print("허브가 선택된 n이 없어 위치 비교를 생략합니다.")
else:
    loc_rows = []
    prev = set()
    for n in sorted(elbow_hubs):
        cur = set(elbow_hubs[n])
        new = cur - prev
        loc_rows.append(dict(n=n, 허브목록=", ".join(sorted(cur)), 신규추가=", ".join(sorted(new)) or "-"))
        prev = cur
    loc_df = pd.DataFrame(loc_rows)
    loc_df.to_csv(f"{OUT}/elbow_hub_locations.csv", index=False, encoding="utf-8-sig")
    print(loc_df.to_string())

    import geopandas as gpd
    shp = gpd.read_file(os.path.join(BASE, "행정동.shp"), encoding="utf-8")
    shp["ADM_CD"] = shp["ADM_CD"].astype(str)
    geo_dong = shp[shp["ADM_CD"].str.startswith("11")].to_crs(epsg=4326)
    geo_dong["GU_KEY"] = geo_dong["ADM_CD"].str[:5]
    geo_gu = geo_dong.dissolve(by="GU_KEY").reset_index()
    geo_seoul = gpd.GeoDataFrame(geometry=[geo_dong.union_all()], crs=geo_dong.crs)

    # 노선 형상(배경용, 1~4호선 전부) — step2.py 섹션 2의 seg/
    # BRANCH_PARENT_OVERRIDE/역명_clean을 그대로 재사용해 "역을 잇는 직선"을 만든다.
    LINE_COLORS_ALL = {"1": "#0052A4", "2": "#00A84D", "3": "#EF7C1C", "4": "#00A5DE"}
    station_coords_clean = {}
    for _, r in stations.iterrows():
        station_coords_clean.setdefault(r["역명_clean"], (r["경도"], r["위도"]))
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
    # 서쪽/동쪽은 한국철도공사 관할이라 그 데이터셋에 없음). "서울시
    # 역사마스터 정보" CSV(호선 카테고리가 경부선/경인선/경원선/중앙선 등
    # 으로 세분돼 있음)에서 해당 구간 역 좌표를 가져와 물리적 실제 순서대로
    # 이어붙인다.
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
    for chain in LINE1_EXT_CHAINS:
        coords = [coord_lookup(n) for n in chain]
        for i in range(len(coords) - 1):
            if coords[i] and coords[i + 1]:
                ALL_LINE_EDGES["1"].append((coords[i], coords[i + 1]))

    def draw_admin_and_subway(ax, xlim, ylim, facecolor="#f5f5f5"):
        ax.set_facecolor(facecolor)
        geo_dong.cx[xlim[0]:xlim[1], ylim[0]:ylim[1]].plot(
            ax=ax, facecolor=facecolor, edgecolor="#999999", linewidth=0.4, alpha=0.4, zorder=0)
        geo_gu.cx[xlim[0]:xlim[1], ylim[0]:ylim[1]].plot(
            ax=ax, facecolor="none", edgecolor="#999999", linewidth=0.7, alpha=0.7, zorder=1)
        geo_seoul.plot(ax=ax, facecolor="none", edgecolor="#333333", linewidth=1.2, alpha=0.8, zorder=1)
        # 1호선을 코레일 관할 구간까지 이어붙였으니 나머지 노선과 동일한
        # 스타일로 그린다(따로 강조할 필요 없음 — 길게 이어지면 자연히 보임).
        for ln, edges in ALL_LINE_EDGES.items():
            c = LINE_COLORS_ALL[ln]
            for (x1, y1), (x2, y2) in edges:
                ax.plot([x1, x2], [y1, y2], color=c, linewidth=1.8, alpha=0.25, zorder=1.2,
                        solid_capstyle="round")

    show_n = [n for n in [3, 6, 9, max(elbow_hubs)] if n in elbow_hubs]
    fig, axes = plt.subplots(1, len(show_n), figsize=(5*len(show_n), 5.5), sharex=True, sharey=True)
    if len(show_n) == 1:
        axes = [axes]

    cand_idx = [j for j in range(N_ST) if OK[j]]
    cand_lon, cand_lat = stations.loc[cand_idx, "경도"], stations.loc[cand_idx, "위도"]

    # 패널 간 축 범위를 완전히 동일하게(sharex/sharey에 더해 명시적으로도)
    # 고정한다 — bbox_inches="tight" 저장 시 패널마다 라벨 텍스트 길이가
    # 달라 유효 크롭 범위가 미세하게 달라지는 걸 막기 위함.
    pad_x = (cand_lon.max() - cand_lon.min()) * 0.05
    pad_y = (cand_lat.max() - cand_lat.min()) * 0.05
    xlim = (cand_lon.min() - pad_x, cand_lon.max() + pad_x)
    ylim = (cand_lat.min() - pad_y, cand_lat.max() + pad_y)

    # 채택 패널 강조 — n=8(시나리오 스윕, n<=n_max 자유)과 n=9(이 엘보우,
    # exact=True 고정)의 단위비용이 사실상 동률(44.75 vs 44.70원/박스,
    # 솔버 gapRel 0.02 오차범위 안)이라 "n=8~9 구간이 최적"이 정확한 표현.
    ADOPTED_N = 9

    for ax, n in zip(axes, show_n):
        is_adopted = (n == ADOPTED_N)
        draw_admin_and_subway(ax, xlim, ylim, facecolor="#fffbf0" if is_adopted else "#f5f5f5")
        ax.scatter(cand_lon, cand_lat, s=5, color="lightgray", alpha=0.4, label="후보역", zorder=2)
        hub_names = set(elbow_hubs[n])
        sel = stations[stations["역명"].isin(hub_names)]
        ax.scatter(sel["경도"], sel["위도"], s=90, color="white", zorder=3)
        ax.scatter(sel["경도"], sel["위도"], s=50, color="crimson", label="허브", zorder=4)
        for _, row in sel.iterrows():
            ax.annotate(row["역명"], (row["경도"], row["위도"]), fontsize=7,
                        xytext=(3, 3), textcoords="offset points", zorder=5)
        ax.set_xlim(*xlim); ax.set_ylim(*ylim)
        if is_adopted:
            ax.set_title(f"n = {n}  ★ 채택 구간(n=8~9)", fontsize=13, fontweight="bold", color="#B71C1C")
            for spine in ax.spines.values():
                spine.set_visible(True); spine.set_linewidth(3); spine.set_color("#B71C1C")
        else:
            ax.set_title(f"n = {n}", fontsize=13, fontweight="bold")
            for spine in ax.spines.values():
                spine.set_visible(False)
        ax.set_xticks([]); ax.set_yticks([])
    axes[0].legend(loc="upper left", fontsize=8)
    rep_unit = best["단위비용"] if len(ok) else None
    elbow9_unit = elbow_df.loc[elbow_df["n"] == ADOPTED_N, "단위비용"].values
    if rep_unit is not None and len(elbow9_unit):
        fig.text(0.5, -0.02,
                f"대표 시나리오 {best['ID']}(허브 {int(best['n'])}개, {rep_unit:.1f}원/박스)와 이 엘보우의 "
                f"n={ADOPTED_N}({elbow9_unit[0]:.1f}원/박스)는 사실상 동률 — n<=n_max로 자유롭게 푼 "
                "시나리오 최적화와 n을 정확히 고정한 엘보우 분석의 방법론 차이일 뿐, "
                "'허브 8~9개 구간이 최적'으로 결론은 같다.",
                ha="center", fontsize=9, color="#555555")
    plt.tight_layout()
    nc.savefig_retry(plt, f"{OUT}/elbow_hub_maps.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

print(f"\n저장: {OUT}\\elbow_results.csv, elbow.png, elbow_hub_locations.csv, elbow_hub_maps.png")
