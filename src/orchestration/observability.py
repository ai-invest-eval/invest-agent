"""F handoff stub, available before worker/planner modules are merged."""


def log_decision(trace_id: str, node: str, decision: str, reason, **extra) -> None:
    """F replaces this with redacted JSONL logging. State carries summaries only."""
