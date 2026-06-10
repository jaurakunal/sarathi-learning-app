"""Interruption handling protocol — seam for Spot instances later."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Optional


@dataclass
class PipelineState:
    step: str
    papers_processed: list[str]
    papers_remaining: list[str]


class InterruptionHandler(Protocol):
    def checkpoint(self, state: PipelineState) -> None: ...
    def resume(self) -> Optional[PipelineState]: ...


class NoOpInterruptionHandler:
    """v0: on-demand compute, no interruptions to handle."""

    def checkpoint(self, state: PipelineState) -> None:
        pass

    def resume(self) -> Optional[PipelineState]:
        return None
