"""
graph.py — LangGraph StateGraph definition.

Pipeline: START → fetch_tos → preprocess → chunk_and_analyze → aggregate → END
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from backend.nodes.aggregate import aggregate
from backend.nodes.chunk_and_analyze import chunk_and_analyze
from backend.nodes.fetch_tos import fetch_tos
from backend.nodes.preprocess import preprocess
from backend.state import AppState


def build_graph() -> StateGraph:
    builder = StateGraph(AppState)

    builder.add_node("fetch_tos", fetch_tos)
    builder.add_node("preprocess", preprocess)
    builder.add_node("chunk_and_analyze", chunk_and_analyze)
    builder.add_node("aggregate", aggregate)

    builder.add_edge(START, "fetch_tos")
    builder.add_edge("fetch_tos", "preprocess")
    builder.add_edge("preprocess", "chunk_and_analyze")
    builder.add_edge("chunk_and_analyze", "aggregate")
    builder.add_edge("aggregate", END)

    return builder


# Compiled graph — imported by main.py
app = build_graph().compile()
