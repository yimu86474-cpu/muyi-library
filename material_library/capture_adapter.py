from typing import Dict


# Explanation contract: docs/EXPLAIN.md
CAPTURE_ADAPTER_CONTRACT = "muyi.capture-adapter.v1"


def link_collected_result() -> Dict[str, object]:
    """Describe a successful link collection without claiming a local file exists."""
    return {
        "contract_version": CAPTURE_ADAPTER_CONTRACT,
        "operation": "collect_link",
        "outcome": "success",
        "artifact_state": "link_collected",
        "local_file_state": "not_created",
        "preview_state": "external_may_expire",
        "retryable": False,
    }


def link_pending_result() -> Dict[str, object]:
    """Describe a link card that needs another attempt to obtain remote media."""
    return {
        "contract_version": CAPTURE_ADAPTER_CONTRACT,
        "operation": "collect_link",
        "outcome": "needs_review",
        "artifact_state": "link_pending",
        "local_file_state": "not_created",
        "preview_state": "external_pending",
        "retryable": True,
    }


def local_file_saved_result(byte_size: int, sha256: str) -> Dict[str, object]:
    """Describe a verified local video created by an explicit user action."""
    return {
        "contract_version": CAPTURE_ADAPTER_CONTRACT,
        "operation": "save_local",
        "outcome": "success",
        "artifact_state": "local_file_saved",
        "local_file_state": "created",
        "preview_state": "local_verified",
        "retryable": False,
        "byte_size": int(byte_size),
        "sha256": str(sha256),
    }


def local_file_failed_result() -> Dict[str, object]:
    """Keep the link card usable when an explicit local save fails."""
    return {
        "contract_version": CAPTURE_ADAPTER_CONTRACT,
        "operation": "save_local",
        "outcome": "needs_review",
        "artifact_state": "link_collected",
        "local_file_state": "failed",
        "preview_state": "external_may_expire",
        "retryable": True,
    }
