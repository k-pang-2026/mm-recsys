"""Explanations shared by the 개요·데이터·검색·추천·참고 tabs: the step card, the search and time-split figures and the
metric glossary. Text and HTML only, so each reads even when no result is saved.

Layout follows Apple HIG charting guidance: a few values are shown as text instead of an invented chart shape, each
figure has a one-line summary above it, and every figure sits in the same gray card as the dashboard's chart cards."""
from __future__ import annotations

import streamlit as st

from dashboard.style import BASE, GRAY, INDIGO, ORANGE, TEAL

# PDF full scale; the selected result's own data_counts replace it.
SPEC = dict(products=50_000, users=10_000, events=1_000_000)
# The project in five steps, in the order of the left list: (category, goal, how), each a few words — the categories
# below explain the rest.
STORY = [('데이터', '가상 고객 만들기', '시뮬레이터로 행동 기록 생성'),
         ('검색', '글·사진으로 찾기', 'CLIP + FAISS, BM25와 비교'),
         ('추천', '50개 골라 보여 주기', '300개 → 50개, 인기순과 비교'),
         ('A/B 실험', '정말 나은지 실험', '두 그룹의 클릭·구매 비교'),
         ('시스템', '빠르고 스스로 고치기', '0.2초 응답, 자동 재학습')]
# One glossary for the 참고 table and the 개요 card tooltips: (area, [(metric key or None, name, meaning, how to read)]).
TERMS = [('검색', [('mrr', 'MRR', '첫 정답이 몇 번째에 나오는지의 역수 평균', '높을수록 좋음 · 최대 1'),
                   ('ndcg_at_10', 'NDCG@10', '상위 10개 안에서 정답이 위쪽에 있을수록 커지는 점수', '높을수록 좋음 · 최대 1')]),
         ('추천', [('recall_at_300', 'Recall@300', '실제로 담거나 산 상품이 후보 300개 안에 든 비율', '높을수록 좋음'),
                   ('auc', 'CTR AUC', '클릭한 상품을 안 한 상품보다 높게 매긴 비율', '높을수록 좋음 · 0.5는 무작위'),
                   ('hit_rate_at_50', 'HitRate@50', '추천 50개 안에 실제로 담거나 산 상품이 하나라도 있는 사용자 비율', '높을수록 좋음'),
                   ('ndcg_at_50', 'NDCG@50', '추천 50개 안에서 정답이 위쪽에 있을수록 커지는 점수', '높을수록 좋음'),
                   ('coverage', 'Coverage', '전체 상품 중 한 번이라도 추천된 비율', '높을수록 고르게 추천')]),
         ('속도', [(None, 'p95', '요청 100번 중 95번째로 느린 응답 시간', '낮을수록 좋음'),
                   ('search_p95_ms', '검색 HTTP p95', '모드별 단건 검색 요청의 p95 중 가장 느린 모드의 값', '기준 이하면 통과'),
                   ('recommend_p95_ms', '추천 HTTP p95', '단건 추천 요청의 p95', '기준 이하면 통과'),
                   ('candidate_p95_ms', '후보 생성 p95', '사용자 벡터 계산과 FAISS 후보 300개 검색 시간의 p95', '기준 이하면 통과'),
                   ('feature_p95_ms', 'Redis 조회 p95', '최근 조회·프로필을 Redis에서 읽는 시간의 p95', '기준 이하면 통과')]),
         ('A/B', [(None, 'CTR · CVR', '보여 준 상품 중 클릭 · 구매로 이어진 비율', '두 그룹을 비교'),
                  (None, 'p값 · 95% 신뢰구간', '두 그룹의 차이가 우연인지 판단하는 값',
                   'p값이 0.05 미만이거나 구간이 0을 벗어나면 의미 있는 차이')])]
HELP = {key: meaning for _, items in TERMS for key, _, meaning, _ in items if key}


def html(body: str) -> None:
    # One line starting with <div: markdown would turn indented or blank-line-split HTML into code blocks.
    st.markdown(body, unsafe_allow_html=True)


def steps(items: list[tuple[str, str, str, str, str]]) -> str:
    """Steps in one gray card joined by chevrons, footers lined up at the bottom. The system structure and the
    recommendation stages share it so both sequences look alike. Each item: (count, count note, title, body, footer)."""
    cells = []
    for count, note, title, body, foot in items:
        unit = '<small>개</small>' if count[:1].isdigit() else ''  # a missing value shows as — without a unit
        head = f'<div class="step-num">{count}{unit}</div><div class="step-sub">{note}</div>' if count else ''
        cells.append(f'<div class="step">{head}<b>{title}</b><span>{body}</span>' + (f'<em>{foot}</em>' if foot else '') + '</div>')
    kind = ' numbers' if any(item[0] for item in items) else ''
    # The wrapper is a CSS container so the steps stack by their own width, not the window's (the sidebar eats ~340px).
    return (f'<div class="steps-box"><div class="steps{kind}">' + '<div class="step-arrow" aria-hidden="true">›</div>'.join(cells)
            + '</div></div>')


def about(counts: dict, criteria: int) -> None:
    """The least a reader needs before any number: what was built, the goal of each step, and the reading order.
    Text only, so it reads even when no result is saved."""
    st.markdown(f"가상 쇼핑몰의 **검색**과 **추천**을 만들고, 과제가 정한 품질·속도 기준{f' {criteria}개를' if criteria else '을'} "
                '넘는지 측정한 프로젝트입니다.')
    html(f"<div class=\"story-facts\">상품 {counts['products']:,}개 · 사용자 {counts['users']:,}명 · "
         f"행동 기록 {counts['events']:,}건 · 시뮬레이터로 만든 가상 데이터</div>")
    cards = ''.join(f'<li class="story-card"><div class="story-step"><span>{i}</span>{tab}</div><b>{goal}</b><p>{how}</p></li>'
                    for i, (tab, goal, how) in enumerate(STORY, 1))
    html(f'<ol class="story" aria-label="프로젝트의 다섯 단계">{cards}</ol>')
    st.caption('아래로 이 순서대로 이어집니다. 왼쪽 목차가 지금 읽는 곳을 따라 펼쳐집니다.')


def embedding_map() -> str:
    """Three same-shaped groups mirrored around the middle one (x=360); the dashed circle is what 「검정 후드티」 returns."""
    groups = [(130, '「청바지」', '데님 팬츠', '일자 청바지'), (360, '「검정 후드티」', '블랙 후디', '오버핏 후드'),
              (590, '「흰 운동화」', '흰 스니커즈', '캔버스화')]

    def label(x: int, y: int, text: str, size: float = 13) -> str:
        return f'<text x="{x}" y="{y}" font-size="{size}" text-anchor="middle" fill="currentColor">{text}</text>'

    marks = ''.join(f'<circle cx="{cx}" cy="60" r="7" fill="{INDIGO}"/>' + label(cx, 86, query) +
                    ''.join(f'<rect x="{x - 6}" y="108" width="12" height="12" rx="2" fill="{TEAL}"/>' + label(x, 138, name)
                            for x, name in ((cx - 45, left), (cx + 45, right)))
                    for cx, query, left, right in groups)
    return ('<div class="figure"><svg viewBox="0 30 720 190" role="img" aria-label="검색어와 상품 사진이 같은 좌표 공간에서 뜻이 비슷할수록 '
            '가깝게 놓인 그림"><ellipse cx="360" cy="97" rx="128" ry="60" fill="none" stroke="currentColor" stroke-opacity=".45" '
            'stroke-dasharray="5 4"/><text x="360" y="178" font-size="12.5" text-anchor="middle" fill="currentColor" opacity=".75">'
            '검색어와 가장 가까운 상품 = 검색 결과</text>' + marks +
            f'<circle cx="278" cy="202" r="6" fill="{INDIGO}"/><text x="290" y="206" font-size="12.5" fill="currentColor">글(검색어)</text>'
            f'<rect x="370" y="196" width="12" height="12" rx="2" fill="{TEAL}"/>'
            '<text x="388" y="206" font-size="12.5" fill="currentColor">상품 사진</text></svg></div>')


def search_how() -> None:
    st.markdown('CLIP 모델이 검색어와 상품 사진을 같은 공간의 좌표(벡터)로 바꿉니다. 뜻이 비슷할수록 가까이 놓이므로, 검색어와 가장 가까운 상품이 '
                '검색 결과가 됩니다.')
    html(embedding_map())
    st.markdown('- **검색 방식** 텍스트 · 이미지 · 하이브리드(글과 사진을 함께)\n'
                '- **빠르게 찾기** 모든 상품과 일일이 비교하지 않고, FAISS 색인으로 가까운 상품을 근사 검색(ANN)합니다\n'
                '- **비교 기준** 검색어와 단어가 겹치는 정도로 찾는 키워드 검색 BM25')


def split_bar(ratios: dict | None = None) -> str:
    """Time split as a thin proportional strip; the labels go in a legend because a 10% slice is too narrow for text.
    Uses the audited ratios when the result has them, else the assignment's 8:1:1."""
    ratios = ratios or dict(train=.8, valid=.1, test=.1)
    parts = [('train', INDIGO, '학습 train', '모델이 배우는 과거 기록'), ('valid', TEAL, '검증 valid', '설정 고르기'),
             ('test', ORANGE, '시험 test', '최종 채점')]
    share = {key: ratios.get(key, 0) for key, *_ in parts}
    bar = ''.join(f'<i style="flex:{share[key]};background:{color}"></i>' for key, color, *_ in parts)
    legend = ''.join(f'<span><i class="sw" style="background:{color}"></i><b>{name} {share[key]:.0%}</b>{note}</span>'
                     for key, color, name, note in parts)
    label = ', '.join(f'{name.split()[0]} {share[key]:.0%}' for key, _, name, _ in parts)
    return (f'<div class="figure"><div class="split-bar" role="img" aria-label="시간순으로 {label}">{bar}</div>'
            f'<div class="split-axis"><span>과거</span><span>시간 →</span><span>최근</span></div><div class="legend">{legend}</div></div>')


def terms_table() -> str:
    """Metric glossary with each area named once (rowspan) and a column saying which direction is good."""
    rows = ''.join('<tr>' + (f'<td class="cat" rowspan="{len(items)}">{group}</td>' if i == 0 else '') +
                   f'<td>{name}</td><td>{meaning}</td><td class="read">{read}</td></tr>'
                   for group, items in TERMS for i, (_, name, meaning, read) in enumerate(items))
    return ('<div><table class="terms"><colgroup><col style="width:9%"><col style="width:21%"><col style="width:40%">'
            '<col style="width:30%"></colgroup><thead><tr><th>구분</th><th>지표</th><th>뜻</th><th>읽는 법</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div>')


def reading_guide() -> None:
    html('<div class="legend"><b>그래프 색</b>'
         f'<span><i class="sw" style="background:{INDIGO}"></i>이 프로젝트의 방식</span>'
         f'<span><i class="sw" style="background:{GRAY}"></i>비교 대상(인기순 · BM25 등)</span>'
         f'<span><i class="sw-line" style="border-color:{BASE}"></i>과제 기준선</span></div>')
    st.markdown('- **미측정**은 측정하지 않았다는 뜻이며 0이 아닙니다.\n'
                '- 숫자는 저장된 측정 기록에서 읽으며, 화면을 열 때 새로 측정하지 않습니다. 시간은 모두 한국 시간(KST)입니다.\n'
                '- 모든 카테고리가 한 페이지에 이어집니다. 내려 읽으면 왼쪽 목록에서 지금 읽는 카테고리가 펼쳐지고 지나온 카테고리는 접히며, '
                '지금 읽는 소제목이 보라색으로 표시됩니다. 목록을 누르면 그 위치로 이동합니다.\n'
                '- 어떤 측정 기록을 볼지는 개요 › 「**측정 기록**」에서 고릅니다. 기록마다의 뜻은 아래 「측정 기록 안내」에 있습니다.\n'
                '- 펼치기는 세 가지입니다. 「표로 보기」는 차트에 그린 값, 「근거」는 원본 JSON과 출처, 「진단」은 판정에 쓰지 않는 부가 분석입니다.\n'
                '- 「**직접 해보기**」 탭은 API 서버를 실행한 로컬 환경에서만 동작합니다.')
