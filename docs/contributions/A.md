# 이제원 (A, 팀장) — 공통 준비

사용자가 지정한 팀장 역할의 SHARED 준비를 Codex가 구현했다. 실제 Git 작성자 설정을
유지하며 다른 팀원의 기여/리뷰/계정을 만들지 않는다. 박정욱(B), 박채영(C)의 구현은 아직 시작 전이다.

- PDF·원본 프롬프트·환경 스크립트를 분석하고 B2 dependency/projection/index/relevance,
  B3 cutoff/truth/negative/signal/학습 진단과 full 지표 기준을 정리했다.
- 실제 공통 config·seed·metrics·타입/API 계약·메모리 FeatureStore를 구현했다.
- 재현 가능한 catalog/JPEG/users/Markov events/노출/split/manifest를 구현했다.
  나노초 시간값 오버플로를 실측 검사에서 찾아 수정했다. 이미지 content hash/동등 그룹도 저장한다.
- dev 10000/2000/200000 및 full 50000/10000/1000000 데이터를 생성하고 구조/시간 인과성을 확인했다.
  모델 평가와 분리한 train/valid history baseline으로 학습 신호를 확인했다.
- clone→setup→A/B/C branch→실행→검사→gate→로컬 commit→설명·허가→push 흐름과 중단 후 재개를 구현했다.
  full 최종 acceptance 수치/해시/실행 근거를 검사하는 최종 통합 제한을 추가했다.
- 실제 설치와 고정 CLIP text/image 추론, 회귀 검사 및 로컬 Git 원격의 병렬 분기/병합을 검증했다.

근거: [SHARED gate](../results/gates/SHARED.json),
[공통 준비 실측](../results/common_readiness.json),
[dev pilot](../results/data_diagnostics.json), [full pilot](../results/data_diagnostics_full.json).
공통 commit/push는 이 문서와 SHARED gate가 포함된 실제 Git 이력으로 확인한다.
검색/Two Tower/DeepFM/Redis/CT/Docker 완성 및 모델 최종 품질은 후속 담당 단계에 남아 있다.
