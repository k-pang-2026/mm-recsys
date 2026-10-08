# 공유 데이터·모델·평가 계약 v1

SHARED에서 상세 타입(src/common/schemas.py)과 생성 스키마를 구현했다. A/B/C는 이 버전을 공통 기반으로 사용한다. 변경 시 계약 버전과
데이터 fingerprint를 바꾸고 영향을 받는 파생 산출물을 다시 생성한다.

| 객체 | 최소 필드 / 의미 | 소유 / 소비 |
|---|---|---|
| products | product_id(str), name, category_l1/l2/l3, brand, color, style, attributes(JSON string), price, created_at(UTC), image_path, image_sha256, visual_group, description_en | A / A,B,C |
| users | user_id(str), age_group, gender, signup_at(UTC), persona. 미래 행동/잠재 선호는 사용자 입력 피처로 저장하지 않음 | A / B,C |
| events | event_id, user_id, product_id(null 허용 search), event_type, timestamp(UTC), session_id, query, impression_id, position | A / B,C |
| impressions | impression_id, request_id, user_id, product_id, exposed_at, position. 클릭/전환은 노출 이후의 이벤트로 linkage | A / B,C |
| splits | 같은 event_id가 한 split에만 존재. timestamp,event_id 정렬; 동률 timestamp는 같은 split. 실제 8/1/1 오차 보고 | A / B,C |
| split_manifest | seed, reference_time, catalog/event hash, split boundary, counts, generator/config version, cutoff policy | A / A,B,C |
| embeddings | aligned ids.json + float32 (N,d) + modality/model revision/normalization/catalog hash manifest | A / A |
| model_bundle | two_tower.pt, item_index.faiss, item_ids.json, feature vocab/scalers, meta.json; config/data hash와 차원/metric/index/model version 일치 | B / C |
| FeatureStore | get_features(user_id), append_event(event), update_reward(feedback), batch_load_profiles(profiles); typed result / memory 또는 Redis backend | C / A,B,C |
| results | run_id, scale, dataset/config/model/evaluation fingerprint, split/cutoff, query/user/item counts, metrics, baselines, environment, status | C 정의 / A,B,C 작성 |

ID 문자열을 DataFrame 행 번호/FAISS 정수 label과 혼용하지 않는다. index `-1`은 제외하고
저장된 명시적 mapping으로 복원한다. price 등 정규화/vocab은 train-only로 fit한다.
카탈로그와 등록일은 컷오프 당시 알려진 정보만 사용하며 미래 등록 상품을 이전 후보 풀에 넣지 않는다.

## 후보 평가 (PDF Recall@300)

- valid cutoff=train_end, test cutoff=valid_end. 각 컷오프 이전 관측 행동만 고정 사용자 히스토리에 사용한다.
- 학습은 train-only, valid는 모델/epoch/인덱스 선택에만 사용. 모델 선택 후 test는 최종 평가한다.
- 기본 truth `R_u`는 해당 평가 구간의 cart/purchase **고유 product_id 집합**이다. search/null과 중복 이벤트를 제외한다.
- 각 사용자의 컷오프 당시 후보 카탈로그 `C_u` 전체를 검색하고 `Top300_u`를 만든다.
- `Recall@300 = mean_u(|Top300_u ∩ R_u| / |R_u|)`; `R_u`가 빈 사용자는 평균에서 제외하고 수를 보고한다.
- `|R_u|>300`이면 max recall `min(300,|R_u|)/|R_u|`도 보고한다. 추천되지 못한 truth를 사후 삭제하지 않는다.
- 미래 등록 때문에 검색 불가능한 truth, 관측 이력 없는 사용자, 반복 구매를 별도 cohort로 분해하되 primary 평균에서 숨기지 않는다.
- known purchase 제외 기본값 false. 제외 정책을 켜면 primary와 별도 정책 평가를 함께 보고한다. truth와 후보 정책을 어긋나게 두지 않는다.
- 학습 네거티브는 target 시점에 등록된 상품에서 랜덤 4개/positive; 해당 시점 이전 positive와 현재 positive만 제외한다. 미래 positive로 exclusion 집합을 만들지 않는다.
- 평가 시 랜덤 negative 4개 중 맞히는 분류 성능은 Recall@300이 아니다. 전체 카탈로그 top300만 primary.
- 모니터링용 rolling evaluation(이벤트 전에 이력을 갱신)은 별도 이름으로 보고하고 fixed-origin 결과와 섞지 않는다.

## 검색 평가

B1에서 관측 속성 기반 relevance 규칙과 독립 query 생성/augmentation seed를 확정한다.
텍스트: 쿼리에 명시된 카테고리/색 등 속성을 모두 만족하는 상품을 relevant로 한다.
이미지: 그림으로 관측 가능한 L1 카테고리/색/패턴으로만 relevance를 정의한다.
그림에서 알 수 없는 브랜드/가격/상품 ID를 이미지 정답 조건에 넣지 않는다.
하이브리드: 두 입력의 관측 가능한 조건을 일관되게 결합한다. 브랜드 문자열 처리 등 별도 필터를
사용하면 공개하고 CLIP-only 수치와 분리한다. 정답 집합 lookup을 검색기에 전달하지 않는다.

이미지 self-retrieval은 exact-duplicate 기능 검사로 별도 보고한다. 품질 평가 query 이미지는
별도 렌더링/증강 버전이며 같은 bytes를 정답 index에 주입하지 않는다. 동일 이미지·속성 상품은
동등 relevance로 처리하고 duplicate/tie 비율을 공개한다. 임의 원본 상품 하나만 정답으로
정하면 구별 불가능한 이미지에서 정확도를 제대로 측정할 수 없다.
BM25는 동일 text/hybrid 텍스트 query와 정답에서 비교하며 image-only는 적용 불가로 표시한다.
ANN recall은 같은 CLIP 벡터의 IndexFlatIP top-k와의 일치율로 따로 측정한다.

## 최종 추천과 지연

HitRate/NDCG는 동일 사용자·미래 truth에서 top50, Coverage는 설정에 고정한 최대 10,000명
사용자 집합의 top50 고유 상품/전체 카탈로그로 평가한다. 실제 대상 수와 cold-start 수를 보고한다.
검색/추천/후보/FeatureStore 모두 10 warm-up 후 100 serial 호출 p50/p95/p99를 저장한다.
API 전체 latency는 인코딩·피처 조회·모델·검색·후처리를 포함하고 별도 HTTP 왕복도 보고한다.
캐시 hit/miss와 CPU/GPU 및 컨테이너 자원을 적는다. dev 결과는 full 최종 PASS를 뜻하지 않는다.
신규 7일 판정은 오프라인 평가에서는 해당 cutoff, 모의 serving에서는 설정한 reference_time
또는 명시된 stream clock을 기준으로 한다. 고정 시뮬레이션 날짜와 실제 실행일을 혼합하지 않는다.


서비스 factory: A는 `src/search/service.py:create_service(cfg,store)`, B는
`src/recommendation/service.py:create_service(cfg,store)`를 제공한다. 구현이 존재하면
공통 app lifespan이 한 번 로드한다. SearchRequest/SearchResponse/RecommendResponse/
FeatureStore는 src/common/schemas.py에 정의되어 있다. C가 Redis를 추가할 때 public interface를 유지한다.
`/health`는 liveness, `/ready`는 두 모델 readiness다. 모델이 없으면 해당 API는 503이다.
속성 변경은 역할별 config overlay로 적용하고 data generator fingerprint에는 search/추천 설정을 넣지 않는다.

dev 데이터는 `data/`, full은 `data/full/`에 분리한다. `SCALE=full`이면 load_config가
data/split/model 경로까지 전환한다. dev 데이터에 full을 덮어쓰지 않는다.

## 최종 acceptance JSON

C의 `docs/results/final_acceptance.json`은 `scale: full`, `status`, `data_fingerprint`,
`metrics`, `checks`를 포함한다. `metrics`의 key는 config.targets와 동일하며
`candidate_count`도 포함한다. 각 값은 `{value, split, status, source, sha256}`이다.
품질/후보 수는 `split: test`, p95 지연은 `split: benchmark`; `source`는 실제 결과 파일의
저장소 상대 경로이고 sha256은 해당 파일의 실제 해시다.
checks에는 `docker_reproduction`, `api_schemas`, `ab_statistics`, `session_response`,
`ct_retrain_and_rollback`, `submission`의 `{status, exit_code, source, sha256}`를 기록한다.
`src/evaluation/acceptance.py`가 모든 수치, full 최소 개수, 데이터/결과 해시와 실행 근거를
검사한다. record_gate의 acceptance PASS와 INTEGRATE publish에서 각각 재검사한다.
결과 파일 존재/해시 검사는 결과의 진위를 대신하지 않는다. C checker는 실제 실행·산출물을 대조한다.
