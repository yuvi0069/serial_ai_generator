"""Wires the nodes into the story state machine.

START -> plan_arc -> expand_beats -> [plan_review]* --feedback--> plan_arc
                                          |approve/edit
                                     init_bible -> [next_gate]* --feedback--> apply_feedback -> next_gate
                                                        |continue(N, auto?)
      build_context -> write_episode -> critique --fail & budget left--> revise_episode -> critique
                                          |pass / out of revisions / cost cap
                                     [human_review]* --feedback--> apply_feedback --+
                                          |approve/edit            reject           |
                                     commit_memory <------------------------------+ (approve/edit)
                                          |batch left -> build_context ; else -> next_gate ; done -> END
(* = interrupt: graph pauses, checkpoint persisted, resumes on POST /act)"""
from langgraph.graph import END, START, StateGraph

from ..db import session_scope
from ..memory import store
from .nodes.critic import critique, route_after_critique
from .nodes.feedback import apply_feedback, route_after_feedback
from .nodes.human import (human_review, next_gate, plan_review, route_after_gate,
                          route_after_plan_review, route_after_review)
from .nodes.memory_nodes import commit_memory, route_after_commit
from .nodes.planning import expand_beats, init_bible, plan_arc
from .nodes.writing import build_context_node, revise_episode, write_episode
from .state import StoryState


def route_start(state: StoryState) -> str:
    """Fresh thread: plan first, unless an approved plan already exists (e.g. re-created thread)."""
    with session_scope() as s:
        plan = store.get_plan(s, state["story_id"])
        return "next_gate" if plan and plan.approved else "plan_arc"


def build_graph(checkpointer):
    g = StateGraph(StoryState)
    for name, fn in [("plan_arc", plan_arc), ("expand_beats", expand_beats), ("plan_review", plan_review),
                     ("init_bible", init_bible), ("next_gate", next_gate), ("build_context", build_context_node),
                     ("write_episode", write_episode), ("critique", critique), ("revise_episode", revise_episode),
                     ("human_review", human_review), ("apply_feedback", apply_feedback),
                     ("commit_memory", commit_memory)]:
        g.add_node(name, fn)
    g.add_conditional_edges(START, route_start, ["plan_arc", "next_gate"])
    g.add_edge("plan_arc", "expand_beats")
    g.add_edge("expand_beats", "plan_review")
    g.add_conditional_edges("plan_review", route_after_plan_review, ["plan_arc", "init_bible"])
    g.add_edge("init_bible", "next_gate")
    g.add_conditional_edges("next_gate", route_after_gate, ["build_context", "apply_feedback", END])
    g.add_edge("build_context", "write_episode")
    g.add_edge("write_episode", "critique")
    g.add_conditional_edges("critique", route_after_critique, ["revise_episode", "human_review"])
    g.add_edge("revise_episode", "critique")
    g.add_conditional_edges("human_review", route_after_review, ["apply_feedback", "commit_memory", "build_context"])
    g.add_conditional_edges("apply_feedback", route_after_feedback, ["commit_memory", "build_context", "next_gate"])
    g.add_conditional_edges("commit_memory", route_after_commit, ["build_context", "next_gate"])
    return g.compile(checkpointer=checkpointer)
