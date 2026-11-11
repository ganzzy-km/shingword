"""Expiry boundary only. Does not decide a retention basis or delete anything."""
from .auth import require_private_owner


def require_retention_policy(policy):
    required = {"basis", "targetScope", "backupRetention", "accountPolicy", "publicDocumentPolicy"}
    if not isinstance(policy, dict) or not required <= policy.keys() or any(policy[k] is None for k in required):
        raise ValueError("RETENTION_POLICY_UNCONFIRMED")


def guarded_output(user, *, owner_id, expires_at, now, producer):
    """Check before AND after a long analysis/PDF producer; return no stale bytes."""
    require_private_owner(user, owner_id, expires_at=expires_at, now=now())
    result = producer()
    require_private_owner(user, owner_id, expires_at=expires_at, now=now())
    return result
