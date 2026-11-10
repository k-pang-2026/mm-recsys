# 2026-11-10 검색·CT·현재 소스 품질 검증

사용자가 요청한 세 문제와 앞선 터미널 시연 수정을 함께 검증했다.
기준 main은 `aa2a8ae807b1d829bd52a115665684d5c28b25a3`이며, 정규 역할 단계의
INTEGRATE 재발행이나 전체 PDF 최종 합격 판정은 아니다.

## 수정 내용과 근거

1. **한국어 하이브리드 검색**: 누락된 `가방 → bag` 전처리를 추가했다.
   텍스트·이미지 가중치를 50:50으로 선택해 갈색 가방 이미지와 `가방`을 함께
   입력하면 상위 10개 모두 갈색 토트백을 반환한다. 상품 ID를 강제하지 않는다.
   [실제 HTTP 응답](hybrid_bag.json), [valid 비교](fusion_valid.json),
   [test를 열기 전 선택 사유](fusion_selection.json)를 보존했다.
   독립 valid 하이브리드 200개에서 MRR/NDCG는 0.96이다. 기존 75:25의 0.97보다
   소폭 낮지만 이미지 반영을 개선하며 고정 기준 0.55/0.50을 충족한다.
   [질의 무결성](query_integrity.json)은 수정 전후 valid/test 정답·이미지 전체의
   SHA256이 동일함을 확인한다. K, 시간 분할, 전체 상품/사용자 코호트는 바꾸지 않았다.

2. **CT 누적 로그의 메모리 초과**: SQLite 전체 `fetchall()`과 중복 Python/Pandas
   복사를 제거하고 묶음 조회 및 Arrow 스냅샷으로 바꿨다. 시간순 분할·중복 방지·원본
   검증은 유지한다. 학습 전 실제 train/valid의 CTR/CVR 양성·음성 라벨을 검사한다.
   라벨이 없으면 `WAITING_FOR_LABELS`로 사유를 알리고 모델과 미처리 로그를 보존한다.
   동일 입력을 감시할 때는 대기 스냅샷을 반복 생성하지 않는다.
   [운영 누적 데이터 검사](ct_backlog.json)는 신규 2,493,556건을 4 GiB 제한에서
   43.31초, 최고 3.15 GiB로 처리했다. 종료 코드 0이고 기존 모델·로그를 보존했다.
   이 데이터의 새 valid 구간은 노출 0건이므로 **대규모 모델 재학습 성공이나 품질 개선은
   측정하지 않았다**. 일반 시뮬레이터 로그를 추천 반응으로 꾸며서 학습하지 않는다.
   [격리 CT 검사](ct_drill.json)는 실제 3개 모델 학습·시간순 분할·동일 valid 비교·
   승격·기존 모델 유지·API 교체·롤백·손상 거부·로그 1회 소비의 12개 검사를 통과했다.
   이 검사는 작은 별도 관측 데이터이며 운영 데이터의 학습 가능성을 대신하지 않는다.

3. **변경된 소스에 대한 품질 근거**: 이전 보고서를 보존하고 이 폴더에 새 HTTP
   성능, valid 동결, test 품질 및 소스·모델·설정 해시를 기록한다.
   [새 동료 평가 실행](peer_review.json)은 다양성·MAB·신상품·콜드스타트·세션·중복
   방지 14개 검사를 통과했다. 최종 수치·파일 해시와 판정은 `verification.json`에 있다.

## 터미널 실행과 성능

`docker compose up`은 간결한 단계 로그를 표시하고 `demo search`, `demo recommend`,
`demo ab`, `demo ct`로 실제 결과를 터미널에서 확인한다. 원본 JSON과 상세 로그는
보존한다. 소스 변경을 받은 뒤에는 `docker compose up --build`로 이미지를 갱신한다.

시뮬레이터는 CT journal을 건별 트랜잭션 대신 배치 트랜잭션으로 저장한다.
동일 seed·동일 10,000건 비교는 37.01초 → 11.09초(3.34배)이며 동일한 이벤트와
중복 방지 의미를 유지한다. 이전 [터미널 검증](../terminal_demo_20261110/verification.json)의
실행 조건과 원본을 보존한다. 배치 주기는 시작 간격이므로 생성이 주기보다 오래 걸리면
완료 후 불필요한 1초를 추가 대기하지 않는다.

## 검증 범위와 재현

최종 전체 테스트 **408개**, mypy **119개 파일**이 통과했다. full valid/test의
11개 품질·성능 기준이 모두 통과했으며 test 수치는 다음과 같다.

| 지표 | 새 측정 | 기준 |
|---|---:|---:|
| 검색 MRR / NDCG@10 | 0.925 / 0.925 | ≥ 0.55 / 0.50 |
| Recall@300 | 0.755056 | ≥ 0.30 |
| CTR AUC | 0.966322 | ≥ 0.70 |
| HitRate@50 / NDCG@50 | 0.678373 / 0.332781 | ≥ 0.20 / 0.08 |
| Coverage | 0.3641 | ≥ 0.20 |
| 검색 / 추천 HTTP p95 | 87.34 / 37.58 ms | ≤ 200 / 200 ms |
| 후보 생성 / Redis 피처 p95 | 4.37 / 0.31 ms | ≤ 100 / 10 ms |

CPU Docker 한 배포, API 4 GiB/4 CPU, 상주 모델, HTTP 직렬 요청으로 측정한다.
각 유형 warmup 10회 + 100회이며 지연 측정 중 simulator·CT·A/B는 멈춘 상태다.
최초 요청·병렬 부하·다중 배포의 지연 보장은 아니다. API·Redis·대시보드는 실행 상태로
남기고 simulator는 추가 로그 축적을 막기 위해 정지 상태를 유지한다.

```bash
docker compose exec api-server demo search --query-text "가방" --query-image data/full-v43/images/P000001.jpg
docker compose exec api-server python scripts/smoke_test.py --benchmark --output docs/results/experiments/A/final_fixes_20261110/smoke_full.json
docker compose run --rm --no-deps --pull never -e QUALITY_RESULTS_DIR=docs/results/experiments/A/final_fixes_20261110 api-server demo evaluate --split valid
docker compose run --rm --no-deps --pull never -e QUALITY_RESULTS_DIR=docs/results/experiments/A/final_fixes_20261110 api-server demo evaluate --split test
docker compose run --rm --no-deps --pull never -e QUALITY_RESULTS_DIR=docs/results/experiments/A/final_fixes_20261110 api-server python -m docker.quality --split test --verify-existing
```

품질 수치와 기준은 재측정 결과 그대로 기록한다. 새 실행은 A/B 개선이나 자연 CT 개선을
입증하지 않으며 전체 PDF 종합 acceptance는 `UNMEASURED`다. 앞선 합성 A/B의 음의 lift,
[원래 감사와 CT OOM](../peer_review_audit_20261110/audit.json), 75:25 측정
(`before_fusion/`), 수정 중 테스트 실패도 보존한다. 브라우저 클릭과 외부 데이터셋은
이번 세 문제 수정 범위에서 새로 검증하지 않았다.
