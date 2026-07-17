"""Tests for POST /research/proposal handler."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from backend.api.proposal import handler
from backend.research.proposal_context import ProposalContext


def _event(body: dict | None, user_id="test-user"):
    return {
        "httpMethod": "POST",
        "requestContext": {"authorizer": {"claims": {"sub": user_id}}},
        "queryStringParameters": None,
        "body": json.dumps(body) if body is not None else None,
    }


def _fake_ctx():
    return ProposalContext(
        workspace_name="Default",
        area_name="AI clone",
        area_description="",
        hypothesis_statement="H",
        background="",
        learning_style="",
    )


@patch("backend.api.proposal.resolve_workspace_id", return_value="w1")
@patch("backend.api.proposal.render_bundle_md", return_value="# bundle md\n")
@patch("backend.api.proposal.assemble_context", return_value=_fake_ctx())
@patch("backend.api.proposal.boto3")
def test_bundle_mode_returns_markdown(mock_boto, mock_assemble, mock_bundle, mock_resolve):
    mock_boto.resource.return_value.Table.return_value = MagicMock()
    resp = handler(_event({"mode": "bundle"}), None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["markdown"].startswith("# bundle md")
    assert body["mode"] == "bundle"
    assert body["filename"].endswith(".md")
    assert "ai-clone-context" in body["filename"]


@patch("backend.api.proposal.resolve_workspace_id", return_value="w1")
@patch("backend.api.proposal.render_proposal_md", return_value="# full draft\n")
@patch("backend.api.proposal.assemble_context", return_value=_fake_ctx())
@patch("backend.api.proposal.boto3")
def test_full_mode_calls_llm_renderer(mock_boto, mock_assemble, mock_full, mock_resolve):
    mock_boto.resource.return_value.Table.return_value = MagicMock()
    resp = handler(_event({"mode": "full"}), None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["markdown"] == "# full draft\n"
    assert body["mode"] == "full"
    assert "ai-clone-proposal" in body["filename"]
    mock_full.assert_called_once()


def test_missing_auth_returns_401():
    resp = handler({"httpMethod": "POST", "body": "{}"}, None)
    assert resp["statusCode"] == 401


def test_bad_mode_returns_400():
    resp = handler(_event({"mode": "nonsense"}), None)
    assert resp["statusCode"] == 400


@patch("backend.api.proposal.resolve_workspace_id", return_value=None)
@patch("backend.api.proposal.boto3")
def test_no_workspace_returns_400(mock_boto, mock_resolve):
    mock_boto.resource.return_value.Table.return_value = MagicMock()
    resp = handler(_event({"mode": "bundle"}), None)
    assert resp["statusCode"] == 400
