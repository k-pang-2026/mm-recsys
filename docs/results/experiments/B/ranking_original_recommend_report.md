# 추천 개발 — B3a 학습 기반 / B3b full ANN 검증

담당 B, 예정 검토자 C. dev 구조 검증 단계이며 full test 품질·ANN·지연은 미측정이다.

## 고정한 계약

- primary는 fixed-origin 전체 카탈로그 exact inner-product Recall@300이다.
- valid cutoff는 train_end이고 히스토리는 `timestamp < cutoff`에 고정한다.
- 정답은 valid cart/purchase의 고유 상품 ID 집합이다. 검색/null/중복 이벤트는 제외한다.
- 등록 시점이 cutoff 이후인 정답도 평균 분모에 유지한다. 모든 nonempty-target 사용자를
  macro 평균에 포함하며 empty/cold/warm/rare/new/repeat/unavailable cohort를 보고한다.
- eligible catalog가 300개 이상이면 정확히 300개 고유 후보를 반환한다.
  평가기는 overretrieve 결과도 300개에서 자른다. primary 구매 제외는 false다.
- train 상품 등록 시점까지 알려진 metadata로 vocabulary와 log-price 평균/표준편차를 fit한다.
  PAD=0, UNK=1, 상품 ID와 행 번호는 별도 mapping이다. persona와 숨은 생성기 선호는 입력하지 않는다.
- 학습에서는 동일 timestamp 그룹을 처리한 뒤 히스토리/구매 집계를 갱신한다.
  타깃 이전 관측 view/cart/purchase와 현재 positive만 네거티브에서 제외한다.
  미래 positive나 valid/test 정답으로 네거티브를 제외하지 않는다.
- 각 positive당 등록 완료된 카탈로그에서 uniform random negative 4개를 뽑는다.
  충분한 pool에서는 고유 4개, 1~3개 pool에서는 replacement와 횟수를 보고한다.
  가능한 negative가 없으면 오류로 종료한다. 각 sample의 독립 seed 기반 draw는 epoch마다 재사용한다.
  in-batch/hard-negative를 사용하지 않는다.

## 모델·학습

상품 tower는 L1/L2/L3/brand/color/style의 개별 embedding과 log-price를 MLP에 넣는다.
사용자 tower는 동일 상품 tower를 통과한 최근 50개 관측 행동의 mean pooling,
age/gender, 과거 purchase의 category/brand 분포와 가격 평균/관측 여부를 사용한다.
PAD는 pooling에서 제외하고 두 tower의 64차원 출력은 L2 normalize한다.
item-ID residual은 없으므로 이 모델 자체가 metadata-only 모델이다.

온도 0.1의 positive+4-negative sampled-softmax와 configured view/cart/purchase
가중치(0.2/0.6/1.0), AdamW를 사용한다. seed 42이고 negative와 shuffle의 RNG를 분리한다.
CPU 4 threads로 실행했다. loss/margin/norm/분산/gradient/update를 매 epoch 기록하고
valid 전체 카탈로그 Recall@300으로 best checkpoint를 선택한다.

실제 train sample 114,966개에서 negative rejected draw 479개, small-pool replacement 0개였다.
train-only 고정 negative 16개 fixture는 160 update 뒤 loss 1.585549 → 0.000003609,
positive top1 accuracy 0.375 → 1.0이었다. 이 결과는 학습 경로 점검이며 retrieval 품질은 아니다.

## dev valid 관측 결과

| 방법 | Recall@300 |
|---|---:|
| train-only popularity | 0.302853 |
| observed-history category/brand/price | 0.819390 |
| Two Tower exact | 0.819066 |

11 epoch를 실행하고 patience 3으로 종료했다. best는 epoch 8이다.
체크포인트를 다시 로드한 평가에서도 동일한 Recall을 얻었다.
eligible 상품 9,600개 중 사용자별 고유 후보 300개를 반환했다.
macro 사용자 1,542명, empty-target 사용자 458명, 평균 truth 크기 1.387808이다.
cutoff 이후 등록된 정답 19개도 분모에 유지했다. cold/no-history nonempty-target 사용자는
이번 valid 구간에서 0명이므로 해당 cohort의 Recall은 null이다. 합성 테스트는 cold 사용자 포함을 검증한다.

Two Tower는 popularity보다 약 170.45% 높지만 관측 이력 기준보다 약 0.0396% 낮다.
B3b에서는 먼저 피처·학습 진단을 검토하고 exact/ANN 품질을 분리해 측정한다.
공통 데이터 진단의 다른 observed-history baseline(0.863057)은 별도 알고리즘이며
이 문서의 category/brand/price baseline과 동일하지 않다.
dev valid 수치는 full frozen test Recall≥0.30 또는 latency 통과를 뜻하지 않는다.

## 모델 bundle과 C 인수 계약

dev는 `models/v1.0/`, full은 `models/full/v1.0/`을 사용한다.
`two_tower.pt`는 valid-selected state_dict이며 weights_only로 로드한다.
`feature_vocab_scalers.json`은 vocabulary/scaler/cutoff/PAD/UNK 정의,
`item_ids.json`은 PAD를 제외한 정렬된 public ID 목록이다.
`meta.json`은 dim/metric/version/data/catalog/config/feature/checkpoint 해시와 선택 epoch를 담는다.
checksum/config/data/ID가 어긋나면 로드가 실패한다.
`item_index.faiss`와 ANN manifest는 B3b에서 이 mapping에 맞춰 추가한다.
C는 candidate 평가를 재구현하지 않고 `eval_candidate` 결과를 집계한다.
API factory·DeepFM·재랭킹 구현은 이후 B4/B5 범위다.

## 재실행·근거

```bash
source scripts/local_env.sh
PYTHONHASHSEED=42 .venv/bin/python -m src.recommendation.train_two_tower
PYTHONHASHSEED=42 .venv/bin/python -m src.recommendation.eval_candidate --split valid
.venv/bin/python -m src.recommendation.diagnose_candidate \
  --report docs/results/candidate_training_dev.json \
  --output docs/results/candidate_diagnostics_dev.json
.venv/bin/python -m pytest -q tests
```

학습 설정은 `config/recommend.yaml` / `config.yaml`에 저장한다.
test는 `--split test`를 명시했을 때만 읽는다. B3a에서는 실행하지 않았다.
데이터·모델·캐시는 커밋하지 않는다.
측정 근거는 `docs/results/candidate_training_dev.json`、`candidate_dev_valid.json`、
`candidate_diagnostics_dev.json`과 `gates/B3a.json`에 저장한다.
로컬 학습 로그는 `.team/train_B3a.log`。
data fingerprint: `3e1de868d26dc7c095f49d3841d98a944befd493937aa0ea3d0044e3062f889c`。


## B3b — full ANN과 최종 측정 (2026-10-09)

상품 50,000개, 사용자 10,000명,
이벤트 1,000,000개의 별도 `data/full/` 데이터로 학습·평가했다.
seed 42, 기존 mean pooling/64차원/temperature 0.1 설정을 유지했다.
10 epoch 중 valid Recall로 epoch 7을 선택했고, 재로드 결과도 일치했다.
새 hyperparameter ablation이나 데이터/정답 변경은 하지 않았다.
valid ANN Recall과 지연을 확인한 뒤 `candidate_selection.json`에 선택을 고정하고
처음으로 test를 평가했다. training 보고서의 stage 필드는 기존 B3a 학습 진단 형식이며,
실제 B3b bundle 계약은 그 보고서의 `bundle.contract`와 `ann` manifest에 기록된다.

| 측정 | full valid | full frozen test |
|---|---:|---:|
| train-only popularity Recall@300 | 0.228129 | 0.234984 |
| observed-history profile Recall@300 | 0.764813 | 0.766795 |
| Two Tower IndexFlatIP Recall@300 | 0.745913 | 0.746281 |
| Two Tower HNSW Recall@300 | 0.745849 | 0.746281 |
| ANN/exact 후보 agreement@300 | 0.999356 | 0.999360 |

미래 정답 Recall과 exact 후보 집합 agreement는 다른 분모다.
Two Tower는 test popularity 대비 217.59% 높지만,
관측 이력 profile 대비 -2.68% 낮다.
관측 이력 기준의 우위를 숨기거나 popularity/profile union을 primary Two Tower로 계산하지 않았다.
최종 기준 0.30은 충족했으므로 test 결과를 보고 모델을 다시 선택하지 않았다.

test macro 대상 7,686명, empty-target 2,314명,
cutoff 당시 eligible 카탈로그 48,872개이며, 모든 대상에 고유 후보 300개를 반환했다.
등록 시점 이후여서 검색 불가능한 정답 58개도 Recall 분모에 남겼다.
cohort별 결과는 `candidate_full_test.json`과 `candidate_metrics.json`에 있다.

### 저장·검증 계약

`models/full/v1.0/item_index.faiss`는 전체 public ID 목록과 같은 순서의 normalized
HNSWFlat/IP이다. M=32, efConstruction=200, efSearch=512이며 단일 스레드로 구축했다.
FAISS label i는 `item_ids.json[i]`와 상품 table row i+1에 대응한다.
후보 생성에서는 cutoff 등록일/구매 제외를 적용하고, 부족하면 검색 범위를 두 배씩 확대한다.
-1 label/PAD/중복을 제외하며, 충분한 카탈로그에서 300개를 못 얻으면 오류로 종료한다.
`index_manifest.json`과 `meta.json`에 model/data/catalog/config/feature/mapping/index/vector 해시를 저장한다.
모델 재생성, ID mapping, checksum, index metric/shape가 어긋나면 로드가 실패한다.
exact reference는 HNSW의 Flat storage에서 동일 벡터를 읽어 `IndexFlatIP`에 넣는다.
동점에서 FAISS가 선택한 top-k 경계 집합은 달라질 수 있으며, 반환된 동점 안에서는 public ID로 정렬한다.

### 지연과 macOS 복구

native CPU, GPU 미사용, 실제 추론 스레드 1개에서 10 warm-up 후
100 serial 요청으로 측정했다. 모델/인덱스 로드를 제외한 메모리 이력 조회, 시점 필터,
피처 구성, user tower, FAISS, 후보 필터/refill, public ID 복원을 포함했다.
HTTP 왕복/Redis I/O는 제외되며 결과/사용자 벡터 캐시는 사용하지 않았다.
p50=1.272ms, p95=1.369ms, p99=1.466ms,
최소 고유 후보=300개다. p95 기준 100ms를 충족했다.
RAM은 sandbox가 `sysctl hw.memsize` 접근을 거부하여 미측정이다. Docker 측정은 아니다.

초기 valid ANN 실행은 exit139로 실패했다. macOS 충돌 보고서의 공통 스택은 `libomp.dylib`였고,
[PyTorch의 macOS ARM/FAISS 충돌 보고](https://github.com/pytorch/pytorch/issues/149201)와 부합한다.
이 환경에서는 두 pinned 라이브러리의 병렬 런타임 충돌을 피하도록 `runtime.py`가
추론을 단일 스레드로 설정한다. 학습 설정·선택 모델·평가 기준은 유지했다.
HNSW 벡터 검증은 Flat storage를 직접 읽어 generic 병렬 reconstruction도 피한다.
수정 후 valid/test/benchmark는 정상 종료했다. 실패·보조 함수 import 오류·복구 근거는
`candidate_runtime_failures.json`에 보존했다. 단일 스레드 설정은 패키지 자체의 근본 수정은 아니다.

### 재현과 gate

```bash
source scripts/local_env.sh
SCALE=full PYTHONHASHSEED=42 .venv/bin/python -m src.simulator.generate
SCALE=full PYTHONHASHSEED=42 .venv/bin/python -m src.recommendation.train_two_tower
OMP_NUM_THREADS=1 SCALE=full PYTHONHASHSEED=42 .venv/bin/python -m src.recommendation.eval_candidate --split valid --ann
OMP_NUM_THREADS=1 SCALE=full .venv/bin/python -m src.recommendation.bench_candidate --split valid --output docs/results/candidate_benchmark_full_valid.json
OMP_NUM_THREADS=1 SCALE=full .venv/bin/python -m src.recommendation.diagnose_candidate --report docs/results/candidate_training_full.json --evaluation docs/results/candidate_full_valid.json --benchmark docs/results/candidate_benchmark_full_valid.json --output docs/results/candidate_diagnostics.json
SCALE=full .venv/bin/python -m src.recommendation.select_candidate
OMP_NUM_THREADS=1 SCALE=full PYTHONHASHSEED=42 .venv/bin/python -m src.recommendation.eval_candidate --split test --ann
OMP_NUM_THREADS=1 SCALE=full .venv/bin/python -m src.recommendation.bench_candidate --split test --output docs/results/candidate_benchmark_full_test.json --evaluation docs/results/candidate_full_test.json --training docs/results/candidate_training_full.json --selection docs/results/candidate_selection.json --metrics docs/results/candidate_metrics.json
OMP_NUM_THREADS=1 SCALE=full .venv/bin/python -m src.recommendation.verify_candidate --metrics docs/results/candidate_metrics.json
```

새 clone에서 위 순서로 실행한다. 이미 선택 파일이 있으면 `select_candidate --verify-existing`로 검증하며, 새 실험은 별도 버전 경로를 사용한다.
최종 test는 모델 선택 후에만 실행한다. 이미 저장된 성공 결과를 확인할 때는 마지막 verifier를 사용한다.
검증기는 원본 training/valid/test/benchmark/선택 파일의 해시와 현재 bundle을 대조하고
저장된 지표에서 B3b 합격 조건을 다시 계산한다. 전체 시스템 종합 acceptance는 후속 단계가 남아
UNMEASURED이며, B3b 후보 생성 자체는 `candidate_metrics.json`에서 PASS다.
구조 gate는 `docs/results/gates/B3b.json`, 담당 변경과 검증은 `docs/contributions/B.md`에 기록한다.
full data fingerprint: `0973c4f2a7e7313f689bcdab0012d609cdf3e1eecb2d9f81e8fe90da541450c6`.

## B4·B5 실행과 계약 (2026-10-13)

B 소유 추천 코드·설정·테스트·결과만 구현했다. 공통 main/schema/FeatureStore/Git helper는
수정하지 않았다. 변경 요청은 `docs/contributions/B.md`의 A-BATCH-001,
A-HANDOFF-002, C-MAB-001, C-SESSION-002, C-TEST-003 OPEN 코멘트에 있다.
OPEN은 공통 적용 완료를 뜻하지 않는다. 독립 클론 담당자에게 본문을 전달해야 한다.

### 라벨과 피처

CTR은 노출 ID에 연결된 view를 클릭 대리값으로 쓴다. 생성기에서 클릭 노출은 항상 position=1,
view와 노출 timestamp도 같다. position/impression ID/request ID/event_type/persona는 모델
피처에서 제외한다. 카테고리·브랜드·가격·인기도·구매 성향·시간 피처의 vocab/scaler는 train에서만
학습한다. train 입력은 동일 timestamp 그룹을 포함해 예측 시점 **이전** 행동만 사용한다.
valid/test 분류·추천 평가 이력은 각각 train_end/valid_end에서 고정한다. test에서 이전 valid 행동을
사용하지만 train-only 인기도와 학습 통계는 변경하지 않는다.

CVR은 같은 사용자·상품·세션의 가장 최근 선행 view에 30분 이내 구매를 연결한다.
관측창이 split 끝을 넘는 음성은 확정하지 않고 mask 및 검열 집계로 따로 남긴다.
조건부 CVR의 분모는 관측 완료 또는 구매가 확인된 클릭 노출이다. 클릭하지 않은 노출은
CVR 학습 손실에 들어가지 않는다. 구매 중복은 클릭 노출별 이진 라벨로 모은다.

full train 구매 35,508건에는 모두 선행 view가 있으나 최소 간격 25,176.096초,
중앙값 50,264.064초로 **30분 귀속 양성은 0건**이다. 사용자는 30분 유지와 이 한계의 공개를
확정했다. 데이터를 재생성하거나 귀속창·정답·임계치를 바꾸지 않았다.
CVR AUC는 미정의이며 낮은 CVR LogLoss는 전부 음성인 라벨의 적합도다.
조건부 구매확률이 학습되었다는 증거로 해석할 수 없다. 기본 순위식 CTR×CVR의 한계도
그대로 보고한다. 미정의 CVR에 학습률/DNN 크기를 바꿔 의미 있는 전환 모델을 만들 수 있다는
근거가 없어 추가 hyperparameter 실험은 수행하지 않았다.

### 모델과 산출물 보존

DeepFM은 sparse/dense linear term, FM pair interaction, DNN [128,64]와 분리된 CTR/CVR
출력을 구현한다. embedding=16, AdamW lr=0.001, batch=1024, 최대20 epoch/patience3이다.
full valid CTR AUC로 epoch11을 선택·동결한 뒤 test를 열었다. 모델·피처·config/data hash와
checkpoint reload를 검사한다. 후보 300개를 한 번에 점수화한다.

세션 모델은 기존 Two Tower의 64차원 상품 임베딩을 고정하고 GRU hidden=64로 다음 view를
학습한다. 우측 PAD를 제외한 마지막 실제 step을 사용하며 빈 세션 벡터는 정확히0이다.
valid next-view sampled loss로 epoch20을 선택하고 세션/장기 벡터를 0.3/0.7로 결합한다.
65개 후보의 sampled Hit@10은 전체 카탈로그 추천 HitRate와 다른 분모다.
오프라인 학습은 생성기의 session_id를 따르지만 그 세션이 시간상 수시간 지속될 수 있다.
실제 메모리 어댑터는 비활동30분 TTL을 지킨다. 이 차이도 제한으로 남긴다.

원본 `models[/full]/v1.0`의 Two Tower·기존 index와 B3b 데이터·측정은 보존했다.
`candidate_config_original.json`은 변경 전에 검증한 전체 추천 설정이다. legacy bundle은
이 스냅샷 해시를 확인하면서 candidate/evaluation/baseline/diagnostic 범위가 그대로인지
검사하고 ranking/session 설정은 각각 별도로 검사한다. dev B3a 후보에는 ANN이 없으므로
`models/b4-dev-candidate/v1.0` 복사본에만 dev 인덱스를 생성했다.
`ranking_preservation.json`의 원본 해시를 종료 시 대조한다.

### 재랭킹·저장소·API 연결

cold-start<5는 train 인기와 최근3일 상승량을 사용한다. 기본 L3 다양성은 같은 범주 최대
연속2개, 신상품은 기준시점 이전7일 상품을 후보에서 찾을 수 있으면 최소1개다.
Epsilon-Greedy/UCB는 설정으로 바꾸며 epsilon=0.1, 탐색 슬롯은 최대2개다.
신상품이 탐색 슬롯을 함께 충족할 수 있도록 quota를 예약한 뒤 전체 고유 후보에서
다양성을 지키며 채운다. 작은N·후보 부족·단일 범주 등 불가능한 조건은 진단으로 남긴다.
없는 상품을 추가하거나 중복으로 수를 채우지 않는다.

B의 `RecommendationFeatureStore`는 노출 수와 누적 보상을 arm별로 보존한다.
최근 TTL 내 동일 사용자·상품 노출에 클릭0.2/구매1.0 보상을 귀속하며 동일 노출의 보상은
최댓값으로 갱신한다. 중복 event ID는 재적용하지 않고 미귀속 피드백은 별도 집계한다.
item/category arm을 지원한다. 기존 공통 `create_app(..., feature_store=store)` 주입 경로의
이벤트·피드백·추천이 같은 저장소를 쓰는 것을 실제 학습 모델과 독립 fixture로 확인했다.

C 기본 서버의 MemoryFeatureStore에는 노출·arm 통계 계약이 아직 없다.
기본 API의 세션 갱신과 B 어댑터 주입의 MAB 학습을 구분한다. Redis·기본 서버 연결은
C-MAB-001/C-SESSION-002가 적용될 때까지 미완료다. C의 기존 미구현503 테스트는
실제 로컬 모델 파일과 분리해야 한다. 회귀에서는 명시적 빈 RECOMMEND_MODEL_DIR을 사용하고
B의 정상/없음/손상 모델 검사는 별도 임시 산출물로 수행한다.

지연은10 warmup/100 serial top50 호출로 측정했다. 내부 pipeline total은 피처 조회,
후보·ranking·reranking·노출 기록을 포함한다. ASGI TestClient HTTP 왕복도 별도로 측정한다.
TCP uvicorn은 startup 후 localhost bind가 sandbox에 거부되어 실제 TCP/curl·Redis·Docker
지연은 미측정이다. 전체 시스템 acceptance는 C·통합 검증 전까지 UNMEASURED다.

full valid는10,000명 Coverage 집합에서 비교했다. Two Tower HitRate@50=0.568542,
NDCG@50=0.179561, Coverage=0.613260이고 DeepFM CTR×CVR은 각각0.051358,
0.010103, 0.606640이다. 품질 회귀를 보존했다. CTR AUC 기준과 추천 품질 기준은 별개다.
라벨 진단의 unassigned_purchases와 동일 timestamp linkage 수는 split 끝까지의 관측 prefix
집계이며, rows/clicks/conversions/mask/censored는 해당 exposure split 집계다.

B3a의 계약상 planned_B3b ANN은 아직 모델 미준비(503)이고, index가 있다고 선언한 B3b
bundle의 누락·손상은 시작 오류다. 현재 기본 dev 회귀176개 통과는 full C fixture의 모델
유무 격리를 완료한 증거가 아니다. full C 503 테스트는 준비된 모델이200을 반환해 실패하며
이를 C-TEST-003 OPEN 인계에 재현 명령과 함께 남겼다.

최종 검토에서 설정한 pipeline 순서가 실제 전략 실행에 반영되도록 수정했다.
기본 cold_start→new_item→exploration→diversity 결과는 동결한 원본과200개 입력에서 완전히
동일했다(실패0). 두 MAB 전략, 작은N, 부족한 후보, 단일 범주, 무작위 reward 상태를 포함했다.
기본 품질/모델 선택은 변경하지 않았다. 설정 순서를 바꾸면 MAB 선택이 그 순서에 반응하는
별도 계약 테스트도 통과했다. 원본·현재 해시와 비교 결과는
`docs/results/experiments/B/reranking_order_differential.json`에 보존했다.

새로 재학습하는 후보 bundle에는 candidate 범위 해시를 별도로 저장한다. 이후 ranking/session
설정만 바뀌어도 후보 가중치와 index를 다시 만들 필요가 없다. legacy B3b bundle은 원본 전체
설정 스냅샷과 동일 candidate 범위를 검증하는 경로를 유지한다. 두 방식 모두 데이터/모델/피처/
index 해시를 계속 검사한다. 기존 bundle과 측정은 수정하지 않았다.

이번 지연은 full 평가 작업도 실행 중인 native CPU 환경의 순차 API 요청이다. ASGI transport
측정이며 독립 Docker/Redis/TCP 결과로 해석하지 않는다.

### 다양성 조건의 반례와 수정

최초 full test의 B5 다양성 미충족2,333건을 그대로 별도 보존했다.
카테고리A 상품4개와 신상품인 B 상품1개에서 Top5를 만드는 반례를 확인했다.
가능한 배열은 A,A,B,A,A인데, 예약한 B를 일찍 쓰면 뒤에 A가3개 이어져 조건을 놓쳤다.
수정은 후보 카테고리 수와 남은 필수 슬롯을 보고 각 선택 뒤에 끝까지 배치할 수 있는지
검사한다. 모델·CTR×CVR 점수·라벨·임계치·test truth는 변경하지 않았다.
카테고리3종/각0~3개, prefix run0/1/2, 필수 quota와 길이의4,044가지 경우를 독립 완전탐색과
대조해 실패0을 확인했고 반례 및 무작위 계약 검사도 통과했다.

최종 B5 re-evaluation은 같은 동결 모델·데이터의 기존 CTR/CVR 분류와 Two Tower/DeepFM
기준값을 해시로 묶어 재사용하고 B5 출력만 다시 실행한다. 이는 모델 선택/품질 튜닝이 아닌
조건 처리 버그 검증이다. 원래 실패 결과는 `experiments/B/ranking_full_test_b5_before_diversity.json`,
수정 근거는 `experiments/B/reranking_constraint_validation.json`에 있다.
최종 평가에는 후보 풀 자체의 다양성 최대 길이, 불가능한 풀 수와 가능한 풀에서의 미충족 수를
따로 기록한다. 후보에 다른 범주가 충분하지 않으면 조건을 달성했다고 표시하지 않는다.

### 최종 측정 (full / frozen test, 2026-10-14)

| 방법 | HitRate@50 | NDCG@50 | Coverage |
|---|---:|---:|---:|
| Two Tower 단독 | 0.569737 | 0.178922 | 0.617980 |
| DeepFM CTR×CVR | 0.059719 | 0.010916 | 0.612580 |
| B5 최종 | 0.048270 | 0.011031 | 0.650540 |
| 목표 | ≥0.20 | ≥0.08 | ≥0.20 |

CTR test AUC=0.963370, LogLoss=0.161054 (관측225,422건).
CVR test AUC=미정의, LogLoss=0.000000851986 (관측 클릭56,261건, 구매 양성0).
CTR 기준은 PASS지만 최종 HitRate/NDCG는 FAIL이다. Coverage는 PASS이다.
높은 CTR AUC나 전부 음성의 낮은 CVR LogLoss를 추천 품질 개선으로 해석하지 않는다.

Coverage10,000명, nonempty cart/purchase truth7,686명, cold-start300명,
카탈로그50,000/사용자10,000/이벤트1,000,000/노출2,255,024건이다.
초기 다양성 미충족2,333건 중20건을 조건 처리 수정으로 해결했다.
최종2,313건은 후보 풀 자체가 Top50 다양성을 충족할 수 없었고,
**가능한 후보 풀의 미충족은0건**이다. 예: blazer297개/loafers3개의 후보300개는
연속2개 제한으로 최대11개만 다양하게 배치할 수 있다. 이 요청의 조건 미충족은 그대로 보고한다.
full test 추천 품질 수치는 수정 전후 같았으며 모델·라벨·점수식 튜닝은 없었다.

10 warmup/100 serial 호출의 내부 p95는 B4=90.014ms/B5=92.787ms,
ASGI HTTP 왕복 p95는 B4=90.854ms/B5=93.591ms로200ms 기준 안이다.
B5 재측정의 실제 클릭·보상 흐름도 PASS다. TCP/curl/Redis/Docker 값은 미측정이다.

회귀180개, B3b 저장 측정·모델/데이터 해시 검증, 새 범위 해시와 legacy 스냅샷 검증,
pip check와 diff/compile 검사가 통과했다. 실제 gate 명령은 `gates/B4.json`, `gates/B5.json`에
별도로 기록한다. `ranking_metrics.json`은 모델·기준선·지연·수정 검증의 원본 파일 해시를 묶는다.

B4 핵심 기준/구조 및 B5 구현·메모리 연결 검증은 PASS이며, 추천 품질은 FAIL이다.
전체 시스템 acceptance와 A/C 공통 통합은 UNMEASURED다. 로컬 commit/게시의 실제 상태는
`ranking_execution_state.json` 및 helper 결과를 확인한다. 이 보고서는 원격 게시·PR 갱신 완료를
의미하지 않는다.
