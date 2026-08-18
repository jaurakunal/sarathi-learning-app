"""Lightweight CloudWatch metric emission via the Embedded Metric Format (EMF).

EMF lets a Lambda emit a metric by writing one structured JSON line to stdout.
CloudWatch Logs extracts the metric asynchronously, so there is no synchronous
PutMetricData call to add latency or fail, and no extra IAM permission needed
beyond the default Lambda log access.

Usage:
    from backend.shared import metrics
    metrics.emit("FeedCardsGenerated", 5, dimensions={"Step": "digest"})

The metric shows up in CloudWatch under namespace "Sarathi". Dimensions are
optional; keep the set small (each unique combination is a separate metric and
costs money). Extra non-dimension context can be attached via ``properties`` —
it is searchable in Logs Insights but does not create metrics.

This module never raises: a monitoring failure must not break a request or a
pipeline step. On any error it falls back to a plain log line.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

NAMESPACE = "Sarathi"

_VALID_UNITS = {
    "Count", "Milliseconds", "Seconds", "Bytes", "Percent", "None",
}


def emit(
    name: str,
    value: float,
    unit: str = "Count",
    dimensions: Optional[dict] = None,
    properties: Optional[dict] = None,
) -> None:
    """Emit a single metric via EMF. Never raises.

    Args:
        name: Metric name (e.g. "FeedCardsGenerated").
        value: Numeric value.
        unit: CloudWatch unit; defaults to Count.
        dimensions: Optional dict of dimension name -> value. Kept small.
        properties: Optional extra fields for Logs Insights (not metricized).
    """
    try:
        if unit not in _VALID_UNITS:
            unit = "None"
        dims = {k: str(v) for k, v in (dimensions or {}).items() if v is not None}
        dim_keys = list(dims.keys())

        emf = {
            "_aws": {
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": NAMESPACE,
                        # A single dimension set. CloudWatch also emits the
                        # metric with no dimensions when the list is empty.
                        "Dimensions": [dim_keys] if dim_keys else [[]],
                        "Metrics": [{"Name": name, "Unit": unit}],
                    }
                ],
            },
            name: value,
            **dims,
        }
        if properties:
            for k, v in properties.items():
                # Don't clobber the metric/dimension keys.
                if k not in emf and k != name:
                    emf[k] = v

        # EMF must be a standalone JSON line on stdout.
        print(json.dumps(emf))
    except Exception:
        # Monitoring must never break the caller.
        logger.debug("metrics.emit failed for %s", name, exc_info=True)
