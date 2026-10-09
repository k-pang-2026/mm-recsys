# 추천 개발 B3a — 학습·평가 기반

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
