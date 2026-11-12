"""Dataset exploration and HTTP interaction in the existing Streamlit app."""
from __future__ import annotations

import json
from pathlib import Path
import uuid

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.assets import catalog, clip_item, deployment, image_path
from dashboard.data import api_call
from dashboard.formatting import display_frame, display_value
from src.common.artifacts import file_hash
from src.search.text import display_text


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


def data_tab(config: dict) -> None:
    st.subheader('서비스 데이터 · EDA · 페르소나')
    active = deployed(config)
    if not active:
        st.info('데이터 준비와 EDA를 먼저 실행하세요.')
        return
    path = config['results_dir'] / 'data_audit.json'
    try:
        audit = json.loads(path.read_text(encoding='utf-8'))
        if audit['data_fingerprint'] != active['data_fingerprint']:
            raise ValueError('현재 배포와 EDA fingerprint가 다릅니다.')
        st.caption(f"데이터={audit['data_fingerprint']} · seed={audit['seed']} · 생성기={audit['generator_version']} · 분석 시각={display_value(audit['generated_at'])}")
        st.json(display_value(dict(counts=audit['counts'], checks=audit['checks'], boundaries=audit['boundaries'], excluded=audit['excluded'])))
        rows = pd.DataFrame(audit['personas'])
        st.dataframe(display_frame(rows.drop(columns=['configured', 'purchase_category_shares'])), hide_index=True)
        fig = go.Figure([go.Bar(name=name, x=rows.persona, y=rows[name])
            for name in ('purchase_per_view', 'purchase_price_percentile_mean', 'top_brand_share_mean')])
        fig.update_layout(barmode='stack', yaxis=dict(tickformat='.1f', hoverformat='.1f'))
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(display_frame(pd.DataFrame({r['persona']: r['purchase_category_shares'] for r in audit['personas']})))
        with st.expander('분모·결측·중복·참조 무결성·분포'):
            st.json(display_value({k: audit[k] for k in ('denominators', 'integrity', 'references', 'daily_events', 'event_counts', 'category_counts', 'brand_counts', 'price_summary', 'limitations')}))
        uid = st.text_input('구매 원장 사용자 ID', 'U000001', key='ledger_user')
        ledger = Path(audit['purchase_ledger'])
        if file_hash(ledger) != audit['purchase_ledger_sha256']:
            raise ValueError('구매 원장 checksum 불일치')
        purchases = pd.read_parquet(ledger, filters=[('user_id', '==', uid)])
        st.caption(f'실제 구매 {len(purchases)}건 · 구매가 없는 사용자도 제외하지 않습니다.')
        if len(purchases):
            brands = purchases.brand.value_counts()
            st.metric('사용자 최다 구매 브랜드 집중도', f'{brands.iloc[0] / len(purchases):.1%}')
            st.caption(f'최다 브랜드={brands.index[0]} · 구매 건수={int(brands.iloc[0])}/{len(purchases)} · 품질/효용 점수가 아닌 관측 구매 비중')
        columns = ['event_id', 'timestamp', 'user_id', 'product_id', 'name', 'category_l3', 'brand', 'price', 'price_percentile', 'views_since_previous_purchase']
        st.dataframe(display_frame(purchases[columns]), hide_index=True)
    except (OSError, ValueError, KeyError) as error:
        st.error(f'EDA 읽기 실패: {error}')


def catalog_tab(config: dict) -> None:
    st.subheader('상품 원천 데이터와 실제 CLIP 벡터')
    active = deployed(config)
    if not active:
        st.info('검색 번들 준비 후 조회할 수 있습니다.')
        return
    try:
        products = catalog(active['data_dir'], active['data_fingerprint'])
        pid = st.text_input('상품 ID', str(products.index[0]), key='catalog_product')
        if pid not in products.index:
            st.warning('현재 카탈로그에 없는 상품 ID입니다.')
            return
        row = products.loc[pid]
        st.image(str(image_path(active, row)), width=224)
        st.json(display_value(row.to_dict()))
        st.json(display_value(clip_item(active, pid)))
        st.caption('item_ids.json의 실제 행과 text_audit.json·text.npy·image.npy를 읽었습니다. 모델은 로컬 CLIP이며 클라우드 추론을 호출하지 않습니다.')
    except (OSError, ValueError, KeyError) as error:
        st.error(f'상품·CLIP 조회 실패: {error}')
