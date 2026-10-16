# B10 Docker 실행·검증 결과

검토된 main `3ea2ee7`을 반영하고 A의 `feat/A/docker`에서 구현했다. 검토 담당은 B/C다.
데이터 생성·검색 준비·추천 학습·Redis warmup을 API 단일 writer로 실행하고,
호환 산출물만 checksum·모델 로딩으로 재사용한다. 기본 서비스는 Redis·API·Streamlit·시뮬레이터다.
선택 CT worker는 별도 Compose profile이다.

## 실제 검증

- 전체 회귀: 실제 Redis를 포함해 288개 통과, 실패·생략 0개.
- 의존 모듈을 포함한 mypy: Docker·준비·smoke Python 12개 파일 통과. pip check·compile·diff 검사 통과.
- 기본 `docker compose up --build -d`와 검색 JSON/multipart·추천·세션·대시보드 smoke 통과.
- full 데이터: 상품 50,000·사용자 10,000·이벤트 1,000,000. 초기 v1.0 모델을 CPU에서 새로 학습했다.
- valid에서 설정·모델·데이터·평가 소스를 동결한 뒤 test를 실행했다. test로 설정을 선택하지 않았다.
- Streamlit AppTest: 네 탭·Plotly 4개, 예외 0개. 브라우저 픽셀 검증은 아니다.
- 선택 CT profile: loopback의 같은 v1.0 reload와 이후 검색·추천 응답 통과. 재학습·승격 개선 측정은 아니다.

## full test 지표

| 지표 | 실측값 | 기준 | 판정 |
|---|---:|---:|---|
| mrr | 0.931667 | 0.55 | PASS |
| ndcg_at_10 | 0.931667 | 0.5 | PASS |
| recall_at_300 | 0.750141 | 0.3 | PASS |
| auc | 0.964767 | 0.7 | PASS |
| hit_rate_at_50 | 0.700885 | 0.2 | PASS |
| ndcg_at_50 | 0.342175 | 0.08 | PASS |
| coverage | 0.415340 | 0.2 | PASS |
| search_p95_ms | 178.893950 | 200 | PASS |
| recommend_p95_ms | 106.317129 | 200 | PASS |
| candidate_p95_ms | 4.966624 | 100 | PASS |
| feature_p95_ms | 0.249760 | 10 | PASS |

별도 배포 HTTP p95(text/image/hybrid/recommendation)는 27.447 / 178.894 / 173.203 / 106.317ms다.
모드당 warmup 10회·100회 순차 HTTP이며 응답 캐시와 ONNX는 사용하지 않았다.
독립 CLIP tower의 병렬 인코딩은 frozen valid 입력 12개에서 직렬 대비 벡터 오차 0·top10 일치였다.
가중치·전처리·합성·FAISS·추천 정책은 그대로 유지했다.

환경은 Linux ARM64·Python 3.11·CPU Torch 2.6.0, API 메모리 4GiB·CPU quota 4,
추론 스레드 2개다. CT 동시 학습이 없는 측정이며 머신·부하별 지연 보장은 아니다.
순차 경로의 지연 미달, GC 진단, 중단한 valid 평가도 보존했다.

## 범위와 다음 단계

B10 구조 검증과 위 full 지표는 통과했지만 최종 종합 acceptance는 **UNMEASURED**다.
오프라인 추천 품질은 B5 메모리 adapter를 사용한다. 라이브 Redis의 MAB 노출·보상 연결은
기존 C 보고서와 같이 **UNCONNECTED**이며 INTEGRATE에서 보완해야 한다.
새 full A/B·실서비스 CT 개선, 새 클론의 전체 생성 시간, B11 제출 검사는 별도 작업이다.
제약 파일은 실제 Python 3.11 Linux ARM64 CPU 환경의 해결 결과이며 다른 플랫폼 검증을 뜻하지 않는다.
데이터·이미지·모델·캐시는 Git에 포함하지 않는다.

기본 실행은 다음과 같다. 최초 준비가 끝나 `/ready`가 200이면 데모를 사용할 수 있다.

```bash
docker compose up --build -d
docker compose exec api-server python scripts/smoke_test.py
```

API: http://localhost:8000/docs · Streamlit: http://localhost:8501

B10 PR이 main에 병합된 후 A B11을 `feat/A/submission`에서 진행한다.

근거: [B10 gate](../gates/B10.json), [full valid](quality_full_valid.json),
[full test](quality_full_test.json), [HTTP 원시 표본](smoke_full.json),
[모델·원시 표본 해시 검사](verified_full.json), [실제 리소스](environment_full.json),
[기본 Compose](environment_default_dev_current.json), [회귀 출력](regression_host_final.txt),
[병렬 인코딩 일치](parallel_encoder_full.json), [Streamlit](dashboard_full.json),
[CT reload](ct_profile_smoke_full.json).
