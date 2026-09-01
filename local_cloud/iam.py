"""Tiny IAM-style authorization checks for the local object store."""

from __future__ import annotations


SERVICE_ACTORS = {"aggregator", "api", "system"}


class AccessDenied(PermissionError):
    """Raised when a local actor tries to access a disallowed object prefix."""


def assert_allowed(actor: str, action: str, key: str) -> None:
    if actor in SERVICE_ACTORS:
        return

    if not actor.startswith("hospital_"):
        raise AccessDenied(f"Unknown actor: {actor}")

    own_prefix = f"clients/{actor}/"
    can_access_own_prefix = key.startswith(own_prefix)
    can_read_global_model = action in {"GetObject", "ListObjects"} and key.startswith("global/")

    if can_access_own_prefix or can_read_global_model:
        return

    raise AccessDenied(f"{actor} cannot {action} {key}")
