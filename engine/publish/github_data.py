"""
GitHub Git Data API state publisher.
Publishes encrypted state.enc.json as a single orphan commit on the 'data' branch.
Implements spec 04 §7.3.
"""
import hashlib
import json
import logging
import time
from typing import Any, Dict, Optional
import requests
from engine.config import get_settings
from engine.core.clock import get_clock
from engine.publish.snapshot import build_snapshot

logger = logging.getLogger(__name__)


def upload_envelope(
    envelope: Dict[str, Any],
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    token: Optional[str] = None
) -> bool:
    """
    Upload envelope JSON to GitHub Git Data API as a single orphan commit on branch 'data'.
    """
    settings = get_settings()
    owner = owner or settings.publish.owner
    repo = repo or settings.publish.repo
    token = token or settings.GITHUB_TOKEN
    data_branch = settings.publish.data_branch
    path = settings.publish.path

    if not token or not owner or not repo:
        logger.warning("GitHub publish skipped: GITHUB_TOKEN, owner, or repo is not configured.")
        return False

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    base_url = f"https://api.github.com/repos/{owner}/{repo}"

    envelope_content = json.dumps(envelope, ensure_ascii=False)

    try:
        # Step 1: Create git tree
        tree_payload = {
            "tree": [
                {
                    "path": path,
                    "mode": "100644",
                    "type": "blob",
                    "content": envelope_content,
                }
            ]
        }
        r_tree = requests.post(f"{base_url}/git/trees", json=tree_payload, headers=headers, timeout=15)
        if r_tree.status_code != 201:
            logger.error(f"Failed to create git tree ({r_tree.status_code}): {r_tree.text}")
            return False
        tree_sha = r_tree.json()["sha"]

        # Step 2: Create orphan commit (parents=[])
        now_time = get_clock().now().strftime("%H:%M")
        commit_payload = {
            "message": f"state {now_time}",
            "tree": tree_sha,
            "parents": [],
        }
        r_commit = requests.post(f"{base_url}/git/commits", json=commit_payload, headers=headers, timeout=15)
        if r_commit.status_code != 201:
            logger.error(f"Failed to create git commit ({r_commit.status_code}): {r_commit.text}")
            return False
        commit_sha = r_commit.json()["sha"]

        # Step 3: Update ref
        ref_url = f"{base_url}/git/refs/heads/{data_branch}"
        r_ref = requests.patch(ref_url, json={"sha": commit_sha, "force": True}, headers=headers, timeout=15)
        if r_ref.status_code in (200, 201):
            logger.info(f"Published state commit {commit_sha[:7]} to {owner}/{repo}:{data_branch}")
            return True

        if r_ref.status_code in (404, 422):
            # Branch does not exist yet: create reference
            create_ref_url = f"{base_url}/git/refs"
            r_create = requests.post(
                create_ref_url,
                json={"ref": f"refs/heads/{data_branch}", "sha": commit_sha},
                headers=headers,
                timeout=15
            )
            if r_create.status_code in (200, 201):
                logger.info(f"Created branch {data_branch} with commit {commit_sha[:7]}")
                return True
            logger.error(f"Failed to create ref {data_branch} ({r_create.status_code}): {r_create.text}")
            return False

        logger.error(f"Failed to update ref {data_branch} ({r_ref.status_code}): {r_ref.text}")
        return False

    except Exception as e:
        logger.error(f"Exception during GitHub state publish: {e}")
        return False


class StatePublisher:
    """
    Manages throttle, periodic heartbeat, and state publishing.
    """

    def __init__(self):
        self.last_published_time: float = 0.0
        self.last_content_hash: str = ""

    def publish_if_needed(
        self,
        health_info: Optional[Dict[str, Any]] = None,
        force: bool = False,
        engine_status: str = "running"
    ) -> bool:
        settings = get_settings()
        now_ts = time.time()
        min_interval = settings.publish.min_interval_sec
        heartbeat_interval = settings.publish.heartbeat_sec

        envelope, state_dict = build_snapshot(health_info=health_info, engine_status=engine_status)
        state_repr = json.dumps(state_dict, sort_keys=True)
        content_hash = hashlib.sha256(state_repr.encode("utf-8")).hexdigest()

        content_changed = content_hash != self.last_content_hash
        elapsed = now_ts - self.last_published_time

        should_publish = force or (
            content_changed and elapsed >= min_interval
        ) or (
            elapsed >= heartbeat_interval
        )

        if not should_publish:
            return False

        success = upload_envelope(envelope)
        if success:
            self.last_published_time = now_ts
            self.last_content_hash = content_hash
        return success
