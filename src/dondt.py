"""
동트식 비례 분배 알고리즘.

감축률 기반 점수로 에너지 단위를 배분한다.

점수 방식 두 가지:
1. 선형 (평행이동): score = max(0, r_i + shift)
   - 꼴찌(보정 후 점수=0)는 분배받지 못함
   - 자연봉쇄선이 뒤에서 2등 감축률에 맞닿도록 k 자동 산출

2. 지수함수: score = exp(α × r_i)
   - 음수 감축률에도 양수 점수 → 모든 자치구 참여 가능
   - α(알파)가 클수록 쏠림 효과 강해짐
   - k 자동 산출: 최하위 자치구가 1단위 받는 최소 k
"""

from __future__ import annotations
import math
from typing import Dict, Tuple

SCORE_MODES = ['선형 (평행이동)', '지수함수 (exp)']


# ── 감축률 계산 ───────────────────────────────────────────────────────────────

def calculate_reduction_rates(
    current: Dict[str, float],
    baseline: Dict[str, float],
) -> Dict[str, float]:
    """각 자치구의 감축률(%). 양수=감축, 음수=증가."""
    return {
        d: 100.0 * (1.0 - current[d] / baseline[d]) if baseline.get(d, 0) > 0 else 0.0
        for d in current
    }


# ── 점수 변환 ─────────────────────────────────────────────────────────────────

def score_linear(rates: Dict[str, float]) -> Tuple[Dict[str, float], float]:
    """
    평행이동 보정 후 선형 점수.
    최솟값이 0이 되도록 전체 이동. 꼴찌 자치구는 score=0 → 분배 없음.
    """
    if not rates:
        return {}, 0.0
    min_r = min(rates.values())
    shift = max(0.0, -min_r)
    return {d: v + shift for d, v in rates.items()}, shift


def score_exponential(
    rates: Dict[str, float],
    alpha: float = 0.1,
) -> Tuple[Dict[str, float], float]:
    """
    지수함수 점수: s_i = exp(α × r_i).

    - 모든 자치구가 양수 점수 → 분배에서 완전 배제되는 자치구 없음
    - α 클수록 상위권 쏠림 강해짐 (권장 범위: 0.05 ~ 0.3)
    - 음수 감축률(배출 증가)도 자동으로 낮은 양수 점수로 처리 → 평행이동 불필요
    """
    return {d: math.exp(alpha * r) for d, r in rates.items()}, 0.0


# ── k값 자동 산출 ─────────────────────────────────────────────────────────────

def find_optimal_k(scores: Dict[str, float]) -> int:
    """
    최하위 비零 점수 자치구가 정확히 1단위 받는 최소 k 산출.
    공식: k = Σ floor(s_i / s_min) , where s_min = min nonzero score
    자연봉쇄선이 뒤에서 2등 점수에 맞닿도록 설계.
    """
    nonzero = {d: s for d, s in scores.items() if s > 1e-10}
    if not nonzero:
        return 1
    if len(nonzero) == 1:
        return 1
    s_min = min(nonzero.values())
    return max(1, sum(int(s / s_min) for s in nonzero.values()))


# ── D'Hondt 배분 ──────────────────────────────────────────────────────────────

def dondt_allocate(scores: Dict[str, float], total_units: int) -> Dict[str, int]:
    """동트식으로 total_units 단위를 점수에 비례하여 배분."""
    districts = list(scores.keys())
    allocation: Dict[str, int] = {d: 0 for d in districts}
    if total_units <= 0:
        return allocation
    for _ in range(total_units):
        quotients = {d: scores[d] / (allocation[d] + 1) for d in districts}
        winner = max(quotients, key=lambda d: quotients[d])
        allocation[winner] += 1
    return allocation


# ── 전체 파이프라인 ───────────────────────────────────────────────────────────

def run_cluster_allocation(
    cluster_name: str,
    cluster_districts: list[str],
    current_emissions: Dict[str, float],
    baseline_emissions: Dict[str, float],
    k_override: int | None = None,
    score_mode: str = '선형 (평행이동)',
    alpha: float = 0.1,
) -> dict:
    """
    클러스터 내 동트식 분배 전체 파이프라인.

    score_mode:
        '선형 (평행이동)' : 평행이동 보정, 꼴찌=0
        '지수함수 (exp)'  : exp(α × 감축률), 모두 양수
    alpha:
        지수함수 모드 전용 곡률 파라미터 (권장 0.05~0.3)

    Returns dict:
        cluster, districts, reduction_rates, scores, shift, alpha,
        score_mode, k, allocation_units, current_emissions, baseline_emissions
    """
    current = {d: current_emissions.get(d, 0.0) for d in cluster_districts}
    baseline = {d: baseline_emissions.get(d, 0.0) for d in cluster_districts}

    raw_rates = calculate_reduction_rates(current, baseline)

    if score_mode == '지수함수 (exp)':
        scores, shift = score_exponential(raw_rates, alpha)
    else:
        scores, shift = score_linear(raw_rates)

    k = k_override if k_override is not None else find_optimal_k(scores)
    units = dondt_allocate(scores, k)

    return {
        'cluster': cluster_name,
        'districts': cluster_districts,
        'reduction_rates': raw_rates,
        'scores': scores,
        'shift': shift,
        'alpha': alpha,
        'score_mode': score_mode,
        'k': k,
        'allocation_units': units,
        'current_emissions': current,
        'baseline_emissions': baseline,
    }
