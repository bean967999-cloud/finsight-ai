"""The dashboard must separate recomputed synthetic scores from unrun documents."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from finsight.domain.access_control import Principal, Role, WorkspaceMembership
from finsight.main import app
from finsight.services.identity import InvalidCredentials


def test_overview_requires_admin_and_keeps_document_cases_unrun() -> None:
    workspace_id = uuid4()

    class AuthStub:
        @staticmethod
        def resolve(token: str) -> Principal:
            roles = {"admin": Role.WORKSPACE_ADMIN, "viewer": Role.VIEWER}
            if token not in roles:
                raise InvalidCredentials("invalid token")
            return Principal(
                user_id=uuid4(),
                memberships=(WorkspaceMembership(workspace_id=workspace_id, role=roles[token]),),
            )

    previous = getattr(app.state, "auth_service", None)
    app.state.auth_service = AuthStub()
    try:
        client = TestClient(app)
        path = "/api/v1/evaluation/overview"
        assert client.get(path).status_code == 401
        assert client.get(path, headers={"Authorization": "Bearer viewer"}).status_code == 403
        response = client.get(path, headers={"Authorization": "Bearer admin"})
        assert response.status_code == 200
        body = response.json()
        assert body["execution"] == "local_synthetic_recomputed_on_request"
        assert body["research"]["source"] == "synthetic_fixture"
        assert body["research"]["metrics"]["tool_case_count"] == 7
        assert body["research"]["metrics"]["numeric_case_count"] == 4
        assert body["retrieval"]["status"] == "not_run"
        assert body["retrieval"]["metrics"] is None
        assert len(body["retrieval"]["unrun_question_ids"]) == 4
    finally:
        if previous is None:
            del app.state.auth_service
        else:
            app.state.auth_service = previous


@pytest.mark.parametrize("stale,expected", [(True,200),(False,503)])
def test_stale_scores_become_not_run_but_corrupt_results_remain_errors(stale, expected):
    from finsight.services.evaluation_overview import build_evaluation_overview
    from finsight.services.real_document_evaluation import EvaluationDatasetChanged

    workspace = uuid4()
    principal = Principal(user_id=uuid4(),memberships=(WorkspaceMembership(workspace_id=workspace,role=Role.WORKSPACE_ADMIN),))
    class Auth:
        def resolve(self, token):
            return principal
    class Service:
        def pending_report(self):
            return build_evaluation_overview().retrieval.model_copy(update={
                "dataset_version":"v2","unrun_question_ids":tuple(f"GQ-{i:03}" for i in range(1,41))})
        def load(self, workspace_id):
            if stale:
                raise EvaluationDatasetChanged("evaluation dataset changed; rerun required")
            raise ValueError("corrupt result")
    old_auth = getattr(app.state,"auth_service",None)
    old_service = getattr(app.state,"real_document_evaluation",None)
    app.state.auth_service,app.state.real_document_evaluation = Auth(),Service()
    try:
        response = TestClient(app).get("/api/v1/evaluation/overview",headers={"Authorization":"Bearer fixture"})
        assert response.status_code == expected
        if stale:
            body=response.json()
            assert body["retrieval"]["status"]=="not_run" and body["retrieval"]["metrics"] is None
            assert body["retrieval"]["dataset_version"]=="v2" and len(body["retrieval"]["unrun_question_ids"])==40
            assert body["retrieval_run"] is None
    finally:
        for name,value in (("auth_service",old_auth),("real_document_evaluation",old_service)):
            if value is None:
                delattr(app.state,name)
            else:
                setattr(app.state,name,value)
