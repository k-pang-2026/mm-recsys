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
