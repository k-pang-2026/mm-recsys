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
