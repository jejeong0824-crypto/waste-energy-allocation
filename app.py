"""
서울시 생활계폐기물 기반 에너지 분배 시스템 (프로토타입)
- 동트식 비례 분배 (선형/지수함수 모드)
- 소각량 기반 에너지 + 보조금 보완
- 기준기간: 2024년 연간 데이터 / 12
"""

from __future__ import annotations
import sys, os, calendar, random, math
sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

from src.config import (
    CLUSTERS, CLUSTER_COLORS,
    get_baseline_monthly_generation,
    get_baseline_monthly_incineration,
    get_incineration_fraction,
    ENERGY_PER_TON_MWH, ELECTRICITY_PRICE_KRW_PER_KWH,
    BASELINE_2024_GENERATION, BASELINE_2024_INCINERATION,
)
from src.dondt import run_cluster_allocation, SCORE_MODES
from src.energy import calc_energy_and_subsidy, calc_district_allocation
from src import archive


# ─────────────────────────────────────────────
st.set_page_config(
    page_title="서울시 생활계폐기물 에너지 분배 시스템",
    page_icon="♻️", layout="wide", initial_sidebar_state="expanded",
)
st.title("♻️ 서울시 생활계폐기물 에너지 분배 시스템")
st.caption(
    "동트식 비례 분배 × 보조금 보완 | 프로토타입 (기준기간: 2024년 연간 ÷ 12) | "
    "경쟁 지표: 발생량 감축률 | 에너지 산출: 소각량 × 0.35 MWh/톤"
)

# ─────────────────────────────────────────────
# 사이드바
# ─────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ 설정")

    st.subheader("📅 분석 월")
    col_y, col_m = st.columns(2)
    with col_y:
        sel_year = st.selectbox("연도", [2025, 2026, 2027], index=1)
    with col_m:
        sel_month = st.selectbox("월", list(range(1, 13)), index=0)
    year_month = f"{sel_year}-{sel_month:02d}"

    st.subheader("⚡ 에너지 파라미터")
    energy_per_ton = st.number_input(
        "소각 폐기물 1톤당 발전량 (MWh)", min_value=0.1, max_value=1.0,
        value=ENERGY_PER_TON_MWH, step=0.05,
        help="실제 자원회수시설 열효율에 따라 조정. 서울 시설 기준 약 0.3~0.4 MWh/톤."
    )
    price_per_kwh = st.number_input(
        "전기 단가 (원/kWh)", min_value=50, max_value=300,
        value=ELECTRICITY_PRICE_KRW_PER_KWH, step=10
    )

    st.subheader("📐 점수 방식")
    score_mode = st.radio("점수 계산 방법", SCORE_MODES, index=0)
    alpha = 0.1
    if score_mode == '지수함수 (exp)':
        alpha = st.slider(
            "α (알파) - 곡률 파라미터", min_value=0.01, max_value=0.50,
            value=0.10, step=0.01,
            help="클수록 상위권 쏠림 효과 강해짐. 0.05~0.15 권장."
        )
        st.info(
            f"점수 공식: exp(α × 감축률)\n\n"
            f"감축률 +10% → {math.exp(alpha*10):.2f}배\n"
            f"감축률 -5% → {math.exp(alpha*-5):.3f}배 (0보다 크므로 배분 참여)\n\n"
            f"**선형과 차이**: 꼴찌도 소량 배분받음"
        )

    st.subheader("🔧 k값 모드")
    k_mode = st.radio("k값 설정", ["자동 (권장)", "수동"], index=0)
    k_manual = None
    if k_mode == "수동":
        k_manual = st.number_input("k값 (총 배분 단위 수)", min_value=1, max_value=2000, value=100)

    st.subheader("🎲 시뮬레이션")
    noise_pct = st.slider("랜덤 변동 폭 (%)", min_value=0, max_value=30, value=10)
    if st.button("🎲 데이터 새로 생성", use_container_width=True):
        st.session_state['sim_seed'] = random.randint(0, 9999)
        st.session_state['data_generated'] = True

# ─────────────────────────────────────────────
# 기준 데이터 (config에서 로드)
# ─────────────────────────────────────────────
baseline_gen = get_baseline_monthly_generation()       # 발생량 기준 (경쟁)
baseline_inc = get_baseline_monthly_incineration()     # 소각량 기준 (에너지)
inc_fraction = get_incineration_fraction()             # 자치구별 소각 비율

all_districts = [d for dlist in CLUSTERS.values() for d in dlist]

def _make_sim_data(seed: int, noise: float) -> dict:
    rng = random.Random(seed)
    return {
        d: round(baseline_gen[d] * (1.0 + rng.uniform(-noise/100, noise/100)), 1)
        for d in all_districts
    }

if 'current_data' not in st.session_state or st.session_state.get('data_generated'):
    seed = st.session_state.get('sim_seed', 42)
    st.session_state['current_data'] = _make_sim_data(seed, noise_pct)
    st.session_state['data_generated'] = False

# ─────────────────────────────────────────────
# 탭 레이아웃
# ─────────────────────────────────────────────
tab_input, tab_result, tab_energy, tab_compare, tab_archive = st.tabs([
    "📋 데이터 입력", "📊 분배 결과", "⚡ 에너지 & 보조금", "🔬 점수 방식 비교", "📁 아카이브"
])


# ══════════════════════════════════════════════
# TAB 1 : 데이터 입력
# ══════════════════════════════════════════════
with tab_input:
    st.subheader(f"📋 {year_month} 자치구별 생활계폐기물 발생량 (톤/월)")
    st.info(
        "**발생량** 열을 수정하거나 사이드바의 🎲 버튼으로 시뮬레이션 데이터를 생성하세요.\n\n"
        "기준배출량 = 2024년 연간 발생량 ÷ 12 | 소각량은 자동으로 '2024년 소각 비율' 적용"
    )

    edited_data: dict[str, float] = {}
    for cluster, members in CLUSTERS.items():
        st.markdown(f"#### 🏭 {cluster} 클러스터")
        rows = []
        for d in members:
            frac = inc_fraction.get(d, 0)
            base = baseline_gen[d]
            curr = st.session_state['current_data'].get(d, round(base, 1))
            rows.append({
                '자치구': d,
                '기준 발생량': round(base, 1),
                '현재 발생량': curr,
                '소각 비율 (%)': round(frac * 100, 1),
                '기준 소각량': round(baseline_inc[d], 1),
                '추정 현재 소각량': round(curr * frac, 1),
            })
        df_in = pd.DataFrame(rows).set_index('자치구')
        edited = st.data_editor(
            df_in,
            column_config={
                '기준 발생량':        st.column_config.NumberColumn(disabled=True, format="%.1f"),
                '현재 발생량':        st.column_config.NumberColumn(min_value=0.0, format="%.1f"),
                '소각 비율 (%)':      st.column_config.NumberColumn(disabled=True, format="%.1f"),
                '기준 소각량':        st.column_config.NumberColumn(disabled=True, format="%.1f"),
                '추정 현재 소각량':   st.column_config.NumberColumn(disabled=True, format="%.1f"),
            },
            use_container_width=True,
            key=f"editor_{cluster}",
        )
        for d in members:
            edited_data[d] = float(edited.loc[d, '현재 발생량'])

    st.session_state['current_data'] = edited_data

    if st.button("✅ 분배 계산하기", type="primary", use_container_width=True):
        st.session_state['calc_done'] = True
        st.session_state['calc_ym'] = year_month
        st.session_state['calc_score_mode'] = score_mode
        st.session_state['calc_alpha'] = alpha


# ══════════════════════════════════════════════
# 계산 실행
# ══════════════════════════════════════════════
def run_calculation(current_data: dict, sm: str, a: float) -> list[dict]:
    results = []
    for cluster, members in CLUSTERS.items():
        dondt = run_cluster_allocation(
            cluster_name=cluster,
            cluster_districts=members,
            current_emissions=current_data,
            baseline_emissions=baseline_gen,
            k_override=k_manual,
            score_mode=sm,
            alpha=a,
        )
        energy = calc_energy_and_subsidy(
            cluster_districts=members,
            current_generation=current_data,
            baseline_generation_monthly=baseline_gen,
            baseline_incineration_monthly=baseline_inc,
            incineration_fraction=inc_fraction,
            energy_per_ton=energy_per_ton,
            price_krw_per_kwh=price_per_kwh,
        )
        da = calc_district_allocation(dondt['allocation_units'], dondt['k'], energy)
        results.append({'cluster': cluster, 'dondt': dondt, 'energy': energy, 'district_alloc': da})
    return results

if st.session_state.get('calc_done'):
    sm = st.session_state.get('calc_score_mode', '선형 (평행이동)')
    a  = st.session_state.get('calc_alpha', 0.1)
    st.session_state['results'] = run_calculation(st.session_state['current_data'], sm, a)


# ══════════════════════════════════════════════
# TAB 2 : 분배 결과
# ══════════════════════════════════════════════
with tab_result:
    if not st.session_state.get('results'):
        st.info("데이터 입력 탭에서 '분배 계산하기' 버튼을 클릭하세요.")
    else:
        results = st.session_state['results']
        ym = st.session_state.get('calc_ym', '')
        sm = st.session_state.get('calc_score_mode', '')

        st.subheader(f"📊 {ym} 분배 결과  |  점수 방식: {sm}")

        # 요약 카드
        total_base = sum(baseline_gen[d] for d in all_districts)
        total_curr = sum(st.session_state['current_data'].get(d, 0) for d in all_districts)
        avg_reduction = (1 - total_curr / total_base) * 100 if total_base > 0 else 0
        total_subsidy = sum(r['energy']['subsidy_krw'] for r in results)
        total_energy  = sum(r['energy']['distributable_energy_mwh'] for r in results)
        total_shortfall = sum(r['energy']['shortfall_mwh'] for r in results)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("전체 평균 감축률", f"{avg_reduction:.2f}%")
        c2.metric("총 분배 에너지 (기준)", f"{total_energy:,.0f} MWh")
        c3.metric("보조금 (소각 부족분)", f"{total_shortfall:,.0f} MWh 상당",
                  delta=f"= {total_subsidy/1e8:.2f}억원")
        c4.metric("클러스터 수", "4개")

        st.divider()

        # 클러스터 선택 상세
        sel_cluster = st.selectbox(
            "클러스터 상세 보기",
            list(CLUSTERS.keys()),
            format_func=lambda c: f"🏭 {c} ({', '.join(CLUSTERS[c][:2])}...)"
        )
        cr = next(r for r in results if r['cluster'] == sel_cluster)
        dondt_r = cr['dondt']
        da = cr['district_alloc']
        members = CLUSTERS[sel_cluster]

        col_l, col_r = st.columns(2)
        with col_l:
            scores = dondt_r['scores']
            raw_rates = dondt_r['reduction_rates']
            sorted_d = sorted(members, key=lambda d: scores[d], reverse=True)
            shift_txt = (f" | 평행이동 +{dondt_r['shift']:.1f}%p"
                         if dondt_r['shift'] > 0 and sm == '선형 (평행이동)' else "")
            st.markdown(f"**점수 (k={dondt_r['k']}){shift_txt}**")
            fig = go.Figure(go.Bar(
                x=[scores[d] for d in sorted_d], y=sorted_d,
                orientation='h',
                marker_color=CLUSTER_COLORS[sel_cluster],
                text=[f"{scores[d]:.3f} (감축률 {raw_rates[d]:+.1f}%)" for d in sorted_d],
                textposition='outside',
            ))
            fig.update_layout(height=320, margin=dict(l=0,r=140,t=10,b=10),
                              xaxis_title="점수", yaxis_title="", showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

        with col_r:
            sorted_d2 = sorted(members, key=lambda d: da[d]['units'], reverse=True)
            st.markdown("**배분 단위 및 에너지 할당량**")
            fig2 = go.Figure(go.Bar(
                x=[da[d]['total_mwh'] for d in sorted_d2], y=sorted_d2,
                orientation='h',
                marker_color=CLUSTER_COLORS[sel_cluster],
                text=[f"{da[d]['units']}단위 / {da[d]['total_mwh']:,.0f} MWh" for d in sorted_d2],
                textposition='outside',
            ))
            fig2.update_layout(height=320, margin=dict(l=0,r=130,t=10,b=10),
                               xaxis_title="에너지 할당 (MWh)", yaxis_title="", showlegend=False)
            st.plotly_chart(fig2, use_container_width=True)

        # 상세 테이블
        rows = []
        for d in members:
            rows.append({
                '자치구': d,
                '발생량 기준 (톤)': round(baseline_gen[d], 1),
                '발생량 현재 (톤)': round(dondt_r['current_emissions'][d], 1),
                '감축률 (%)': round(raw_rates[d], 2),
                '점수': round(scores[d], 4),
                '배분 단위': da[d]['units'],
                '에너지 (MWh)': round(da[d]['energy_mwh'], 1),
                '보조금 (만원)': round(da[d]['subsidy_krw'] / 1e4, 0),
                '합계 MWh': round(da[d]['total_mwh'], 1),
            })
        st.dataframe(pd.DataFrame(rows).set_index('자치구'), use_container_width=True)

        # 클러스터 요약
        st.divider()
        st.markdown("**클러스터별 요약**")
        crow = []
        for r in results:
            e = r['energy']
            crow.append({
                '클러스터': r['cluster'],
                '기준 소각량 (톤)': round(e['baseline_incineration_tons'], 0),
                '현재 소각량 (톤)': round(e['current_incineration_tons'], 0),
                '기준 에너지 (MWh)': round(e['baseline_energy_mwh'], 0),
                '실제 에너지 (MWh)': round(e['actual_energy_mwh'], 0),
                '보조금 (억원)': round(e['subsidy_krw'] / 1e8, 3),
                'k값': r['dondt']['k'],
            })
        st.dataframe(pd.DataFrame(crow).set_index('클러스터'), use_container_width=True)

        st.divider()
        if st.button("💾 결과 아카이브에 저장", type="secondary"):
            archive.save_results(ym, results)
            st.success(f"✅ {ym} 결과가 저장되었습니다.")


# ══════════════════════════════════════════════
# TAB 3 : 에너지 & 보조금
# ══════════════════════════════════════════════
with tab_energy:
    if not st.session_state.get('results'):
        st.info("데이터 입력 탭에서 '분배 계산하기' 버튼을 클릭하세요.")
    else:
        results = st.session_state['results']
        st.subheader("⚡ 소각량 기반 에너지 & 보조금")

        # 소각량 vs 에너지 비교
        clusters_nm = [r['cluster'] for r in results]
        fig_e = go.Figure()
        fig_e.add_trace(go.Bar(
            name='실제 에너지 (소각량×0.35)', x=clusters_nm,
            y=[r['energy']['actual_energy_mwh'] for r in results],
            marker_color='#4C9BE8',
            text=[f"{r['energy']['actual_energy_mwh']:,.0f}" for r in results],
            textposition='inside',
        ))
        fig_e.add_trace(go.Bar(
            name='보조금 보전분 (MWh 환산)', x=clusters_nm,
            y=[r['energy']['shortfall_mwh'] for r in results],
            marker_color='#E8834C',
            text=[f"{r['energy']['shortfall_mwh']:,.0f}" for r in results],
            textposition='inside',
        ))
        fig_e.update_layout(
            barmode='stack', title="클러스터별 실제 에너지 + 보조금 vs 기준 에너지",
            yaxis_title="MWh", height=380,
        )
        # 기준 에너지 선
        for i, r in enumerate(results):
            fig_e.add_shape(
                type='line', x0=i-0.4, x1=i+0.4,
                y0=r['energy']['baseline_energy_mwh'],
                y1=r['energy']['baseline_energy_mwh'],
                line=dict(color='white', width=2, dash='dash'),
            )
        st.plotly_chart(fig_e, use_container_width=True)
        st.caption("점선 = 기준 에너지 (항상 이 값으로 배분 고정)")

        # 에너지/보조금 구성 파이
        cols = st.columns(len(results))
        for i, r in enumerate(results):
            with cols[i]:
                e = r['energy']
                fig_p = go.Figure(go.Pie(
                    labels=['실 에너지', '보조금'],
                    values=[e['energy_fraction']*100, e['subsidy_fraction']*100],
                    marker_colors=['#4C9BE8', '#E8834C'],
                    textinfo='label+percent', hole=0.4,
                ))
                fig_p.update_layout(
                    title=f"{r['cluster']}",
                    height=230, margin=dict(l=5,r=5,t=35,b=5), showlegend=False,
                )
                st.plotly_chart(fig_p, use_container_width=True)

        # 소각 비율 현황 (기준연도 기준)
        st.subheader("2024년 자치구별 소각 비율 (발생량 대비)")
        ratio_rows = []
        for cluster, members in CLUSTERS.items():
            for d in members:
                ratio_rows.append({
                    '클러스터': cluster,
                    '자치구': d,
                    '발생량 (톤/년)': BASELINE_2024_GENERATION[d],
                    '소각량 (톤/년)': BASELINE_2024_INCINERATION[d],
                    '소각 비율 (%)': round(inc_fraction[d]*100, 1),
                    '월 기준 에너지 (MWh)': round(baseline_inc[d] * energy_per_ton, 0),
                })
        df_ratio = pd.DataFrame(ratio_rows)
        fig_ratio = px.bar(
            df_ratio, x='자치구', y='소각 비율 (%)', color='클러스터',
            color_discrete_map=CLUSTER_COLORS,
            title="자치구별 소각 비율 (낮을수록 재활용/매립 비중 큼)",
            height=380,
        )
        fig_ratio.update_layout(xaxis_tickangle=-45)
        st.plotly_chart(fig_ratio, use_container_width=True)
        st.caption(
            "강서구(590,910톤)는 발생량이 크지만 소각 비율은 약 8.5% → 에너지 기여도가 발생량 대비 낮음.\n"
            "금천구는 소각 비율 10.9%로 매립 비중이 높음 (직매립금지 법 시행 후 변화 예상)."
        )

        # 상세 보조금 테이블
        st.subheader("자치구별 최종 할당 상세")
        all_rows = []
        for r in results:
            for d, info in r['district_alloc'].items():
                all_rows.append({
                    '클러스터': r['cluster'], '자치구': d,
                    '배분 단위': info['units'],
                    '에너지 (MWh)': round(info['energy_mwh'], 1),
                    '보조금 상당 (MWh)': round(info['subsidy_mwh_equiv'], 1),
                    '보조금 (만원)': round(info['subsidy_krw']/1e4, 0),
                    '합계 (MWh)': round(info['total_mwh'], 1),
                })
        st.dataframe(pd.DataFrame(all_rows), use_container_width=True, hide_index=True)

        total_subsidy_krw = sum(r['energy']['subsidy_krw'] for r in results)
        st.info(
            f"💡 **총 보조금 규모: {total_subsidy_krw/1e8:.2f}억원** (소각량 감소분 전기 환산)\n\n"
            "보조금 재원 논리: 폐기물 감축 시 서울시의 관외 민간 소각 위탁비·매립비·운송비가 절감되므로, "
            "그 절감분으로 보조금을 충당하는 자기충족적 구조. **용도: 전기 공급에만 한정.**"
        )


# ══════════════════════════════════════════════
# TAB 4 : 점수 방식 비교
# ══════════════════════════════════════════════
with tab_compare:
    st.subheader("🔬 선형 vs 지수함수 점수 방식 비교")
    st.markdown("""
    | 항목 | 선형 (평행이동) | 지수함수 exp(α·r) |
    |------|---------------|-------------------|
    | 꼴찌 자치구 | **0점 → 배분 없음** | 낮은 양수점수 → 소량 배분 |
    | 음수 감축률 처리 | 전체 평행이동 (왜곡 가능) | **자동 처리 (왜곡 없음)** |
    | 쏠림 강도 | 선형 비례 | **α에 따라 지수적 증가** |
    | 추가 감축 유인 | 중간 수준 | α 크면 매우 강함 |
    | 정치적 수용성 | 직관적 | 설명 필요 |
    | α 튜닝 필요 | 불필요 | **필요** |
    """)

    st.divider()

    if not st.session_state.get('current_data'):
        st.info("먼저 데이터 입력 탭에서 계산을 실행하세요.")
    else:
        comp_cluster = st.selectbox("비교할 클러스터", list(CLUSTERS.keys()), key="comp_cluster")
        comp_alpha = st.slider("비교용 α값", 0.01, 0.50, 0.10, 0.01, key="comp_alpha")

        members = CLUSTERS[comp_cluster]
        current = st.session_state['current_data']

        # 두 방식 계산
        r_linear = run_cluster_allocation(
            comp_cluster, members, current, baseline_gen,
            k_override=k_manual, score_mode='선형 (평행이동)',
        )
        r_exp = run_cluster_allocation(
            comp_cluster, members, current, baseline_gen,
            k_override=k_manual, score_mode='지수함수 (exp)', alpha=comp_alpha,
        )

        col1, col2 = st.columns(2)

        def make_comparison_chart(result, title, color):
            members_sorted = sorted(members, key=lambda d: result['allocation_units'][d], reverse=True)
            rates = result['reduction_rates']
            scores = result['scores']
            units = result['allocation_units']
            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=[units[d] for d in members_sorted],
                y=members_sorted,
                orientation='h',
                marker_color=color,
                text=[f"{units[d]}단위 | 점수:{scores[d]:.3f} | 감축률:{rates[d]:+.1f}%"
                      for d in members_sorted],
                textposition='outside',
            ))
            fig.update_layout(
                title=title, height=350,
                margin=dict(l=0,r=200,t=40,b=10),
                xaxis_title="배분 단위", showlegend=False,
            )
            return fig

        with col1:
            st.plotly_chart(
                make_comparison_chart(r_linear, f"선형 (k={r_linear['k']})", '#4C9BE8'),
                use_container_width=True
            )
            if r_linear['shift'] > 0:
                st.caption(f"⚠️ 음수 감축률 발생 → 전체 +{r_linear['shift']:.1f}%p 평행이동 적용")

        with col2:
            st.plotly_chart(
                make_comparison_chart(r_exp, f"지수함수 α={comp_alpha} (k={r_exp['k']})", '#E84CA0'),
                use_container_width=True
            )

        # 쏠림 효과 수치 비교
        st.divider()
        st.markdown("**쏠림 효과 수치 비교**")
        comp_rows = []
        for d in members:
            u_lin = r_linear['allocation_units'][d]
            u_exp = r_exp['allocation_units'][d]
            k_lin = r_linear['k']
            k_exp = r_exp['k']
            comp_rows.append({
                '자치구': d,
                '감축률 (%)': round(r_linear['reduction_rates'][d], 2),
                '선형 점수': round(r_linear['scores'][d], 4),
                '선형 배분 단위': u_lin,
                '선형 배분 비율 (%)': round(u_lin/k_lin*100, 1) if k_lin else 0,
                f'exp(α={comp_alpha}) 점수': round(r_exp['scores'][d], 4),
                '지수 배분 단위': u_exp,
                '지수 배분 비율 (%)': round(u_exp/k_exp*100, 1) if k_exp else 0,
            })
        st.dataframe(pd.DataFrame(comp_rows).set_index('자치구'), use_container_width=True)

        # α에 따른 배분 비율 변화 시뮬레이션
        st.divider()
        st.markdown("**α값에 따른 배분 비율 변화 (최고 vs 최저 감축 자치구)**")
        alphas = [0.02, 0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50]
        rates_sorted = sorted(members, key=lambda d: r_linear['reduction_rates'][d])
        d_best = rates_sorted[-1]
        d_worst = rates_sorted[0]

        best_ratios, worst_ratios = [], []
        for a in alphas:
            r_a = run_cluster_allocation(comp_cluster, members, current, baseline_gen,
                                         k_override=k_manual, score_mode='지수함수 (exp)', alpha=a)
            k_a = r_a['k']
            best_ratios.append(r_a['allocation_units'][d_best] / k_a * 100 if k_a else 0)
            worst_ratios.append(r_a['allocation_units'][d_worst] / k_a * 100 if k_a else 0)

        fig_alpha = go.Figure()
        fig_alpha.add_trace(go.Scatter(
            x=alphas, y=best_ratios, mode='lines+markers',
            name=f'최고 감축 ({d_best})', line=dict(color='#4CE87A'),
        ))
        fig_alpha.add_trace(go.Scatter(
            x=alphas, y=worst_ratios, mode='lines+markers',
            name=f'최저 감축 ({d_worst})', line=dict(color='#E84CA0'),
        ))
        fig_alpha.add_vline(x=comp_alpha, line_dash='dash', line_color='white',
                            annotation_text=f"현재 α={comp_alpha}")
        fig_alpha.update_layout(
            title="α값과 배분 비율의 관계",
            xaxis_title="α (알파)", yaxis_title="배분 비율 (%)",
            height=350,
        )
        st.plotly_chart(fig_alpha, use_container_width=True)
        st.caption(
            "α가 커질수록 상위권에게 자원이 집중되는 쏠림 효과가 강해집니다. "
            "α → 0이면 균등 배분에 수렴. 논문이 우려한 '지나치게 강한 쏠림'은 α > 0.2 이상에서 나타납니다."
        )


# ══════════════════════════════════════════════
# TAB 5 : 아카이브
# ══════════════════════════════════════════════
with tab_archive:
    st.subheader("📁 저장된 분석 이력")
    months = archive.list_months()
    st.caption(
        "⚠️ Streamlit Community Cloud 환경에서는 앱 재시작 시 아카이브가 초기화됩니다. "
        "중요한 데이터는 CSV 다운로드로 보관하세요."
    )
    if not months:
        st.info("아직 저장된 데이터가 없습니다. 분배 결과 탭에서 '결과 저장' 버튼을 누르세요.")
    else:
        df_all = archive.load_all()

        trend = (
            df_all.groupby('year_month')
            .agg(
                avg_reduction=('reduction_rate', 'mean'),
                total_subsidy_億=('cluster_subsidy_krw', lambda x: x.unique().sum() / 1e8)
            ).reset_index()
        )

        fig_t = make_subplots(specs=[[{"secondary_y": True}]])
        fig_t.add_trace(
            go.Scatter(x=trend['year_month'], y=trend['avg_reduction'],
                       mode='lines+markers', name='평균 감축률 (%)', line=dict(color='#4CE87A')),
            secondary_y=False,
        )
        fig_t.add_trace(
            go.Bar(x=trend['year_month'], y=trend['total_subsidy_億'],
                   name='총 보조금 (억원)', marker_color='#E8834C', opacity=0.5),
            secondary_y=True,
        )
        fig_t.update_yaxes(title_text="감축률 (%)", secondary_y=False)
        fig_t.update_yaxes(title_text="보조금 (억원)", secondary_y=True)
        fig_t.update_layout(title="월별 추이", height=380)
        st.plotly_chart(fig_t, use_container_width=True)

        cl_trend = (
            df_all.groupby(['year_month', 'cluster'])['reduction_rate']
            .mean().reset_index()
        )
        fig_cl = px.line(
            cl_trend, x='year_month', y='reduction_rate', color='cluster',
            markers=True, color_discrete_map=CLUSTER_COLORS,
            labels={'reduction_rate': '감축률 (%)', 'year_month': '월'},
            title="클러스터별 평균 감축률",
            height=350,
        )
        st.plotly_chart(fig_cl, use_container_width=True)

        st.markdown("**월별 데이터 조회**")
        view_month = st.selectbox("조회 월", months, key='view_month')
        df_v = archive.load_month(view_month)
        show_cols = ['cluster','district','baseline_monthly_tons','current_monthly_tons',
                     'reduction_rate','k','units','total_mwh','subsidy_krw','saved_at']
        st.dataframe(df_v[show_cols], use_container_width=True, hide_index=True)

        csv = df_all.to_csv(index=False)
        st.download_button(
            "⬇️ 전체 아카이브 CSV 다운로드",
            data=csv.encode('utf-8-sig'),
            file_name="waste_allocation_archive.csv",
            mime="text/csv",
        )
