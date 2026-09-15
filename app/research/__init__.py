"""Layer3外部研究任务的可恢复执行框架。"""

from .contracts import ResearchExecutionSummary, ResearchResultProvider
from .execution import (
    DISABLED,
    DOCKER_OPENCLAW,
    LOCAL_OPENCLAW,
    RESEARCH_EXECUTORS,
    ResearchExecutionConfig,
    resolve_research_execution,
)
from .orchestrator import ResearchOrchestrator
from .workspace import ResearchWorkspace, load_research_request

__all__ = [
    "ResearchExecutionSummary",
    "ResearchExecutionConfig",
    "ResearchOrchestrator",
    "ResearchResultProvider",
    "ResearchWorkspace",
    "load_research_request",
    "resolve_research_execution",
    "LOCAL_OPENCLAW",
    "DOCKER_OPENCLAW",
    "DISABLED",
    "RESEARCH_EXECUTORS",
]
