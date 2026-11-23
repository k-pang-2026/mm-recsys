"""Data tab, product/CLIP lookup and product cards for the HTTP demos."""
from __future__ import annotations

from pathlib import Path
import statistics
import uuid

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.assets import catalog, clip_item, deployment, image_path
from dashboard.data import DEEPFASHION, REALISM, api_call, evidence, read_json
from dashboard.formatting import display_frame, display_value, korean
from dashboard.guide import html, split_bar
from dashboard.sections import section
from dashboard.style import GRAY, INDIGO, chart
from src.common.artifacts import file_hash
from src.search.text import display_text

ROOT = Path(__file__).resolve().parents[1]
PERSONAS = dict(bargain='가성비', brand_loyal='브랜드 충성', careful='신중형', impulsive='충동형', pragmatist='실용형', trendsetter='트렌드형')
CATEGORIES = dict(tops='상의', bottoms='하의', outerwear='아우터', footwear='신발', accessories='액세서리')
EVENTS = dict(view='조회', search='검색', cart='장바구니', purchase='구매')
SPLITS = dict(train='학습 (train)', valid='검증 (valid)', val='검증 (val)', test='시험 (test)')
REALISM_LABELS = dict(price_mae='가격 평균 오차', price_quantile_mae='가격 분위수 오차', category_tv='카테고리 분포 차이(TV)',
                      activity_top10_error='상위 10% 활동량 비중 오차', session_purchase_error='세션 구매율 오차',
                      session_length_error='세션 길이 오차', gap_error='행동 간격 오차', behavior_objective='행동 종합 목표')


def deployed(config: dict) -> dict | None:
    try:
        return deployment(config['results_dir'])
    except (OSError, ValueError, KeyError) as error:
        st.error(f'배포 데이터 확인 실패: {error}')
        return None


def product_cards(rows: list[dict], config: dict, key: str, user_id: str | None = None,
                  exposure: dict | None = None) -> None:
    active = deployed(config)
    if not active:
        st.info('상품 원천 데이터는 배포 준비 완료 후 표시됩니다.')
        return
    products = catalog(active['data_dir'], active['data_fingerprint'])
    for i, item in enumerate(rows):
        pid = item['product_id']
        if pid not in products.index:
            st.warning(f'{pid}: 현재 카탈로그에 없는 상품입니다.')
            continue
        row = products.loc[pid]
        with st.container(border=True):
            left, right = st.columns([1, 4])
            left.image(str(image_path(active, row)), width=120)
            right.write(f"**{display_text(row['name'])}** · {pid} · {row['price']:,.1f}원")
            right.caption(f"{display_text(row['category_l1'])} / {display_text(row['category_l2'])} / {display_text(row['category_l3'])} · {row['brand']} · {item.get('reason', '검색 결과')}")
            if user_id and right.button('이 상품 클릭 후 추천 비교', key=f'{key}_click_{i}_{pid}'):
                # Keep the same ID on retry until this action is acknowledged.
                event_key = f'{key}_event_{pid}'
                event_id = st.session_state.setdefault(event_key, uuid.uuid4().hex)
                params = dict(user_id=user_id, top_n=len(rows))
                # Attribute the click to the recommendations actually displayed.
                before = exposure or dict(ok=True, data=dict(recommendations=rows))
                payload = dict(event_id=event_id, user_id=user_id, product_id=pid,
                    category=row['category_l3'], event_type='view', session_id='dashboard-demo')
                result = api_call(config['api_url'], 'POST', '/api/event', payload=payload,
                                  request_id=before.get('request_id'), timeout=config['api_timeout'])
                if result['ok']:
                    after = api_call(config['api_url'], 'GET', '/api/recommend', params=params, timeout=config['api_timeout'])
                    st.session_state[f'{key}_comparison'] = dict(before=before, event=payload, response=result, after=after)
                    st.session_state.pop(event_key, None)
                else:
                    st.error(f"{result['error']} · event_id={event_id} · 같은 버튼으로 재시도하세요.")
    if f'{key}_comparison' in st.session_state:
        st.subheader('실제 클릭 전후 비교')
        comparison = st.session_state[f'{key}_comparison']
        if comparison['before']['ok'] and comparison['after']['ok']:
            st.success('클릭 전후 추천 API 응답을 모두 받았습니다.')
        else:
            st.error('클릭 전후 추천 조회가 실패했습니다. 아래 응답을 확인하세요.')
        st.json(display_value(comparison))


def hbar(labels: list[str], values: list[float], text: list[str], title: str, highlight: int | None, tickformat: str) -> go.Figure:
    colors = [INDIGO if highlight is None or i == highlight else GRAY for i in range(len(values))]
    fig = go.Figure(go.Bar(y=labels, x=values, orientation='h', marker_color=colors, text=text, textposition='outside'))
    chart(fig, title, 320).update_yaxes(autorange='reversed')
    fig.update_xaxes(tickformat=tickformat, range=[0, max(values) * 1.18 or 1])
    return fig


def with_table(column, fig: go.Figure, frame: pd.DataFrame) -> None:
    column.plotly_chart(fig, use_container_width=True)
    with column.expander('표로 보기'):
        st.dataframe(frame, hide_index=True, use_container_width=True)


def audit(bundle: dict | None) -> dict | None:
    return read_json(evidence(bundle, 'data_audit.json'), bundle['root']) if bundle else None


def data_tab(report: dict, bundle: dict | None, config: dict) -> None:
    found = audit(bundle)
    ratios = (found or {}).get('split_ratios', {})
    if found:
        counts = found.get('counts', {})
        split = '/'.join(f'{ratios[name]:.1%}' for name in ('train', 'valid', 'test') if name in ratios)
        st.markdown(f"**합성 데이터: 상품 {counts.get('products', 0):,} · 사용자 {counts.get('users', 0):,} · 이벤트 {counts.get('events', 0):,}"
                    f" · 노출 {counts.get('impressions', 0):,}, 시간순 {split} 분할**")
    section('데이터', 0)
    st.markdown('기록을 시간순으로 나눠, 과거로 학습하고 그 뒤에 실제로 일어난 행동을 맞히는지로 채점합니다.')
    html(split_bar(ratios))
    if found:
        audit_sections(found, config)
    else:
        st.info('이 결과 묶음에는 데이터 감사 결과(data_audit.json)가 없습니다. 외부 데이터 검증만 표시합니다.')
    external_section(config['published_dir'])


def audit_sections(audit: dict, config: dict) -> None:
    ratios = audit.get('split_ratios', {})
    boundaries, split_counts = audit.get('boundaries', {}), audit.get('split_counts', {})
    st.dataframe(pd.DataFrame([{'분할': SPLITS.get(name, name), '비율': f'{ratios.get(name, 0):.1%}', '이벤트': f'{split_counts.get(name, 0):,}',
                                '시작': display_value(row['start']), '끝': display_value(row['end'])} for name, row in boundaries.items()]),
                 hide_index=True, use_container_width=True)
    st.caption(f"seed={audit.get('seed')} · 생성기={audit.get('generator_version')} · 분석 시각={display_value(audit.get('generated_at'))}")
    personas = audit.get('personas', [])
    if personas:
        section('데이터', 1, f'유형 {len(personas)}개 · 설정값과 관측값')
        names = [PERSONAS.get(row['persona'], row['persona']) for row in personas]
        specs = [('buyer_rate', '구매 경험 사용자 비율', '.0%', lambda v: f'{v:.1%}'),
                 ('purchase_per_view', '조회당 구매', '.1%', lambda v: f'{v:.1%}'),
                 ('purchase_price_percentile_mean', '구매가 백분위 평균 (낮을수록 저렴)', '.2f', lambda v: f'{v:.3f}'),
                 ('top_brand_share_mean', '최다 브랜드 집중도', '.0%', lambda v: f'{v:.1%}')]
        for start in (0, 2):
            columns = st.columns(2)
            for column, (key, label, tick, shown) in zip(columns, specs[start:start + 2]):
                values = [row.get(key, 0) for row in personas]
                top = max(range(len(values)), key=values.__getitem__)
                with_table(column, hbar(names, values, [shown(v) for v in values], f'{label}: 가장 높은 유형 {names[top]}', top, tick),
                           pd.DataFrame({'유형': names, label: [shown(v) for v in values]}))
        users = ', '.join(f"{name} {row['users']:,}" for name, row in zip(names, personas))
        st.caption(f"분모: {audit.get('denominators', {}).get('price', '구매 이벤트 기준')} · 페르소나별 사용자 {users}")
        total = sum(row['users'] for row in personas) or 1
        st.markdown('**설정값과 관측값** (config의 페르소나 비율·가격 민감도·전환율)')
        st.dataframe(pd.DataFrame([{'유형': name, '코드 이름': row['persona'],
            '설정 비율': f"{row.get('configured', {}).get('ratio', 0):.1%}", '관측 비율': f"{row['users'] / total:.1%}",
            '설정 가격 민감도': f"{row.get('configured', {}).get('price_sensitivity', 0):.3f}",
            '설정 전환율': f"{row.get('configured', {}).get('cvr', 0):.1%}", '관측 조회당 구매': f"{row.get('purchase_per_view', 0):.1%}"}
            for name, row in zip(names, personas)]), hide_index=True, use_container_width=True)
        with st.expander('진단'):
            st.caption('페르소나별 구매 카테고리 비중')
            shares = pd.DataFrame({name: row.get('purchase_category_shares', {}) for name, row in zip(names, personas)})
            st.dataframe(shares.rename(index=CATEGORIES).map(lambda v: f'{v:.1%}'), use_container_width=True)
    catalog_events(audit, config)
    integrity(audit)


def catalog_events(audit: dict, config: dict) -> None:
    section('데이터', 2)
    leaves = audit.get('category_counts', {})
    taxonomy = config.get('taxonomy', {})
    parent = {leaf: top for top, middles in taxonomy.items() for items in middles.values() for leaf in items}
    tops: dict[str, int] = {}
    for leaf, count in leaves.items():
        tops[parent.get(leaf, '기타')] = tops.get(parent.get(leaf, '기타'), 0) + count
    first, second = st.columns(2)
    if tops:
        order = sorted(tops, key=lambda name: tops[name], reverse=True)
        labels = [CATEGORIES.get(name, name) for name in order]
        middles = sum(len(middles) for middles in taxonomy.values())
        title = f'대분류 {len(tops)}개 · 중분류 {middles}개 · 소분류 {len(leaves)}개 (대분류별 상품 수)'
        with_table(first, hbar(labels, [tops[n] for n in order], [f'{tops[n]:,}' for n in order], title, None, ','),
                   pd.DataFrame(dict(대분류=labels, 상품=[tops[n] for n in order])))
    events = audit.get('event_counts', {})
    if events:
        order = sorted(events, key=lambda name: events[name], reverse=True)
        fig = go.Figure(go.Bar(x=[EVENTS.get(n, n) for n in order], y=[events[n] for n in order], marker_color=INDIGO, width=.55,
                               text=[f'{events[n]:,}' for n in order], textposition='outside'))
        chart(fig, f'이벤트 유형별 건수 (전체 {sum(events.values()):,}건, 반복 포함 — 퍼널 아님)', 320)
        fig.update_yaxes(range=[0, max(events.values()) * 1.15])
        with_table(second, fig, pd.DataFrame(dict(유형=[EVENTS.get(n, n) for n in order], 건수=[events[n] for n in order])))
    first, second = st.columns(2)
    daily = audit.get('daily_events', {})
    if daily:
        days, counts = list(daily), list(daily.values())
        fig = go.Figure(go.Scatter(x=days, y=counts, mode='lines+markers', line=dict(color=INDIGO, width=2), marker=dict(size=6)))
        chart(fig, f'일별 이벤트 {len(days)}일 (중앙값 {statistics.median(counts):,.0f}건)', 320).update_xaxes(title='날짜 (KST)')
        with_table(first, fig, pd.DataFrame(dict(날짜=days, 이벤트=counts)))
    price = audit.get('price_summary', {})
    if {'min', '25%', '50%', '75%', 'max'} <= set(price):
        # shortcut: the audit keeps quantiles only, so this is a five-number box; a histogram needs the catalog file.
        fig = go.Figure(go.Box(q1=[price['25%']], median=[price['50%']], q3=[price['75%']], lowerfence=[price['min']],
                               upperfence=[price['max']], mean=[price.get('mean')], name='상품 가격', orientation='h',
                               marker_color=INDIGO, fillcolor='rgba(97,85,245,.45)'))
        chart(fig, f"상품 가격 분포 (중앙값 {price['50%']:,.0f}원)", 320).update_xaxes(title='가격 (원)', tickformat=',')
        with_table(second, fig, pd.DataFrame(dict(항목=list(price), 값=[f'{v:,.0f}' for v in price.values()])))


def integrity(audit: dict) -> None:
    section('데이터', 3)
    checks = audit.get('checks', {})
    passed = sum(bool(v) for v in checks.values())
    st.markdown(f"**무결성 검사 {len(checks)}개 {'모두 통과' if passed == len(checks) else f'중 {passed}개 통과'}**")
    excluded, references = audit.get('excluded', {}), audit.get('references', {})
    a, b, c = st.columns(3)
    a.metric('구매 없는 사용자 (제외 아님)', f"{excluded.get('no_purchase_users', 0):,}")
    b.metric('상품 없는 이벤트 (검색)', f"{excluded.get('null_product_events', 0):,}")
    c.metric('참조 오류', f'{sum(references.values()):,}')
    with st.expander('근거'):
        st.caption('검사 전체와 분모·결측·중복·참조 원시값')
        st.json(display_value({key: audit.get(key) for key in ('checks', 'denominators', 'integrity', 'references', 'limitations')}))


def ledger(audit: dict) -> None:
    uid = st.text_input('구매 원장 사용자 ID', 'U000001', key='ledger_user')
    path = ROOT / audit.get('purchase_ledger', '')
    if not audit.get('purchase_ledger') or not path.is_file():
        st.info('구매 원장 파일이 이 환경에 없습니다. 경로는 아래 근거에 있습니다.')
    else:
        try:
            if file_hash(path) != audit['purchase_ledger_sha256']:
                raise ValueError('구매 원장 checksum 불일치')
            purchases = pd.read_parquet(path, filters=[('user_id', '==', uid)])
            st.caption(f'실제 구매 {len(purchases)}건 · 구매가 없는 사용자도 제외하지 않습니다.')
            if len(purchases):
                brands = purchases.brand.value_counts()
                st.metric('사용자 최다 구매 브랜드 집중도', f'{brands.iloc[0] / len(purchases):.1%}')
            columns = ['event_id', 'timestamp', 'user_id', 'product_id', 'name', 'category_l3', 'brand', 'price', 'price_percentile',
                       'views_since_previous_purchase']
            st.dataframe(display_frame(purchases[[c for c in columns if c in purchases]]), hide_index=True, use_container_width=True)
        except (OSError, ValueError, KeyError) as error:
            st.error(f'구매 원장 읽기 실패: {error}')
    with st.expander('근거'):
        st.json(display_value({key: audit.get(key) for key in ('purchase_ledger', 'purchase_ledger_sha256', 'data_fingerprint')}))


def external_section(root: Path) -> None:
    section('데이터', 4, '선택 과제 · 학습 데이터셋 추천')
    realism = read_json(root / REALISM, root)
    if realism and realism.get('distances'):
        distances = realism['distances']
        splits = list(distances)
        st.markdown('**H&M·Retailrocket 실제 통계와의 거리** (작을수록 가까움, 교정 적용 후 분할별)')
        keys = list(distances[splits[0]])
        st.dataframe(pd.DataFrame([{'지표': REALISM_LABELS.get(key, key),
                                    **{SPLITS.get(name, name): f'{distances[name][key]:.4f}' for name in splits}}
                                   for key in keys]), hide_index=True, use_container_width=True)
        st.caption(f"지표마다 정의와 단위가 달라 한 축에 그리지 않습니다. {korean(realism.get('scope', ''))}")
    deepfashion = read_json(root / DEEPFASHION, root)
    metrics = (deepfashion or {}).get('metrics', {})
    splits = [name for name in ('val', 'test') if name in metrics]
    if splits:
        top1 = [metrics[name]['zero_shot_top1'] for name in splits]
        top5 = [metrics[name]['zero_shot_top5'] for name in splits]
        majority = [metrics[name]['majority_accuracy'] for name in splits]
        names = [SPLITS.get(name, name) for name in splits]
        fig = go.Figure()
        fig.add_bar(name='CLIP 1순위 정답률 (zero-shot)', x=names, y=top1, marker_color=INDIGO, text=[f'{v:.1%}' for v in top1], textposition='outside')
        fig.add_bar(name='CLIP 5순위 안 정답률 (zero-shot)', x=names, y=top5, marker=dict(color=INDIGO, pattern=dict(shape='/')),
                    text=[f'{v:.1%}' for v in top5], textposition='outside')
        fig.add_bar(name='최빈 카테고리 기준선', x=names, y=majority, marker_color=GRAY, text=[f'{v:.1%}' for v in majority],
                    textposition='outside')
        higher = all(a > b for a, b in zip(top1, majority))
        title = ('DeepFashion 카테고리 분류: 사전학습 CLIP이 최빈값 기준선보다 높습니다' if higher
                 else 'DeepFashion 카테고리 분류: 사전학습 CLIP과 최빈값 기준선') + ' (검증·시험 분할)'
        chart(fig, title, 340, legend=True).update_yaxes(tickformat='.0%', range=[0, 1.05])
        st.plotly_chart(fig, use_container_width=True)
        with st.expander('표로 보기'):
            st.dataframe(pd.DataFrame({'분할': names, '1순위 정답률': top1, '5순위 안 정답률': top5, '최빈 기준선': majority}),
                         hide_index=True, use_container_width=True)
        st.caption('질의 수: ' + ', '.join(f"{SPLITS.get(name, name)} {metrics[name].get('queries', 0):,}" for name in splits))
        with st.expander('근거'):
            st.json(display_value({key: deepfashion.get(key) for key in ('scope', 'model', 'limitations')}))
    if not realism and not splits:
        st.info('외부 데이터셋 검증 결과가 없습니다.')


def catalog_section(config: dict) -> None:
    active = deployed(config)
    if not active:
        st.info('상품 원천 데이터와 CLIP 벡터는 배포 데이터(deployment.json)가 있는 환경에서 표시됩니다.')
        return
    try:
        products = catalog(active['data_dir'], active['data_fingerprint'])
        pid = st.text_input('상품 ID', str(products.index[0]), key='catalog_product')
        if pid not in products.index:
            st.warning('현재 카탈로그에 없는 상품 ID입니다.')
            return
        row = products.loc[pid]
        left, right = st.columns([1, 2])
        left.image(str(image_path(active, row)), width=224)
        right.dataframe(pd.DataFrame(dict(속성=list(row.index), 값=[str(display_value(v)) for v in row.values])),
                        hide_index=True, use_container_width=True)
        item = clip_item(active, pid)
        st.markdown(f"**CLIP 텍스트 입력**: `{item['text']}`")
        st.caption(f"item_ids 인덱스 {item['item_ids_index']} · 벡터 차원 {item['vectors']['text']['dimension']} · "
                   f"norm 텍스트 {item['vectors']['text']['norm']:.3f} / 이미지 {item['vectors']['image']['norm']:.3f}")
        with st.expander('근거'):
            st.json(display_value(item))
        st.caption('item_ids.json의 실제 행과 text_audit.json·text.npy·image.npy를 읽었습니다. 모델은 로컬 CLIP이며 클라우드 추론을 호출하지 않습니다.')
    except (OSError, ValueError, KeyError) as error:
        st.error(f'상품·CLIP 조회 실패: {error}')
