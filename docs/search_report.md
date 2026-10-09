# 검색 구현 보고서 — A B2a

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
