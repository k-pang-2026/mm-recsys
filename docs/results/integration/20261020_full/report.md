# 2026-10-20 full 통합 결과

**현재 데이터 종합 판정: PASS.** [최종 집계](../../final_acceptance.json),
[실제 제출 검사](submission/checks.json), [대시보드 최종 검사](dashboard_final.json)를 대조한다.
현재 기본 네 서비스가 실행 중이며 API http://localhost:8000/docs,
대시보드 http://localhost:8501, 시뮬레이터 재생이 정상이다.
원격 push/PR은 이번 로컬 commit을 설명한 뒤 새 승인 대기이며 외부 과제 시스템 URL 제출은 하지 않았다.

## 원본 보존과 구현

기준 main은 `aaa4184c0d03eb47e90eb899aac77cc9797cbb18`, 브랜치는 `feat/integration`이다.
생성기 4.2, seed42, 상품 50,000개·사용자 10,000명·행동 1,000,000건,
데이터 fingerprint는 `8b578e5cf32d1074fabbabf8fff9db3135c23e34ea65424a0376f54570d9fb40`다.

사용자의 `docs/results/docker/evaluation_20261020_165756/` 평가 7파일을 바이트 그대로
보존·재사용했다. valid 동결·test·원시 지연을 새 측정으로 덮어쓰지 않았다.
원본 데이터, 초기 모델 12파일, 모델 메타데이터와 측정 소스 82파일도 보존했다
([최종 보존 검사](preservation_final.json)). 이 test는 이미 관측한 결과의 재사용이며
새 미관측 holdout 평가가 아니다. 이전 4.1 종합 판정도 previous_final_acceptance.json에 보존했다.

대시보드는 같은 규모의 test 결과를 우선 선택한다. 새 publisher는 실제 제출 검사·여섯
필수 통합 검사·데이터/모델/소스 해시와 활성 v1.0을 대조한 뒤에만 판정을 연결한다.
원래 품질 파일과 새 표시 파일을 분리했다. CT 검증 도구의 결과 경로를 인자로 받도록 했다.

## full 품질 재사용과 별도 새 지연 측정

동결 test의 MRR@10/NDCG@10은 0.931667, Recall@300은 0.737377,
CTR AUC는 0.965100, HitRate@50은 0.662995, NDCG@50은 0.323153,
Coverage는 0.353880이다. 수치 조건 11개·후보 최소300개·실현 가능한 추천 제약을
통과했다. CVR AUC 0.507732는 측정 가능하지만 구매 예측 개선을 뜻하지 않는다.
전체 카탈로그·시간 cutoff·K·정답·기준·cohort는 유지했다.

아래 값은 위 품질 원본의 지연과 별개로 **이번에 새로 측정**했다.
학습/평가 워커와 중복 배포를 종료하고 기본 배포 하나에서 시뮬레이터 재생을 잠시
정지했다. 측정 후 재생을 복구했다. 각 모드 직렬 HTTP의 원시 표본과 실제 모델/소스
해시 검증은 [새 smoke](current_benchmark/smoke_full.json),
[재검증](current_benchmark/verified_full.json)에 있다.

| 모드 | HTTP p95 | warmup | 측정 요청 | 오류 |
|---|---:|---:|---:|---:|
| text | 50.543ms | 10 | 100 | 0 |
| image | 80.982ms | 10 | 100 | 0 |
| hybrid | 84.933ms | 10 | 100 | 0 |
| recommendation | 38.601ms | 10 | 100 | 0 |

## 새 A/B

실제 popularity 대 full_pipeline으로 군당 5,000명·30일·top10을 실행했다.
각 군 노출 1,500,000회, Control 클릭 377,500회·구매 18,704회,
Treatment 클릭 307,112회·구매 12,979회다.
CVR은 1.2469% 대 0.8653%, 상대 변화 **−30.61%**다.
사용자 군집 기준 CVR 차이 95% CI는 [−0.0041241452, −0.0035091882],
p=9.76194e−131이다. 합성 환경의 악화를 그대로 보존하며 운영 개선으로 주장하지 않는다.
[통계 재검증](ab_verification_full.json), [필수 검사](ab_acceptance_full.json),
[무손실 archive](ab_full_archive.json)와 11개 사용자 통계 shard를 보존했다.
seed42 CPU, Python 3.11.17, Torch 2.6.0+cpu,
NumPy 2.1.3, Torch 4스레드 조건이다.

## 실제 CT와 별도 full 기능 검사

실제 HTTP top50 추천에서 고유 view 10,000건을 수집하고 원래 full과 결합한 새 시간
분할 snapshot에서 candidate/ranking/session 세 모델을 실제 학습·checkpoint 재로딩했다.
monitor 관측 성숙도는 query clock만 명시적으로 앞당겼고 실제 1시간 대기를 주장하지 않는다.
학습·선택은 train/valid를 사용했으며 CT test는 열지 않았다.

paired valid 227,736개 CTR 표본, truth 사용자 7,519명의 비교에서
CTR AUC 0.965535035 →
0.965946299, HitRate@50
0.681340604 →
0.676552733다.
AUC 개선 0.000411265는 원래 최소 개선 0.001에 미달해 자연 판정은 **RETAINED**다.
watermark 소비·중복 재학습 방지 WAITING과 기존 v1.0 유지를 확인했다
([자연 결과](ct_full.json), [실제 학습](ct_training_sources_full.json)).

별도 full 크기 fixture에서 초기 ranker만 등록 전에 상수화하고 실제 재학습 후보는
바이트 그대로 재사용했다. 원래 guard와 같은 valid CTR 표본을 사용해 실제 교체,
재로딩 두 번, 롤백 및 기존/신규 사용자 HTTP 6응답의 버전 `v1.0→v1.1→v1.0`을 확인했다.
초기 fixture의 fault injection은 운영 성능 개선이나 자연 승격을 뜻하지 않는다.
[분리 집계](ct_acceptance_full.json), [실제 기능 결과](ct_controlled_lifecycle_full.json),
[registry 로그](ct_controlled_lifecycle_full.jsonl), [HTTP 재로딩 로그](ct_controlled_reload_full.jsonl)를 대조한다.

## 빈 경로 재현·현재 화면·최종 검사

원격 main의 별도 클론에서 빈 data/models로 full 생성·세 모델 학습·기동을 완료했다.
준비 1906.485초이며 기존 소스 일치 서비스 이미지와 pinned HF 다운로드 cache만 재사용했다.
데이터 manifest의 모든 필드/체크섬과 새 추천/인덱스/인코더 12파일이 원본과 같다
([재현](fresh_checkout.json), [데이터](data_reproduction_full.json),
[모델](fresh_model_identity_full.json)). 이후 추가 병렬 부하 실패와 구분한다.

실제 HTTP와 독립 Redis의 MAB·세션·보상·중복 방지는 mab_full.json,
검색 3모드·multipart·잘못된 입력·추천은 smoke_functional_full.json으로 확인했다.
완료 전 UNMEASURED 화면은 dashboard_full.json에 보존했다. 완료 후 실제 컨테이너
Streamlit AppTest에서 최종 PASS, 군별 CVR, CT 유지와 복구 검사, 검색/추천 각10개 결과,
4탭·예외0을 확인했다. 브라우저 픽셀 렌더링은 측정하지 않았다.
[표시 파일 보관본](dashboard_published_full_test.json)과
[발행/화면 근거](dashboard_publication_receipt.json)를 대조한다.

실제 Redis를 포함한 독립 소스 checkout의 전체 회귀는 **384 passed**, 오류·실패·skip0이다.
타입 검사는 제출 도구9개와 runtime 소스117개, pip check와 공개 함수 AST 감사를 통과했다.
호스트 Python 3.12.3, PYTHONHASHSEED42, OMP/MKL/OpenBLAS 각2,
테스트는 dev 설정과 localhost Redis, 실제 서비스/품질/CT/A-B는 full로 구분했다.
기본 Docker는 aarch64 CPU 8개,
메모리 7.547GiB다.
원격 공개 접근·A/B/C 기여 및 병합 PR18 head는 read-only snapshot으로 확인했다.
현재 INTEGRATE 원격 반영은 아직 하지 않았다.

## 보존한 실패와 적용 한계

- 두 API·full A/B·CT 병렬 실행의 검증 API OOM/137은 parallel_load_failure.json에 보존했다.
  같은 API의 top50 추천200회·동시8개를 다른 무거운 워커 없이 다시 실행해 오류0·OOM없음을
  확인했다 (separate_http_load_full.json, parallel_failure_recheck.json).
  이 성공을 원래 병렬 실행 용량으로 확대 해석하지 않는다.
- 4GB CT 한 프로세스의 학습 후 비교 OOM/137은 ct_memory_failure.json에 남겼다.
  실제 완료 모델을 검증한 뒤 별도 프로세스의 비교로 복구했다. 복구 관측 peak는
  3,189,202,944bytes, OOM없음이며 exit2는 자연 유지 결과다 (ct_failure_recovery.json).
  기본4GB 한 프로세스 학습·비교의 성공을 주장하지 않는다.
- WSL RAM 약7.5GB와 swap2GB 포화로 Docker 관리가 멈춰 사용자가 Docker 배포판만
  재시작했다. 디스크·볼륨·평가·학습 산출물을 유지했고 단일 작업으로 이어 검증했다
  (docker_management_recovery.json).
- 호스트 발행 첫 시도는 Docker 생성 디렉터리 쓰기 권한 때문에 실패했다.
  runtime/full 디렉터리 한 곳의 소유권만 UID/GID1000으로 맞추고 같은 검증·발행 명령을
  성공시켰다. 0755와 하위 파일 내용은 유지했다 (dashboard_directory_permissions.json,
  commands/publish_dashboard_permission_failure.txt).
- 합성 A/B/view-only CT·별도 초기 fixture는 실제 사용자 효과를 입증하지 않는다.
  다른 하드웨어·다중 배포·학습과의 동시 지연, A/B 다른 seed 반복은 미측정이다.

원본 실패를 지우거나 test 정답/기준을 바꿔 통과시키지 않았다. 현재 판정은 보존한 full
품질과 이번 실제 통합 검사 범위에 한정한다. 로컬 commit은 Git 이력과 INTEGRATE gate를,
원격 push/PR은 새 승인 후 실제 원격 head/CI/보호 규칙을 확인한다.
