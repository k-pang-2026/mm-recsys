"""Read-only four-tab experiment dashboard; inference uses HTTP only."""
from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dashboard.data import api_call, available_reports, ct_log, read_report, settings, search_payload

COLORS = dict(primary='#2563eb', baseline='#94a3b8', treatment='#0f766e', target='#e35d42')
LABELS = dict(mrr='MRR', ndcg_at_10='NDCG@10', recall_at_300='Recall@300', auc='CTR AUC',
    hit_rate_at_50='HitRate@50', ndcg_at_50='NDCG@50', coverage='Coverage',
    search_p95_ms='검색 HTTP p95 (ms)', recommend_p95_ms='추천 HTTP p95 (ms)',
    candidate_p95_ms='후보 p95 (ms)', feature_p95_ms='Redis p95 (ms)')


def metric_table(report: dict, names: tuple[str, ...]) -> pd.DataFrame:
    return pd.DataFrame([dict(지표=LABELS.get(row['name'], row['name']), 측정값=row['value'],
        기준=row['target'], 판정=row['status'], 평가구간=row['split'])
        for row in report.get('metrics', []) if row['name'] in names])


def layout(fig: go.Figure, title: str, y: str) -> go.Figure:
    fig.update_layout(title=title, template='plotly_white', font=dict(color='#334155'), yaxis_title=y,
        margin=dict(l=10, r=20, t=65, b=10), height=340, legend=dict(orientation='h', y=-.2),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    return fig


def search_tab(report: dict, config: dict) -> None:
    search = report.get('search', {})
    st.subheader('같은 쿼리로 비교한 검색 품질')
    if search.get('status') == 'MEASURED':
        key = st.radio('검색 지표', ['mrr', 'ndcg_at_10'], format_func=lambda x: LABELS[x], horizontal=True, key='search_metric')
        modes, labels = ('text', 'image', 'hybrid'), ['텍스트', '이미지', '하이브리드']
        fig = go.Figure()
        fig.add_bar(name='CLIP', x=labels, y=[search['per_mode'][mode][key] for mode in modes], marker_color=COLORS['primary'])
        fig.add_bar(name='BM25', x=labels, y=[search['bm25'][mode].get(key) for mode in modes], marker_color=COLORS['baseline'])
        target = next(row['target'] for row in report['metrics'] if row['name'] == key)
        fig.add_hline(y=target, line_dash='dash', line_color=COLORS['target'], annotation_text=f'기준 {target}')
        st.plotly_chart(layout(fig, 'CLIP · BM25', LABELS[key]), use_container_width=True)
        st.caption('이미지 전용 입력에는 BM25가 적용되지 않습니다. ANN/exact 벡터 일치율은 relevance 품질과 별개입니다.')
        st.dataframe(metric_table(report, ('mrr', 'ndcg_at_10')), hide_index=True, use_container_width=True)
        rows = search.get('tradeoff', [])
        if rows:
            fig = go.Figure()
            for i, mode in enumerate(modes):
                values = [row for row in rows if row['mode'] == mode]
                fig.add_scatter(name=labels[i], x=[row['vector_p95_ms'] for row in values],
                    y=[row[key] for row in values], mode='lines+markers+text',
                    text=[f'{row["parameter"]}={row["requested_value"]}' for row in values], textposition='top center')
            st.plotly_chart(layout(fig, 'ANN 설정과 품질·속도', LABELS[key]).update_xaxes(title='벡터 검색 p95 (ms)'), use_container_width=True)
            st.caption('valid 진단입니다. 인코딩·HTTP 시간을 제외하며 API 지연 판정에 사용하지 않습니다.')
        else:
            st.info('test 결과에서는 설정 탐색을 실행하지 않습니다.')
    else:
        st.info('검색 품질이 아직 측정되지 않았습니다.')
    st.divider()
    st.subheader('검색 데모')
    with st.form('search_demo'):
        text = st.text_input('검색어', placeholder='예: black shirt', key='query_text')
        image = st.file_uploader('이미지 · 선택', type=['png', 'jpg', 'jpeg'], key='query_image')
        count = st.number_input('검색 결과 수', 1, 100, 10, key='search_top_k')
        submit = st.form_submit_button('검색 실행')
    if submit:
        try:
            payload = search_payload(text, image.getvalue() if image is not None else None, int(count))
        except ValueError as error:
            st.warning(str(error))
            return
        response = api_call(config['api_url'], 'POST', '/api/search', payload=payload, timeout=config['api_timeout'])
        if response['ok']:
            body = response['data']
            st.caption(f'{body["search_type"]} · {body["latency_ms"]:.2f}ms · 후보 {body["total_count"]:,}개')
            st.dataframe(pd.DataFrame(body['results']), hide_index=True, use_container_width=True)
        else:
            st.warning(response['error'])


def recommendation_tab(report: dict, config: dict) -> None:
    rec = report.get('recommendation', {})
    st.subheader('미래 행동에 대한 추천 품질')
    st.dataframe(metric_table(report, ('recall_at_300', 'auc', 'hit_rate_at_50', 'ndcg_at_50', 'coverage')), hide_index=True, use_container_width=True)
    if rec.get('status') == 'MEASURED':
        cohort = rec['cohort']
        st.caption(f'고정 사용자 {cohort["total_users"]:,}명 · 정답 사용자 {cohort["truth_users"]:,}명 · 콜드스타트 {cohort.get("cold", 0):,}명 · top50')
        key = st.radio('추천 비교 지표', ['hit_rate_at_50', 'ndcg_at_50', 'coverage'], format_func=lambda x: LABELS[x], horizontal=True, key='recommend_metric')
        labels = dict(train_popularity='인기순', two_tower='Two Tower', deepfm='DeepFM', full_pipeline='전체 파이프라인')
        fig = go.Figure(go.Bar(x=list(labels.values()), y=[rec['metrics'][name][key] for name in labels],
            marker_color=[COLORS['baseline'], '#64748b', COLORS['primary'], COLORS['treatment']]))
        target = next(row['target'] for row in report['metrics'] if row['name'] == key)
        fig.add_hline(y=target, line_dash='dash', line_color=COLORS['target'], annotation_text=f'기준 {target}')
        st.plotly_chart(layout(fig, '동일 사용자·정답·카탈로그 기준', LABELS[key]), use_container_width=True)
        cvr = rec['classification']['cvr']
        if cvr['auc'] is None:
            st.info(f'CVR AUC 미정의: {cvr["auc_status"]} · 클릭 노출 {cvr["samples"]:,}개, 구매 양성 {cvr["positives"]:,}개')
    else:
        st.info('추천 평가가 아직 없습니다.')
    st.divider()
    st.subheader('사용자 추천 데모')
    with st.form('recommend_demo'):
        uid = st.text_input('사용자 ID', value='U000001', key='user_id')
        count = st.number_input('추천 결과 수', 1, 100, 10, key='recommend_top_n')
        submit = st.form_submit_button('추천 실행')
    if submit:
        if not uid.strip():
            st.warning('사용자 ID를 입력하세요.')
            return
        response = api_call(config['api_url'], 'GET', '/api/recommend', params=dict(user_id=uid.strip(), top_n=int(count)), timeout=config['api_timeout'])
        if response['ok']:
            body = response['data']
            st.dataframe(pd.DataFrame(body['recommendations']), hide_index=True, use_container_width=True)
            st.caption(f'파이프라인 {body["pipeline_latency"]["total_ms"]:.2f}ms · 세션 관심사 {body["session_context"]["session_interest"] or "없음"}')
        else:
            st.warning(response['error'])


def ab_tab(report: dict) -> None:
    ab = report.get('ab', {})
    st.subheader('사용자 단위 A/B 실험')
    if ab.get('status') != 'MEASURED':
        st.info(ab.get('reason', 'A/B 실험 결과가 없습니다.'))
        return
    control, treatment = ab['arms']['control'], ab['arms']['treatment']
    st.caption(f'합성 실험 · {control["users"]:,}명/군 · {ab["days"]}일 · 사용자별 적응 학습 상태 분리')
    inference = ab['inference']['cvr']
    a, b, c = st.columns(3)
    a.metric('Control CVR', f'{control["cvr"]:.4%}' if control['cvr'] is not None else '미측정')
    b.metric('Treatment CVR', f'{treatment["cvr"]:.4%}' if treatment['cvr'] is not None else '미측정')
    lift = inference.get('relative_lift')
    c.metric('CVR 상대 lift', f'{lift:+.2%}' if lift is not None else '정의되지 않음')
    st.caption('CTR = 클릭/노출 · CVR = 구매/노출. control이 0이면 상대 lift는 정의되지 않습니다.')
    fig = go.Figure()
    for name, values, color in [('Control', control, COLORS['baseline']), ('Treatment', treatment, COLORS['treatment'])]:
        fig.add_bar(name=name, x=['CTR', 'CVR', '탐색 슬롯 비율'], y=[values['ctr'], values['cvr'], values['exploration_rate']], marker_color=color)
    st.plotly_chart(layout(fig, '관측 비율', '비율').update_yaxes(tickformat='.0%'), use_container_width=True)
    ci = inference.get('difference_ci95')
    if ci is not None:
        st.write(f'사용자 cluster CVR 차이 95% CI: [{ci[0] * 100:+.4f}, {ci[1] * 100:+.4f}]%p')
        p = inference.get('z_p_value')
        st.write(f'양측 cluster Z p-value: {p:.6g}' if p is not None else '퇴화된 분산으로 cluster p-value를 계산할 수 없습니다.')
    risks = ab['inference']['independent_user_risks']
    st.dataframe(pd.DataFrame([dict(지표=label, Control=risks[name]['control'], Treatment=risks[name]['treatment'],
        양측_Z_p=risks[name]['z_p_value'], 카이제곱_p=risks[name]['chi_square_p_value'], 저빈도=risks[name]['low_expected_counts'])
        for name, label in [('any_click', '한 번 이상 클릭한 사용자'), ('any_purchase', '한 번 이상 구매한 사용자')]]), hide_index=True, use_container_width=True)
    st.caption('반복 노출을 독립 표본으로 세지 않습니다. 양의 lift나 유의성은 보장되지 않으며 실제 서비스 효과로 해석할 수 없습니다.')


def system_tab(report: dict, config: dict) -> None:
    st.subheader('서비스와 측정 환경')
    st.caption('실시간 상태와 저장된 성능 측정은 서로 다른 시점의 결과입니다.')
    health = api_call(config['api_url'], 'GET', '/health', timeout=min(config['api_timeout'], 2))
    ready = api_call(config['api_url'], 'GET', '/ready', timeout=min(config['api_timeout'], 2))
    a, b, c = st.columns(3)
    a.metric('API 연결', '정상' if health['ok'] else '연결 안 됨')
    b.metric('모델 준비', '준비됨' if ready['ok'] else '준비 안 됨')
    live_version = health['data'].get('model_version') if health['ok'] else None
    c.metric('현재 모델 버전', live_version or '미측정')
    st.caption(f"저장된 성능 측정의 모델 버전: {report.get('model_version', '미측정')}")
    if not health['ok']:
        st.info(health['error'])
    st.dataframe(metric_table(report, ('search_p95_ms', 'recommend_p95_ms', 'candidate_p95_ms', 'feature_p95_ms')), hide_index=True, use_container_width=True)
    rows = [row for row in report.get('metrics', []) if row['name'].endswith('_ms') and row['value'] is not None]
    if rows:
        fig = go.Figure(go.Bar(x=[LABELS[row['name']] for row in rows], y=[row['value'] for row in rows], marker_color=COLORS['primary']))
        fig.add_scatter(name='각 지표 기준', x=[LABELS[row['name']] for row in rows], y=[row['target'] for row in rows], mode='markers', marker=dict(symbol='line-ew', size=25, color=COLORS['target']))
        st.plotly_chart(layout(fig, 'p95와 기준', 'ms'), use_container_width=True)
    st.subheader('CT 기록')
    ct = report.get('integration', {}).get('ct')
    if ct:
        st.info(f'full 재학습 {ct["retraining"]} · 교체·복구 검사 {ct["lifecycle"]} · 신규 관측 {ct["observed_new_events"]:,}건')
        st.caption('별도 full 배포의 통합 검증 결과입니다. 현재 API 모델은 위 실시간 상태를 따릅니다.')
    logs = ct_log(config['results_dir'])
    if logs['rows']:
        if any(row.get('scope') == 'controlled_fixture' for row in logs['rows']):
            st.caption('controlled_fixture 기록은 소규모 기능 검증이며 실제 서비스 품질을 뜻하지 않습니다.')
        st.dataframe(pd.json_normalize(logs['rows'], sep='.'), hide_index=True, use_container_width=True)
        if logs['invalid_lines']:
            st.warning(f'읽을 수 없는 로그 {logs["invalid_lines"]}개를 제외했습니다.')
    else:
        st.info(logs.get('reason', 'CT 실행 기록이 없습니다. CT 모니터 실행과 결과 경로를 확인하세요.'))
    with st.expander('측정 근거와 제한'):
        st.json(dict(environment=report.get('environment', {}), identity=report.get('identity', {}), limitations=report.get('limitations', [])))


def main() -> None:
    st.set_page_config(page_title='검색·추천 평가실', page_icon='◈', layout='wide')
    st.markdown('<style>.block-container{padding-top:2rem;max-width:1400px}h1{letter-spacing:-.04em}div[data-testid="stMetric"]{padding:1rem;border-radius:.75rem}</style>', unsafe_allow_html=True)
    st.title('검색·추천 평가실')
    st.caption('고정된 평가 기준으로 검색, 추천, 실험과 시스템 상태를 확인합니다.')
    config = settings(Path(__file__).resolve().parents[1])
    files = available_reports(config['results_dir'])
    report = {}
    with st.sidebar:
        st.subheader('평가 결과')
        if files:
            preferred = next((i for split in ('test', 'valid') for i, path in enumerate(files)
                              if path.name == f'evaluation_{config["scale"]}_{split}.json'), 0)
            path = st.selectbox('결과 파일', files, index=preferred, format_func=lambda p: p.name)
            try:
                report = read_report(path, config['results_dir'])
            except (OSError, ValueError, KeyError, TypeError) as error:
                st.error(f'결과를 읽을 수 없습니다: {error}')
        else:
            st.info('저장된 통합 평가 결과가 없습니다.')
        st.button('결과 새로고침')
        st.caption(f'API · {config["api_url"]}')
    if report:
        counts = report['data_counts']
        st.caption(f'{report["scale"].upper()} · {report["split"]} · 상품 {counts["products"]:,} · 사용자 {counts["users"]:,} · 이벤트 {counts["events"]:,}')
        a, b, c = st.columns(3)
        a.metric('측정 기준 판정', report['quality_status'])
        b.metric('측정 지표', f'{sum(row["value"] is not None for row in report["metrics"])}/{len(report["metrics"])}')
        c.metric('최종 종합 품질', report['acceptance'])
        if report.get('integration'):
            st.caption('full test와 필수 통합 검사 결과를 연결한 판정입니다. A/B의 양의 효과나 CT 모델 교체를 뜻하지 않습니다.')
            with st.expander('최종 통합 검사 근거'):
                st.json(report['integration'])
        st.caption('dev/valid 결과는 full test 최종 통과를 뜻하지 않습니다. 기준 미달과 미측정은 그대로 표시합니다.')
    else:
        st.info('통합 평가를 실행하면 측정값이 표시됩니다. 데모는 실행 중인 API에 연결합니다.')
    tabs = st.tabs(['검색', '추천', 'A/B 실험', '시스템'])
    with tabs[0]:
        search_tab(report, config)
    with tabs[1]:
        recommendation_tab(report, config)
    with tabs[2]:
        ab_tab(report)
    with tabs[3]:
        system_tab(report, config)


if __name__ == '__main__':
    main()
