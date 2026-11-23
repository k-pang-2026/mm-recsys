"""Categories and their sections, all on one page. One list feeds the left contents and the headings, so they match.

Order: the answer first (개요), then the areas in the order the system works (데이터 → 검색 → 추천 → A/B 실험 → 시스템), then
the live demos and the reference lists. Each topic has one home; other categories point to it instead of repeating it."""
from __future__ import annotations

from html import escape
import json

import streamlit as st
import streamlit.components.v1 as components

TABS = ['개요', '데이터', '검색', '추천', 'A/B 실험', '시스템', '직접 해보기', '참고']
# Anchor of each category heading on the page.
CATEGORIES = dict(zip(TABS, ('overview', 'data', 'search', 'recommend', 'ab', 'system', 'try', 'reference')))
SECTIONS = {
    '개요': [('프로젝트 소개', 'about'), ('측정 기록', 'record'), ('결론', 'verdict'), ('영역별 요약', 'areas'),
           ('과제 기능 4가지', 'features'), ('동료 평가 길잡이', 'peer-review'), ('한계', 'limits')],
    '데이터': [('시간 분할', 'protocol'), ('페르소나 비교', 'personas'), ('카탈로그와 이벤트', 'catalog'), ('무결성 검사', 'integrity'),
            ('외부 데이터 검증', 'external')],
    '검색': [('작동 방식', 'how-search'), ('검색 품질', 'search-quality'), ('ANN 설정 탐색', 'ann')],
    '추천': [('작동 방식', 'how-recommend'), ('최종 품질', 'baselines'), ('단계별 진단', 'stages'), ('사용자군별 결과', 'cohorts')],
    'A/B 실험': [('실험 설계와 표본', 'ab-design'), ('CTR·CVR 결과', 'ab-rates'), ('차이와 신뢰구간', 'ab-difference'),
               ('오프라인과 온라인 비교', 'offline-online')],
    '시스템': [('응답 시간', 'latency'), ('응답 시간 분포', 'latency-samples'), ('측정 조건', 'conditions'), ('자동 재학습', 'ct')],
    '직접 해보기': [('API 상태', 'api-status'), ('검색해 보기', 'try-search'), ('추천해 보기', 'try-recommend'),
               ('상품·CLIP 벡터 조회', 'try-product'), ('구매 원장 조회', 'try-ledger')],
    '참고': [('지표 사전', 'glossary'), ('요구사항 전체', 'requirements'), ('통합 검사 근거', 'integration'), ('화면 보는 법', 'how-to-read'),
           ('측정 기록 안내', 'records')],
}


def category(name: str) -> None:
    st.header(name, anchor=CATEGORIES[name])


def section(tab: str, index: int, note: str | None = None) -> None:
    """Section heading from SECTIONS; conditions such as the split or sample size go in the gray line below it."""
    title, anchor = SECTIONS[tab][index]
    st.subheader(title, anchor=anchor)
    if note:
        st.caption(note)


def place(tab: str, index: int) -> str:
    return f'{tab} › {SECTIONS[tab][index][0]}'


def contents() -> str:
    """Left contents: every category with its sections under it. 개요 starts open; the script below opens the category
    being read and closes the rest."""
    return '<nav class="toc" aria-label="목차">' + ''.join(
        f'<div class="toc-group{" open" if index == 0 else ""}"><a class="toc-cat" href="#{CATEGORIES[name]}" target="_self" '
        f'aria-expanded="{"true" if index == 0 else "false"}">{escape(name)}</a><div class="toc-items">'
        + ''.join(f'<a class="toc-item" href="#{anchor}" target="_self">{escape(title)}</a>' for title, anchor in SECTIONS[name])
        + '</div></div>' for index, name in enumerate(TABS)) + '</nav>'


# Runs in the app page. The place being read is the last category or section heading above 30% of the window height;
# at the very bottom it is the last section, and right after a contents click it is the clicked place until the reader
# scrolls on their own. Its category opens in the contents and the others close, so scrolling down unfolds the next
# category and scrolling up returns to the one before.
SPY = """(() => {
  if (window.tocSpy) return;
  let pinned = null;
  let timer = 0;
  function update() {
    timer = 0;
    const pairs = [...document.querySelectorAll('.toc a[href^="#"]')]
      .map(link => [link, document.getElementById(decodeURIComponent(link.hash.slice(1)))])
      .filter(([, heading]) => heading);
    if (!pairs.length) return;
    let active = pinned && pairs.find(([link]) => link.hash === pinned);
    if (!active) {
      const main = document.querySelector('[data-testid="stMain"]');
      const line = (main ? main.getBoundingClientRect().top : 0) + window.innerHeight * 0.3;
      active = pairs[0];
      for (const pair of pairs) if (pair[1].getBoundingClientRect().top <= line) active = pair;
      if (main && main.scrollTop > 0 && main.scrollTop + main.clientHeight >= main.scrollHeight - 4) active = pairs[pairs.length - 1];
    }
    const group = active[0].closest('.toc-group');
    for (const each of document.querySelectorAll('.toc-group')) {
      each.classList.toggle('open', each === group);
      each.querySelector('.toc-cat').setAttribute('aria-expanded', String(each === group));
    }
    for (const [link] of pairs) {
      const on = link === active[0];
      link.classList.toggle('active', on && link.classList.contains('toc-item'));
      if (on) link.setAttribute('aria-current', 'location'); else link.removeAttribute('aria-current');
    }
  }
  // A short timer, not requestAnimationFrame: a busy or partly covered window can hold frames back for a second.
  const schedule = () => { if (!timer) timer = setTimeout(update, 50); };
  window.tocSpy = schedule;
  document.addEventListener('scroll', schedule, true);
  window.addEventListener('resize', schedule);
  document.addEventListener('click', event => {
    const link = event.target.closest && event.target.closest('.toc a, a.go-link');
    pinned = link ? link.hash : null;
    schedule();
  }, true);
  // Any input of the reader's own releases it, the scrollbar too (pointerdown); a contents click pins again right after.
  for (const type of ['wheel', 'touchmove', 'keydown', 'pointerdown']) {
    document.addEventListener(type, () => { if (pinned) { pinned = null; schedule(); } }, {capture: true, passive: true});
  }
  new MutationObserver(schedule).observe(document.body, {childList: true, subtree: true});
  schedule();
})();"""


def follow_reading() -> None:
    """Opens the category being read in the left contents and marks its section. Streamlit drops <script> from
    markdown, so a zero-height component adds the script to the app page once; from there it follows scrolling and
    contents clicks."""
    with st.container(key='toc_spy'):
        components.html("<script>const page = window.parent.document; if (!page.getElementById('toc-spy')) { "
                        "const script = page.createElement('script'); script.id = 'toc-spy'; "
                        f'script.textContent = {json.dumps(SPY)}; page.head.appendChild(script); }}</script>', height=0)
