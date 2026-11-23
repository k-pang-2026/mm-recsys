"""Look of the evaluation room (Figma design 2026-11-19): purple navigation, HIG system colors for data.

Light theme follows the design; light-dark() keeps the same layout readable when Streamlit runs dark.
"""
from __future__ import annotations

import plotly.graph_objects as go

# Data colors follow Apple HIG system colors: our system = indigo, comparison = gray, modes = indigo/mint/orange.
INDIGO, GRAY, TEAL, ORANGE = '#6155f5', '#6c6c70', '#008575', '#c55300'
GRID, BASE = 'rgba(128,128,128,.28)', '#97979d'

CSS = """<style>
[data-testid="stDecoration"]{background:#7a4fe0;background-image:none;height:2px}
[data-testid="stSidebar"]{background:light-dark(#f0f0f0, #1c1c1e);min-width:336px;max-width:336px}
[data-testid="stSidebarUserContent"]{padding-top:3.5rem}
.block-container{padding:4rem 5rem 4rem;max-width:1440px}
[data-testid="stAppViewContainer"] :is(p, li, span, summary, h1, h2, h3){word-break:keep-all;overflow-wrap:break-word}
[data-testid="stAppViewContainer"] h1{font-size:2.05rem;letter-spacing:-.025em;padding-bottom:0}
[data-testid="stMain"] h2{font-size:1.85rem;letter-spacing:-.02em}
[data-testid="stMain"] h3{font-size:1.375rem}
/* left contents: every category; the one being read is open (purple, ⌄) with its sections under it, the rest closed */
.toc{display:flex;flex-direction:column;gap:2px}
.toc-cat{display:flex;align-items:center;gap:6px;padding:6px 4px;border-radius:6px;font-size:16.5px;font-weight:600;
  color:inherit !important;text-decoration:none !important}
.toc-cat::before{content:'›';display:inline-block;width:16px;text-align:center;font-size:19px;line-height:1;opacity:.7;
  transition:transform .15s}
.toc-cat:hover{color:light-dark(#4b2c9f, #b9a4ff) !important}
.toc-group.open .toc-cat{font-weight:700;color:light-dark(#4b2c9f, #b9a4ff) !important}
.toc-group.open .toc-cat::before{transform:rotate(90deg);opacity:1}
.toc-items{display:none;margin:2px 0 10px}
.toc-group.open .toc-items{display:block}
.toc-item{display:block;margin-left:22px;padding:5px 8px;border-radius:6px;font-size:14.5px;color:inherit !important;
  opacity:.85;text-decoration:none !important;line-height:1.38}
/* the record line under each category and the jumps further down the page */
.now-line{font-size:14px;opacity:.75}
a.go-link{font-size:14px;font-weight:600;color:light-dark(#5b3fc4, #b9a4ff) !important;text-decoration:none !important}
a.go-link:hover{text-decoration:underline !important}
/* 측정 기록 card at the top of 개요: records as a plain list, the scoring data as a two-way switch */
.st-key-record label[data-baseweb="radio"]{padding:4px 0}
.st-key-record label[data-baseweb="radio"] p{font-size:15.5px;font-weight:600}
.st-key-record label[data-baseweb="radio"]:has(input:checked) > div:first-child{background-color:#7a4fe0 !important}
.st-key-split [role="radiogroup"]{gap:0}
.st-key-split label[data-baseweb="radio"]{margin:0;padding:4px 16px;border:1px solid light-dark(#d5d6d8, #4a4a4f)}
.st-key-split label[data-baseweb="radio"]:first-child{border-radius:8px 0 0 8px}
.st-key-split label[data-baseweb="radio"]:last-child{border-radius:0 8px 8px 0;border-left:none}
.st-key-split label[data-baseweb="radio"] > div:first-child{display:none}
.st-key-split label[data-baseweb="radio"]:has(input:checked){border-color:#7a4fe0;background:light-dark(#efe9fc, rgba(122,79,224,.25))}
.st-key-split label[data-baseweb="radio"]:has(input:checked) p{color:light-dark(#6a3fd4, #b9a4ff);font-weight:700}
.toc-item:hover{background:light-dark(#efe9fc, rgba(122,79,224,.2));opacity:1}
/* the section being read (dashboard/sections.py SPY): same purple as the open category */
.toc-item.active{background:light-dark(#e3dafa, rgba(122,79,224,.35));color:light-dark(#4b2c9f, #e4dbff) !important;
  font-weight:700;opacity:1}
/* the zero-height component that adds that script takes no room in the sidebar */
.st-key-toc_spy{position:absolute;width:0;height:0;overflow:hidden}
/* 「기록 다시 읽기」 in the 측정 기록 card */
[data-testid="stMain"] [data-testid="stBaseButton-tertiary"] p{font-size:14px;color:light-dark(#5b3fc4, #b9a4ff)}
/* chart cards */
[data-testid="stPlotlyChart"]{background:light-dark(#f2f2f7, #1c1c1e);border-radius:14px;overflow:hidden}
.st-key-verdict [data-testid="stMetricValue"]{font-size:20px;font-weight:700}
.st-key-verdict [data-testid="stMetricLabel"] p{font-size:14px}
.stage-note{font-size:14px;opacity:.75}
/* explanatory figures (dashboard/guide.py) drawn in HTML so they read without any saved measurement; each sits in the
   chart-card gray */
/* subgrid rows line up titles, bodies and footers across the columns */
.steps{display:grid;grid-template-columns:1fr auto 1fr auto 1fr auto 1fr;grid-template-rows:repeat(3,auto);gap:0 14px;
  margin:.4rem 0 1rem;padding:18px 22px;
  border-radius:14px;background:light-dark(#f2f2f7, #1c1c1e)}
.steps.numbers{grid-template-rows:repeat(5,auto)}
.step{display:grid;grid-row:1/-1;grid-template-rows:subgrid;min-width:0;font-size:14px;line-height:1.5}
.step-num{font-size:34px;font-weight:700;line-height:1.15;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.step-num small{margin-left:2px;font-size:16px;font-weight:600}
.step:last-child .step-num{color:light-dark(#6155f5, #8f87ff)}
.step-sub{margin-bottom:10px;font-size:13px;opacity:.65}
.step b{font-size:15px}
.step > span{opacity:.8}
.step em{padding-top:8px;font-style:normal;font-size:12.5px;opacity:.65}
.step-arrow{grid-row:1;align-self:start;font-size:22px;line-height:1.1;opacity:.35}
.steps.numbers .step-arrow{font-size:30px;line-height:1.2}
/* 프로젝트 소개: the five steps as cards in the order of the left list; they wrap to fewer columns when narrow */
.story{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:.4rem 0 1rem;padding:0;list-style:none}
/* !important: Streamlit's markdown list style indents every <li> */
.story-card{margin:0 !important;padding:16px 18px !important;border-radius:14px;background:light-dark(#f2f2f7, #1c1c1e);font-size:14px;line-height:1.55}
.story-step{display:flex;align-items:center;gap:8px;margin-bottom:6px;font-size:13px;font-weight:700;color:light-dark(#4b2c9f, #b9a4ff)}
.story-step span{display:inline-grid;place-items:center;width:20px;height:20px;border-radius:50%;font-size:12px;
  background:light-dark(#e3dafa, rgba(122,79,224,.35))}
.story-card b{display:block;margin-bottom:3px;font-size:15.5px}
.story-card p{margin:0;font-size:13px;opacity:.7}
.story-facts{margin:-.4rem 0 .2rem;font-size:14px;opacity:.7}
.figure{margin:.4rem 0 1rem;padding:18px 22px;border-radius:14px;background:light-dark(#f2f2f7, #1c1c1e)}
.figure svg{display:block;width:100%;max-width:720px;height:auto;margin:0 auto}
.split-bar{display:flex;gap:3px;height:14px}
.split-bar i{border-radius:4px}
.split-axis{display:flex;justify-content:space-between;margin:6px 0 14px;font-size:12.5px;opacity:.6}
.legend{display:flex;flex-wrap:wrap;align-items:center;gap:8px 28px;margin:.2rem 0 .8rem;font-size:14px;line-height:1.5}
.figure .legend{margin:0}
.legend > span b{margin-right:6px}
.sw{display:inline-block;width:12px;height:12px;margin-right:7px;border-radius:3px;vertical-align:-1px}
.sw-line{display:inline-block;width:22px;margin-right:7px;border-top:2px dashed;vertical-align:middle}
.terms{width:100%;border-collapse:collapse;margin:.4rem 0 .6rem;font-size:15px;line-height:1.5}
.terms th,.terms td{padding:8px 12px;border:1px solid light-dark(#e4e4e8, #34343a);text-align:left;vertical-align:middle}
.terms th{font-weight:600;background:light-dark(#f7f7f9, #1c1c1e)}
.terms td.cat{font-weight:600}
.terms td.read{opacity:.75}
.terms .nw{white-space:nowrap}
.steps-box{container-type:inline-size}
@container (max-width:720px){.steps,.steps.numbers{grid-template-columns:1fr;grid-template-rows:none;gap:0}
  .step{display:flex;flex-direction:column;grid-row:auto;padding:12px 0;border-top:1px solid rgba(128,128,128,.25)}
  .step:first-child{padding-top:0;border-top:none}.step:last-child{padding-bottom:0}.step-arrow{display:none}}
</style>"""


def chart(fig: go.Figure, title: str, height: int = 320, legend: bool = False) -> go.Figure:
    """Chart card: bold title on the card background (CSS), gridlines only where values are read.

    A second line after <br> becomes a subtitle: a multi-line title anchored at the top overflowed the card."""
    head, _, rest = title.partition('<br>')
    fig.update_layout(
        title=dict(text=f'<b>{head}</b>', x=0.02, xanchor='left', y=0.97, yanchor='top', font=dict(size=15),
                   subtitle=dict(text=rest, font=dict(size=13)) if rest else None),
        height=height, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font=dict(size=12),
        # Keep a wider right margin set earlier by baseline() for its label beside the plot.
        margin=dict(l=16, r=max(24, fig.layout.margin.r or 0), t=64 + 22 * bool(rest), b=16 if not legend else 40),
        showlegend=legend, bargap=0.35,
        legend=dict(orientation='h', x=0.5, xanchor='center', y=-0.18, bgcolor='rgba(0,0,0,0)'))
    fig.update_xaxes(gridcolor=GRID, zeroline=False, linecolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    return fig


def baseline(fig: go.Figure, value: float, label: str, horizontal: bool = True) -> go.Figure:
    """Dashed target line with its label beside the plot so it never covers the bars."""
    if horizontal:
        fig.add_hline(y=value, line_dash='dash', line_color=BASE, annotation_text=label, annotation_position='right')
        fig.update_layout(margin_r=80)
    else:
        fig.add_vline(x=value, line_dash='dash', line_color=BASE, annotation_text=label, annotation_position='top')
    return fig
