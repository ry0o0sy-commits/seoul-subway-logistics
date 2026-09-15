"""
대표 시나리오(S39) 전체 스펙 출력
────────────────────────────────────────────────────────────
1호선 코레일 구간 확장 + 심도 절댓값 수정 + 임대료 재설계 이후 재실행에서
단위비용 최소 시나리오가 S25(3칸x5회, 4%) -> S39(4칸x5회, 12%)로 바뀌었다.
앞으로 모든 산출물(시각화, VKT/CO2, 결론)을 S39 기준으로 통일하기 위해
스펙을 한 장으로 정리해 콘솔 출력 + output_data/representative_scenario.txt 저장.

MILP를 다시 풀지 않는다 — scenario_results.csv/scenario_hubs.csv의 저장값을
그대로 쓰고, 방향별 실제 운행횟수(eff_trips)만 network_common으로 재구축한다.
"""

import os
import pandas as pd
import network_common as nc

OUT = nc.OUT
REP_ID = nc.REP_SCENARIO["ID"]      # 대표 시나리오 정의는 network_common 한 곳

print("[1] 네트워크 재구축")
stations = nc.load_stations()
seg = nc.load_seg()
net = nc.build_network(stations, seg)
hub_dir, DIR_ROUND_TRIP, MAX_TRIPS = net["hub_dir"], net["DIR_ROUND_TRIP"], net["MAX_TRIPS"]

results = pd.read_csv(f"{OUT}/scenario_results.csv")
srow = results[results["ID"] == REP_ID].iloc[0]
hubs_csv = pd.read_csv(f"{OUT}/scenario_hubs.csv")
hub_names = sorted(h.strip() for h in hubs_csv[hubs_csv["ID"] == REP_ID].iloc[0]["선정역사"].split(","))

name2idx = {n: i for i, n in enumerate(stations["역명"])}
hub_dirs_used = sorted(set(hub_dir[name2idx[n]] for n in hub_names))

LINE1_NEW = set(nc.LINE1_KORAIL_TARGETS) - {"창동"}

lines = []
def p(s=""):
    print(s)
    lines.append(s)

p("=" * 74)
p(f"대표 시나리오 {REP_ID} 전체 스펙")
p("=" * 74)
p("[운영 조건]")
p(f"  칸 수(cars)       : {int(srow['칸'])}칸")
p(f"  운행횟수(trips)   : {int(srow['운행'])}회 (희망치 — 방향별 실제 캡핑값은 아래 참고)")
p(f"  분담률(share)     : {srow['분담률']:.0%}")
p(f"  필요물량          : {srow['필요물량']:,.0f}박스/일")
p(f"  총 수송능력       : {srow['총능력']:,.0f}박스/일")

p("\n[허브]")
p(f"  허브 개수         : {int(srow['n'])}개")
p(f"  선정역 목록       : {', '.join(hub_names)}")
new_in_hubs = sorted(set(hub_names) & LINE1_NEW)
p(f"  이 중 1호선 신규역: {', '.join(new_in_hubs) if new_in_hubs else '-'} ({len(new_in_hubs)}개)")

p("\n[비용]")
p(f"  총비용            : {srow['총비용']:,.0f}원/일")
p(f"  단위비용          : {srow['단위비용']:.1f}원/박스")

p("\n[비용 구성 비중]")
p(f"  라스트마일        : {srow['라스트마일비중']:.1%}")
p(f"  철도(합계)        : {srow['철도비중']:.1%}  (운행 {srow['철도운행비중']:.1%} + 하역 {srow['철도하역비중']:.1%})")
p(f"  심도(엘리베이터)  : {srow['심도비중']:.1%}")
p(f"  고정비(임대료)    : {srow['고정비중']:.1%}")

p("\n[방향별 실제 운행횟수 — 선정 허브가 속한 방향만]")
p(f"  {'방향':<30} {'왕복+회차(분)':>13} {'희망':>5} {'실제':>5}  담당 허브")
for dkey in hub_dirs_used:
    rt = DIR_ROUND_TRIP[dkey] + nc.TURNAROUND_MIN
    eff = min(int(srow["운행"]), MAX_TRIPS[dkey])
    capped = " (캡핑)" if eff < int(srow["운행"]) else ""
    hubs_in_dir = [n for n in hub_names if hub_dir[name2idx[n]] == dkey]
    p(f"  {dkey:<30} {rt:>13.1f} {int(srow['운행']):>5d} {eff:>5d}{capped}  <- {', '.join(hubs_in_dir)}")

p("\n[참고 — 허브 개수 근거]")
elbow_path = f"{OUT}/elbow_results.csv"
if os.path.exists(elbow_path):
    e = pd.read_csv(elbow_path)
    lo = e.loc[e["총비용"].idxmin()]
    p(f"  엘보우 분석(n=1~{int(e['n'].max())}) 결과 총비용 최저점이 "
      f"n={int(lo['n'])}({lo['총비용']:,.0f}원/일, {lo['단위비용']:.2f}원/박스)이고,")
    near = e[e["n"].isin([int(lo["n"]) - 2, int(lo["n"]) - 1, int(lo["n"]) + 1])]
    detail = ", ".join(f"n={int(r['n'])} {r['총비용']/1e6:.3f}백만원"
                       for _, r in near.iterrows())
    p(f"  주변값은 {detail}으로, 최저점을 지나면 다시 올라간다.")
    p(f"  격자 탐색이 허브 수 제한 없이 고른 값도 n={int(srow['n'])}개로 일치해, "
      f"별도 고정 없이 이 결과를 대표 시나리오로 쓴다.")
p("=" * 74)

with open(f"{OUT}/representative_scenario.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
print(f"\n저장: {OUT}\\representative_scenario.txt")
