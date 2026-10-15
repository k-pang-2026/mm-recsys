# C 기여 기록

역할 C(박채영), 검토자 A(이제원). Git 작성자는 사용자가 지정한 chaezero03이다.
브랜치는 feat/C/platform이며 이번 범위는 B6 Redis Feature Store다.

## B6 변경

기존 공통 메모리 저장소와 같은 public interface를 제공하는 Redis backend와 factory를 추가했다.
API lifespan은 설정된 저장소를 선택하고 소유한 연결을 종료 시 정리한다.
최근 조회 LIST를 최대 50개로 제한하고 세션 HASH의 카운터·관심 카테고리·sliding TTL을 함께 갱신한다.
세션 ID 변경 시 조회 이력과 카운터를 초기화한다. 프로필 HASH는 세션 만료 후에도 남는다.
WATCH/MULTI로 이벤트·보상 중복 방지와 세션 갱신을 원자적으로 처리한다.
get_features는 한 번의 pipeline으로 일관된 스냅샷을 읽고 Redis 장애 시 경고와 빈 피처를 반환한다.

프로필 초기 적재는 1,000명 단위이며 잠재 persona와 미래 행동을 읽지 않는다.
C 소유 스트림 adapter가 공통 시뮬레이터의 parquet 청크를 소비하고 체크포인트·해시를 검증한다.
Redis 실패 시 체크포인트를 진행하지 않아 재시도가 가능하다.
API 테스트는 C 소유 pytest 지원 어댑터를 사용해 실제 Redis의 namespace를 테스트별로 격리한다. 이전 실행의 중복 방지 키나 만료 세션과 충돌하지 않는다.
CI workflow에 Redis 7 서비스와 localhost 환경, 실제 Redis 통합 검사 플래그를 추가했다. 원격 CI 실행 결과는 아직 미측정이다.
직접 의존성 추가/버전 변경은 없다.

## 실제 검증

- Python 3.12.10, CPU PyTorch 2.6.0, Redis Windows MSYS2 이식판 7.4.11을 사용했다.
- pip check 통과. 고정 CLIP revision의 텍스트/이미지 추론과 FAISS sanity 통과.
- seed 42의 dev 상품 10,000개·사용자 2,000명·이벤트 200,000개와 시간 분할 160,000/20,000/20,000을 검증했다.
- train/valid 진단에서 test outcomes를 읽지 않았다.
- 초기 전체 Windows 검사: 69 PASS/19 FAIL. B6 예외 이름 충돌 1개를 수정했다.
- Windows 실행 가능한 회귀 검사: 70 PASS. 공통 bootstrap 모듈의 POSIX /tmp 경로 관련 18개 검사는 BLOCKED다.
- B6 코드의 타입검사를 수행했다. 최종 검사 파일은 pytest 지원 어댑터를 포함한 6개다.
- 실제 Redis에 2,000명의 프로필을 적재했다. train 구간 스트림 2,100행 중 행동 이벤트 100개를 반영하고, 재실행 시 0개 추가 반영을 확인했다.
- 100명의 최대 길이 이력으로 10회 워밍업·100회 순차 호출을 측정했다. 목표 p95 10ms의 실제 수치와 원시 샘플은 latency 결과 파일을 따른다.
- Redis 장애 시 추천 200 검사는 공급된 테스트 추천 서비스를 사용했다. 실제 A/B 모델 경로의 장애 검증은 B5 병합 후 필요하다.

재현 명령은 [B6 실행 안내](../submission/b6_runbook.md)에 있다.
측정 근거는 [지연 결과](../results/latency/feature_dev.json),
[스트림 결과](../results/experiments/C/stream_dev.json),
[환경 검사](../results/experiments/C/bootstrap_environment.json),
[직접/전이 패키지 버전](../results/experiments/C/installed_packages.txt),
[train/valid 진단](../results/experiments/C/bootstrap_diagnostics_dev.json)에 저장했다.

## 제한과 다음 단계

B6 구조 검증과 전체 full acceptance를 구분한다. full 품질은 UNMEASURED이며 Docker 재현도 UNMEASURED다.
Windows build 19044와 RAM 약 8GiB 환경이므로 Windows 업데이트·WSL 2·Docker 준비와 충분한 메모리의 full 환경이 필요하다.
원격 푸시·PR 생성은 사용자의 해당 커밋 승인 후 수행한다. 이 단계의 PR은 Draft다.
다음 B7은 B5 추천 단계가 main에 병합되어 있어야 진행할 수 있다.

## 2026-10-15 새 macOS 기기 준비와 B7

역할 C(박채영), 검토자 A(이제원). 원격 C 브랜치 `7f6d922`를 추적하고,
PR #8까지 병합된 main `e5f1840`을 fast-forward로 반영했다.
fetch 대상을 main과 feat/C/platform으로 제한했으며 다른 역할의 미병합 브랜치는 가져오지 않았다.
PR #6의 B6와 PR #8의 B5 구조 gate가 main에서 PASS여서 B7을 진행했다.

macOS 26.6 arm64, RAM 24GiB, CPU 10코어에서 Python 3.11.17과 고정 의존성을 사용했다.
기본 Git/Python은 Xcode 도구 미설치로 실행되지 않아 저장소 바깥 `../.devtools/`에
Git·Python·GitHub CLI·Bash를 설치했다. 기본 Bash 3.2의 빈 배열/nounset 오류는
Bash 5.2.37로 해결했으며 공통 setup 스크립트를 수정하지 않았다.
공식 Apple Silicon Docker Desktop을 설치하고 Rosetta 시작 오류를 해소했다.
Docker 29.8.2, Compose 5.6.0, 엔진 메모리 약 8GiB와 healthy Redis 7.4.11을 확인했다.
GitHub CLI는 미인증이고 Codex CLI는 ChatGPT 로그인 상태다. 외부 푸시·PR 생성은 하지 않았다.

이 기기의 실행 진입점은 저장소 루트에서 `source .team/activate.sh`다.
이후 `bash setup_env.sh . --role=C`를 실행한다. 로컬 도구 경로, localhost 서비스,
실제 Redis 검사 및 C pytest 격리 플러그인이 적용된다. `.team/`은 커밋하지 않는다.
생략 옵션 없는 setup에서 pip check, 전체 검사, 데이터/이미지 검증, train/valid 진단,
고정 CLIP revision의 실제 양 모달 추론, Docker info와 Compose config가 통과했다.
setup 시점 242개 검사, 최종 B7 회귀 243개 검사가 통과했다.

seed 42 dev 데이터는 상품 10,000·사용자 2,000·이벤트 200,000개,
시간 분할 160,000/20,000/20,000이다. generation fingerprint
`3e1de868d26dc7c095f49d3841d98a944befd493937aa0ea3d0044e3062f889c`가 기존 B6와 일치했다.
`src.evaluation.ab_prepare`는 B 소유 trainer와 기존 config를 그대로 호출해
Two Tower·FAISS·DeepFM·세션 모델을 재생성한다. 파일·catalog·config·ID mapping·차원과
각 모델의 checksum, 실제 service load를 검사한다. 기존 비호환 산출물은 덮어쓰지 않는다.
학습은 train, 선택은 valid만 사용했다. 데이터·이미지·모델·CLIP 캐시는 모두 Git에서 제외된다.
B7에서 사용하지 않는 검색 임베딩·인덱스와 full 모델은 재생성하지 않았다.

B7은 설정 registry의 popularity 또는 Two Tower control과 B5 전체 pipeline treatment를 비교한다.
full 기본값 5,000명/군·30일을 유지하고 dev는 전체 사용자의 20%를 두 군에 나눈다.
이번 실행은 200명/군·30일·top10, 각 군 60,000회 노출이다.
persona의 카테고리 선호·가격 민감도·전환율과 위치 효과로 결과를 생성하며
treatment에 별도 가산점을 넣지 않는다. 추천기는 잠재 선호와 test outcomes를 읽지 않는다.
arm별 config·store·RNG·lock을 분리하고 사용자/날짜별 난수 stream을 고정했다.
사용자 간 적응 학습의 간섭을 막기 위해 MAB 피드백 상태도 사용자별로 분리했다.
초기 공용 bandit 실행은 독립성 가정에 맞지 않아 탐색 결과로 보존하고
`ab_initial_design_review.json`에 한계를 기록했다. 최종 gate에는 사용자별 분리 실행을 사용한다.

CTR=clicks/impressions, CVR=purchases/impressions이며 purchase/click도 별도 보고한다.
반복 노출을 독립 표본으로 세지 않고 사용자 cluster의 비율 차이·95% CI를 계산한다.
사용자별 한 번 이상 클릭/구매 여부에는 양측 Z와 Pearson chi-square를 적용하고,
빈도 부족 시 Fisher 검정과 점근 검정 한계를 표시한다. 모든 분모와 사용자별 집계를 저장한다.

실제 dev 결과는 control CTR 24.7833%, CVR 1.1517%, treatment CTR 19.8767%, CVR 0.9000%다.
treatment의 CVR 상대 lift는 **-21.8524%**, 차이는 -0.2517%p,
사용자 cluster 95% CI는 [-0.4043, -0.0991]%p, 양측 p=0.001228이다.
탐색 슬롯 비율은 control 0%, treatment 20%다. 이 수치는 합성 실험 결과이며
실제 서비스 우월성이나 full 최종 품질 통과를 뜻하지 않는다. 양의 lift는 B7 필수 gate가 아니다.
실제 Redis의 10회 워밍업·100회 순차 피처 조회 p95는 약 0.163ms로 10ms 목표를 통과했다.

재현·검증 명령:

```bash
source .team/activate.sh
OMP_NUM_THREADS=1 .venv/bin/python -m src.evaluation.ab_prepare
OMP_NUM_THREADS=1 .venv/bin/python -m src.evaluation.ab_test
OMP_NUM_THREADS=1 .venv/bin/python -m src.evaluation.ab_test --output .team/ab-repeat-dev.json
.venv/bin/python -m src.evaluation.verify_ab --repeat .team/ab-repeat-dev.json
.venv/bin/python -m pytest -q tests
```

[실험 결과](../results/ab_test.json), [모델 호환성](../results/experiments/C/ab_models_dev/compatibility.json),
[환경 검사](../results/experiments/C/macos_environment.json),
[기기 준비 근거](../results/experiments/C/macos_bootstrap.json),
[Redis 지연](../results/experiments/C/feature_macos_dev.json)을 저장했다.
동일 기기의 실제 반복 실행 비교는 B7 gate의 verify_ab 명령과 검증 JSON을 따른다.
다른 OS/Python에서는 동일 config/seed라도 부동소수점과 모델 바이트가 달라질 수 있어
기존 모델을 섞지 않고 로더의 호환성 검사를 통과한 새 bundle을 사용한다.
직접 의존성 추가는 없다. 전체 full acceptance와 전체 Compose 서비스 재현은 UNMEASURED다.
라이브 Redis의 MAB 노출/보상 연결은 이번 메모리 기반 실험과 구분하며 후속 통합에서 확인해야 한다.

B7 로컬 커밋은 설명과 명시 허가 후에만 푸시하고 Draft PR을 생성한다.
다음 담당 단계는 B8이며, 필요한 B2b는 이미 PR #3으로 main에 병합되어 있다.
C는 B9까지만 담당하고 B10 Docker와 B11 제출은 A에게 인계한다.
