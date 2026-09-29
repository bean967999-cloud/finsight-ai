"""Opt-in contract check against the project's own MinerU container."""

import os

import httpx
import pytest

from finsight.core.config import get_settings

pytestmark = pytest.mark.skipif(
    os.environ.get("FINSIGHT_MINERU_INTEGRATION") != "1",
    reason="Set FINSIGHT_MINERU_INTEGRATION=1 to check local MinerU",
)


def test_project_mineru_health_and_expected_parse_fields() -> None:
    base_url = get_settings().mineru_api_url

    health = httpx.get(f"{base_url}/health", timeout=10)
    health.raise_for_status()
    assert health.json()["status"] == "healthy"
    assert health.json()["version"] == "3.4.5"

    schema = httpx.get(f"{base_url}/openapi.json", timeout=10)
    schema.raise_for_status()
    specification = schema.json()
    parse_request = specification["paths"]["/file_parse"]["post"]["requestBody"]
    reference = parse_request["content"]["multipart/form-data"]["schema"]["$ref"]
    body_name = reference.rsplit("/", 1)[-1]
    fields = specification["components"]["schemas"][body_name]["properties"]
    assert {"files", "return_md", "return_content_list", "return_middle_json"} <= set(fields)
