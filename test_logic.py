"""알고리즘 검증 테스트"""
import sys, os, math
sys.path.insert(0, os.path.dirname(__file__))

from src.config import (
    CLUSTERS, get_baseline_monthly_generation,
    get_baseline_monthly_incineration, get_incineration_fraction,
    BASELINE_2024_GENERATION, BASELINE_2024_INCINERATION,
)
from src.dondt import run_cluster_allocation
from src.energy import calc_energy_and_subsidy, calc_district_allocation

baseline_gen = get_baseline_monthly_generation()
baseline_inc = get_baseline_monthly_incineration()
inc_frac = get_incineration_fraction()

import random
random.seed(42)

print("=" * 60)
print("기준기간 데이터 확인 (발생량 vs 소각량, 월 기준)")
print("=" * 60)
for cluster, members in CLUSTERS.items():
    b_gen = sum(baseline_gen[d] for d in members)
    b_inc = sum(baseline_inc[d] for d in members)
    energy = b_inc * 0.35
    print(f"  {cluster}: 발생량 {b_gen:,.0f}톤/월 | 소각량 {b_inc:,.0f}톤/월 ({b_inc/b_gen*100:.1f}%) | 기준에너지 {energy:,.0f} MWh")

print()
print("=" * 60)
print("동트식 분배 + 에너지 계산 (10% 전후 랜덤 감축)")
print("=" * 60)

for cluster, members in CLUSTERS.items():
    current = {d: baseline_gen[d] * (1 - random.uniform(0.03, 0.15)) for d in members}

    r_lin = run_cluster_allocation(cluster, members, current, baseline_gen, score_mode='선형 (평행이동)')
    r_exp = run_cluster_allocation(cluster, members, current, baseline_gen, score_mode='지수함수 (exp)', alpha=0.1)

    energy = calc_energy_and_subsidy(
        members, current, baseline_gen, baseline_inc, inc_frac, 0.35, 120
    )
    da_lin = calc_district_allocation(r_lin['allocation_units'], r_lin['k'], energy)

    print(f"\n[{cluster}] k(선형)={r_lin['k']}, k(지수)={r_exp['k']}")
    print(f"  기준에너지={energy['baseline_energy_mwh']:,.0f} MWh | 실제={energy['actual_energy_mwh']:,.0f} MWh | 보조금={energy['subsidy_krw']/1e6:.1f}M원")

    for d in sorted(members, key=lambda x: r_lin['reduction_rates'][x], reverse=True):
        rate = r_lin['reduction_rates'][d]
        u_lin = r_lin['allocation_units'][d]
        u_exp = r_exp['allocation_units'][d]
        mwh = da_lin[d]['total_mwh']
        print(f"  {d}: 감축률={rate:+.1f}% | 선형={u_lin}단위 | 지수={u_exp}단위 | {mwh:,.0f}MWh")

print()
print("=" * 60)
print("지수함수 특성: 음수 감축률 테스트")
print("=" * 60)
# 강제로 음수 감축률 발생시키기
cluster = '양천'
members = CLUSTERS[cluster]
current_neg = {members[0]: baseline_gen[members[0]] * 1.10,   # +10% 증가
               members[1]: baseline_gen[members[1]] * 0.95,   # -5% 감축
               members[2]: baseline_gen[members[2]] * 0.88}   # -12% 감축

r_lin_neg = run_cluster_allocation(cluster, members, current_neg, baseline_gen, score_mode='선형 (평행이동)')
r_exp_neg = run_cluster_allocation(cluster, members, current_neg, baseline_gen, score_mode='지수함수 (exp)', alpha=0.1)

for d in members:
    rate = r_lin_neg['reduction_rates'][d]
    s_lin = r_lin_neg['scores'][d]
    s_exp = r_exp_neg['scores'][d]
    u_lin = r_lin_neg['allocation_units'][d]
    u_exp = r_exp_neg['allocation_units'][d]
    print(f"  {d}: 감축률={rate:+.1f}% | 선형점수={s_lin:.3f}({u_lin}단위) | exp점수={s_exp:.3f}({u_exp}단위)")

print(f"\n  선형 shift = +{r_lin_neg['shift']:.1f}%p (평행이동)")
print(f"  지수 shift = {r_exp_neg['shift']:.1f} (이동 없음 - 자동 처리)")
