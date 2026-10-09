# B6 Redis Feature Store 실행 안내

저장소 루트에서 실행한다. Python은 프로젝트의 `.venv`를 사용한다.
Windows PowerShell의 기본 Restricted 정책에서는 현재 세션에 한해 `Set-ExecutionPolicy -Scope Process RemoteSigned`를 실행한다. 이 클론의 VS Code 워크스페이스는 해당 세션 정책을 가진 터미널 프로필을 사용한다.
Windows PowerShell에서는 먼저 `. .\docs\submission\local_env.ps1`로 로컬 환경을 설정한다.
VS Code의 Windows 인터프리터 설정은 이 클론의 `.team/windows.code-workspace`에 있다.

## Redis 실행과 프로필 준비

Docker 환경에서는 `docker compose up -d redis`로 Redis만 시작한다.
이 PC의 검증에는 `redis-windows/redis-windows`의 Redis 7.4.11 MSYS2 이식판을
작업 폴더 상위의 `.tools/redis7`에 설치해 사용했다. 이식판은 Docker 재현 검증을 대신하지 않는다.
프로세스는 localhost:6379에만 바인딩하며 maxmemory=1gb, allkeys-lru를 적용한다.
Windows 재로그인 후에는 다음처럼 다시 시작할 수 있다.

```powershell
. .\docs\submission\local_env.ps1
$redisExecutable = Join-Path (Split-Path (Get-Location).Path) '.tools\redis7\Redis-7.4.11-Windows-x64-msys2\redis-server.exe'
Start-Process -FilePath $redisExecutable -WorkingDirectory (Split-Path $redisExecutable) -WindowStyle Hidden -ArgumentList @('--bind','127.0.0.1','--protected-mode','yes','--port','6379','--maxmemory','1gb','--maxmemory-policy','allkeys-lru','--save','""','--appendonly','no')
.\.venv\Scripts\python.exe -m src.serving.warmup_features
```

초기 적재는 사용자 ID와 관측 가능한 age_group/gender/signup_at만 사용하며 잠재 persona와
미래 행동은 적재하지 않는다. 1,000명씩 HASH에 적재하고 실제 ping 실패 시 nonzero로 종료한다.
기본 warmup은 행동 이력을 재생하지 않아 오프라인 평가 컷오프를 넘는 피처를 주입하지 않는다.

## 테스트와 지연 측정

```powershell
$env:RUN_REDIS_TESTS = '1'
.\.venv\Scripts\python.exe -m pytest -q -p src.serving.pytest_support tests/test_redis_features.py tests/test_feature_stream.py tests/test_integration_redis.py tests/test_serving_contract.py
.\.venv\Scripts\python.exe -m src.evaluation.bench_latency
```

지연 검사는 별도 임시 namespace에 100명의 프로필과 최대 50개 조회 이력을 준비한다.
10회 워밍업 뒤 100회 순차 조회의 p50/p95/p99를 측정하고 원시 샘플·RAM·CPU·Redis 버전과
데이터/config fingerprint를 `docs/results/latency/feature_dev.json`에 기록한다.
p95 목표는 10ms이며 실패하면 nonzero다. 임시 키만 정리하며 실제 세션은 보존한다.
dev 결과는 full 품질 PASS를 의미하지 않는다.

## 스트림 반영

공통 시뮬레이터가 `data/stream/events-*.parquet`에 쓴 청크를 별도 C 소유 adapter로 소비한다.
`python -m src.serving.stream_features --once`로 현재 청크를 한 번 소비하거나,
`--once` 없이 실행해 주기적으로 읽는다. 동일 namespace에는 소비자를 하나만 실행한다.
청크 해시와 데이터 fingerprint를 확인하며 Redis 실패 시 해당 청크 체크포인트를 진행하지 않는다.
부분 재시도는 event/feedback 중복 방지 키로 처리한다. 이미 소비한 청크 변경은 거부한다.
메모리 전용 Redis를 재시작해 피처가 사라졌다면 새 `serving.redis.namespace`를 설정하고
프로필 warmup 후 필요한 스트림을 다시 재생해야 한다.

## 설정과 API 동작

`config/serving.yaml`에서 redis backend, timeout_seconds, max_connections, write_retries, db를 설정한다.
추가 namespace가 없으면 `mm-recsys:<scale>`을 사용한다. host/port는 공통 REDIS_HOST/REDIS_PORT를 따른다.
memory backend를 명시하면 기존 메모리 저장소도 사용할 수 있다.
최근 조회 LIST와 세션 HASH는 동일한 sliding TTL을 사용하고 세션 ID 변경 시 함께 초기화한다.
프로필은 세션 만료 후에도 남는다. event/feedback 중복 방지는 각각 feedback_ttl_seconds 동안 유지된다.

Redis 조회 장애 시 경고와 빈 UserFeatures를 반환한다. API에서 공급된 추천 서비스가 이 빈 피처로
응답할 수 있음을 테스트한다. 현재 main에는 A/B 모델 구현이 없어 실제 기본 추천 API와
`/ready`는 503이다. 실제 추천 모델을 통한 장애 시 200 동작은 B5 병합 후 재검증해야 한다.

## 이 PC의 환경 제한

Windows 10 build 19044에서는 현재 Docker Desktop의 최소 Windows 10 build 19045 조건을 충족하지 않는다.
Windows 업데이트 후 WSL 2 및 Docker Desktop 설치·실행이 필요하다.
[Docker 공식 요구사항](https://docs.docker.com/desktop/setup/install/windows-install/)을 따른다.
Docker·Compose 재현은 미측정이다. RAM 약 8GB는 프로젝트 권장 16GB보다 적으며 full 검증은 별도 환경이 필요하다.
공통 bootstrap 테스트의 POSIX 임시경로/실행 파일 가정이 Windows에 맞지 않는 경우 전체 setup은
완료로 처리하지 않는다. B6 검사와 가능한 회귀 검사의 실제 결과는 C 기여 기록에 별도로 남긴다.
