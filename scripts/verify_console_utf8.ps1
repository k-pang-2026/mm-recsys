param(
    [string]$Image = "mm-recsys-api-server:latest",
    [string]$OutputDir = ".team/console-utf8"
)
$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding($false, $true)
$OutputEncoding = $utf8
[Console]::OutputEncoding = $utf8
if ($Image -notmatch '^[a-zA-Z0-9][a-zA-Z0-9._/:@-]*$') { throw "Docker 이미지 이름을 확인하세요." }
[IO.Directory]::CreateDirectory($OutputDir) | Out-Null
$OutputDir = (Resolve-Path $OutputDir).ProviderPath
$code = @'
import sys
from src.common.console import configure_utf8, log, emit_json
configure_utf8()
message = '한글 출력·저장 확인'
log('문자 인코딩', '검사', message, status='성공')
emit_json(dict(status='PASS', message=message, stdout_encoding=sys.stdout.encoding, stderr_encoding=sys.stderr.encoding))
'@
$encoded = [Convert]::ToBase64String($utf8.GetBytes($code))
$start = New-Object System.Diagnostics.ProcessStartInfo
$start.FileName = (Get-Command docker -ErrorAction Stop).Source
$start.Arguments = "run --rm --pull never --entrypoint python $Image -c `"import base64;exec(base64.b64decode('$encoded'))`""
$start.UseShellExecute = $false
$start.RedirectStandardOutput = $true
$start.RedirectStandardError = $true
$start.StandardOutputEncoding = $utf8
$start.StandardErrorEncoding = $utf8
$process = New-Object System.Diagnostics.Process
$process.StartInfo = $start
try {
    [void]$process.Start()
    $stdout = $process.StandardOutput.ReadToEndAsync()
    $stderr = $process.StandardError.ReadToEndAsync()
    $process.WaitForExit()
    $raw = $stdout.GetAwaiter().GetResult()
    $logs = $stderr.GetAwaiter().GetResult()
    [IO.File]::WriteAllText((Join-Path $OutputDir "result.json"), $raw, $utf8)
    [IO.File]::WriteAllText((Join-Path $OutputDir "run.log"), $logs, $utf8)
    [Console]::Error.Write($logs)
    if ($process.ExitCode -ne 0) { throw "Docker 검사 실패. run.log의 원본 오류와 Engine·이미지 상태를 확인하세요." }
    $result = [IO.File]::ReadAllText((Join-Path $OutputDir "result.json"), $utf8) | ConvertFrom-Json
    $saved = [IO.File]::ReadAllText((Join-Path $OutputDir "run.log"), $utf8)
    if ($result.message -ne '한글 출력·저장 확인' -or -not $saved.Contains('한글 출력·저장 확인') -or
        $result.stdout_encoding -ne 'utf-8' -or $result.stderr_encoding -ne 'utf-8') {
        throw "UTF-8 왕복 검사 실패. 터미널 인코딩과 저장 파일을 확인하세요."
    }
    [Console]::Out.Write($raw)
} finally {
    $process.Dispose()
}
