"""Evidence-backed candidate mining. No rendering and no remote model calls."""

from clipforge.candidates.engine import mine_documents, reset_stage_calls, stage_calls

__all__ = ["mine_documents", "reset_stage_calls", "stage_calls"]
