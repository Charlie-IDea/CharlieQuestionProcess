param([string]$OutputDirectory = './backups')
$ErrorActionPreference = 'Stop'
# 本地SQLite备份使用SQLite backup API，避免复制正在写入的数据库。
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$backupDirectory = [System.IO.Path]::GetFullPath((Join-Path $projectRoot $OutputDirectory))
New-Item -ItemType Directory -Path $backupDirectory -Force | Out-Null
$targetPath = Join-Path $backupDirectory ('zhixu-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.sqlite3')
& (Join-Path $projectRoot '.venv/Scripts/python.exe') -c 'import sqlite3,sys; src=sqlite3.connect(sys.argv[1]); dst=sqlite3.connect(sys.argv[2]); src.backup(dst); dst.close(); src.close()' (Join-Path $projectRoot 'backend/db.sqlite3') $targetPath
if ($LASTEXITCODE -ne 0) { throw '备份失败。' }
Write-Host "数据库备份完成：$targetPath"
Write-Host '还需备份 backend/private_media；S3部署请启用对象版本和独立备份。'
