# INTEGRATE full 검증 기록

B11 PR #13의 main b40712a에서 시작한 feat/integration의 실제 실행 근거다.
원격 INTEGRATE 반영에는 새 로컬 commit 설명 후 별도 푸시 승인이 필요하다.
최종 제출 준비 여부와 전체 회귀 수는 [실행 결과](submission/checks.json)·[pytest XML](submission/pytest.xml)을 따른다.

| 검증 | 실제 결과와 범위 |
|---|---|
| 데이터 재현 | full 50K 상품·10K 사용자·1M 이벤트, 두 번 독립 생성한 parquet/image manifest/split hash 일치 |
| 빈 경로 준비 | 2,725.892초, 데이터·임베딩·인덱스·세 모델 재생성; HF 다운로드 캐시/의존성 레이어 재사용 |
| full valid/test | valid 동결 후 원래 11개 수치 기준과 후보 수 통과; 과거 관측된 test의 재검증 |
| HTTP p95 | text 36.767, image 123.496, hybrid 118.009, 추천 54.323ms; warmup10·serial100 |
| 라이브 Redis | 귀속 TTL·중복·최대 보상·세션 응답을 실제 HTTP와 독립 Redis client로 확인 |
| full A/B | 5,000명/arm·30일·top10, C 재검산 PASS; CTR lift −23.73%, CVR −37.18% |
| CT 자연 재학습 | 실제 10,000건 HTTP 관측·세 모델 학습·paired valid, AUC 0.971602→0.971574로 RETAINED |
| CT 별도 기능 검증 | full 50K/10K 규모의 초기 상수 ranker fixture, 원래 승격 가드·실제 HTTP 재로딩/롤백 PASS; 운영 모델 보존 |
| Streamlit | 실제 컨테이너 AppTest 4탭·4차트·검색/추천 버튼 PASS, 브라우저 픽셀 미측정 |
| P0 | 사용자 전달 강사 결정에 따라 실데이터는 개발 후 추가 검증용, RESOLVED_OPTIONAL |

[full 품질](quality_full_test.json), [재현](fresh_checkout.json), [HTTP](smoke_full.json),
[무손실 A/B](ab_full_archive.json), [분리된 CT 집계](ct_acceptance_full.json),
[Streamlit](dashboard_full.json), [실제 명령 영수증](commands/executions.json)을 대조한다.
CVR AUC는 양성 0으로 미정의다. 실제 사용자 lift와 full seeded A/B 반복은 측정하지 않았다.
품질 test는 B10의 과거 관측 이력이 있으며 새로운 미관측 holdout이라고 주장하지 않는다.

초기 지연 실패 두 번과 YAML 순서 결함, 지원되지 않는 CT CLI 옵션, 종료 코드 미복구 중단을 보존했다.
별도 CT 기능 fixture 첫 실행은 paired CTR 후 API 준비 중 4GiB OOM(137)으로 종료됐다.
평가와 API 단계를 프로세스 교체로 분리한 재검사는 같은 4GiB에서 종료 0으로 통과했다.
[메모리 실패](attempts/ct_lifecycle_memory_initial/command_receipt.json)와
실제 registry 로그·별도 HTTP reload 로그를 모두 보존하며 RETAINED를 PROMOTED로 바꾸지 않았다.

# 최초 실행 기록 (당시 상태 보존)

기준 main은 B11 PR [#13](https://github.com/k-pang-2026/mm-recsys/pull/13)의
병합 커밋 b40712a다. feat/integration에서 작업하며 이 브랜치는 아직 푸시하지 않았다.
본 문서 작성 시 최종 acceptance는 미측정이며, 실행 중인 준비를 완료로 집계하지 않는다.

## 확인한 수정과 검증

- Redis에 실제 MAB 노출·귀속 TTL·원자적 최댓값 보상·중복 방지·카테고리 arm을 연결했다.
  epsilon-greedy는 후보 arm만 조회하고, UCB는 전체 노출 수 계산을 유지한다.
- 사용자 메타데이터를 요청마다 전체 DataFrame에서 다시 만드는 작업을 제거했다.
  기존 full 모델의 serving 문맥 진단에서 21개 사용자의 피처와 100회 top10 결과가 정확히 일치했다.
  호스트 p95 172.289→34.748ms는 동시 준비 중의 진단이며 최종 Docker 지연을 대신하지 않는다.
- A/B의 사용자별 가변 상태는 분리하고 불변 카탈로그 메타데이터만 공유한다.
  popularity의 정렬 순서/등록 시각 조건을 유지하며 필요한 topN을 찾으면 순회를 마친다.
- 공개 함수의 누락 타입과 기존 전역 mypy 오류를 수정했다. 개발용
  types-requests==2.32.0.20241016을 추가하고 런타임 모델 패키지는 유지했다.
- P0는 사용자 전달 강사 지시에 따라 RESOLVED_OPTIONAL이다. 실제 데이터는 개발 이후 추가 검증용이며,
  필수 full acceptance는 합성 데이터 기준이다. 외부 데이터 획득은 수행하지 않았다.

## 재현성 결함과 보존

첫 독립 full 실행은 YAML의 기본 키 정렬이 카테고리/페르소나 순서를 바꾸는 문제를 드러냈다.
기존 fingerprint는 dict를 정렬해 해시하므로 달라진 생성 순서를 구분하지 못했다.
400-item 재현으로 원인과 순서 보존 시의 일치를 확인했고 새 full test를 열기 전에 중지했다.
첫 환경의 데이터·미완료 모델·로그·볼륨을 보존했다. 결과를 PASS로 집계하지 않는다.

준비 YAML에 sort_keys=False를 적용하고 generator 4.1.0의 identity에 순서 정보를 포함했다.
새 원격 clone+현재 통합 patch의 별도 빈 data/models에서 다시 시작했다.
고정 Docker Python 3.11 환경에서 full 데이터를 두 번 독립 생성한 결과 모든 parquet와
이미지 manifest checksum, split boundary, 개수가 일치했다.

새 데이터 식별자는 6cbd02ebd828afc464e02bc95edd25c80f96175f2f14f53af707edcba3665ae9다.
상품 50,000·사용자 10,000·이벤트 1,000,000·노출 2,255,024다.
이전 4.0.0 데이터/모델은 덮어쓰지 않고 보존하며 새 버전 경로를 사용한다.
기존 데이터의 generation fingerprint가 다르면 preparation은 재사용을 거부한다.

## 검증 범위

fresh_checkout.json은 실제 원격 main clone 위에 아직 미커밋인 INTEGRATE patch를 적용한
소스와 최초 빈 data/models 상태를 기록한다. CLIP의 사전 학습 checkpoint 다운로드 캐시와
Docker 의존성 레이어는 재사용하지만 임베딩·인덱스·추천 모델은 재생성한다.
기본 서비스는 네 개이며 CT worker는 별도 선택 profile로 검증한다.
full API는 localhost:19000, Streamlit은 localhost:19501, Redis는 localhost:17379다.
호스트 최종 validator는 integration_config.yaml과 ignored 로컬 artifact 경로를 사용해
이 새 환경을 확인하며, 원래 data/full·models/full을 바꾸지 않는다.

최종 수치·A/B·CT·실제 컨테이너 지연·최종 제출 준비 상태는 해당 실행이 끝난 후
원본 JSON과 명령 종료 코드로 판정한다. 소스/해시 확인만으로 실행 성공을 주장하지 않는다.

생성 순서를 복구한 4.1.0의 실제 test parquet가 B10의 원래 올바른 데이터와 같으므로
이 test는 과거에 관측된 적이 있다. 이번 변경은 점수 hyperparameter나 정답을 바꾸지 않으며,
현재 소스의 valid를 동결한 뒤 재검증한다. 신규 미관측 holdout이라고 주장하지 않는다.
