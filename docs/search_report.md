# 검색 구현 보고서 — A B2a / B2b

현재 최신 단계는 B2b다. full 상품 50,000개에서 고정 test 600개의 MRR/NDCG@10은
0.931667이며 실제 HTTP의 최대 모드 p95는 178.251ms다. 검색 단계 기준은 통과했고,
추천 모델과 전체 Docker 재현을 포함한 최종 종합 acceptance는 아직 UNMEASURED다.
아래 B2a 내용은 이전 단계의 기록이며 최신 설정/평가는 뒤의 B2b 절을 따른다.

## 완료 범위

`feat/A/search`에서 고정 revision의 실제 CLIP 투영 벡터, 내용 기반 중복 계산 방지,
청크 재개, 완성된 임베딩·FAISS 인덱스의 원자적 발행, BM25와 평가 보조 함수를 구현했다.
검색 API, 독립 품질 쿼리, full test MRR/NDCG 및 HTTP p95는 B2b에서 구현·측정한다.

기존 Python 3.12.3 환경에서 torch 2.6.0+cpu, torchvision 0.21.0, transformers 4.46.3,
FAISS 1.9.0을 사용했다. CLIP은 `openai/clip-vit-base-patch32`, revision
`3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268`이고 텍스트·이미지 투영 차원은 모두 512다.
캐시를 사용한 실제 양 모달 추론과 Docker/Compose 사전 검사는 통과했다.
종료된 Docker Desktop을 다시 시작했으며 기존 컨테이너·볼륨은 변경하지 않았다.

## 구현과 산출물 계약

- `encoder.py`: `eval()`/`inference_mode()`와 projected feature API를 사용한다.
  실제 model max length(77)로 텍스트를 자르고 RGB 이미지를 처리한다.
  FP32 유한값·차원·비영 벡터를 확인하고 L2 정규화한다. 잘못된 이미지와 0 벡터는 실패한다.
- `text.py`: 카탈로그·쿼리·BM25가 동일한 한국어 카테고리/색/스타일 별칭을 사용한다.
  원문, 인코딩 문장, 적용한 별칭, 미등록 한국어 단어를 보존한다. 별도 다국어 인코더는 사용하지 않는다.
- `build_embeddings.py`: product_id를 안정 정렬하고 텍스트 내용/실제 이미지 SHA256로
  중복 계산을 줄인다. 완료 청크는 해시·내용 키·차원·norm을 검증한 후 재사용한다.
  완료 영수증 없는 청크는 재계산하고 완료 청크 손상은 실패한다.
  OS 프로세스 잠금은 동시 쓰기를 차단하고 프로세스 종료 시 해제되어 재개를 지원한다.
  전체 파일 검증 후 version directory를 원자적으로 발행하고 current pointer를 갱신한다.
- `index.py`/`build_index.py`: text/image/hybrid 각각 HNSW를 만들고 explicit
  `METRIC_INNER_PRODUCT`를 적용한다. 설정 M=32, efConstruction=200, efSearch=128,
  threads=4이며 호출 k가 더 크면 efSearch를 올린다. query -1 label을 제외하고
  저장된 string ID로 복원한다. IVFPQ는 설정으로 선택할 수 있지만 차원·학습 표본 최소 개수
  `max(39*nlist,39*2**nbits)`를 충족해야 하며 실패 시 HNSW로 조용히 바꾸지 않는다.
- `bm25.py`/`eval_support.py`: 같은 텍스트 전처리와 후보 ID 집합을 사용하는 BM25,
  관측 속성 기반 relevance, exact IndexFlatIP와의 ANN 일치율 진단을 제공한다.
  이미지 relevance에 브랜드 등 비관측 조건을 넣으면 실패한다.

`models/search/embeddings/<fingerprint>/`에는 `text.npy`, `image.npy` `(N,512)`,
`item_ids.json`, `text_audit.json`, `manifest.json`이 있다.
`models/search/indexes/<fingerprint>/`에는 text/image/hybrid `.faiss`, `item_ids.json`,
`manifest.json`이 있다. manifest에 카탈로그·내용·ID 순서·데이터/모델/전처리 버전·파일 해시를
저장한다. 둘 모두 완성 여부/파일 해시/ID 정렬/설정 호환성을 검증한다.
dev와 full 경로는 공통 설정대로 분리되고 바이너리·데이터·캐시는 Git에 올리지 않는다.

후속 A/C 코드는 `current_bundle(cfg)`, `current_indexes(cfg)`,
`SearchIndex.load(folder, mode, embedding_fingerprint)`로 검증된 산출물을 읽는다.
검색 결과는 `SearchHit(product_id: str, score: float)`이며 정규화한 query 벡터를 입력한다.
상품 hybrid 벡터는 search.fusion, query hybrid 벡터는 search.query_fusion 설정을 사용한다.
`create_service(cfg,store)`와 JSON/multipart API 처리는 B2b에서 제공할 예정이다.

## 실제 dev 실행 결과

상품 10,000개의 텍스트·이미지 임베딩 `(10000,512)`와 세 HNSW 인덱스를 만들었다.
고유 텍스트 1,439종/이미지 256종만 인코딩했고 나머지는 내용 캐시로 ID별 벡터를 복원했다.
32개 상품을 고정 seed로 골라 query 전처리로 다시 인코딩한 벡터가 저장된 벡터와 일치함을
확인했다. text→text/image→image exact self-content top score≈1 및 저장·재로드 검색 parity도 통과했다.

| 진단, k=10, 쿼리 32개 | exact ID 겹침 | exact kth score 기준 동점 허용 일치율 |
|---|---:|---:|
| text→text | 0.890625 | 1.000000 |
| image→image | 0.212500 | 0.906250 |
| text→image | 0.228125 | 0.718750 |
| hybrid→hybrid | 0.925000 | 1.000000 |

이 수치는 **동일 벡터의 ANN/exact 검색 비교**이며 PDF Recall@300이나 relevance MRR/NDCG가 아니다.
동일 내용의 여러 상품 때문에 raw ID overlap은 낮아질 수 있다. 동점 허용 일치율도 image와
cross-modal에서 1에 미달하므로 B2b에서 efSearch와 중복 벡터에 대한 검색 동작을 진단해야 한다.
현재 표를 검색 품질 통과로 해석하지 않는다. HNSW 점수와 원 벡터 IP의 최대 오차는 5e-7 미만이다.

별도 cross-modal 내용 검사를 위해 black shirt/red sneakers/blue jeans/white coat/pink bag을
조회해 top5 상품의 카테고리와 색을 저장했다. 일부 쿼리는 요구 색과 다른 상품이 선두에 나온다.
합성 실루엣과 CLIP의 실제 표현을 관찰한 결과이며 정답 하나만 지정하거나 실패를 숨기지 않는다.
검색기에 relevance 정답 집합을 전달하지 않았다. B2b의 독립 증강 쿼리와 고정 relevance에서
모드별 품질을 측정하고 valid에서 진단·선택한 뒤 full test를 평가해야 한다.

근거: [실측 진단](results/search_b2a_dev.json), [환경 검사](results/search_b2a_environment.json),
[B2a gate](results/gates/B2a.json). 세부 shape/norm/정렬, corrupted image, 중단/손상 재개,
호환성, IVFPQ 표본 부족, explicit IP, sentinel/ID 복원, save/load parity, 별칭/relevance 테스트를 수행했다.
단위 테스트의 fixture encoder는 무결성 검사 용도이며 실제 CLIP 결과는 별도 verify 실행으로 확인했다.

## 재현과 후속 작업

```bash
source scripts/local_env.sh
export HF_HUB_OFFLINE=1
SCALE=dev .venv/bin/python -m src.search.build_embeddings
SCALE=dev .venv/bin/python -m src.search.build_index
SCALE=dev .venv/bin/python -m src.search.verify
.venv/bin/python -m pytest -q tests
```

설치 캐시가 없는 새 clone에서는 먼저 생략 옵션 없이 `bash setup_env.sh . --role=A`를 실행한다.
완성된 버전은 검증 후 재사용하고 중단된 청크는 동일 버전에서 재개한다.
모델 revision/카탈로그/전처리가 달라지면 새 fingerprint 버전을 생성하고 기존 버전을 덮어쓰지 않는다.
seed=42를 고정하지만 플랫폼·threaded HNSW 삽입의 비결정성을 명시한다.

**B2a 구조 검증은 PASS, full 최종 검색 품질·HTTP 지연은 UNMEASURED다.**
다음 단계는 B2b이며 MRR≥0.55, NDCG@10≥0.50, total p95≤200ms 기준을 유지한다.

구현 API 근거: [Transformers 4.46.3 CLIP](https://huggingface.co/docs/transformers/v4.46.3/en/model_doc/clip),
[FAISS index 설명](https://github.com/facebookresearch/faiss/wiki/Faiss-indexes),
[FAISS 학습 표본 안내](https://github.com/facebookresearch/faiss/wiki/FAQ).

## B2b — 검색 API·고정 품질 평가·실제 HTTP 성능

### 검색 방식과 중복 처리

`searcher.py`, `service.py`, `api.py`, `queries.py`, `eval_search.py`, `benchmark.py`,
`finalize.py`를 추가했다. SearchService factory는 공통 앱 lifespan에서 검증된 모델과
인덱스를 한 번 로드한다. 모델 pointer가 없으면 503 readiness를 유지하고, 존재하는
모델이 손상/비호환/불완전하면 시작을 실패시킨다. 임의의 랜덤 모델은 사용하지 않는다.

동일 벡터를 HNSW에 반복 삽입하지 않도록 전체 product ID를 유지한 채 벡터별 membership을
저장한다. full text/image/hybrid HNSW의 실제 row 수는 각각 1,440/256/2,880이다.
전체 50,000개 상품을 각 membership에 정확히 한 번 포함하고 결과에서 ID를 복원한다.
생성된 합성 데이터의 벡터 중복률은 text 97.12%, image 99.488%, hybrid 94.24%다.
상품을 삭제하거나 정답 집합을 변경한 것이 아니다. cutoff 이후 상품은 membership에서
가용성 필터로 제외한다. 이 수정은 [FAISS가 안내한 중복 벡터 처리](https://github.com/facebookresearch/faiss/wiki/FAQ#searching-duplicate-vectors-is-slow)를 따른다.

valid 600개만으로 text→text/text→image, image→image/image→text 및
hybrid query→text/image/fused gallery를 비교했다. hybrid query text weight는
0.25/0.50/0.75, efSearch는 32/64/128/256을 비교하고 NDCG, MRR, 작은 efSearch 순서로
선택했다. query fusion은 normalized projected vectors에 적용하며 image-only는 제출한
이미지를 실제 CLIP으로 인코딩한다. relevance나 frozen query ID를 검색기에 전달하지 않는다.

최종 선택: **text→text, image→image, hybrid(텍스트 75%+이미지 25%)→text**, efSearch=32.
기존 text/image/hybrid gallery를 모두 저장하며 gallery fusion은 0.5/0.5다.
hybrid 입력 이미지는 실제 query 벡터에 기여한다. model/index 선택에 test 점수를 쓰지 않았다.

### 품질 쿼리와 정답 고정

점수 계산 전에 dev/full 각각 valid seed=42001, test seed=42002로 세 모드의 쿼리를
200개씩 고정했다. 카탈로그 생성 seed=42와 평가 seed를 분리했고 manifest·이미지 해시를
검사한다. 품질 쿼리 이미지는 새 렌더링/회전 ±6도/이동 ±4px/brightness·contrast 0.9~1.1로
생성했으며 카탈로그 JPEG와 동일한 바이트는 하나도 없다.

text/hybrid 정답은 명시된 category_l3·color·선택적으로 style을 모두 만족하는 상품 집합이다.
image 정답은 그림으로 알 수 있는 category_l1·color만 사용한다. 브랜드/가격/원본 ID를
이미지 정답 조건에 넣지 않는다. 카탈로그 속성은 query의 생성/평가에서 쓰고 runtime 검색에는
정답 조건을 전달하지 않는다. valid cutoff=train_end, test cutoff=valid_end이고 두 검색 방식의
가용 후보 정책이 같다. full test의 cutoff 카탈로그는 48,872개다.

MRR은 top10의 첫 relevant item rank, NDCG@10은 공통 `src/evaluation/metrics.py`의
binary multi-relevant 정의를 사용한다. 평균은 모드별 200개, 전체 600개 macro query다.
동일 내용의 여러 상품을 relevant로 인정하고 임의 원본 ID 하나만 정답으로 삼지 않는다.
중복 bucket에 관련 상품이 충분히 많아 이 합성 평가에서는 MRR과 NDCG가 같은 값으로 나왔다.
이는 실제 쇼핑 고객의 관련성이나 다양한 현실 사진에 대한 일반화를 보장하지 않는다.

| 모드 | valid MRR/NDCG@10 | 최종 full test MRR/NDCG@10 | BM25 full test | HTTP p95, ms |
|---|---:|---:|---:|---:|
| text | 0.965 / 0.965 | 0.940 / 0.940 | 1.000 / 1.000 | 52.149 |
| image | 0.910 / 0.910 | 0.880 / 0.880 | 적용 불가 | 137.806 |
| hybrid | 0.970 / 0.970 | 0.975 / 0.975 | 1.000 / 1.000 | 178.251 |
| 전체 | 0.948333 / 0.948333 | **0.931667 / 0.931667** | 이미지 포함 평균 계산 안 함 | 최대 모드 **178.251** |

BM25는 같은 text/hybrid 쿼리·별칭·정답·cutoff 후보 집합에서 평가했다. 합성 메타데이터의
키워드가 정확히 맞아 BM25가 더 높다. CLIP 기반 text는 -6.0%, hybrid는 -2.5%이며
개선이라고 바꾸어 쓰지 않는다. image-only BM25는 실제 텍스트가 없어 N/A다.
모드별 ANN의 exact kth score 동점 허용 일치율은 모두 1.0이다. raw ID overlap과
벡터 점수 오차도 결과 JSON에 별도로 남겼으며 relevance MRR/NDCG와 혼합하지 않는다.

### API와 C 인계

공통 `src.serving.main:app`은 factory를 자동 로드해 JSON/base64 검색을 제공한다.
**JSON과 multipart 모두 지원하는 실행 진입점은 A 어댑터 `src.search.api:app`이다.**
이 어댑터는 공통 앱을 감싸므로 기존 health/recommend/event/feedback 경로도 유지한다.
C는 B8/서빙 통합에서 이 entrypoint를 쓰거나 `SearchTransport(shared_create_app(...))`로
자신의 Redis FeatureStore를 주입한 공통 앱을 감싼다. A는 C 소유의 main/Docker 파일을 수정하지 않았다.

`POST /api/search`: JSON `query_text`, base64/data-URI `query_image`, 정수 `top_k`(1~100).
multipart도 같은 필드를 사용하며 `query_image`는 이미지 파일 또는 base64 문자열이다.
입력 없음·잘못된 이미지/base64·k·추가 필드는 422, 8MiB 초과 body는 413이다.
text/image/hybrid 200과 JSON 필드 계약, multipart hybrid 200을 실제 HTTP로 확인했다.
`total_count`는 요청 시점에 가용한 전체 카탈로그 크기이며 응답 페이지 길이가 아니다.
`latency_ms`는 서비스 내부 이미지 decode/CLIP/검색/상품 후처리를 포함한다.

### 실제 CPU HTTP 지연과 실패 기록

full 카탈로그, CPU, WSL2 ARM64, logical CPU=8, FAISS threads=4 환경에서
각 모드 10회 warm-up 후 서로 다른 valid 요청 100회를 concurrency=1로 측정했다.
실제 localhost Uvicorn+HTTPX 왕복을 사용했고 request validation/직렬화·decode·CLIP·ANN·
후처리를 포함한다. 모델 로드 시간은 제외하고 p50/p95/p99·개별 요청을 저장했다.
요청 이미지/쿼리 결과를 캐시하는 최적화는 사용하지 않았다.

처음 torch threads=4의 hybrid p95=276.784ms로 실패했다. valid 요청으로만 threads=1/2/4를
비교했고 2 threads=206.986ms도 실패했다. 세 모드의 최대 p95를 최소화하는 1 thread를
선택했고 모든 모드가 nominal 200ms 이하다. CPU ±50ms 완화는 적용하지 않았다.
실행 thread 설정만 바뀌었고 모델·데이터·정답·검색 mode/fusion 선택은 유지했다.
최종 CPU 설정으로 query vectors/test 평가를 재생성했으며 최초 4-thread test 결과도 보존했다.
이 수치는 현재 호스트의 결과이며 최종 Docker 자원 배분의 재현은 C B10/INTEGRATE에서 다시 측정한다.

### 검증·근거·재현

전체 API 계약 테스트는 명시적인 미준비 모델 경로로 격리하여 개발자 로컬 cache 유무에
좌우되지 않는다. fixture encoder 검사는 무결성/계약 용도이며 실제 CLIP과 성능은 pytest 밖의
실제 평가/HTTP 명령으로 측정했다. 새 의존성은 추가하지 않았다.

- [full 최종 검색 결과](results/search_metrics.json), [test per-query/ANN/BM25](results/search_test_full.json)
- [valid 선택/실험](results/search_valid_full.json), [동결 쿼리 manifest](results/search_queries_full.json)
- [실제 HTTP 요청 샘플](results/search_latency_full.json), [CPU 실행 선택](results/search_runtime_selection.json)
- [4-thread 미달](results/experiments/A/search_latency_threads4_full.json), [2-thread 미달](results/experiments/A/search_latency_threads2_full.json)
- [최초 test 결과](results/experiments/A/search_test_threads4_full.json), [고정 선택 근거](results/search_selection_full.json)
- [B2b gate](results/gates/B2b.json), [환경 검사](results/search_b2b_environment.json)

```bash
source scripts/local_env.sh
export HF_HUB_OFFLINE=1
SCALE=full .venv/bin/python -m src.simulator.generate
SCALE=full .venv/bin/python -m src.search.queries
SCALE=full .venv/bin/python -m src.search.build_embeddings
SCALE=full .venv/bin/python -m src.search.build_index
# 새 clone에서는 valid 선택을 기록하고 Codex가 설정 일치를 확인한 뒤 test를 실행한다.
SCALE=full .venv/bin/python -m src.search.eval_search --split valid --sweep
# selection.json과 현재 설정이 일치해야 test를 실행할 수 있다.
SCALE=full .venv/bin/python -m src.search.eval_search --split test
SCALE=full .venv/bin/python -m src.search.benchmark
SCALE=full .venv/bin/python -m src.search.finalize
SCALE=full .venv/bin/python -m uvicorn src.search.api:app --host 127.0.0.1 --port 8000
.venv/bin/python -m pytest -q tests
```

새 clone에서도 사람이 코드를 편집하지 않고 `A 다음 단계 실행`으로 Codex에 재생성과
설정 확인을 요청할 수 있다. 이미 기록한 선택으로 재개할 때는 selection을 재사용하며,
기존 frozen test/쿼리를 튜닝에 사용하지 않는다. 검색 단계는 PASS이고 최종 시스템의
global acceptance는 UNMEASURED로 유지한다.
