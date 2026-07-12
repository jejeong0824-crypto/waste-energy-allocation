"""
에너지 생산량 및 보조금 계산.

에너지는 소각량 기준으로 산출한다.
  cluster_energy = Σ(자치구 소각량) × energy_per_ton_mwh

당월 소각량 추정:
  현재 발생량 데이터만 있을 경우, 2024년 소각 비율을 적용하여 소각량 추정.
  current_incineration[d] = current_generation[d] × (소각량_2024 / 발생량_2024)

총 분배 가능량 = 항상 기준 에너지로 고정 (정합게임 유지).
  실제 < 기준: 보조금으로 부족분 보전
  실제 > 기준: 기준량만 분배, 잉여분은 미배분 (담합 방지)
"""

from __future__ import annotations
from typing import Dict


def calc_energy_and_subsidy(
    cluster_districts: list[str],
    current_generation: Dict[str, float],
    baseline_generation_monthly: Dict[str, float],
    baseline_incineration_monthly: Dict[str, float],
    incineration_fraction: Dict[str, float],
    energy_per_ton: float,
    price_krw_per_kwh: float,
) -> dict:
    """
    클러스터 에너지 생산량, 부족분, 보조금 계산.

    당월 소각량 = 당월 발생량 × (2024년 소각 비율)
    (소각 비율은 자치구별 상이, 금천구처럼 낮은 구는 낮게 반영)

    Returns:
        baseline_generation_tons, current_generation_tons,
        baseline_incineration_tons, current_incineration_tons,
        baseline_energy_mwh, actual_energy_mwh, distributable_energy_mwh,
        shortfall_mwh, subsidy_krw,
        energy_fraction, subsidy_fraction, energy_ratio,
        price_krw_per_kwh
    """
    base_gen = sum(baseline_generation_monthly.get(d, 0.0) for d in cluster_districts)
    curr_gen = sum(current_generation.get(d, 0.0) for d in cluster_districts)

    base_inc = sum(baseline_incineration_monthly.get(d, 0.0) for d in cluster_districts)

    # 당월 소각량 = 당월 발생량 × 자치구별 소각 비율
    curr_inc = sum(
        current_generation.get(d, 0.0) * incineration_fraction.get(d, 0.0)
        for d in cluster_districts
    )

    baseline_energy = base_inc * energy_per_ton
    actual_energy = curr_inc * energy_per_ton
    distributable = baseline_energy

    shortfall = max(0.0, baseline_energy - actual_energy)
    subsidy_krw = shortfall * 1000.0 * price_krw_per_kwh

    energy_frac = min(1.0, actual_energy / baseline_energy) if baseline_energy > 0 else 1.0
    subsidy_frac = 1.0 - energy_frac

    return {
        'baseline_generation_tons': base_gen,
        'current_generation_tons': curr_gen,
        'baseline_incineration_tons': base_inc,
        'current_incineration_tons': curr_inc,
        'baseline_energy_mwh': baseline_energy,
        'actual_energy_mwh': actual_energy,
        'distributable_energy_mwh': distributable,
        'shortfall_mwh': shortfall,
        'subsidy_krw': subsidy_krw,
        'energy_ratio': actual_energy / baseline_energy if baseline_energy > 0 else 1.0,
        'energy_fraction': energy_frac,
        'subsidy_fraction': subsidy_frac,
        'price_krw_per_kwh': price_krw_per_kwh,
    }


def calc_district_allocation(
    allocation_units: Dict[str, int],
    k: int,
    energy_info: dict,
) -> Dict[str, dict]:
    """
    단위당 에너지량 × 단위 수 → 자치구별 에너지+보조금 할당량.
    단위 구성 = (energy_fraction)만큼 실 에너지 + (subsidy_fraction)만큼 보조금
    """
    distributable = energy_info['distributable_energy_mwh']
    energy_frac = energy_info['energy_fraction']
    subsidy_frac = energy_info['subsidy_fraction']
    price = energy_info['price_krw_per_kwh']
    unit_energy = distributable / k if k > 0 else 0.0

    result: Dict[str, dict] = {}
    for district, units in allocation_units.items():
        total_mwh = units * unit_energy
        energy_mwh = total_mwh * energy_frac
        subsidy_mwh_equiv = total_mwh * subsidy_frac
        subsidy_krw = subsidy_mwh_equiv * 1000.0 * price
        result[district] = {
            'units': units,
            'total_mwh': total_mwh,
            'energy_mwh': energy_mwh,
            'subsidy_mwh_equiv': subsidy_mwh_equiv,
            'subsidy_krw': subsidy_krw,
        }
    return result
