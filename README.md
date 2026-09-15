# 서울 지하철 심야 유휴시간을 활용한 도심 화물 허브 입지 최적화

서울 지하철 1~4호선의 심야 유휴 시간대(00:30~03:30)에 택배 화물을 실어
도심으로 진입하는 화물트럭의 주행거리(VKT)와 CO₂ 배출을 줄이는 방안을 평가했다.
**어느 역을 화물 허브로 쓸 것인가**와 **각 행정동을 어느 허브가 담당할 것인가**를
혼합정수계획법(MILP)으로 동시에 결정하고, 확정된 배정에 대해 차량경로문제(VRP)를
풀어 실제 라스트마일 주행거리를 산출했다.

서울 426개 행정동, 지하철 135개역(1호선 코레일 관할 구간 포함)을 대상으로
칸수·운행횟수·분담률 격자 48개 조합을 탐색했다.

---

## 1. 주요 결과

**대표 시나리오 S39 — 4칸 × 5회 운행, 지하철 분담률 12%**

| 항목 | 값 |
|---|---|
| 허브 수 | **18개** |
| 단위비용 | **73.27원/박스** |
| 총비용 | 10,640,332원/일 |
| 처리 물량 | 145,222박스/일 |
| VKT 절감 | 56,984km/일 (**90.6%**) |
| CO₂ 절감 | 18,108kg/일 · 연 **6,609톤** (승용차 2,754대분) |
| 도심 진입 트럭 | 933대/일 → 0대/일 |

**선정 허브 18개**
가락시장 · 교대 · 구로 · 구의 · 대방 · 독산 · 불광 · 서울역 · 수서 · 신답 ·
신설동 · 신용산 · 신이문 · 양천구청 · 오금 · 창동 · 총신대입구 · 충정로

**정책 제언** — 하역 출입문 3개 병렬(450박스/분) 확보가 사업 성립의 최소 조건이다.
이를 확보하지 못하면 다른 조건이 모두 유리해도 분담률 12%를 달성할 수 없다
(`diag_stress_combinations.csv`: 12%가 깨지는 5개 조합이 전부 저속하역을 포함).

> **인용 시 조건** — VKT/CO₂ 절감률은 **"외곽 물류센터 직배송 대비"**, **"지하철이
> 담당한 물량(서울 전체의 12%) 기준"** 이다. 서울 전체 택배 물동량 대비로는
> VKT 10.9% · CO₂ 10.7% 감축이다.

---

## 2. 데이터

**본 저장소에는 원본 데이터가 포함되어 있지 않습니다.**

- **택배 물동량**: 서울시 빅데이터캠퍼스(bigdata.seoul.go.kr)의
  「서울시 행정동단위 CJ대한통운 택배 유형별 월 데이터」
  ※ 폐쇄형 분석 환경에서 이용 신청 후 반출 절차를 거쳐 취득
- **그 외**: 공공데이터포털 등에서 다운로드 (보고서 표 1 참조)

아래 파일들을 저장소 루트에 놓으면 실행된다.

| 파일명 | 내용 | 출처 |
|---|---|---|
| `반출_행정동별_일평균수요.xls` | 행정동별 일평균 택배 물동량 | 서울시 빅데이터캠퍼스 (반출 승인 필요) |
| `행정동.shp` / `.dbf` / `.shx` / `.prj` | 서울 행정동 경계 | 통계청 통계지리정보서비스(SGIS) |
| `서울교통공사 역간거리 및 소요시간_240810.csv` | 1~4호선 역간 거리·소요시간 | 공공데이터포털 |
| `서울교통공사_역사심도정보_20241104.csv` | 역사 심도(지반고·레일면고) | 공공데이터포털 |
| `서울교통공사_지하상가 임대정보_20251231.csv` | 역사 상가 임대료 | 공공데이터포털 |
| `서울교통공사_환승역거리 소요시간 정보_20250331.csv` | 환승역 정보 | 공공데이터포털 |
| `서울시 역사마스터 정보 (1).csv` | 역 좌표 | 서울열린데이터광장 |
| `한국철도공사_도시광역철도_역사정보_20260228.xlsx` | 1호선 코레일 구간 역 좌표 | 공공데이터포털 |
| `202608281a045c6bb40560.xlsx` | 1호선 코레일 구간 열차 시각표 | 국토교통부 |
| `2026년+7월+역별+상업시설...xls` | 코레일 상업시설 매출(임대료 환산용) | 코레일유통 사전정보공개 |

도로망은 OSMnx로 서울 경계 내 `drive` 네트워크를 내려받아 캐시한다
(`output_data/seoul_drive.graphml`, 약 72MB — 용량 문제로 미포함, `step1.py`가 생성).

> `output_data/scenario_assignments.csv`에는 **수요 열을 제외**했다. 행정동별
> 물량은 위 반출 자료에서 파생된 값이라 공개 대상이 아니기 때문이다. 이 열이
> 필요한 스크립트(`step5`, `step6`)는 원자료가 있으면 자동으로 되살린다
> (`network_common.attach_demand`).

---

## 3. 실행 순서

`step1` 계열은 한 번만 돌리면 되고(거리행렬 캐시 생성), 이후는 반복 실행 가능하다.

### 전처리 — 거리행렬 (최초 1회, 수십 분 소요)

```
python step1.py                        # 행정동 정리 + OSM 도로망 → 역×동 거리행렬(dist_km.npy)
python step1b_dong_distance_matrix.py  # 동×동 거리행렬(dong_dist_km.npy) — VRP용
python step1c_extend_line1_stations.py # 1호선 코레일 26개역을 거리행렬에 확장(110→135행)
```

### 최적화 — 허브 입지

```
python step2.py                        # 격자 48조합 MILP 탐색 → scenario_results/hubs/assignments
python step2_refine_rep.py 10          # 상위 10개 조합을 gapRel 0.2%로 정밀 재계산 ★필수
python step2_elbow_s39.py              # 허브 개수 n=1~30 엘보우 분석 → elbow.png
python step2_max_feasible_share_v2.py  # 실행가능 최대 분담률(SMAX) 이분탐색
```

> **`step2_refine_rep.py`를 반드시 함께 돌려야 한다.** 격자 탐색은 48조합을 훑느라
> 허용오차 `gapRel=0.02`로 느슨한데, 라스트마일을 왕복으로 계산한 뒤 비용 곡선이
> 평탄해져(n=15~22가 1.5% 안) 허용오차가 곡선의 기복보다 넓어졌다. 이 상태로는
> 차선해가 최적으로 잡힌다. 실제로 `step2.py`만 돌리면 S39가 74.16원/n=16으로
> 나오고, 정밀화를 거쳐야 **73.27원/n=18**이 된다.

### 후속 분석

```
python step3_vrp_lastmile.py           # 허브별 VRP → 실제 라스트마일 주행거리
python step3_vrp_lastmile.py SMAX      # SMAX 시나리오도 동일하게
python step4_emission.py               # VKT·CO₂ 산출 (D_TRUNK 20/30/40/50km 민감도)
python step2_diagnostics.py all        # 민감도·정책·강건성·인접허브·인입선 진단
python step2_tornado.py                # 8개 변수 ±30% 토네이도 민감도
python step2_install_cost.py           # 허브 구축비 P별 최적 규모 (추가 분석)
python step2_install_cost_tiered.py    # 구축비 지상/지하 차등 버전
python step2_install_elbow_overlay.py  # 구축비별 비용 곡선 겹쳐 그리기
python step2_seoul_boundary_audit.py   # 서울 경계 밖 역 판정(지축 제외 근거)
python step2_representative_scenario_spec.py  # 대표 시나리오 스펙 요약 txt
```

### 시각화

```
python step2_scenario_viz_v2.py        # 시나리오 히트맵·순위 막대
python step2_scenario_surface3d.py     # 3차원 비용 곡면
python step3_vrp_route_viz.py all      # 허브별 라스트마일 경로 (상위 5대 / 전체)
python step5_hub_service_area.py       # 허브별 서비스 권역 코로플레스
python step6_presentation_figs.py      # 수요밀도·정책민감도·심야 간트
```

`pipeline_for_review.py`는 실행용이 아니라 **외부 코드 검증용 단일 파일**이다.
데이터 로드 → 노선망 → 비용 → MILP → VRP의 계산 로직만 한 파일에 모았고,
모델링 판단 6가지와 알려진 한계 A~E를 헤더에 정리했다.

---

## 4. 결과 파일

### 핵심

| 파일 | 내용 |
|---|---|
| `scenario_results.csv` | 48개 조합의 실행가능 여부·허브 수·총비용·단위비용 |
| `scenario_hubs.csv` | 조합별 선정 허브 목록 |
| `scenario_assignments.csv` | 행정동 → 허브 배정 (※ 수요 열 제외, 2절 참고) |
| `elbow_results.csv` / `elbow.png` | 허브 개수별 비용 곡선 (최저점 n=18) |
| `vrp_summary.csv` / `vrp_hub_routes.csv` | 허브별 VRP 주행거리·트럭 수 / 경로 상세 |
| `emission_summary.csv` | VKT·CO₂ 절감량 (D_TRUNK 민감도 포함) |
| `representative_scenario.txt` | 대표 시나리오 스펙 요약 |

### 진단

| 파일 | 내용 |
|---|---|
| `diag_sensitivity.csv` | ALPHA_RAIL·UNLOAD_RATE·AVAILABLE_MIN 민감도 |
| `diag_policy_unload_rate.csv` / `_available_min.csv` | 정책 변수별 최대 분담률 |
| `diag_stress_combinations.csv` | 보수 가정 4개 복합 스트레스 16조합 |
| `diag_tornado.csv` | 8개 변수 ±30% 민감도 |
| `diag_adjacent_hub.csv` | 인접 허브 쌍이 둘 다 필요한지 |
| `diag_access_line_sensitivity.csv` | 기지 인입선 시간 민감도 |
| `diag_install_cost*.csv` | 허브 구축비별 최적 규모 |
| `diag_unload_time.csv` | 심야 가용시간 제약 사후검증 |
| `station_seoul_audit.csv` | 전 역 서울 경계 내외 판정 |

### 그림

| 파일 | 내용 |
|---|---|
| `scenario_heatmap.png` · `scenario_ranked.png` | 조합별 단위비용 히트맵 / 순위 |
| `scenario_surface3d.png` | 설계변수 2개씩 × 단위비용 3차원 곡면 |
| `elbow.png` · `elbow_hub_maps.png` | 허브 개수 엘보우 / n별 허브 위치 |
| `hub_service_area.png` | 허브 18개의 서비스 권역 |
| `demand_density_hubs.png` | 행정동 수요밀도 + 허브 입지 |
| `vrp_route_{N}호선_{역명}.png` | 노선별 대표 허브 라스트마일 (상위 5대) |
| `vrp_route_{N}호선_{역명}_전체.png` | 같은 허브의 전체 경로 |
| `emission_comparison.png` | VKT·CO₂ 비교 |
| `policy_sensitivity.png` | 하역속도·심야시간별 최대 분담률 |
| `night_window_gantt.png` · `night_window_timeline.png` | 심야 180분 소모 구조 / 운행 타임라인 |
| `tornado_sensitivity.png` | 변수 민감도 토네이도 |
| `install_elbow_overlay.png` | 구축비별 비용 곡선 |

---

## 5. 환경

- **Python 3.13**
- 최적화: PuLP + CBC (MILP), OR-Tools (VRP)
- 공간/네트워크: OSMnx, GeoPandas, Shapely, NetworkX
- 그림: Matplotlib (한글 폰트 `Malgun Gothic` — Windows 기준)

```
pip install -r requirements.txt
```

Windows 외 환경에서는 `matplotlib.rcParams["font.family"]`를 설치된 한글 폰트로
바꿔야 한다(`NanumGothic` 등).

**실행 시간 참고** — `step1.py`는 OSM 도로망 다운로드와 Dijkstra 계산으로 수십 분,
`step2.py`는 48조합 MILP로 수십 분, `step2_refine_rep.py 10`은 조합당 최대 10분,
`step2_diagnostics.py stress`는 이분탐색 16조합으로 1시간 이상 걸린다.

---

## 6. 알려진 한계

보고서 본문과 `pipeline_for_review.py` 헤더에 상세히 정리했다. 요약하면:

- **배정 경성화** — MILP의 연속 배정을 "동 하나 = 허브 하나"로 확정하는 과정에서
  일부 방향이 적재량·엘리베이터 상한을 0.6~2.8% 초과한다(시간 제약은 전부 충족).
- **코레일 구간 임대료**는 실계약이 아니라 상업시설 매출 × 수수료율 15.5% 환산치다.
- **1호선 코레일 구간 역간 거리**는 시각표 소요시간 × 평균 표정속도 환산치다.
- **기지 인입선 주행시간을 0분**으로 가정했다(차량기지와 접속역을 동일 노드 처리).
  편도 3·5분을 넣어도 접속역 허브는 유지되나 전체 구성에는 영향이 있다.
- **CO₂ 기준선**은 현행 택배 시스템이 아니라 "외곽 직배송" 가정이다. 절감의 98%가
  간선 트럭 제거에서 나오며, 차량기지 반입 주행은 산정에 포함하지 않았다.
- **허브 구축비(CAPEX) 미반영** — 운영비 기준 결과다. 허브당 3억원을 반영하면
  최적 규모가 18 → 16개로 줄어든다. 정확한 규모 산정에는 별도 경제성 분석이 필요하다.
- **역명 중복** — `신도림`이 2호선 원본과 1호선 코레일 신규 행으로 두 번 들어가 있다
  (창동은 병합 처리했으나 신도림은 누락). 현재 어떤 시나리오에서도 허브로 선정되지
  않아 결과에 영향은 없다. 실행 시 경고가 출력된다.
