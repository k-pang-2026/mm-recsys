# Multimodal Search + Multi-Stage Recommendation

Version 5 — Docker 담당 A 이관, 공통 PR 선행 후 Codex가 구현·검증하고 설명·허가 후 기능 브랜치 푸시와 PR을 처리하는 3인 가이드.
Work in the **existing repository root** (prepared by `bash setup_env.sh . --role=A`, v4).
이 문서는 앞으로 각 단계를 호출할 때의 지시서다. 문서 분석 요청만으로 모든 단계를 실행하지 않는다.
PDF가 요구사항의 기준이며, 아래 기본값/실험 설계/역할 3인은 구현 선택 또는 사용자 요청이다.

## Dispatch

`setup_env.sh` copies this file to `docs/ai_step_prompts.md` and writes root `AGENTS.md`, which tells the agent to read **section A** first. If the agent does not auto-load `AGENTS.md`, paste A once per new session.

공통 **SHARED(P0 범위 기록+B0 설정/계약+B1 시뮬레이터+기초 serving/평가/자동화)**는
팀장이 chore/shared-foundation에서 완료·검증한다. 내용을 설명하고 허가받아 브랜치를
푸시하고 main 대상 공통 PR을 생성한다. 충돌·gate·CI·품질·필수 리뷰 조건을 통과하면 공통 PR을 자동으로 먼저 main에 병합한다.
이후에는 `config/team_workflow.yaml`이 순서 기준이다.

| 담당 | 사람 | 병렬 시작 이후 순서 | 기본 브랜치 |
|---|---|---|---|
| A | 이제원 | B2a → B2b → B10 → INTEGRATE | feat/A/search → feat/A/docker → feat/integration |
| B | 박정욱 | B3a → B3b → B4 → B5 | feat/B/recommendation |
| C | 박채영 | B6 → B7 → B8 → B9 → B11 | feat/C/platform (B9 병합 후 B11 새 PR) |

A/B/C는 독립 clone에서 시작한다. C의 B9 플랫폼 PR → A B10 Docker PR → C B11 제출 PR 순서를 따른다.
B7은 B5+B6, B8은 B2b+B7, B10은 B2b+B5+B9, B11은 B9+B10을 기다리고 필요한
다른 역할의 PR이 main에 병합된 뒤 검토된 main만 자동 merge한다. 미병합 기능 브랜치를
직접 가져오지 않는다. 구조 검증과 full 품질을 구분하며 실패를 숫자 조작으로 숨기지 않는다.
`A/B/C 다음 단계 실행`은 구현·검증·필요 수정·로컬 commit·내용 설명까지 요청한 것이다.
각 기능 브랜치 push·PR 생성은 설명을 받은 사용자의 명시 허가 후에만 수행한다.
단계 실행 지시는 push 허가가 아니다. 안전한 PR 병합은 자동 수행하며 main 직접 push는 금지한다.
개발자가 직접 파일을 편집하거나 각 명령을 복사할 필요 없이 Codex가 실제 파일과 명령을 처리한다.
진행은 `scripts/team.py status`, 준비는 `scripts/team.py prepare <role>`, 실제 검사 근거는
`scripts/record_gate.py`, 푸시는 `scripts/step_git.py`로 자동화한다.
최초 사용과 CLI wrapper는 docs/codex_quickstart.md, PR은 docs/pr_workflow.md를 따른다. B12는 별도 요청한 선택 보너스다.

Always run Python via the project venv: `./.venv/bin/python` (Windows Git Bash: `./.venv/Scripts/python.exe`), never the system interpreter.

입력 예:
- `B 개발환경 준비하고 다음 단계 실행`
- `A 다음 단계 실행`
- `B 다음 단계 구현·검증하고 푸시 전에 내용 설명`
- `설명한 B B3a 커밋을 브랜치에 푸시하고 PR 생성을 승인한다` (실제 설명을 확인한 뒤 입력)
- `C 다음 단계 실행`
- `A 통합 단계 실행`
- `Recall@300 미달을 C2로 진단하고 valid에서 수정·검증한 뒤 푸시 전 설명`

CLI 한 줄: `bash scripts/codex_run.sh B`. 실행 중 runner가 publication을 맡으면 모델은
검증과 gate만 작성한다. 모델을 또 실행해 실제 commit/push를 수행한 척하지 않는다.

## A — Shared execution contract

### A1. Inspect, edit, validate

- Read repository instructions (`AGENTS.md`), relevant files, config, and existing tests first. Verify scaffolding; do not assume `setup_env.sh` ran.
- Before edits, list affected files and design in ≤5 lines. Preserve paths, public interfaces, and existing config keys.
- Make complete edits directly in the workspace; no placeholders or omitted implementations. Do not print whole files unless requested. Show concise diffs and new config keys instead.
- Implement only the requested entry. Run its checks and relevant regression tests. Repair failures before proceeding; if blocked, stop with evidence and next action.
- End with a Korean SUMMARY: changed files, commands run, observed results, gate PASS/FAIL/BLOCKED, unmet targets, run/validation commands, and expected outputs clearly labeled as expectations.
- Never invent runs, metrics, artifacts, or PASS results. Record unmeasured values as `미측정`. Do not loosen targets or change evaluation to manufacture success.
- Preserve unrelated changes. 구현·검증·로컬 commit은 진행한다. 원격 push 전에는 변경/검사/제한/commit을 설명하고 그 결과의 명시적 허가를 받아야 한다. --approved를 자동으로 붙이거나 단계 실행 요청을 푸시 허가로 해석하지 않는다. 동일 승인 commit의 push 실패 재시도는 가능하며 새 commit은 새 설명·허가가 필요하다. 삭제/volume 제거/visibility 변경은 별도 명시 요청이 있어야 한다.
- Follow the three human roles in `docs/team_workflow.md`; use persistent `feat/A/search`, `feat/B/recommendation`, `feat/C/platform`. SHARED uses chore/shared-foundation, A B10 uses feat/A/docker, and INTEGRATE uses feat/integration. C finishes and merges the B9 platform PR before A B10; after B10 is merged C uses the same platform branch for a new B11 submission PR. Stage-specific paths override role paths. Requested shared workflow maintenance uses WORKFLOW on chore/team-workflow, outside normal progression. Every branch submits a main-target PR; never commit/push main directly. Draft intermediate stages, update the existing branch PR, mark the completed feature ready, and automatically merge completed, non-draft PRs only after verifying the exact published SHA, remote gate/quality, all CI checks, required review/protection rules, and clean mergeability. The user authorized these safe merges; do not ask for merge approval again. Each step reports owner/reviewer, file list, branch, tests, commit hash/push state and PR draft. Use `scripts/step_git.py` to discover owned changed files (explicit list optional); no `git add .`, force push, fabricated contributions or credentials.
- Use `scripts/record_gate.py --step <STEP> --role <ROLE> --command "실제 검증 명령" --artifact <실제 산출물>` to run actual checks and write `docs/results/gates/<STEP>.json`; do not handwrite a fabricated PASS. Separate structural status from full acceptance. Failed quality results may accompany a verified implementation PR; document them visibly.
- All commits follow docs/commit_convention.md: `type(scope): 한국어 변경 요약`, title ≤72 characters. Codex supplies an actual diff summary via record_gate --summary; helper automatically generates Korean added/modified file details and measured validation evidence. Human-written messages are not required. Do not fabricate changes or tests.
- If a stage measures its mandatory full target and misses it, record `--acceptance FAIL`, even if structure passes. team.py keeps that stage as next and blocks dependents; re-run to repair it on valid. Partial-stage passes use UNMEASURED for overall final acceptance. Global PASS is reserved for the strict final_acceptance schema in docs/contracts.md.
- Secrets: `.env` holds only non-secret defaults and is committed (the repo must run after clone). Real secrets, if any, go in `.env.local` (gitignored). Never print/read secrets unnecessarily.
- New dependencies: add to `requirements.txt` (API/ML), `requirements-dashboard.txt`, or `requirements-dev.txt`, then report them in the SUMMARY.

### A2. Runtime and configuration

- Python 3.10–3.12 for the pinned scaffold (PDF minimum 3.10; Docker 3.11, code 3.10-compatible); PyTorch ≥2.0; FastAPI; Streamlit; FAISS CPU; transformers CLIP; redis-py; Docker Compose v2 (`docker compose`; mention `docker-compose` as an alias in docs). CPU support mandatory; GPU optional and disclosed.
- No external cloud APIs. Hugging Face model downloads allowed. Keep runtime local. Exclude payment, shipping, inventory, full authentication, and Kafka; identify users by ID.
- Use `src/common/config.py:load_config` for parameters, paths, ratios, strategies, and targets; `.env` for environment values. No scattered hardcoded settings. Seed with `set_seed(cfg["seed"])` (seed 42 from config) throughout, including CUDA. Set `PYTHONHASHSEED` **before starting Python**; setting it inside a running interpreter does not reseed its hash function. Seed DataLoader workers/generator and FAISS training; disclose platform/thread nondeterminism.
- Host resolution: `.env` uses Docker service names (`redis`, `api-server`). For local runs (tests, warmup, `streamlit run`, benchmarks outside Docker) run `source scripts/local_env.sh` (REDIS_HOST=localhost, API_URL=http://localhost:8000). Environment variables take precedence over config/.env values.
- Common implementation v4 (verify rather than assume): `scale/scales`, cutoff/negative/fusion/HNSW/target settings already exist; `load_config` merges SCALE and Redis env overrides. `src/simulator/generate.py` builds deterministic catalog/images/users/events/impressions/splits; run.py replays chronological event chunks. Schemas and memory FeatureStore are implemented. Model APIs return 503 until service factories exist; `/health` is liveness and `/ready` model readiness. metrics already provides MRR/NDCG/HitRate/Recall/Coverage/AUC/LogLoss/entropy. Docker is scaffolding, not completed preparation. Existing clones preserve edited files; use the PR-merged main as the common baseline. Setup copies actual source, not old heredoc stubs.
- Pin direct dependencies, share `requirements-torch.txt` between local and Docker, run `pip check`, record `installed_packages.txt` and environment. B2 starts only after importing CLIPModel/CLIPProcessor and actual text/image inference succeeds. Use documented APIs for the pinned transformers version; do not blindly upgrade to a different major release.
- Keep `src/{common,simulator,search,recommendation,serving,evaluation,ct}/`, `dashboard/app.py`, `tests/`, `docs/`, `data/`, `models/`; type-hint major functions.
- `scale: dev`: products/users/events = 10000/2000/200000. `scale: full`: 50000/10000/1000000 minimum. `SCALE` overrides config. Dev checks are not final acceptance.
- `load_config` switches full data/splits/models to `data/full`, `data/full/split`, `models/full`; dev stays in `data`/`models`. A full run never overwrites dev. Diagnose result names distinguish dev/full.
- Chronological train/valid/test = 80/10/10; stable ordering and identical timestamp groups stay together. Persist boundaries/counts/hash in split_manifest. Fit vocabularies/scalers/popularity/learned feature statistics on train only. Use observable histories before target time in training, before evaluation cutoff at valid/test fixed-origin serving. Valid cutoff=train_end; test cutoff=valid_end. Using earlier valid actions as test context is allowed; fitting on test outcomes is not. `docs/contracts.md` fixes aggregation/truth/catalog policies.
- Freeze dataset/evaluation version after train/valid pilot. Test is not a tuning set. If a genuine simulator/label defect requires a new dataset, record old failures, version the generator/data/queries/splits, regenerate all dependents and report fresh final test evaluation. Never silently strengthen preference after observing test Recall.
- Benchmarks: 10 warm-ups, 100 serial requests, p50/p95/p99; p95 determines latency gates. Record CPU, RAM, GPU use, Docker allocation, scale, config, and versions. Minimum: RAM 16GB, CPU 4 cores, storage 50GB, Docker memory 8GB.
- Preserve nominal latency targets; report the PDF's CPU ±50ms allowance separately, not as an automatic PASS or blanket relaxation of Redis's 10ms target.
- Sandbox/network may block Hugging Face or Docker. If so, report BLOCKED with the exact command for the user to run (e.g. `bash setup_env.sh <project> --prefetch-clip`), never fake the result.

### A3. API contracts and acceptance

`POST /api/search`: optional `query_text`, optional image (base64 or multipart), `top_k=10`; infer text/image/hybrid; neither input → 422.

Required response:
```json
{"search_type":"text|image|hybrid","results":[{"product_id":"...","name":"...","score":0.0,"price":0}],"latency_ms":0.0,"total_count":0}
```
Document whether `total_count` counts matches or retrieved candidates; never silently equate it with page length.

`GET /api/recommend?user_id=U0001&top_n=10`; unknown users use cold-start fallback, not 404.

Required response:
```json
{"user_id":"U0001","recommendations":[{"product_id":"...","score":0.0,"reason":"recent_view|similar_users|popular|mab_exploration","is_exploration":false}],"pipeline_latency":{"candidate_ms":0.0,"ranking_ms":0.0,"reranking_ms":0.0,"total_ms":0.0},"session_context":{"recent_clicks":[],"session_interest":""}}
```
Example strings describe allowed values, not literal output enums. Use lifespan to load models/indexes/metadata once; batch candidate inference; time stages and full requests with `perf_counter`.

Full-scale test gates: MRR ≥0.55; NDCG@10 ≥0.50; Recall@300 ≥0.30; AUC ≥0.70; HitRate@50 ≥0.20; NDCG@50 ≥0.08; Coverage ≥0.20; candidate retrieval ≥300 items within 100ms; search/recommend p95 ≤200ms; feature lookup p95 ≤10ms. Defaults: search K=10, recommendation N=10; offline recommendation evaluation K=50.

Coverage = unique items recommended (at N=50) over a fixed evaluation user set ÷ full catalog size. Fix the user-set size and N in config and report both; never compute it on a convenient subset after the fact.

Baselines: BM25 search, train-only popularity, Two Tower without ranking. Store measured results under `docs/results/`; report baseline-relative improvement and undefined ratios explicitly.

## P — Pre-flight

### P0 — Dataset scope check [SHARED 범위 기록; 최종 B11 재확인]

The PDF p.7 titles H&M, Retailrocket, and DeepFashion as "required-use datasets" but the body says they "can" be used and the mission is simulator-based. Do not silently omit this, and do not assume raw data must ship.
- Produce a short Korean question list for the reviewer/instructor: is real-dataset use required or optional; if required, which validations (H&M calibration, Retailrocket transition calibration, DeepFashion CLIP validation) and at what depth.
- Until answered, plan all three as optional calibration/validation and keep simulator full-scale acceptance as the primary path.
- Before any acquisition, verify current access, terms and intended use on the official pages (the PDF license table is assignment guidance, not a verified license). No automatic restricted downloads, no credential requests in chat, no raw-data redistribution. Record source/version/license/allowed use/acquisition steps/blocked evidence in `docs/data_sources.md`.
- Owner A, reviewer C. Record the ambiguity and simulator-first provisional scope in `docs/data_sources.md`; no download. P0 is not a blocker for B0–B10 synthetic implementation. B11 marks the dataset interpretation as unresolved until an instructor decision exists; do not claim every ambiguous requirement fulfilled.

## B — Implementation entries

### B0 — Configuration and shared contracts [SHARED에서 완료; 재구현 금지]

These common files are already implemented. Verify the SHARED gate; only an explicit common-contract change reopens this stage.
- Verify current v4 settings, selected SCALE, Redis env overrides and role overlays without replacing public keys. Legacy v2/v3 migration is already completed in SHARED.
- Configure ≥5 L1 with 3–4 L2/L1 and 3–4 L3/L2 fashion leaves, brands/colors, Markov transitions, persona parameters, reference UTC time, model/index/reranking/benchmark settings. Choice-model parameters are simulator hypotheses, not acceptance guarantees.
- Fix candidate truth=unique future cart/purchase items, macro-user Recall@300, fixed-origin history/candidate availability/exclusion policy; query relevance based on observable attributes; cold-start/cohort/coverage sample and top50. Record formulas before evaluating models.
- Define product/user/event/impression/split/model/FeatureStore/result schemas with typed interfaces. Agree which files A/B/C own; fill real names/accounts in team_workflow and README, leave unprovided identity as 미등록.
- Gate: SCALE=dev/full counts resolve correctly (full 50000/10000/1000000); invalid SCALE/Redis overrides/copy isolation tested. Three-role table and schemas exist. Commit/push workflow follows A1.

### B1 — Simulator and learnability pilot [SHARED에서 구현; 검증·버전 변경 기준]

Verify `src/simulator/{catalog,users,events,split,generate,run}.py`,
`src/evaluation/diagnose_data.py` (already shared); tests, `docs/results/data_diagnostics.json`.
- Products: fields in contracts; ≥3-level taxonomy; 3–5% new items relative to configured clock. Registration precedes events referring to an item; evaluation excludes future inventory using catalog_as_of(cutoff).
- Generate decodable RGB 224px product images with recognizable category silhouettes, color/pattern/sleeve/shape, seeded non-text variation. Plain color blocks + random icon are only a smoke fixture: they do not guarantee pretrained CLIP understands fashion. Image-independent brand/price/id must not enter image-only relevance. Save description_en with visible attributes first; Korean aliases/templates cover taxonomy.
- Preserve visual-equivalence groups and image content hashes. Distinct product IDs need not have distinguishable images. Quality queries use independent rendering/augmentation, not byte-identical indexed images; exact self-query is separate smoke evidence.
- Users: six personas, ratios summing to 1, differentiated conversion/category/price responses, some <5-history users. Persistent per-user leaf/brand tastes and session focus influence choices. Simulator latent tastes are not fed directly into recommendation features; derive preferences from observed histories.
- Within a preferred broad category, uniform sampling can make item-level future retrieval unlearnable. Current generator uses configurable leaf/brand affinities, persona price sensitivity, item-level Zipf demand, session focus and discovery/uniform noise. Color/style preferences are possible future hypotheses, not current implemented features. Do not limit each user's truth to a fixed list of 300 or inject candidate outputs into future labels.
- Generate temporal Markov search/view/cart/purchase/exit events, 1M at full; vectorize/chunk to bound memory. Repeatable NumPy Generator(seed), reference time, stable ordering; no wall-clock dates or Python hash dependent seeds.
- Generate actual impression records (including nonclicks), impression linkage and event causality. State conditional CTR/CVR denominator. No inferred nonclick labels for items never exposed.
- Persist `products/users/events/impressions.parquet`, chronological split parquet, split_manifest hash/config/generator version. CLI batch then continuous `data/stream/` or Redis; idempotent batch/single-writer semantics so Docker preparation and simulator do not regenerate data concurrently.
- **Before freeze**, diagnose on train/valid: null/duplicate/timestamp leakage, events/user, positive targets/user, preferred-category support, item-frequency concentration, top300 probability mass, popularity and history-derived category/brand/price retrieval. For a uniform support of M items, expected hit probability is min(1,300/M); 50K uniform ≈0.006, 3000 uniform ≈0.10. These are conditional illustrations, not a universal bound for arbitrary data.
- Compute a separate simulator-distribution diagnostic using latent parameters (top300 expected mass, not future sampled truth); NEVER pass latent or future target information into real model/retriever. If even the diagnostic is <0.30, identify unrealistic generator assumptions before model training. Validate realistic cohort behavior and popularity Coverage trade-off; pilot passing does not guarantee final test passing.
- Gate: dev counts/distributions/persona rates, schema/types/causality, unique counts, ratios ±2 points, four events, stable hashes, timestamp-safe split near 8/1/1, real JPEG decode and pilot diagnostics. If full frozen data already exists, first diagnose it; changes require a visible new version and archived failures.

### B2 — Multimodal search (B2a → B2b) [owner A, reviewer B]

#### B2a — Runtime, encoders, artifacts and exact-search sanity

Implement `src/search/{encoder,build_embeddings,build_index,index,bm25,eval_support}.py`
and encoder/index tests. Run sequentially; do not debug model/download/index/API all at once.
1. Confirm dependency versions + `pip check`, CPU torch/torchvision import and actual `CLIPModel`/`CLIPProcessor` text/image forward. Use `bash setup_env.sh . --prefetch-clip`; if blocked, record network/cache traceback and exact recovery command. Random-weight or all-zero embeddings are not a fallback. Cache model revision; support offline local_files_only once prefetched.
2. Use `CLIPModel.get_text_features`/`get_image_features` projected vectors, **not** raw `last_hidden_state`, pooler output or classification logits. `eval()` + inference_mode; validate `model.config.projection_dim` for both modalities. Text tokenizer truncation to actual max length (77 for default checkpoint); processor RGB decoding; FP32 finite nonzero output and unit norms.
3. CLIP default English text path: shared Korean→English taxonomy/color/style alias conversion for catalog and queries. Unknown terms reported; do not feed a different multilingual text encoder into the original image space without alignment. Store raw query, encoded text and applied aliases for diagnosis.
4. Save separate text/image vectors `(N,d)` plus aligned product IDs, stable order/content hashes/catalog/model/processor revision/normalization manifest. Resume per completed chunk with matching fingerprint only; cache identical **content**, not filename/product ID. Atomic finalization; never mark partially written arrays complete.
5. First validate exact IndexFlatIP on normalized vectors: text→text, image→image and text→image sanity fixtures. Cross-modal checks inspect ranking/content, not fabricated expected thresholds. Query vectors use identical preprocessing. FAISS row labels map through saved item_ids; reject -1/out-of-range/stale mappings.
6. Search index default **HNSW with explicit METRIC_INNER_PRODUCT**; PDF p.4 permits HNSW or IVFPQ. Set M/efConstruction/efSearch from config (efSearch at least query k) and bounded thread count. IndexFlatIP is diagnostic reference, not the final substitute for mandated ANN.
7. If IVFPQ requested: train normalized, representative vectors, explicitly metric=IP; require d%m==0, train count ≥ max(39*nlist,39*2**nbits) for recommended sampling, distinguish FAISS warnings from hard errors. At nlist=256, 9984 training samples nearly exhaust dev 10000; a further random subsample may violate guidance. Reject/ask for configured smaller nlist or use declared HNSW; do not silently swap index/metric.
8. CLI: `SCALE=dev ./.venv/bin/python -m src.search.build_embeddings`, then `... -m src.search.build_index`. Tests cover shape/norm/correct ID alignment, corrupted images, incomplete resume, incompatible manifests, insufficient IVF samples and save/load search parity.
- Gate B2a: real projected encoders + complete manifests + exact/ANN integrity. Search quality and HTTP latency may still be 미측정. Save gate B2a.json and share validated artifacts/interfaces with C.

#### B2b — Query modes, relevance, API and quality tuning

Implement `src/search/{searcher,service,eval_search}.py`. Provide `create_service(cfg,store)` returning SearchService per src/common/schemas.py. Shared main lifespan auto-loads this factory. Publish search metrics via shared evaluation contract; C aggregates them without editing A files. Keep the entry `python -m src.search.eval_search` executable.
- Keep separate modality indexes or implement explicit normalized fusion. Do not discard separate vectors and force every text/image query against an arbitrary 50/50 catalog blend. Compare text→text, text→image, image→image, fused-gallery variants on valid; choose documented mode-specific weights. Hybrid query uses normalized weighted text+image vectors with config weights; image-only genuinely encodes the submitted image.
- Freeze independent valid/test queries + relevance rules from B1. Grade only observable attributes; image self-identification/duplicate ambiguity separate. Multi-relevant MRR and binary/graded NDCG must match the frozen definitions; do not set source item as the only answer for indistinguishable visuals.
- BM25 shares text normalization/queries/relevance/candidate availability; image-only BM25 is N/A. Text/hybrid comparison and all mode metrics saved, no image-only BM25 fabricated.
- Support JSON query_text and base64 query_image plus explicitly documented multipart fields. Pydantic/request validation: neither input, invalid base64/image, invalid k → 422. Infer mode, ensure A3 fields/float timings. total_count meaning documented consistently; HTTP models loaded once in lifespan, no per-request initialization.
- Default HNSW sweep efSearch and record **ANN agreement vs exact** separately from human/attribute relevance MRR/NDCG. IVF experiment varies nprobe and sample quality separately. If exact quality fails, ANN tuning cannot fix encoder/relevance defects; inspect aliases, image fidelity, truncation, duplicate ties and fusion. Select on valid, measure fixed test after selection.
- Gate: tests + text/image/hybrid actual 200, missing/invalid 422, all schema fields; full frozen test MRR≥0.55/NDCG@10≥0.50 and total p95≤200ms. Save aggregate/per-mode/BM25/ANN/environment/data hashes to search_metrics.json; per-mode non-qualifying results stay visible. Never claim bare-icon CLIP achieves gates without measurements.
- Write the measured architecture/evaluation/trade-off report to `docs/search_report.md` (A-owned).

### B3 — Two Tower candidate generation (B3a → B3b) [owner B, reviewer C]

#### B3a — Evaluation contract, baselines and training integrity

Implement `src/recommendation/{features,datasets,two_tower,train_two_tower,candidate,baselines}.py`,
`src/recommendation/{eval_candidate,diagnose_candidate}.py`; tests. Executable candidate evaluation remains owned by B; C aggregates its output.
1. Verify B1 data/split_manifest and learnability diagnostics. Freeze cutoff/truth/catalog/aggregation using docs/contracts. For every training sample, history/profile aggregates precede target; no persona latent tastes or future labels in inputs. Item metadata/vocab and price scalers fit train-only with explicit UNK/PAD handling.
2. Return unique **exactly top300** for Recall@300 whenever eligible catalog has ≥300. Serving may overretrieve >300 to refill excluded items, but metric truncates to 300. No pooled positive+4-negative evaluation, category-level relevance substitution or evaluating train positives as test targets.
3. Build train-only popularity and observed-history category/brand/price baselines. At identical valid cutoff, compute all-catalog exact dot-product Recall@300, macro-user count, average truth size, empty/cold/warm/rare/new cohorts, candidate-size and eligibility diagnostics. Keep all nonempty-target users in primary average; no convenient warm-only gate.
4. User tower: recent N **observed** item-feature embeddings (mean/GRU) plus age/gender and history-derived purchase price/category/brand distribution. Reuse a compatible item/history embedding pathway; padding excluded from pooling. Item tower: separate L1/L2/L3/brand/color/style and price representations through MLP. Optional trainable item-ID residual must be declared, use UNK for new products and ablate metadata-only performance. Normalize both final `(batch,d)` outputs.
5. Train positives purchase/cart/view weights configured; exactly four **random** valid catalog negatives per positive (PDF p.6). Exclude only current/previous observed positives, not future test positives. Sample with independent seeded generators; report collisions and impossible-small-pool policy. False negatives/in-batch positives are masked using past/current observable positive relation only.
6. Default sampled-softmax across positive+4 random negatives, logits dot/temperature (initial 0.1), AdamW. If BCE used, explicitly scale cosine logits/calibrate temperature; unscaled normalized cosine logits have a narrow range and may make retrieval learning weak. In-batch/hard negatives are separately reported ablations, not a hidden replacement for required random 1:4.
7. Monitor weighted loss, positive/negative score margin, user/item norm and collapse diagnostics, actual gradient/update counts and valid **all-catalog Recall@300** each epoch. Early-stop on valid Recall, not just loss or binary accuracy/AUC over sampled negatives. Save best checkpoint, not last unconditionally.
8. Before full training, deliberately overfit a tiny **train-only** fixture with fixed negatives. Confirm loss declines and expected positives rise (fixture is debugging only). If not, fix label sign, detach/no_grad mistakes, optimizer registration, mapping, normalization/PAD and feature mismatch before expensive tuning.
- Gate B3a: sample timestamp/negative policy, shape/norm/repeatability/gradient/ID mapping tests, tiny train-fit and valid diagnostics pass. Record validation Recall even when <0.30; no test tuning. Freeze feature and model_bundle contract for C.

#### B3b — Full catalog ANN, Recall diagnosis and measured improvement

- After best checkpoint load, compute every eligible product embedding via eval/inference_mode; persist matched IDs/vocab/scalers/model/config/data hashes. Build configured HNSW/IP (or explicit IVF with validated training). Use **models/v1.0/** from the start, same format as B9 registry; no v1→v1.0 migration mid-pipeline.
- Exact reference: `IndexFlatIP` over identical normalized item embeddings. Final ANN agreement@300 compares ANN IDs to exact top300. PDF Recall@300 compares recommendations to future item truth; they are different denominators. Compare both under identical exclusions/catalog and measure feature+user-tower+FAISS+refill latency.
- If Recall misses 0.30, follow this order and write `candidate_diagnostics.json`:
  (a) metric correctness: full catalog, macro aggregation, unique targets, cutoff/positive/exclusion policy, unseen users, ID mapping, target availability; fix defects without dropping hard cases;
  (b) data signal: uniform-support mass, repeated behavior, history coherence, train/valid baseline Recall and tiny overfit. If observed-history baseline beats model, focus on training/feature defects; if even latent expected-mass diagnostic is low, explain item-level irreducible noise;
  (c) training: score margins, representation collapse, BCE scaling/temperature, sampling collisions, price/vocab/sequence consistency, early-stop criterion, data loader updates;
  (d) ANN: exact high but ANN low → metric/normalization/ID/index staleness and efSearch/nprobe. Exact low → encoder/loss/data; ANN tuning is insufficient;
  (e) bounded valid ablations: history pooling/recency; explicit category-brand-price cross-signal; temperature 0.05/0.1/0.2, d=64/128, epochs/patience; change one factor, record resource time and full-catalog valid recall. Repeat selected config with seed42; optional additional seeds are diagnostics only.
- Primary pipeline remains learned Two Tower retrieval. A hybrid popularity/profile candidate union may be an explicitly named experiment, but cannot quietly count as pure Two Tower acceptance. Improving Ranking does not restore positives absent from top300 candidates.
- Fixing generator defects after freeze requires explicit versioned reset and fresh evaluation, never deleting unpopular targets, increasing K above300 to claim Recall@300, truncating truth, supplying target IDs or lowering the PDF threshold.
- Gate B3b commands: train_two_tower, tests/test_two_tower.py, eval_candidate (valid/test split explicit), bench candidate. Full frozen test Recall@300≥0.30; ≥300 distinct candidates within p95≤100ms. Save popularity/exact/ANN/cohort scores, eligible counts, baseline lift, checkpoint selection, data/config/index hashes and environment to candidate_metrics.json. Save failure runs too. Passing architecture or dev gate is not full acceptance; no promise of 0.30 without actual run.

### B4 — DeepFM and recommendation API [owner B, reviewer C]

Implement `src/recommendation/{deepfm,ranking_features,train_deepfm,recommender,eval_ranking}.py`. Provide `src/recommendation/service.py:create_service(cfg,store)` returning RecommendationService; shared main loads this factory. Keep main/schema untouched; C reviews the adapter. B's implementation stays under recommendation so it does not overlap C's serving ownership.
- Direct PyTorch DeepFM: linear term + FM pair interactions + DNN. Do not use `deepctr-torch` (not in requirements). Sparse user/item/time fields; standardized dense price/popularity/user-price/session-count fields.
- Centralize User/Item/Cross/Context features; cross category match, price difference, brand match. Fit statistics on train and enforce event-time histories.
- CTR from linked impression outcomes: click positives vs exposed nonclick negatives. CVR as configured separate head/model with explicit conditional target/denominator; do not conflate click and purchase labels. Early-stop on valid AUC; report valid/test AUC and LogLoss (use `metrics.auc`/`metrics.logloss`).
- Flow: user/features → ≥300 Two Tower candidates → batched DeepFM → Stage 3 pass-through interface → Top N. Unknown-user popularity fallback; preserve A3 response and timing fields.
- Save Two Tower-only vs ranked HitRate@50/NDCG@50 lift in `docs/results/ranking_metrics.json`.
- Gate: `./.venv/bin/python -m src.recommendation.train_deepfm`; schema tests and `curl "localhost:8000/api/recommend?user_id=U0001&top_n=10"`; AUC ≥0.70 and p95 ≤200ms. If missed, ablate cross features before speculative tuning.

### B5 — Re-ranking, MAB, session [owner B, reviewer C]

Implement `src/recommendation/{reranking,mab,session,train_session}.py`; `tests/test_reranking.py`; `/api/event`, `/api/feedback`.
- Strategy Protocol + configured pipeline/order/sort (similarity/recency/popularity). Cold start <5 actions: popularity + recent-growth trending; diversity: configured L2/L3, maximum consecutive=2; new-item booster: ≥1 ≤7-day item when available.
- Epsilon-Greedy and UCB; common extension interface for Thompson. Arms=item/category; click/purchase rewards; Redis state with memory fallback; default 1–2 exploration slots, flags/reasons per A3. Validate small N and insufficient candidates; document feasibility limits rather than fabricate items.
- Ensure final output preserves diversity/new-item/exploration constraints after all insertions; deduplicate and revalidate. Report impossible constraints explicitly.
- `/api/feedback(user_id,product_id,event_type)` updates rewards with documented attribution/idempotence policy.
- Train GRU/Transformer next-click session encoder reusing item embeddings; combine short-term vector with user long-term vector via configured weighted sum or concat+MLP. CLI: `python -m src.recommendation.train_session`.
- `/api/event(user_id,product_id,event_type)` updates recent clicks/session count in Feature Store; use a functional store interface now, complete Redis backend in B6. Fill recent_clicks/session_interest.
- Gate: 100 randomized reranking cases; cold start; new item; exploration count/flags; config-only strategy swap. Send three controlled clicks and show changed recommendations/interests on a reproducible fixture; inspect five outputs; maintain p95 ≤200ms.
- Write `docs/recommend_report.md` with measured candidate/ranking/session results and unresolved limitations (B-owned).

### B6 — Redis Feature Store [owner C, reviewer A]

Implement `src/serving/{feature_store,warmup_features}.py`; `src/evaluation/bench_latency.py`; tests with fakeredis/local Redis.
- `fakeredis` is in requirements-dev.txt. Local runs/tests use REDIS_HOST=localhost (`source scripts/local_env.sh`, see A2); inside Docker the host is `redis`.
- Connection pool and config; recent_views LIST with cap, session_clicks counter and session TTL, profile HASH. Apply consistent expiration/session-reset semantics.
- `get_features(user_id)` uses one pipeline round-trip; Redis failure returns empty features and warning without taking serving down.
- Batch profile loading (1000); simulator streaming updates store. Set Redis maxmemory=1gb, allkeys-lru.
- Gate: `./.venv/bin/python -m src.serving.warmup_features`; p95 ≤10ms with environment recorded; unavailable Redis still permits recommendation 200 with fallback.

### B7 — A/B simulation [owner C, reviewer A]

Implement `src/evaluation/ab_test.py`; `tests/test_ab.py`.
- Config strategy registry: control popularity/Two Tower-only; treatment full pipeline with MAB. Seeded user assignment; 5000/group and 30 simulated days as configured **experiment defaults from PDF p.12 examples**, not extra mandatory PDF thresholds; dev proportional.
- Generate outcomes from persona preference/price/conversion model, not hardcoded treatment advantages. Independent arm state, no cross-arm contamination; deterministic per-user streams for fair comparison/reproducibility.
- Report CTR, CVR, exploration rate, lift; both two-sided Z-test and chi-square, p-value and 95% difference CI. Declare experimental unit and denominators; aggregate independent user outcomes or use cluster-aware inference for repeated exposures. Handle zero counts and low expected frequencies.
- Avoid flaky significance tests: fixed count fixtures for equal/clearly different rates, known CI behavior, seeded rerun equality.
- Gate: `./.venv/bin/python -m src.evaluation.ab_test`; tests pass; save `docs/results/ab_test.json` and console comparison. Significant positive lift is not guaranteed or required.

### B8 — Evaluation and dashboard [owner C, reviewers A/B]

Implement `src/evaluation/run_all.py`, final recommendation evaluation, metrics, `dashboard/app.py`.
- Evaluate search/candidate/ranking/final recommendation/store/latency; include HitRate@50, NDCG@50, Recall@300, AUC, Coverage (per A3 definition) and all baselines. Store machine-readable measured results and PASS/FAIL/UNMEASURED table.
- Streamlit/Plotly four tabs: search (CLIP/BM25, efSearch/nprobe trade-off); recommendation (targets/status); A/B (CVR,p,CI,lift); system (health,p95,CT logs,model version). Consistent colors and target reference lines.
- Read configured `docs/results/`; API_URL from `.env` (local runs: `source scripts/local_env.sh`); text/image search and user recommendation demos. Handle missing data/services without invented values. Dashboard code must not import torch/faiss (its image does not install them); use HTTP calls to the API.
- Dashboard independent container; results mount read-only.
- Gate: `./.venv/bin/python -m src.evaluation.run_all`; `./.venv/bin/streamlit run dashboard/app.py`; four tabs render and results match JSON.

### B9 — Continuous Training [owner C, reviewer B]

Implement `src/ct/{monitor,retrain_trigger,model_registry}.py`; `tests/test_ct.py`.
- Periodically compute recent HitRate@50 and CTR from attributable impressions/outcomes. Configured thresholds; alert and append `docs/results/ct_log.jsonl`.
- Count new events since last successful training; default trigger 10000; retrain Two Tower/DeepFM/session with fresh chronological splits and seed 42. Prevent duplicate concurrent triggers.
- Reuse B3 `models/v{major}.{minor}/` (initial v1.0); register version/date/metrics/config/parent/status in `models/registry.json`; initial v1.0. Promote only on configured validation improvement; otherwise retain latest/rollback.
- `/api/admin/reload`: local/internal operation, atomically swap a fully loaded compatible model/index/feature bundle; avoid downtime. Optional CT Compose profile keeps four mandatory services.
- Gate: test alert, event threshold, increment and rollback; controlled fixture demonstrates v1.0→v1.1 and log evidence. Do not fabricate improvement to force promotion.
- B9 completes the C platform feature: mark its existing Draft PR ready, then merge after approved push and all safe checks. Do not wait for B11 to merge this PR: A B10 must consume reviewed B9 from main.

### B10 — Docker and performance [owner A 이제원, reviewers B/C]

Require B2b, B5 and B9 PRs merged into main. Prepare `feat/A/docker` via `scripts/team.py prepare A --step B10`; never merge unreviewed teammate branches.
Edit `docker-compose.yml`, `docker/Dockerfile.{api,dashboard,simulator}`, `.dockerignore` (all exist as scaffold); add `scripts/{prepare_all,smoke_test}.sh` or equivalent Makefile. Use stage B10 paths; keep C-owned serving/evaluation/CT/dashboard implementations and training interfaces intact. Add Docker tests under `tests/test_docker*`; write evidence under `docs/results/docker*`, `docs/results/latency*`, `docs/results/experiments/A/` and contributions/A.md.
Write README Docker startup, ports, readiness, first-run time and resource/performance sections here. C edits submission documentation only after this B10 PR is merged. The shared search API requires A's `src.search.api:app` entrypoint for JSON and multipart; preserve common Redis/recommendation factories.
This is a completed Docker feature PR with its own title/scope, not a continuation of the merged search PR.
- Four core services: redis, api-server, dashboard, simulator. Healthchecks redis ping/API health; healthy dependencies; API mem_limit=4g; Redis settings B6; env_file; HF cache/data/models/results volumes; optional CT profile.
- CPU torch and lean images. The dashboard image installs only `requirements-dashboard.txt` (no torch/faiss/transformers); keep torch/torchvision versions identical between the local venv and API/simulator images. Reuse pinned direct requirements and requirements-torch.txt; produce reviewed platform-specific transitive locks/constraints after successful resolution. Record pip freeze snapshots but do not mislabel them as portable CPU/GPU locks. Exclude `.venv`, `.git`, bulk data from build context, not runtime mounts.
- Preparation: generate → build_embeddings → build_index → train_two_tower → train_deepfm → train_session → warmup_features. Skip only compatible complete artifacts (config/data/model fingerprints); invalidate stale outputs. Redis must be healthy before warmup; provide runnable startup orchestration.
- Ensure fresh `docker compose up --build` prepares required artifacts with a single preparation owner (API entrypoint or init service; core four still present); no simulator/API concurrent dataset generation. `/health` is liveness; `/ready` returns 503 until compatible artifacts load. Use readiness for dependent model demos with clear bounded waits/errors, no readiness deadlock. Existing prepared artifacts reuse safely. Measure and document first-run preparation time per scale (CPU-only can be long) in the README.
- Log loaded index size and model names. Smoke-test health, text/image/hybrid search, known/new-user recommendations and port 8501.
- Benchmark API/store p95; save `docs/results/latency.json`; record efSearch/nprobe/cache/batch/optional ONNX before/after results.
- Gate: nondestructive `docker compose up --build`, then smoke tests and A3 gates. Clean-volume test only after approval: `docker compose down -v && docker compose up --build`.

### B11 — Documentation and submission [owner C, reviewers A/B]

Require C B9 platform and A B10 Docker PRs merged into main. Synchronize reviewed main into `feat/C/platform`, then create a new B11 submission PR (the prior B9 PR is already merged).
Write README, `docs/ab_test_report.md`, `scripts/check_submission.py`; preserve the Docker instructions and measured evidence added by A B10, and collect A's search_report and B's recommend_report without overwriting their owned reports. Request required corrections through the integration workflow.
- README: overview, Mermaid architecture, stack/tree, fresh-start preparation/Compose commands (`docker compose up --build`, alias `docker-compose`), ports/curl, expected first-run time, config changes, limitations, **filled three-member role/contribution table** linked to actual PRs/commits. All real names are provided; unknown GitHub handles stay 미등록, never guessed. PDF does not make a separate handle field a numerical acceptance criterion.
- Reports: chronological split/cutoff, metric formulas (MRR,NDCG,Recall,HitRate,Coverage,AUC,CVR,Z-test), seed/config snapshots, baseline lifts, every A3 target/status, environment, unmet causes and measured optimization attempts. Explain CLIP contrastive space, ANN trade-off, offline item indexing, candidate-vs-ranking roles, MAB and offline/online metric mismatch.
- Populate numbers only from result JSON. Cite assignment pages for requirements, not branding or example scores.
- Submission checker: required files/modules, suspected hardcoded settings, AST type hints, mypy summary, pytest, seed usage, live API schemas if available. Unavailable checks are BLOCKED, not PASS. Confirm P0 status (dataset scope) is recorded.
- Ignore `.env.local`, bulk data/models/.venv; keep non-secret `.env` tracked; document regeneration. Provide public-repo/evaluator-access and GitHub URL checklist, branch/PR/push state and missing commits; honor an authorized stage push. Changing visibility/inviting evaluators needs that explicit request.
- Gate: run checker; attach clean clone/Docker evidence, filled A/B/C contribution evidence, actual GitHub repository URL/push commit, and requirement→file→test→result mapping. Produce `docs/results/final_acceptance.json` containing all target statuses and measured full-scale evidence for INTEGRATE. If authorized push or access verification fails, report BLOCKED command/error; never claim URL submission or accessibility merely because origin exists. Report unresolved P0 interpretation and every unmet numerical target.

### B12 — Optional bonuses [original bonus prompts]

Execute only the named bonus after mandatory gates, not automatically. ONNX needs `pip install onnx onnxruntime` (not in requirements; add to requirements-dev.txt and report).
- Query understanding: rule/dictionary price/color/category parser; ≥20 Korean price tests; filters and before/after MRR/NDCG@10.
- MMR: lambda 0/0.3/0.5/0.7/1; HitRate@50/NDCG@50/Coverage/category entropy table and accuracy–diversity plot.
- ONNX: export Two Tower/DeepFM; CPU runtime vs PyTorch p50/p95, max output error ≤1e-4; profile toward total ≤100ms.
- Thompson: Beta-Bernoulli vs Epsilon-Greedy/UCB under identical simulation; regret/convergence curves.
- Concurrency: 10/50 concurrent requests; p95 and model/Redis/FAISS bottlenecks, separate from serial acceptance.

## C — Targeted maintenance entries

### C1 — Repair

Input: failing command/log + relevant paths. Diagnose in 1–2 sentences; inspect dependencies; apply smallest fix; no unrelated refactor; rerun failing test and relevant regressions. Stop and report Korean SUMMARY.

### C2 — Metric diagnosis

Input: metric/value/target + measured JSON/logs. If missing, collect actual configs/counts/commands; do not invent root cause. Check leakage, split, labels, denominators and benchmark conditions first. For B2 use exact/ANN + visible relevance; for B3 use B3b(a–e). Rank five evidence-backed causes and falsifiable experiments. When the user has requested a fix, implement the smallest supported repair/valid experiment within that scope without a new approval round; version dataset/evaluation changes visibly. Preserve final test integrity and report before/after measured evidence.

### C3 — Review

Inspect named files for hardcoded config, missing types, leakage, unset seed, responsibility violations and missing API fields. Report file:line, severity and fix; apply approved minimal patches and test.

### C4 — Resume

Read prior gate evidence and current artifacts; restate passed/failed/blocked entries. Execute only the requested next entry. A new session must reload A (via `AGENTS.md` or paste); do not assume prior chat state.

## Source and rights note

Requirement authority: attached assignment PDF (14 pages), especially pp.3–6, 8–10, 13–14; implementation choices: original `ai_step_prompts.md`. Required schema overrides incomplete illustrative responses. Dataset scope/licensing requires P0 review. This file paraphrases only necessary technical requirements; do not copy the PDF, logos, personal details, credentials, or restricted datasets into a public repository.


## 3인 단계 완료 응답 양식

각 요청이 끝날 때 한국어로 다음을 짧게 보고한다.

- 주 담당/리뷰 담당/단계/브랜치와 실제 변경 파일.
- 실행 명령·exit code·실제 결과 경로·scale/data/model/evaluation version.
- 구조 PASS/FAIL/BLOCKED와 full acceptance PASS/FAIL/UNMEASURED를 구분.
- 측정값/목표/미달 원인/valid에서 수행한 개선·다음 필요한 입력.
- 커밋 hash·origin 브랜치 푸시/PR URL·head/base/draft 상태와 자동 병합 상태와 차단 사유. 미실행이면 미실행.

PDF pp.1,5–6,9는 GitHub 제출/접근/필수 파일, pp.13–14는 팀별 기여를 요구한다.
3인 구성, HNSW 기본값, 하위 단계 분리와 진단 실험은 이 요청을 해결하기 위한 설계 선택이다.


## INTEGRATE — 팀장 최종 통합 [이제원 A]

`A 통합 단계 실행`에서 실행한다. B2b/B5/B10/B11 PR이 모두 main에 병합되어야 한다.
scripts/team.py prepare A --step INTEGRATE로 main에서 feat/integration 브랜치를 준비한다.
실제 merge 충돌은 두 구현과 공유 contracts에 맞춰 해결하고 전체 테스트를 수행한다.
`SCALE=full`로 config/data/model/index fingerprint를 맞추고 B10 prepare/benchmark/Compose/smoke 및
B11 checker를 재실행한다. C의 final_acceptance.json 수치를 실제 산출물과 대조한다.
미달하면 담당 구현의 최소 수정과 valid 실험으로 해결하고 frozen test에 독립 재평가한다.
모든 mandatory gate가 실제 PASS일 때 record_gate --step INTEGRATE --role A --acceptance PASS와
로컬 commit·PR 미리보기를 만든 후 최종 변경·측정·제한을 설명하고 사용자의 푸시·PR 생성 허가를 받는다.
허가 후 step_git --mode publish --approved로 feat/integration을 푸시하고 main 대상 최종 PR을
생성/갱신해 원격 hash와 PR URL을 보고한다. 충돌·CI·품질·필수 리뷰 조건이 통과하면 자동으로 main에 병합하며
main 직접 push는 금지한다. Docker/권한/모델 품질
미측정은 완료 처리하지 않는다. PDF p.7의 실데이터 활용 해석은 별도로 공개한다.

## WORKFLOW — 요청된 공통 역할·실행 계약 변경 [이제원 A]

자동 A/B/C 단계 순서에는 넣지 않는다. 사용자가 공통 역할 변경을 요청했을 때만
chore/team-workflow에서 config/team_workflow.yaml, 소유권·PR 자동화, README와 가이드를 함께 수정한다.
WORKFLOW.paths의 범위를 지키고 기존 완료 gate를 덮어쓰지 않는다. 의존성 교착·브랜치 전환·
다른 역할 소유권 거부·PR 완료 시점을 실제 테스트한 뒤 별도 WORKFLOW gate와 한국어 커밋을 만든다.
설명된 변경에 대한 명시 푸시 허가 후만 발행하며, 안전한 완료 PR은 자동 병합한다.

## 단계 실행의 공통 종료 규칙 (v5)

- 사람이 코드를 작성하거나 commit 파일 목록을 조립하게 하지 않는다. Codex가 직접 구현/검사한다.
- setup 후 공통 data/split_manifest checksum을 확인하고 자신 소유의 config overlay만 수정한다.
- 서비스 factory/CLI/result 인터페이스를 유지해 다른 clone의 병렬 구현과 조립 가능하게 한다.
- 실제 검사를 record_gate로 실행하고 로컬 commit을 준비한다. 변경/검사/제한을 설명한 후
  기능 브랜치 푸시·PR 생성 허가를 받는다. CLI runner도 승인 대기에서 멈춘다.
  main은 PR 병합으로만 반영하고 안전 조건을 통과한 기능 완료 PR은 자동 병합한다. 승인한 동일 commit의 push 실패만
  기존 허가로 재시도하며 pending commit을 버리지 않는다.
- 각 role/단계의 실제 기여는 docs/contributions/<role>.md에 기록한다. GitHub 계정은 추측하지 않는다.
