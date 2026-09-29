if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
}
uv sync --extra dev
uv run uvicorn finsight.main:app --reload --port 9300
