"""Observability & Metrics Module — Pipeline telemetry, performance tracking,
and real-time analytics for enterprise monitoring.

Aligned with Akaike Technologies' MLOps and DataOps standards.
"""
from __future__ import annotations
import time
import threading
from collections import defaultdict
from app.core.logging import get_logger

logger = get_logger(__name__)

_lock = threading.Lock()


class PipelineMetrics:
    """Collects and exposes pipeline-level metrics for observability.
    Tracks query patterns, latency distributions, cache efficiency,
    and verification pass rates — critical for enterprise SLA monitoring.
    """

    def __init__(self):
        self._counters = defaultdict(int)
        self._histograms = defaultdict(list)
        self._gauges = {}
        self._start_time = time.time()

    def increment(self, metric: str, value: int = 1):
        with _lock:
            self._counters[metric] += value

    def record_latency(self, stage: str, elapsed_ms: float):
        with _lock:
            hist = self._histograms[stage]
            hist.append(elapsed_ms)
            if len(hist) > 1000:
                hist[:] = hist[-500:]

    def set_gauge(self, metric: str, value: float):
        with _lock:
            self._gauges[metric] = value

    def get_summary(self) -> dict:
        with _lock:
            uptime = round(time.time() - self._start_time, 1)
            summary = {
                "uptime_seconds": uptime,
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "latency_summary": {},
            }
            for stage, values in self._histograms.items():
                if values:
                    sorted_v = sorted(values)
                    n = len(sorted_v)
                    summary["latency_summary"][stage] = {
                        "count": n,
                        "avg_ms": round(sum(sorted_v) / n, 2),
                        "min_ms": round(sorted_v[0], 2),
                        "max_ms": round(sorted_v[-1], 2),
                        "p50_ms": round(sorted_v[n // 2], 2),
                        "p95_ms": round(sorted_v[int(n * 0.95)], 2),
                        "p99_ms": round(sorted_v[int(n * 0.99)], 2),
                    }
            return summary

    def reset(self):
        with _lock:
            self._counters.clear()
            self._histograms.clear()
            self._gauges.clear()
            self._start_time = time.time()


# Singleton metrics collector
pipeline_metrics = PipelineMetrics()
