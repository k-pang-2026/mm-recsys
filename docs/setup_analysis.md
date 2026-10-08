# PDF·프롬프트·환경 스크립트 분석과 수정 근거

현재 버전은 v4다. 아래 v3 분석·실행 기록은 원래 결함과 수정 근거를 보존한 역사 기록이다.
현재 구현/실측/첫 푸시 상태는 문서 마지막의 v4 기록과 `results/common_readiness.json`,
`results/gates/SHARED.json`, `codex_quickstart.md`를 기준으로 확인한다.

분석일: 2026-10-08 (Asia/Seoul). 기준: 첨부 PDF 14페이지, 수정 전 프롬프트 v2 232줄,
수정 전 setup_env.sh v2 606줄. 현재 저장소는 초기 README와 입력 문서만 있었고
`src/`, 생성 데이터, B2/B3 실패 로그, 학습 모델, 측정 JSON은 없었다.
따라서 아래는 **확인된 설계/설정 문제와 조건부 실패 가설**이다. 특정 실행에서의
traceback 원인이나 Recall 개선 실측을 확보했다는 뜻은 아니다. PDF 파일은 수정하지 않았다.

## 요구사항과 구현 선택의 구분

| PDF 근거 | 필수 요구 | 반영 위치 / 담당 |
|---|---|---|
| pp.3,6 | 상품≥50K, 사용자≥10K, 이벤트≥1M; 이미지/텍스트 메타, 6페르소나, 3단계 카테고리 | config full / B0,B1 / A |
| pp.3,6,9 | 시드42, 8/1/1, 설정 분리, 타입, Two Tower 랜덤 negative1:4, Ranking exposed nonclick | config, shared contracts / A,B |
| pp.3–4 | transformers CLIP text/image/hybrid, FAISS IVFPQ **또는 HNSW** | B2a/B2b / A |
| p.4 | 검색 MRR≥0.55, NDCG@10≥0.50, 응답≤200ms | search_metrics / B2b,B8,B10 |
| p.4 | 최근 행동/프로필 User Tower, 카테고리/속성/가격 Item Tower, offline item index, 후보≥300/≤100ms, Recall@300≥0.30 | B3a/B3b / B |
| p.4 | DeepFM 또는 Wide&Deep, User/Item/Cross/Context, CTR/CVR, AUC≥0.70 | B4 / B |
| pp.4–5 | 연속 동일 카테고리≤2, 이력<5 cold fallback, 탐색1–2, 신규7일 노출, GRU/Transformer 세션과 장기 선호 결합 | B5 / B |
| p.5 | HitRate@50≥0.20, NDCG@50≥0.08, Coverage≥0.20, 추천≤200ms | B8 / C + B |
| p.5 | Redis 실시간 피처/≤10ms, Compose 일괄 실행, 독립 API/대시보드 컨테이너 | B6,B10 / C |
| p.5 | ≥2 A/B 전략, Chi-square **또는** Z-test, p-value/95%CI, 대시보드 | B7,B8 / C |
| p.5 | HitRate/CTR 모니터·알림·로그량 재학습·모델 버전 | B9 / C |
| pp.1,5–6,9 | README 아키텍처/실행, docs 실험 리포트, GitHub URL, Public 또는 평가자 접근 | B11 + 단계별 Git workflow / C |
| pp.13–14 | 팀원별 역할 및 개인 주요 기여 명시 | team_workflow/contributions/README / A,B,C |
| pp.9–10 | CPU 가능, 로컬 완결, Docker 자원 조건, warm-up10/serial100/p95, CPU 허용오차 별도 기재 | A2/B10 / C |
| pp.6–7 | Query理解/MMR/ONNX/Thompson 등 **선택** 보너스 | B12, 자동 실행 금지 |

PDF는 팀 인원 3명을 지정하지 않는다. **3인**은 사용자의 요청이다. A/B/C 역할,
HNSW 기본값, sampled-softmax/temperature, 하위 단계 분리, pilot 진단은 구현 선택이다.
PDF p.12의 A/B 5000명/그룹·30일·양의 lift/p-value는 예시이며 필수 성공 수치가 아니다.
PDF p.7의 “필수 활용 데이터셋” 제목과 “활용할 수 있다” 본문은 모호하다.
P0에서 기록하고 강사 확인을 남기되 synthetic 구현 전체를 질문 응답까지 중단하지 않는다.
실제 데이터의 현재 권리·접근 조건은 획득할 때 공식 페이지로 별도 확인한다.

## 확인한 문제와 변경

아래 줄 번호는 **수정 전 입력 파일**의 위치다.

| 원래 위치 | 문제 / 영향 | v3 변경 |
|---|---|---|
| setup 22,80–82 | 기본 mm-recsys 대상이 기존 clone 안에 중첩 저장소를 만들 수 있음 | 기본 `.`; 다른 Git root 하위 생성 거부; origin 유지 |
| setup 55–63 | 모든 Python≥3.10을 선택, 최신 Python과 wheel 호환성 검증 없음 | 고정 조합은 3.10–3.12, Docker3.11, 범위 검증 |
| setup 148–197, Docker/545–554 | torch/torchvision/transformers/numpy/faiss 등 무고정; 로컬·컨테이너 버전 drift | 직접 의존성 pin, 공통 requirements-torch; pip check/버전 기록 |
| setup 553–595 | 설치·pytest·prefetch 실패를 warn으로 삼키고 완료/exit0 가능 | 실패하면 nonzero; 완료 문구는 실제 검사 이후 |
| setup 581–587 | 모델 download만 수행, CLIP 클래스 import/양 모달 실제 추론 확인 안 함 | `--prefetch-clip` projected text/image shape/finite 실제 검증 |
| setup config/프롬프트 A2,B0 | flat full 설정과 dev 계약 사이 간극, SCALE merge 미구현 | 초기부터 dev/full, env precedence, 잘못된 scale/port 검증 |
| setup seed.py | 함수 내부 PYTHONHASHSEED 설정이 현재 Python hash를 재시드하지 못함 | 실행 전 export와 Docker env; seed 함수에 실제 의미 설명 |
| setup prompts copy/AGENTS | 재실행 시 오래된 프롬프트·지침이 조용히 유지됨 | 차이 경고와 명시적 `--refresh-prompts`; 기존 설정은 보존 |
| 프롬프트 B1,B2 | 랜덤 도형/아이콘이 CLIP에 의미 있는 패션 이미지를 보장하지 않음 | 실제 관측 속성 기준 relevance, 독립 이미지 query, 데이터 진단 |
| 프롬프트 B2 | source item 정답과 matching set 선택이 자유로워 동등 이미지의 품질 해석 불안정 | B1에서 relevance를 동결; ID/self-retrieval과 의미 검색 구분 |
| 프롬프트 B2 | 512 차원/IVFPQ/fusion/API를 한 번에 구현, 실패 계층 불명확 | B2a 인코더·정합성→B2b API·품질; actual projection과 exact 참조 |
| 프롬프트 B2 | IVFPQ만 지정, dev10000에서 39×256=9984 권장 표본에 거의 여유 없음 | PDF 허용 HNSW 기본; IVF nlist/nbits/m/sample 조건 명시 |
| 프롬프트 B3 | epoch/dim/negative 조정만 제안, 데이터 예측 가능성·all-catalog 검증 없음 | B1 pilot, B3a cutoff/baseline/tiny fit, B3b exact/ANN/학습 진단 |
| 프롬프트 B3 | known positive 제외 시간/반복 구매 제외/집계·catalog 정책 불명확 | timestamp-safe negative와 고유 cart/purchase macro-user Recall 고정 |
| 프롬프트 B3,B9 | models/v1과 v1.0 버전 규약 불일치 | B3부터 v1.0 bundle |
| 프롬프트 A1,B11 | 매 commit/push 확인, 팀 기여 blank template만 제공 | 3인 owner/reviewer, 명시 승인된 단계 push 진행, scoped helper, 실제 PR/기여 증거 |
| 프롬프트 Dispatch,C2 | 하나의 품질 실패가 전 팀 개발 정체, 요청된 수정에도 재승인 유발 | 구조와 full acceptance 분리; 범위 안 valid 실험 수행; 미달 숨김 금지 |
| setup Compose/cache | 로컬/컨테이너 HF cache 경로 통일 안 됨, readiness 없는 기본 의존 | cache 경로 통일·Redis/API healthcheck; 실제 single-owner 준비는 B10에 명시 |

v2의 단일 gate/스켈레톤 자체가 곧 버그인 것은 아니다. v3도 setup만으로 완제품을
생성하지 않는다. 특히 기본 API의 빈 결과·simulator TODO는 구현 단계가 남았다는 증거다.

## B2 진단 순서

1. traceback/versions: pip check → torch/torchvision → CLIP 클래스 import → 실제 projected text/image 추론.
2. decode/tokenizer: RGB, 깨진 이미지, English aliases, max token truncation, actual projection_dim.
3. embeddings: finite/unit norm, row-ID 정합성, 모달별 vectors, content cache, 미완료 resume/stale hashes.
4. exact relevance: 이미지에 보이지 않는 brand/price/ID를 정답 기준으로 넣었는지 확인. 동등 이미지 tie를 숨기지 않는다.
5. ANN: 같은 벡터 IndexFlatIP와 HNSW/IVFPQ 비교. metric과 정규화/mapping을 먼저 맞춘다.
6. API: 모델 한 번 로딩, base64/multipart 규약, 총 p95와 422/필수 필드. 품질은 valid로 고른 뒤 frozen test 실측.

## Recall@300 미달을 해결하는 기준

`Recall@300 = mean_u(|Top300_u ∩ R_u|/|R_u|)`이고 `R_u`는 미래 cart/purchase 고유
상품이다. 전체 후보 catalog에서 검색한다. positive와 random negative4개 사이를 맞히는
분류 실험은 이 수치가 아니다. ANN agreement@300도 별도 지표다.

조건부로 상품 M개를 균등 선택한다면 top300에 들어갈 기대 확률은 `min(1,300/M)`이다.
M=50000이면 0.006, M=3000이면 0.10이다. 넓은 카테고리 선호만 있고 내부 상품 선택이
무작위라면 모델을 오래 학습해도 0.30을 보장할 수 없다. 실제 원인이 이 조건인지는
주어진 저장소에서 아직 측정되지 않았다. train/valid 분포와 history baseline으로 먼저 판별한다.
시뮬레이터 latent choice probability의 top300 질량은 진단 참고이며 모델 입력/정답 주입에 쓰지 않는다.

| 실측 증거 | 우선 조치 |
|---|---|
| tiny train fixture도 못 외움 | gradient/optimizer/PAD/label/ID mapping/코사인 logit scale 수정 |
| train 개선, valid exact 낮음 | cutoff/피처 일치·negative policy·과적합·개인/세션 신호·데이터 분포 점검 |
| history baseline이 모델보다 높음 | Tower 입력·pooling·price/category/brand 표현과 loss/temperature 검증 |
| exact Recall 높음, ANN만 낮음 | IP/L2·norm·매핑·stale index, efSearch/nprobe와 refill 검사 |
| latent 기대 질량도 낮음 | 학습 설정이 아닌 generator의 상품 선택 모델을 검토; 동결 후면 새 버전과 독립 재평가 |
| purchased 제외 시 반복 truth가 남음 | exclusion 정책을 일치시켜 primary와 별도 cohort 모두 보고 |

학습은 랜덤1:4 유지, sampled-softmax/코사인 temperature, 관측 히스토리 기반 features,
valid 전체 catalog Recall로 best epoch 선택, bounded ablation 순서로 개선한다.
K 증가·정답 잘라내기·희귀/cold 사용자 제거·미래 labels/latent preferences 입력·test 튜닝·
popularity union을 Two Tower로 표시하는 방법은 최종 통과 근거로 인정하지 않는다.
Recall≥0.30 달성 여부는 구현 데이터/모델의 실제 full 평가로만 판단한다.

## 실행과 기존 v2 이관

현재 clone에서는 기본 경로를 `.`으로 사용한다. v3는 지원 문서/스크립트를 포함한
**저장소 전체**가 배포 단위이며 setup_env.sh 한 파일만 복사하지 않는다.

```bash
# 파일 생성만 검토 (네트워크/venv 설치 없음)
bash setup_env.sh . --scaffold-only
# 실제 환경 설치 + CLIP 양 모달 추론
bash setup_env.sh . --prefetch-clip
source scripts/local_env.sh
./.venv/bin/python -m pytest -q tests
```

이미 v2가 실행된 프로젝트의 파일은 자동 덮어쓰지 않는다. 변경 파일을 보존한 뒤
새 참고 뼈대를 만들어 **선택적 diff를 병합**한다.

```bash
bash setup_env.sh /tmp/mm-recsys-v3-reference --scaffold-only --skip-docker-check
# 아래 경로는 자신이 검토할 기존 프로젝트에서 실행하는 예
# 차이가 있으면 diff의 exit1은 정상이다.
diff -u config.yaml /tmp/mm-recsys-v3-reference/config.yaml
diff -u requirements.txt /tmp/mm-recsys-v3-reference/requirements.txt
diff -u src/common/config.py /tmp/mm-recsys-v3-reference/src/common/config.py
# 검토 후 source revision과 생성본의 문서 차이도 병합한다.
```

이관 대상: schema_version/scales/search/candidate/evaluation/targets, config loader,
requirements-torch/runtime/dashboard/dev, Docker Python/torch/cache/healthcheck,
local_env/seed, AGENTS, team/contracts, step_git. 사용자 taxonomy/persona/모델/소스는 보존한다.
`--refresh-prompts`는 docs/ai_step_prompts.md만 갱신한다. AGENTS/설정/소스는 수동 리뷰 대상이다.
기존 .venv 호환성이 맞지 않으면 삭제부터 하지 말고 별도 환경으로 확인한 뒤 경로를 선택한다.

CI/PR 보호 설정과 저장소 접근은 C가 실제 GitHub 권한으로 준비하고 결과를 기록한다.
현재 요청은 파일 분석/수정이므로 실제 commit/push/visibility 변경은 수행하지 않았다.
앞으로 단계별 명시적인 commit/push 요청은 반복 승인 없이 workflow에 따라 수행한다.

## 기술 근거 (공식 자료)

- [Hugging Face CLIP 4.46.3 API](https://huggingface.co/docs/transformers/v4.46.3/en/model_doc/clip): projected text/image features와 processor, 모델별 projection/token 설정 확인.
- [FAISS metric과 cosine](https://github.com/facebookresearch/faiss/wiki/MetricType-and-distances): IP와 L2의 차이, cosine에 사용할 정규화 방식 확인.
- [FAISS FAQ](https://github.com/facebookresearch/faiss/wiki/FAQ): clustering train 표본 권장치와 표본 부족 경고 구분.
- [FAISS index 선택](https://github.com/facebookresearch/faiss/wiki/Guidelines-to-choose-an-index): exact reference와 ANN 선택의 역할 구분.
- [PyTorch 공식 이전 버전 설치](https://docs.pytorch.org/get-started/previous-versions/): torch2.6.0/torchvision0.21.0 짝과 CPU/cu124 설치 인덱스 확인.

pin은 이 API 세대의 재현 기준이다. 모든 플랫폼에서의 검증이나 최신 버전 사용을 뜻하지 않는다.
전이 의존성은 실제 `pip freeze` snapshot으로 기록하고 배포 플랫폼별 lock/constraints는 B10에서 생성한다.

## 실제 환경 검증 중 발견한 추가 오류

새 venv에서 설치 전에 `load_config`가 PyYAML을 import하는 순서 오류를 발견했고,
설치 전 schema 검사에는 표준 라이브러리만 사용하도록 수정했다. 이 경로는 site-packages가
없는 Python으로도 회귀 검사한다.

실제 ARM64/Linux·Python3.12.3에서 faiss1.9 + numpy1.26.4는
`ModuleNotFoundError: numpy.distutils`로 import에 실패했다. 공식
[FAISS 이슈3936](https://github.com/facebookresearch/faiss/issues/3936) 및
[loader 소스](https://github.com/facebookresearch/faiss/blob/main/faiss/python/loader.py)에서
SVE 탐지 경로를 확인했다. numpy2.1.3 pin으로 이 구형 fallback 경로를 피했고 실제 FAISS import/검색 및 CLIP 추론까지 통과했다.
설치 실패가 성공으로 표시되지 않는 것도 확인했다. 이 오류는 이번 테스트 환경에서의 실측이며
사용자의 과거 B2 오류 로그를 대신하는 증거는 아니다.

## 이번 수정의 검증

실제 수행한 검증 결과는 [setup_validation.json](results/setup_validation.json)에 기록한다.
setup 회귀 검사는 시스템 Python+PyYAML로 임시 폴더에서 실행한다. 생성된 애플리케이션 검사는
해당 프로젝트의 .venv로 실행한다. 네트워크·Docker·모델·최종 full 품질의 상태를 따로 표시한다.


최종 실측: bootstrap 회귀 **12개 통과**; 임시 프로젝트의 생성된 검사 **20개 통과**;
패키지 설치/`pip check`/FAISS import와 exact search/CLIP text·image `(1,512)` 추론 통과.
CLIP revision `3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268`을 고정했다.
[환경 snapshot](results/setup_environment.json)과 [설치 패키지 목록](results/setup_installed_packages.txt)을 보존한다.
Git helper의 publish 경로는 로컬 임시 저장소에서 명시 파일만 commit하고 push 실패를
BLOCKED로 보고하는지 검사했다. 실제 GitHub push/CI 실행을 수행했다는 의미는 아니다.
Docker는 WSL2 연동 미활성으로 BLOCKED. CUDA/macOS/x86_64의 실측과 full 모델 품질은 미측정이다.

## v4: 추가 요청에 따른 운영 흐름 변경

이전 v3는 환경 뼈대/문서 수정 중심이었다. 사용자는 초기 공통 구현을 끝내 첫 main push 후
이제원(A)·박정욱(B)·박채영(C)이 독립 clone에서 Codex 명령만으로 개발/검증/자동 push할 것을
요청했다. v4는 실제 common source와 simulator/시간분할/평가/API 계약/메모리 저장소,
role config overlays, 기계 판독 순서와 Git scope, gate runner, CLI wrapper를 포함한다.
setup은 파일 stub 생성 대신 현재 공통 코드를 clone에서 그대로 설치하고 실제 데이터를 준비한다.
외부 계정/Docker host 조건은 검사하며 미측정을 완료로 표시하지 않는다.
앞선 v3 검증 JSON은 역사 기록이다. v4 현재 검증은 SHARED gate와 common_readiness.json을 따른다.

v4 실제 공통 구현에서는 시간 나노초 구간×event index 연산의 int64 overflow를
발견했다. 나누기를 먼저 수행해 1M 이벤트에서도 시간 순서가 유지되도록 수정했고
상품 등록/노출/이벤트/시간 분할 인과성을 전체 dev/full 데이터에서 검사했다.
full은 dev와 다른 data/model 경로로 전환해 데이터 덮어쓰기와 모델 혼용을 방지한다.

train/valid 전용 pilot에서 관측 이력 기반 Recall@300은 dev 0.863057, full 0.790127이었다.
full popularity는 0.229502였다. 이는 관측 가능한 개인 신호가 있다는 실제 증거다.
Two Tower 학습/최종 test 통과를 의미하거나 사용자의 과거 모델 Recall이 개선됐다는 뜻은 아니다.
잠재 취향·미래 정답을 모델 입력에 공급하지 않았고 모델 test 품질은 아직 미측정이다.

일반 도구 sandbox에서는 FastAPI TestClient의 thread→asyncio portal이 멈추는 현상이
발생했다. traceback으로 확인하고 승인된 실행 권한에서 실제 API 검사를 실행했다.
테스트를 삭제/생략해 성공으로 만들지 않았다. Git/Docker/모델 등 환경 조건은 각각 기록한다.
SHARED 검증 명령/소스 해시가 첫 공통 commit의 근거다.

최신 사용자 지시: **원격 푸시 전에 작업 내용을 설명하고 허가를 받은 후 푸시**한다.
이 규칙이 앞선 자동 push 설계를 대체한다. 구현/검증/로컬 commit은 자동으로 준비하지만
원격 push는 승인 대기에서 멈춘다. helper의 publish는 --approved와 검토된 pending commit의
정확한 hash가 필요하며, 승인 전 publish·다른 commit으로의 승인 재사용을 회귀 검사한다.
현재 원격 GitHub push는 수행하지 않았다. 사용자 확인/허가 후 첫 SHARED push를 수행한다.

최신 추가 지시: 공통 커밋 메시지 규칙을 사용하고 변경 설명을 한국어로 자동 생성한다.
`docs/commit_convention.md`와 helper에 type(scope), 한국어 실제 diff 요약, 파일 상태와
검증 결과 본문을 구현했다. 영어-only/다중 행 요약은 staging 전에 거부하며 문서 변경은
별도 docs type으로 분류한다. 실제 Git fixture의 생성된 commit 메시지를 검사했다.


## 기능 브랜치와 PR에 대한 최신 지시

사용자의 최신 요청으로 앞선 첫 main 직접 push와 기능 브랜치 직접 통합 설계를 대체했다.
SHARED는 chore/shared-foundation → main PR로 먼저 병합하고 이후 3인이 독립 클론에서
검색/추천/플랫폼 기능 브랜치를 사용한다. INTEGRATE도 feat/integration → main PR로 제출한다.
main 직접 commit/push는 helper에서 거부하며 다른 역할 의존성은 PR 병합된 origin/main에서만
가져온다. 미병합/실패 의존성을 로컬 Git fixture로 검사한다.

로컬 한국어 PR 미리보기, 승인 후 기존 PR 검색/생성/본문 갱신, Draft→검토 준비 전환을 구현했다.
PR 병합은 별도 명시 허가와 정확한 SHA, CI/미해결 리뷰 조건 확인 후 수행한다. GitHub API 동작은
모의 검사로 확인했으며 실제 인증·원격 PR/CI/병합은 승인 전이라 미측정이다. 기존 공통 commit은
기능 브랜치로 옮겼고 local main은 기존 origin/main 커밋을 유지한다. 상세 절차는 pr_workflow.md다.

## Docker WSL 복구와 공통 발행 허가

사용자는 Docker WSL 연동을 해결한 뒤 공통 브랜치를 푸시하도록 명시 허가했다.
앞서 연동 미활성으로 추정한 오류의 실제 원인은 Docker Desktop 종료였다. Ubuntu의
EnableIntegrationWithDefaultWslDistro와 IntegratedWslDistros 설정은 이미 활성화되어 있었다.
설치된 Windows Docker CLI로 Desktop을 시작해 Ubuntu의 CLI/소켓/엔진 연결을 복구했다.
시작 중 업데이트로 연결이 잠시 재설정된 뒤 엔진 29.8.2 / Desktop 4.94.0 / Compose 5.5.1로
사전 검사를 통과했다. WSL 저장소 읽기 전용 bind mount와 임시 Redis 컨테이너의 PONG을
확인했고 생략 옵션 없이 setup_env.sh 전체 실행도 통과했다. 현재 근거는 common_environment.json,
common_readiness.json, docker_wsl_verification.json이다. 이전 BLOCKED 기록은 과거 상태다.

이 허가는 복구 결과를 반영한 공통 기능 브랜치 push와 합의한 PR 제출에 적용한다.
PR 병합은 별도 허가 대상이며 모델 포함 최종 4서비스 재현과 full 품질은 여전히 미측정이다.


## 안전한 PR의 자동 병합에 대한 최신 지시

사용자는 앞으로 충돌이 없고 병합해도 문제가 없는 PR은 자동 병합하라고 요청했다.
이 지시가 앞선 PR 병합 별도 승인 규칙을 대체한다. 푸시 전 설명·허가 규칙은 유지한다.
설정은 auto_merge_when_safe=true / merge_requires_user_approval=false다. 기능 완료 PR의
정확한 푸시 SHA에서 원격 gate, 품질, CI, 변경 요청과 GitHub 보호 규칙을 검사한다.
mergeable=true / mergeable_state=clean을 확인하고 쓰기 직전 head/base SHA와 PR 상태를
다시 읽는다. CI 진행 중은 최대 10분 기다리고 상태를 보존해 재개한다. 충돌·품질 미달·
실패 검사·필수 리뷰 미완료는 자동 병합하지 않으며 새 수정 commit은 푸시 허가를 다시 받는다.
이 규칙은 이미 검증·푸시된 공통 PR #1에도 적용한다.
