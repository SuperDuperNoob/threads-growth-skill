"""Inspect and upgrade Meta (Threads/Facebook) access tokens.

Meta tokens come in two flavors:
- short-lived (~1 hour) — what Graph API Explorer gives by default
- long-lived (~60 days) — what you get by exchanging a short-lived one

Without proactive renewal, sync fails silently when the token dies. We
inspect via /debug_token and (if app_id+app_secret are configured) exchange
to a long-lived variant. Either way, we record the expires_at timestamp
so callers can warn the user before it lapses.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from orbit.config import Config

# Threads uses graph.threads.net; Facebook uses graph.facebook.com. Both
# accept the same /debug_token + /oauth/access_token routes but on their
# own host.
HOSTS = {
    "threads": "https://graph.threads.net",
    "facebook": "https://graph.facebook.com",
}


@dataclass
class TokenInfo:
    token: str
    expires_at_iso: str | None
    upgraded: bool


def inspect_and_upgrade_token(token: str, platform: str) -> TokenInfo:
    """Inspect the token's expiry and, if we have app credentials, upgrade it
    to long-lived. Returns the (possibly new) token + expiry.

    Raises on hard errors (token rejected). Soft failures (no app credentials,
    no expiry returned) are surfaced via the TokenInfo fields, not exceptions.
    """
    host = HOSTS.get(platform, HOSTS["facebook"])

    cfg = Config()
    app_id = cfg.get(f"{platform}.app_id")
    app_secret = cfg.get(f"{platform}.app_secret")

    upgraded = False
    final_token = token

    # 1. Try the upgrade if we have credentials. Skip silently if not.
    #    Threads and Facebook use DIFFERENT endpoints + grant types for token exchange:
    #      Facebook: GET /oauth/access_token?grant_type=fb_exchange_token&client_id=&client_secret=&fb_exchange_token=
    #      Threads:  GET /access_token?grant_type=th_exchange_token&client_secret=&access_token=
    #    (the Threads call does NOT take client_id and does NOT live under /oauth/)
    #    See: https://developers.facebook.com/docs/threads/get-started/long-lived-tokens
    if app_id and app_secret:
        try:
            if platform == "threads":
                r = httpx.get(
                    f"{host}/access_token",
                    params={
                        "grant_type": "th_exchange_token",
                        "client_secret": app_secret,
                        "access_token": token,
                    },
                    timeout=15,
                )
            else:
                r = httpx.get(
                    f"{host}/oauth/access_token",
                    params={
                        "grant_type": "fb_exchange_token",
                        "client_id": app_id,
                        "client_secret": app_secret,
                        "fb_exchange_token": token,
                    },
                    timeout=15,
                )
            r.raise_for_status()
            data = r.json()
            if data.get("access_token"):
                final_token = data["access_token"]
                upgraded = True
                # Threads returns expires_in (seconds) — capture it now so we
                # don't depend on the /debug_token inspect step that often
                # rejects user tokens without app-token credentials.
                if data.get("expires_in"):
                    from datetime import datetime, timedelta, timezone as _tz
                    expiry = datetime.now(_tz.utc) + timedelta(seconds=int(data["expires_in"]))
                    # Stash on a closure-accessible attribute via the return path below
                    final_expires_at = expiry.isoformat()
                else:
                    final_expires_at = None
            else:
                final_expires_at = None
        except httpx.HTTPError:
            # Exchange can fail for many reasons (already long-lived, wrong
            # app, scope mismatch). Fall through and keep the original token.
            final_expires_at = None
    else:
        final_expires_at = None

    # 2. Inspect — works with or without app credentials. App access token
    #    (app_id|app_secret) gives more info; otherwise we send the same token
    #    as input_token AND access_token, which still returns expires_at for
    #    user tokens on most Meta endpoints.
    inspector_token = f"{app_id}|{app_secret}" if (app_id and app_secret) else final_token
    expires_at_iso: str | None = None
    try:
        r = httpx.get(
            f"{host}/debug_token",
            params={
                "input_token": final_token,
                "access_token": inspector_token,
            },
            timeout=15,
        )
        r.raise_for_status()
        data = (r.json() or {}).get("data") or {}
        expires_at = data.get("expires_at") or data.get("data_access_expires_at") or 0
        if expires_at:
            expires_at_iso = datetime.fromtimestamp(int(expires_at), tz=timezone.utc).isoformat()
    except httpx.HTTPError:
        # Inspect failing isn't fatal — caller just won't get expiry tracking.
        pass

    # Fall back to the expires_in we captured from the exchange response, if
    # /debug_token didn't yield one (common for Threads user tokens which
    # /debug_token often refuses without an app-token inspector).
    if not expires_at_iso and final_expires_at:
        expires_at_iso = final_expires_at

    return TokenInfo(token=final_token, expires_at_iso=expires_at_iso, upgraded=upgraded)


def days_until_expiry(expires_at_iso: str | None, now: datetime | None = None) -> int | None:
    """Return whole days remaining until the token expires, or None if unknown."""
    if not expires_at_iso:
        return None
    try:
        when = datetime.fromisoformat(expires_at_iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    delta = when - (now or datetime.now(timezone.utc))
    return int(delta.total_seconds() // 86400)
