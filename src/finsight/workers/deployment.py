"""Container entrypoint: explicit environment, no local acceptance credentials."""

import argparse
import os

from finsight.core.deployment import require_runtime_environment


def wire_research_services(application, settings, sessions, search):
    from finsight.agents.graph import build_research_graph
    from finsight.agents.tools import ResearchToolAdapter
    from finsight.infrastructure.storage.local import LocalObjectStorage
    from finsight.services.grounded_document_answer import GroundedDocumentAnswerService
    from finsight.services.real_document_evaluation import RealDocumentEvaluationService

    application.state.evidence_search = search
    application.state.document_answer = GroundedDocumentAnswerService(
        search, sessions, LocalObjectStorage(settings.object_storage_root),
    )
    from pathlib import Path

    application.state.real_document_evaluation = RealDocumentEvaluationService(
        search, application.state.document_answer, Path(settings.evaluation_runs_root),
        golden_path=Path(settings.evaluation_golden_path) if getattr(settings, "evaluation_golden_path", None) else None,
        suite_path=Path(settings.evaluation_suite_path) if getattr(settings, "evaluation_suite_path", None) else None,
    )
    # Evaluations above keep the local verifier: never spend external quota implicitly.
    generation_config = os.environ.get("FINSIGHT_GENERATION_CONFIG_FILE")
    if generation_config:
        from finsight.core.generation_config import load_generation_settings
        from finsight.infrastructure.providers.deepseek_generation import DeepSeekGenerationClient
        from finsight.services.generation_answer import (
            EvidenceGenerationAnswerService,
            PublicGenerationRegistry,
        )
        from finsight.services.generation_budget import create_generation_budget

        generation_settings = load_generation_settings(Path(generation_config))
        registry = PublicGenerationRegistry.load(Path("Evaluation/PublicGenerationPolicyV1.json"))
        application.state.document_answer = EvidenceGenerationAnswerService(
            application.state.document_answer,
            DeepSeekGenerationClient(generation_settings, create_generation_budget(settings.redis_url)),
            generation_settings, registry, sessions,
        )
    application.state.research_graph = build_research_graph(ResearchToolAdapter(
        structured_query=application.state.structured_query, document_search=search,
        document_answer=application.state.document_answer,
    ))
    from finsight.services.deployment_health import DeploymentReadiness

    application.state.deployment_readiness = DeploymentReadiness(application, settings, sessions)
    return application


def create_application():
    # Validate before Settings, database engines or application singleton are imported.
    require_runtime_environment(os.environ)
    from finsight.core.config import get_settings
    from finsight.infrastructure.database.session import SessionFactory
    from finsight.main import app
    from finsight.workers.mcp_stdio import make_document_search

    settings = get_settings()
    return wire_research_services(app, settings, SessionFactory, make_document_search(settings))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=("api", "worker", "dispatcher", "preflight"), default="api")
    args = parser.parse_args()
    try:
        require_runtime_environment(os.environ)
    except RuntimeError as exc:
        print(str(exc))  # Only allowlisted field names and static reasons, never values.
        return 2
    if args.role == "preflight":
        print("Runtime configuration and model manifests present; connectivity not checked")
        return 0
    if args.role == "api":
        import uvicorn

        uvicorn.run("finsight.workers.deployment:create_application", factory=True,
                    host=os.environ["APP_HOST"], port=int(os.environ["APP_PORT"]))
    else:
        import sys

        from finsight.workers.async_jobs import main as run_jobs

        sys.argv = [sys.argv[0], "--role", args.role,
                    "--model-path", os.environ["FINSIGHT_BGE_M3_PATH"],
                    "--device", os.environ.get("FINSIGHT_BGE_DEVICE", "cpu")]
        return run_jobs()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
