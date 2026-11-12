# 리팩터링 후 남은 검증 최종 보고

2026-11-12 리팩터링 검증 시점의 **최종 INTEGRATE 판정은 PASS**다.
[실제 제출 검사](final_validation_20261112/submission/checks.json)의 readiness·delivery가 모두 PASS이고 blocker는 없다.
[최종 집계](../../final_acceptance.json), 저장 근거 재검증, 대시보드 게시 검증도 통과했다.
이 판정은 아래 평가 계약의 로컬 기능·품질 검증이며 A/B 개선이나 운영 CT 승격을 뜻하지 않는다.
후속 KST·소수 한 자리 표시를 포함한 게시 직전 검증은
[release 검사](final_validation_20261112/release/submission/checks.json)에 별도로 기록한다.
아래 488개 회귀·품질·빈 경로 재현은 표시 수정 전 실행이며 원본을 보존한다.

| 검증 | 실제 결과 |
|---|---|
| 전체 회귀·실제 Redis | **488 passed**, 외부 라이브러리 경고 2개, 303.01초 |
| 타입·의존성 | 제출 checker mypy, 저장소 mypy, pip check 모두 종료 코드 0 |
| full valid → 동결 → test | 각각 품질·지연 **11개 기준 PASS**; 품질 지표 7개는 리팩터링 이전과 동일 |
| 빈 데이터·모델 경로 재현 | 생성·감사·CLIP·FAISS·세 모델 학습·Redis 준비 **6단계 PASS** |
| 재생성 동일성 | 데이터 기록 파일 8개 및 모델 가중치·피처·상품 매핑·후보 인덱스 8개 실제 해시 일치 |
| 단일 API HTTP p95 | text **19.817ms**, image **73.177ms**, hybrid **77.677ms**, 추천 **18.924ms** |
| 후보·Redis p95 | **3.351ms / 0.245ms**; 후보 수 300 유지 |
| 실제 HTTP·Redis | 검색 의미·입력 검증·세션·MAB 귀속·최대 보상·중복 방지 PASS |
| 브라우저 | 여섯 탭·한국어·검색·추천, 최종 PASS·full A/B·CT 표시 확인; 오류·실패 요청 0 |
| 한 명령 시연 | `demo examples`의 API→A/B→CT 연결 PASS; 20명/군·2일 연결 검사와 별도 full A/B 측정을 구분 |

측정은 상품 50,000개·사용자 10,000명·이벤트 1,000,000건, seed 42,
원래 80/10/10 시간순 분할·관측 cutoff·K·정답·기준을 유지했다.
지연은 aarch64 단일 API 4GiB/4CPU, 추론 2스레드, 10회 예열·100회 순차 요청이며 동시 학습·수집은 없었다.
다른 하드웨어·동시 학습 환경의 성능으로 일반화하지 않는다.

## 실제 A/B·CT 결과와 제한

- **full A/B:** 5,000명/군·30일. Control CVR 1.2253%, Treatment 0.8857%, 상대 변화 **−27.72%**.
  실제 통계 검산은 PASS이며 treatment의 개선은 확인되지 않았다.
- **전후 완전 동일성:** 사용자 배정·클릭·구매·통계는 같지만, treatment 노출 150만 건 중 1건의 상품 배분이 달랐다.
  [완전 동일성 비교 FAIL](final_validation_20261112/ab_regression_detail.json)을 보존했고 모든 노출의 동등성을 주장하지 않는다.
- **실제 full CT:** 기존 배포 로그 13,404건으로 세 모델을 재학습했다.
  동일 valid CTR AUC는 0.966114654 → 0.966329962로 **+0.000215308**이며,
  최소 개선 0.001 미달로 **RETAINED**, 운영 **v1.0 유지**가 정상 판정이다.
  이번 학습은 1회 CLI 감시 호출이며, 기본 자동 worker의 기동·연결 검증과 구분한다.
- **승격·교체·롤백:** 별도 full 규모의 약한 초기 모델에서 동일한 실제 후보와 원래 guard로 검증했다.
  실제 HTTP 6건 모두 200이며 운영 registry는 변경하지 않았다. 이 통제 검증은 운영 개선 실험이 아니다.
- 실제 외부 데이터셋·실사용자 효과·원격 게시·외부 과제 제출은 이번 범위가 아니다.

## 검증 중 수정과 실패 보존

첫 빈 경로 재현의 Redis timeout에 대해 제한된 멱등 프로필 재시도를 추가했다.
전체 회귀에서 발견한 Redis `ConnectionError`와 Python 기본 예외의 이름 충돌은 별칭 import로 수정했다.
오류 복구 14개 테스트, 최종 이미지의 실제 HTTP·Redis, full valid/test, 전체 488개 테스트를 다시 통과했다.
초기 재현 실패·독립 재현한 예외 오류·중단한 혼재 검사 기록은 [실행 기록](final_validation_20261112/verification_attempts.json)에 남겼다.

대시보드가 마지막 빠른 A/B 시연을 표시하던 상태는 검증된 full 실험 원본으로 복원했다.
빠른 시연·첫 브라우저 실패를 보존했고, 실제 비동기 렌더링 완료를 기다린 뒤 동일 조건을 검증했다.
[A/B 화면](final_validation_20261112/browser_final/ab.png), [CT 화면](final_validation_20261112/browser_final/ct.png),
[브라우저 결과](final_validation_20261112/browser_final/browser.json)를 확인할 수 있다.

## 상태와 재확인

이 보고서를 작성한 로컬 검증 시점의 브랜치는 `refactor/pdf-requirements`였으며 커밋·push·PR 전이었다.
후속 게시·병합 상태는 GitHub PR 기록으로 확인한다.
검증용 API·대시보드를 종료해 [기존 Redis만 실행하던 상태](final_validation_20261112/runtime_restored.json)로 복원했다.
데이터·모델·Docker 볼륨과 모든 실패 근거는 유지했다. 로컬 화면은 `docker compose up -d` 후 `http://localhost:8501`에서 확인한다.
구현·역할·실행 가이드는 [README](../../../../README.md), 전체 기준과 해시는 [제출 보고서](../../../submission/report.md)를 따른다.

주요 원본: [quality](final_validation_20261112/quality_full_test.json),
[회귀](final_validation_20261112/submission/pytest.txt),
[빈 경로](final_validation_20261112/fresh_reproduction_full.json),
[모델 재현](final_validation_20261112/model_reproduction_full.json),
[실제 CT](final_validation_20261112/ct_full.json),
[분리된 CT 검증](final_validation_20261112/ct_acceptance_full.json),
[최종 무결성 검사](final_validation_20261112/submission_verify_final.txt).
