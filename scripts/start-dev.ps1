param([switch]$Demo)
$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (!(Test-Path -LiteralPath $pythonPath)) { throw '请先按 README 创建虚拟环境并安装依赖。' }
Push-Location $projectRoot
try {
    & $pythonPath backend/manage.py migrate
    if ($LASTEXITCODE -ne 0) { throw '数据库迁移失败。' }
    if ($Demo) { & $pythonPath backend/manage.py seed_demo }
    $apiProcess = Start-Process -FilePath $pythonPath -ArgumentList 'backend/manage.py','runserver','127.0.0.1:8000','--noreload' -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru
    Write-Host '知序本地地址：http://127.0.0.1:5173/，按 Ctrl+C 停止。'
    try { Set-Location (Join-Path $projectRoot 'frontend'); pnpm run dev }
    finally { if (!$apiProcess.HasExited) { Stop-Process -Id $apiProcess.Id } }
} finally { Pop-Location }
