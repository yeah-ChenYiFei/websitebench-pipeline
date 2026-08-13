"""Privacy-preserving browser interaction trajectory capture."""

from __future__ import annotations

from .recorder import (
    ACTION_SCHEMA_VERSION,
    SESSION_SCHEMA_VERSION,
    BrowserTrajectoryError,
    RecorderConfig,
    TrajectoryRecorder,
)

__all__ = [
    "ACTION_SCHEMA_VERSION",
    "SESSION_SCHEMA_VERSION",
    "BrowserTrajectoryError",
    "RecorderConfig",
    "TrajectoryRecorder",
]
