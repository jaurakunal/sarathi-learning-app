"""Web Push notification sender."""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

import boto3

from backend.shared import db

logger = logging.getLogger(__name__)


def _get_vapid_keys() -> Optional[dict]:
    """Read VAPID keys from SSM."""
    param_name = os.environ.get("VAPID_KEYS_PARAM", "/sarathi/vapid-keys")
    try:
        ssm = boto3.client("ssm")
        resp = ssm.get_parameter(Name=param_name, WithDecryption=True)
        return json.loads(resp["Parameter"]["Value"])
    except Exception:
        logger.warning("Could not read VAPID keys from SSM")
        return None


def send_push_notification(
    table,
    user_id: str,
    title: str,
    body: str,
    url: Optional[str] = None,
) -> int:
    """Send a push notification to all of a user's subscribed devices.

    Returns number of notifications successfully sent.
    """
    from pywebpush import webpush, WebPushException

    vapid_keys = _get_vapid_keys()
    if not vapid_keys:
        logger.warning("No VAPID keys — cannot send push")
        return 0

    subscriptions = db.list_push_subscriptions(table, user_id)
    if not subscriptions:
        return 0

    payload = json.dumps({
        "title": title,
        "body": body,
        "url": url or "/",
    })

    sent = 0
    for sub in subscriptions:
        subscription_info = {
            "endpoint": sub["endpoint"],
            "keys": sub["keys"],
        }
        try:
            webpush(
                subscription_info=subscription_info,
                data=payload,
                vapid_private_key=vapid_keys["private_key"],
                vapid_claims={"sub": f"mailto:{vapid_keys['contact_email']}"},
            )
            sent += 1
        except WebPushException as e:
            if "410" in str(e) or "404" in str(e):
                logger.info("Subscription expired, removing: %s", sub["endpoint"][:60])
                db.delete_push_subscription(table, user_id, sub["endpoint"])
            else:
                logger.warning("Push failed for endpoint %s: %s", sub["endpoint"][:60], e)
        except Exception as e:
            logger.warning("Push error: %s", e)

    logger.info("Sent %d/%d push notifications for user %s", sent, len(subscriptions), user_id)
    return sent
