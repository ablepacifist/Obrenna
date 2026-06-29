"""LangGraph workflow: CSV file -> profiled data -> dashboard spec -> validated -> saved.

`generate_artifact_spec` is deterministic today (wraps the dashboard builder). It is the
single seam where a configured local model could later author the spec instead — the rest
of the graph (load/profile/validate/save) stays identical.
"""
from __future__ import annotations

from typing import Any, Callable, Optional, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from ..schemas.artifact import validate_artifact
from ..services import csv_profiler, dashboard_builder


class DashboardState(TypedDict, total=False):
    file_path: str
    file_id: Optional[str]
    filename: str
    instruction: Optional[str]
    df: Any
    profile: dict
    artifact_spec: dict
    artifact_id: Optional[str]
    errors: list[str]


def _load_csv(state: DashboardState) -> DashboardState:
    state["df"] = csv_profiler.load_csv(state["file_path"])
    return state


def _profile_data(state: DashboardState) -> DashboardState:
    state["profile"] = csv_profiler.profile_dataframe(state["df"])
    return state


def _generate_artifact_spec(state: DashboardState) -> DashboardState:
    # Deterministic. Swap to model_runtime.chat_completion(...) here later.
    state["artifact_spec"] = dashboard_builder.build_dashboard(
        state["df"],
        state["profile"],
        file_id=state.get("file_id"),
        filename=state.get("filename", "data.csv"),
        instruction=state.get("instruction"),
    )
    return state


def _validate_artifact_spec(state: DashboardState) -> DashboardState:
    # Raises if the generated spec doesn't conform to the canonical schema.
    validate_artifact(state["artifact_spec"])
    return state


def _save_artifact(state: DashboardState, config: RunnableConfig) -> DashboardState:
    save_fn: Optional[Callable[[dict], str]] = (
        (config or {}).get("configurable", {}).get("save_fn")
    )
    if save_fn:
        state["artifact_id"] = save_fn(state["artifact_spec"])
    return state


_compiled = None


def build_graph():
    graph = StateGraph(DashboardState)
    graph.add_node("load_csv", _load_csv)
    graph.add_node("profile_data", _profile_data)
    graph.add_node("generate_artifact_spec", _generate_artifact_spec)
    graph.add_node("validate_artifact_spec", _validate_artifact_spec)
    graph.add_node("save_artifact", _save_artifact)

    graph.add_edge(START, "load_csv")
    graph.add_edge("load_csv", "profile_data")
    graph.add_edge("profile_data", "generate_artifact_spec")
    graph.add_edge("generate_artifact_spec", "validate_artifact_spec")
    graph.add_edge("validate_artifact_spec", "save_artifact")
    graph.add_edge("save_artifact", END)
    return graph.compile()


def run_csv_dashboard(
    *,
    file_path: str,
    file_id: str | None,
    filename: str,
    instruction: str | None,
    save_fn: Callable[[dict], str] | None = None,
) -> DashboardState:
    global _compiled
    if _compiled is None:
        _compiled = build_graph()
    return _compiled.invoke(
        {
            "file_path": file_path,
            "file_id": file_id,
            "filename": filename,
            "instruction": instruction,
            "errors": [],
        },
        config={"configurable": {"save_fn": save_fn}},
    )
