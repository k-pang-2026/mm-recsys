# Dot-source from PowerShell: . .\docs\submission\local_env.ps1
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$taskTools = Join-Path (Split-Path $projectRoot) '.tools'
$toolPaths = @(
    (Join-Path $taskTools 'python312'),
    (Join-Path $taskTools 'python312\Scripts'),
    (Join-Path $taskTools 'git\cmd'),
    (Join-Path $taskTools 'git\bin')
) | Where-Object { Test-Path -LiteralPath $_ }
if ($toolPaths) { $env:Path = ($toolPaths -join ';') + ';' + $env:Path }
$env:PYTHONUTF8 = '1'
$env:PYTHONHASHSEED = '42'
$env:REDIS_HOST = 'localhost'
$env:REDIS_PORT = '6379'
$env:API_URL = 'http://localhost:8000'
$env:CONFIG_PATH = Join-Path $projectRoot 'config.yaml'
if (-not $env:HF_HOME) { $env:HF_HOME = Join-Path $projectRoot '.cache\huggingface' }
if (-not $env:SCALE) { $env:SCALE = 'dev' }
Write-Output "Local environment: Redis localhost:6379, SCALE=$env:SCALE"
