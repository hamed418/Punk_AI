"""
graph/wizard_exit.py
────────────────────
Signal exception raised inside ``wizard_interrupt()`` when the resume-router
decides the user wants out of the current wizard (e.g. tapped "exit wizard"
on the escape menu, or exceeded the off-path retry budget).

The wizard sub-node catches this exception and returns a state update that
routes execution back to ``chatbot_node``. The catcher (``builder_act`` in
``builder/builder_node.py``) deliberately KEEPS ``campaign_builder_state`` —
only ``next_action`` is cleared — so every slot, POI and plan draft the user
had already built survives the exit.
Kept in its own module so importing it does not pull in the heavier
``wizard_helpers`` graph.
"""

from __future__ import annotations


class WizardExitRequested(Exception):
    """Raised from inside wizard_interrupt() when the user wants to exit.

    Carries no payload — the catching wizard supplies its own ``next_nodes``
    route and decides what of its scratch to keep (currently: all of it).
    """


class StepPaused(Exception):
    """End this task NOW so the planner re-dispatches it as a fresh one.

    Raised by an executor right after its interrupt resolves (an answer it
    persisted, or a non-answer — an edit, question or reject — it stashed), so
    no second ``interrupt()`` is reached in the same task. LangGraph matches
    resume values to interrupts by their order within a task; one interrupt per
    task is what keeps a replay from reading the wrong answer, and what lets a
    stashed edit be applied (by ``builder_plan``) before the step is shown again.
    ``builder_act`` catches it, persists the executor scratch, and returns with
    the operation NOT marked done.
    """
