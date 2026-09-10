"""Inbound git-webhook handling for the CI/CD pipeline.

A GitHub/GitLab push whose commit SHA matches a ``staged`` change request
advances that change request: ``approve`` (dispatch the deploy run) when the
repository has ``webhook_auto_deploy``, otherwise ``mark_reviewed``. The
endpoint is unauthenticated — its only defences are HMAC / shared-secret
verification, per-repo+IP rate limiting, replay dedup, and fail-closed on a
missing secret. See ``doc/CICD_PIPELINE.md`` §3.5.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

import service_factory
from core.domain_exceptions import ConflictError
from core.webhook_signatures import (
    GITHUB_SIGNATURE_HEADER,
    GITLAB_TOKEN_HEADER,
    verify_github_signature,
    verify_gitlab_token,
)
from repositories.change_request_repository import ChangeRequestRepository
from services.auth.login_rate_limiter import RateLimitExceededError
from services.change_requests.change_request_service import ChangeRequestService
from services.git.repository_service import GitRepositoryService

logger = logging.getLogger(__name__)

_DELIVERY_DEDUP_TTL_SECONDS = 24 * 60 * 60
_GITHUB_DELIVERY_HEADER = "X-GitHub-Delivery"
_GITLAB_DELIVERY_HEADER = "X-Gitlab-Event-UUID"

WebhookResult = tuple[int, dict[str, Any]]


def _extract_commit_shas(payload: dict[str, Any]) -> list[str]:
    """Every commit SHA a push payload carries (GitHub or GitLab), including the
    branch tip. The CR-branch push carries the change request's ``commit_sha``
    regardless of the target ref, so target-branch matching is not required.
    """
    shas: list[str] = []
    for key in ("after", "checkout_sha"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            shas.append(value)
    head = payload.get("head_commit")
    if isinstance(head, dict) and isinstance(head.get("id"), str):
        shas.append(head["id"])
    for commit in payload.get("commits", []) or []:
        if isinstance(commit, dict) and isinstance(commit.get("id"), str):
            shas.append(commit["id"])
    # De-dupe, preserve order.
    seen: set[str] = set()
    return [s for s in shas if not (s in seen or seen.add(s))]


class GitWebhookService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo_service = GitRepositoryService(db)
        self.cr_repo = ChangeRequestRepository(db)

    def process(
        self,
        *,
        git_repository_id: int,
        raw_body: bytes,
        headers: dict[str, str],
        client_host: str,
    ) -> WebhookResult:
        repo = self.repo_service.get_repository(git_repository_id)
        if repo is None:
            return 404, {"detail": "not found"}

        secret = self.repo_service.get_webhook_secret(git_repository_id)
        if not secret:
            # Fail closed — a repo without a configured secret cannot be driven
            # by a webhook.
            return 401, {"detail": "webhook not configured"}

        limiter = service_factory.build_login_rate_limiter()
        try:
            limiter.check(f"webhook:{git_repository_id}:{client_host}")
        except RateLimitExceededError:
            return 429, {"detail": "rate limited"}

        lower = {k.lower(): v for k, v in headers.items()}
        github_sig = lower.get(GITHUB_SIGNATURE_HEADER.lower())
        gitlab_token = lower.get(GITLAB_TOKEN_HEADER.lower())
        if github_sig is not None:
            provider = "github"
            verified = verify_github_signature(secret, raw_body, github_sig)
        elif gitlab_token is not None:
            provider = "gitlab"
            verified = verify_gitlab_token(secret, gitlab_token)
        else:
            return 401, {"detail": "missing signature"}
        if not verified:
            logger.warning(
                "Rejected %s webhook for repo_id=%s: bad signature", provider, git_repository_id
            )
            return 401, {"detail": "invalid signature"}

        delivery_id = lower.get(_GITHUB_DELIVERY_HEADER.lower()) or lower.get(
            _GITLAB_DELIVERY_HEADER.lower()
        )
        cache = service_factory.build_cache_service()
        if delivery_id and cache is not None:
            dedup_key = f"webhook-delivery:{git_repository_id}:{delivery_id}"
            if cache.get(dedup_key) is not None:
                return 200, {"status": "duplicate"}
            cache.set(dedup_key, {"seen": True}, ttl_seconds=_DELIVERY_DEDUP_TTL_SECONDS)

        try:
            payload = json.loads(raw_body)
        except (json.JSONDecodeError, ValueError):
            return 400, {"detail": "invalid payload"}
        if not isinstance(payload, dict):
            return 400, {"detail": "invalid payload"}

        change_request = None
        for sha in _extract_commit_shas(payload):
            change_request = self.cr_repo.find_active_for_commit(git_repository_id, sha)
            if change_request is not None:
                break
        if change_request is None:
            return 200, {"status": "ignored"}

        auto_deploy = bool(repo.get("webhook_auto_deploy"))
        service = ChangeRequestService(self.db)
        try:
            if auto_deploy:
                service.approve(change_request.id, actor_user_id=None, via="webhook")
                outcome = "approved"
            else:
                service.mark_reviewed(change_request.id, via="webhook")
                outcome = "reviewed"
        except ConflictError:
            # Already actioned by a UI click or an earlier delivery — not an error.
            return 200, {"status": "ignored"}

        logger.info(
            "Webhook %s change_request_id=%s repo_id=%s outcome=%s",
            provider,
            change_request.id,
            git_repository_id,
            outcome,
        )
        return 202, {"status": outcome, "change_request_id": change_request.id}
