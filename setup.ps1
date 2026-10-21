$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'uv를 먼저 설치하세요: https://docs.astral.sh/uv/getting-started/installation/'
}
uv sync
if ($LASTEXITCODE -ne 0) { throw 'uv 설치 실패. 위 오류를 확인하세요.' }
if (-not (Test-Path -LiteralPath '.env')) {
    Copy-Item -LiteralPath '.env.example' -Destination '.env'
}
Write-Host '준비 끝! .env에 키를 넣고 uv run python app.py 를 실행하세요.'
