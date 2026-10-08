from pathlib import Path
import json
import streamlit as st

st.title('멀티모달 검색 및 Multi-Stage 추천')
st.caption('공통 준비 완료 · 검색 A / 추천 B / 서빙·평가 C')
path=Path('docs/results/data_diagnostics.json')
if path.exists():
    st.subheader('공통 train/valid 데이터 진단')
    st.json(json.loads(path.read_text()))
else:
    st.info('setup_env.sh로 공통 데이터 진단을 생성하세요.')
st.info('검색·추천 서비스와 최종 평가 화면은 담당 단계에서 연결됩니다.')
