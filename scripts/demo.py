#!/usr/bin/env python3
"""검색·추천 JSON, A/B 결과 표, CT 알림을 터미널에서 실행합니다."""
from __future__ import annotations

import argparse
import base64
import math
import os
from pathlib import Path
import sys
import urllib.error
from urllib.parse import urlencode
import uuid
import subprocess
import contextlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from docker.http import request
from src.common.artifacts import write_json
from src.common.console import emit_json, log, run_cli
from src.common.schemas import EventRequest, RecommendResponse, SearchRequest, SearchResponse


def summarize_recommendation(result: dict) -> None:
    parsed = RecommendResponse.model_validate(result)
    latency = parsed.pipeline_latency
    log('추천', '완료', f'사용자={parsed.user_id} / 반환 상품={len(parsed.recommendations)}개 / '
        f'후보 생성={latency.candidate_ms:.1f}ms / 랭킹={latency.ranking_ms:.1f}ms / '
        f'재정렬={latency.reranking_ms:.1f}ms / 전체={latency.total_ms:.1f}ms / '
        f'최근 클릭={len(parsed.session_context.recent_clicks)}개 / '
        f'세션 관심={parsed.session_context.session_interest or "없음"}', status='성공')


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == 'examples':
        return examples(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] in ('ab', 'ct', 'evaluate', 'verify-peer-review'):
        return operational(sys.argv[1:])
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name, label in [('search', '텍스트·이미지·하이브리드 검색'),
                        ('recommend', '사용자별 추천'), ('session', '클릭 전송 및 추천 전후 비교')]:
        child = commands.add_parser(name, help=label, description=label)
        child.add_argument('--api-url', default=os.getenv('API_URL', 'http://127.0.0.1:8000'), help='실행 중인 API 주소')
        child.add_argument('--json', action='store_true', help='stdout은 원본 JSON만 출력 (기본값); 안내는 stderr')
        child.add_argument('--output', type=Path, help='원본 결과를 UTF-8 JSON 파일로 저장')
        child.add_argument('--timeout', type=float, default=60, help='HTTP 제한 시간(초)')
        if name == 'search':
            child.add_argument('--query-text', help='검색 텍스트')
            child.add_argument('--query-image', type=Path, help='실제 이미지 파일 경로 (컨테이너에서는 마운트 경로)')
            child.add_argument('--top-k', type=int, default=10, help='반환 상품 수')
        else:
            child.add_argument('--user-id', required=True, help='추천 사용자 ID')
            child.add_argument('--top-n', type=int, default=10, choices=range(1, 101), metavar='1..100', help='반환 상품 수')
            if name == 'session':
                child.add_argument('--product-id', required=True, help='클릭할 실제 상품 ID')
                child.add_argument('--category', required=True, help='클릭 상품의 실제 카테고리')
                child.add_argument('--event-id', default=None, help='재시도할 때 원래 event_id를 지정하여 중복 반영 방지')
                child.add_argument('--session-id', default='cli-demo', help='세션 ID')
    for name, label in [('ab', '실제 두 전략 A/B 실험'), ('ct', 'CT 모니터·재학습·격리 시연'),
                        ('evaluate', 'Docker 품질 평가'), ('verify-peer-review', '실제 HTTP·Redis 동료 평가'),
                        ('examples', 'PDF pp.10–12: 검색·세션 추천·A/B·CT를 순서대로 실제 실행')]:
        commands.add_parser(name, help=label)
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('--timeout은 유한한 양수여야 합니다.')
    api = args.api_url.rstrip('/')
    log('시연', '요청', f'명령={args.command} / API={api}')
    try:
        if args.command == 'search':
            payload = SearchRequest(query_text=args.query_text, top_k=args.top_k,
                query_image=base64.b64encode(args.query_image.read_bytes()).decode('ascii') if args.query_image else None)
            result = request(api + '/api/search', payload.model_dump(exclude_none=True), timeout=args.timeout)
            parsed = SearchResponse.model_validate(result)
            mode = {'text': '텍스트', 'image': '이미지', 'hybrid': '하이브리드'}[parsed.search_type]
            log('검색', '완료', f'검색 유형={mode} / 반환 상품={len(parsed.results)}개 / '
                f'total_count={parsed.total_count} / 응답 시간={parsed.latency_ms:.1f}ms', status='성공')
        else:
            url = api + '/api/recommend?' + urlencode(dict(user_id=args.user_id, top_n=args.top_n))
            before = request(url, timeout=args.timeout)
            summarize_recommendation(before)
            result = before
            if args.command == 'session':
                event = EventRequest(event_id=args.event_id or uuid.uuid4().hex, user_id=args.user_id,
                    product_id=args.product_id, category=args.category, event_type='view', session_id=args.session_id)
                log('세션', '클릭 전송', f'event_id={event.event_id} / 상품={event.product_id} / 재시도 시 같은 event_id를 사용하세요.')
                response = request(api + '/api/event', event.model_dump(), timeout=args.timeout)
                after = request(url, timeout=args.timeout)
                summarize_recommendation(after)
                result = dict(before=before, event=event.model_dump(), event_response=response, after=after)
                log('세션', '완료', f"클릭 반영={response['applied']} / 추천 전후 원본 응답을 확인하세요.", status='성공')
    except urllib.error.HTTPError as error:
        original = error.read().decode('utf-8', errors='replace')
        log('API', '응답 오류', f'HTTP {error.code} / 원문={original} / 다음 조치: 요청 인자와 서버 준비 상태를 확인하세요.', status='실패')
        raise
    if args.output:
        write_json(args.output, result)
        log('시연', '저장', f'UTF-8 JSON={args.output}', status='성공')
    emit_json(result)
    return 0


def examples(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description='PDF 결과 예시 순서로 실제 실행합니다. A/B·CT는 별도 작업 컨테이너에서 실행하세요.')
    parser.add_argument('--api-url', default=os.getenv('API_URL', 'http://127.0.0.1:8000'))
    parser.add_argument('--user-id', default='U000001', help='학습 이력이 있는 합성 사용자; 새 세션에 클릭 두 건을 전송')
    parser.add_argument('--output-dir', type=Path, help='새 결과 폴더; 생략하면 runtime에 고유 폴더 생성')
    parser.add_argument('--users-per-group', type=int)
    parser.add_argument('--days', type=int)
    args = parser.parse_args(argv)
    from docker.runtime import runtime_config
    cfg = runtime_config()
    args.users_per_group = args.users_per_group if args.users_per_group is not None else cfg['serving']['ab_test']['users_per_group']
    args.days = args.days if args.days is not None else cfg['serving']['ab_test']['days']
    args.output_dir = args.output_dir or Path(cfg['paths']['results_dir']) / 'pdf-examples' / uuid.uuid4().hex[:12]
    if args.users_per_group <= 0 or args.days <= 0:
        parser.error('users-per-group와 days는 양수여야 합니다.')
    args.output_dir.mkdir(parents=True, exist_ok=False)
    api = args.api_url.rstrip('/')
    log('PDF 시연', '범위', '검색·추천·통계는 실제 결과이며, CT 승격·롤백은 별도 소규모 통제 시연입니다.')
    search = SearchResponse.model_validate(request(api + '/api/search',
        dict(query_text='검정 오버핏 후드티', top_k=10)))
    write_json(args.output_dir / 'search.json', search.model_dump())
    emit_json(search.model_dump())
    if len(search.results) < 2:
        raise ValueError('PDF 세션 시연에는 실제 검색 상품 두 개가 필요합니다.')
    # Keep trained long-term history and start a real, separate short-term session.
    user, session = args.user_id, 'pdf-demo-' + uuid.uuid4().hex
    events = []
    for item in search.results[:2]:
        event = EventRequest(event_id=uuid.uuid4().hex, user_id=user, product_id=item.product_id,
                             event_type='view', session_id=session)
        response = request(api + '/api/event', event.model_dump())
        if response.get('applied') is not True:
            raise ValueError('PDF 시연 클릭이 저장되지 않았습니다.')
        events.append(dict(request=event.model_dump(), response=response))
    write_json(args.output_dir / 'session_events.json', events)
    recommendation = RecommendResponse.model_validate(request(api + '/api/recommend?' +
        urlencode(dict(user_id=user, top_n=10))))
    if recommendation.session_context.recent_clicks != [item.product_id for item in search.results[:2]]:
        raise ValueError('추천 응답에 실제 클릭 두 개가 반영되지 않았습니다.')
    write_json(args.output_dir / 'recommendation.json', recommendation.model_dump())
    emit_json(recommendation.model_dump())
    # Separate children release loaded models between full A/B and CT training.
    for arguments in [
        ['ab', '--users-per-group', str(args.users_per_group), '--days', str(args.days),
         '--output', str(args.output_dir / 'ab_test.json')],
        ['ct', '--drill', '--output', str(args.output_dir / 'ct_drill.json')],
    ]:
        code = subprocess.call([sys.executable, str(Path(__file__).resolve()), *arguments])
        if code:
            return child_status(code)
    log('PDF 시연', '완료', f'원본 결과={args.output_dir}', status='성공')
    return 0


def child_status(code: int) -> int:
    if code:
        cause = f'시그널 {-code}에 의해 종료' if code < 0 else f'종료 코드 {code}'
        log('시연', '하위 명령', f'원인: {cause} / 다음 조치: 위 원본 오류와 컨테이너 상태를 확인하세요. '
            '시그널 9이면 OOM 기록·메모리와 중단된 학습 산출물을 확인한 뒤 복구하세요.', status='실패')
    return code


def summarize_ab(result: dict) -> None:
    def percent(value: float | None, signed: bool = False) -> str:
        return '미측정' if value is None else (f'{value*100:+.2f}%' if signed else f'{value*100:.4f}%')
    print('========== A/B 테스트 결과 ==========')
    print(f"실험 기간: 시뮬레이션 {result['days']}일 (합성 실험)")
    print(f"샘플 수: Control {len(result['assignment']['control']):,}명, Treatment {len(result['assignment']['treatment']):,}명")
    print(f"전략: {result['strategies']['control']} → {result['strategies']['treatment']}")
    border = '+' + '+'.join('-' * width for width in (19, 14, 14, 14)) + '+'
    print(border)
    print(f'| {"Metric":17} | {"Control":12} | {"Treatment":12} | {"Lift":12} |')
    print(border)
    for key in ('ctr', 'cvr'):
        row = result['inference'][key]
        print(f"| {key.upper():17} | {percent(row['control']):12} | {percent(row['treatment']):12} | {percent(row['relative_lift'], True):12} |")
    arms = result['arms']
    rates = [arms[a]['explorations']/arms[a]['impressions'] if arms[a]['impressions'] else None
             for a in ('control', 'treatment')]
    print(f'| {"MAB Exploration":17} | {percent(rates[0]):12} | {percent(rates[1]):12} | {"-":12} |')
    print(border)
    print('통계적 유의성 (사용자 단위, 반복 노출 보정):')
    for key in ('ctr', 'cvr'):
        row = result['inference'][key]
        p, ci = row['z_p_value'], row['difference_ci95']
        label = '미측정/추론 불가' if p is None else '유의함' if p < .05 else '유의하지 않음'
        interval = '미측정' if ci is None else f'[{ci[0]*100:+.4f}, {ci[1]*100:+.4f}] %p'
        print(f"  {key.upper()} p-value: {p if p is not None else '미측정'} ({label}) / 차이의 95% CI: {interval}")


def operational(argv: list[str]) -> int:
    """Reuse the actual experiment/evaluation/training runners, preserving exit codes."""
    command, *arguments = argv
    if command == 'ab':
        parser = argparse.ArgumentParser(description='실제 두 추천 전략의 사용자 단위 A/B 실험')
        parser.add_argument('--users-per-group', type=int)
        parser.add_argument('--days', type=int)
        parser.add_argument('--output', type=Path)
        parser.add_argument('--json', action='store_true')
        args = parser.parse_args(arguments)
        from docker.runtime import runtime_config
        from src.evaluation.ab_test import run
        cfg = runtime_config()
        for key in ('users_per_group', 'days'):
            value = getattr(args, key)
            if value is not None:
                if value <= 0:
                    parser.error(f'--{key.replace("_", "-")}는 양수여야 합니다.')
                cfg['serving']['ab_test'][key] = value
        output = args.output or Path(cfg['paths']['results_dir']) / 'ab_test.json'
        output.parent.mkdir(parents=True, exist_ok=True)
        from src.ct.storage import file_lock
        log('A/B', '실행 순서', '같은 배포의 CT 학습과 순차 실행합니다. 실행 중인 학습이 있으면 완료를 기다립니다.')
        with file_lock(Path(cfg['paths']['model_dir']) / '.ct' / 'training.lock'):
            with output.with_suffix('.log').open('w', encoding='utf-8') as detail, contextlib.redirect_stdout(detail):
                result = run(cfg, output)
        from src.evaluation.verify_ab import verify
        verified = verify(output, cfg)
        write_json(output.with_name(output.stem + '_verification.json'), verified)
        display = Path(cfg['paths']['results_dir']) / 'ab_test.json'
        if display.resolve() != output.resolve():
            write_json(display, result)
        if args.json:
            emit_json(result)
        else:
            summarize_ab(result)
            print(f'원본 결과: {output}')
        return 0
    if command == 'ct':
        parser = argparse.ArgumentParser(description='CT 모니터링·재학습 또는 격리된 전체 생명주기 시연', add_help=False)
        parser.add_argument('--drill', action='store_true')
        parser.add_argument('--output', type=Path)
        parser.add_argument('--json', action='store_true')
        args, remaining = parser.parse_known_args(arguments)
        module = 'src.ct.verify_ct' if args.drill else 'src.ct.retrain_trigger'
        if '--help' in remaining or '-h' in remaining:
            parser.print_help()
            return subprocess.call([sys.executable, '-m', module, '--help'])
        # Exec children need the same resolved runtime config as the API process.
        from docker.runtime import runtime_config, config_path
        if args.drill:
            args.output = args.output or (Path(runtime_config()['paths']['results_dir']) /
                                         'ct-drills' / (uuid.uuid4().hex + '.json'))
            remaining += ['--output', str(args.output)]
        env = dict(os.environ)
        if not args.json:
            env['CT_OUTPUT'] = 'human'
        if args.drill:
            log('CT', '격리 시연', '작은 별도 데이터로 실제 학습·승격·롤백을 검사합니다. 운영 모델 개선 측정과 구분합니다.')
        runtime = config_path(runtime_config())
        if runtime.is_file() and not args.drill:
            env['CONFIG_PATH'] = str(runtime)
        if not args.output and not args.drill and not args.json:
            args.output = (Path(runtime_config()['paths']['results_dir']) /
                           'ct-cli' / (uuid.uuid4().hex + '.jsonl'))
            log('CT', '기록', f'원본 JSON: {args.output}')
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
        # Stream each JSON line: --watch --output must not buffer until the worker exits.
        with contextlib.ExitStack() as stack:
            if args.drill:
                from src.ct.storage import file_lock
                log('CT', '실행 순서', '같은 배포의 자동 CT·A/B 실행이 끝난 뒤 격리 시연을 시작합니다.')
                stack.enter_context(file_lock(Path(runtime_config()['paths']['model_dir']) / '.ct' / 'training.lock'))
            saved = stack.enter_context(args.output.open('wb')) if args.output and not args.drill else None
            process = subprocess.Popen([sys.executable, '-m', module, *remaining], env=env, stdout=subprocess.PIPE)
            try:
                assert process.stdout is not None
                for line in process.stdout:
                    if saved:
                        saved.write(line); saved.flush()
                    if args.json:
                        sys.stdout.write(line.decode('utf-8')); sys.stdout.flush()
                return child_status(process.wait())
            except KeyboardInterrupt:
                log('CT', '종료', '사용자가 모니터링을 중지했습니다. 저장된 기록과 모델은 유지합니다.')
                return 130
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.wait()
                if process.stdout is not None:
                    process.stdout.close()
    if command == 'evaluate':
        from docker.runtime import runtime_config
        os.environ.setdefault('QUALITY_RESULTS_DIR', str(Path(runtime_config()['paths']['results_dir']) / 'quality'))
        return child_status(subprocess.call([sys.executable, '-m', 'docker.quality', *arguments]))
    return child_status(subprocess.call([sys.executable, 'scripts/verify_peer_review.py', *arguments]))


if __name__ == '__main__':
    raise SystemExit(run_cli(main, 'API 시연', 'API /ready, 요청 ID·이미지 경로를 확인하세요. 세션 재시도는 로그의 동일 --event-id를 사용하세요.'))
