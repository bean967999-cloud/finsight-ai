FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea AS dependencies
WORKDIR /app
RUN pip install --no-cache-dir uv==0.12.5
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --extra embedding --no-install-project --no-cache

FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea AS runtime
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 finsight && useradd --uid 10001 --gid 10001 --create-home finsight \
    && mkdir -p /Data/ObjectStorage /Data/EvaluationRuns \
    && chown -R finsight:finsight /Data /app
COPY --from=dependencies /app/.venv /app/.venv
COPY --chown=10001:10001 src ./src
COPY --chown=10001:10001 Evaluation ./Evaluation
COPY --chown=10001:10001 alembic ./alembic
COPY --chown=10001:10001 alembic.ini ./
COPY --chown=10001:10001 pyproject.toml uv.lock ./
ENV PATH=/app/.venv/bin:$PATH PYTHONPATH=/app/src PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
USER 10001:10001
EXPOSE 9300
ENTRYPOINT ["python", "-m", "finsight.workers.deployment"]
CMD ["--role", "api"]
