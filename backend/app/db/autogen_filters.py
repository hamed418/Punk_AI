"""
What ``--autogenerate`` is allowed to touch.

Lives here rather than in ``alembic/env.py`` because that module runs the
migrations at import time and so cannot be imported by a test — and ``alembic/``
is not a package, so a module beside ``env.py`` would collide with the installed
``alembic`` library on import.

The reason it exists: ``cf552df2d140``, an unreviewed autogenerate revision named
"added in ads model selected_account_id", also contained ``drop_table`` for all
four LangGraph checkpointer tables and ``drop_column('campaigns',
'publish_state')``. Autogenerate compares the live database against
``Base.metadata`` and writes a DROP for anything it finds that the models do not
declare — and the checkpointer tables are created and owned by
``AsyncPostgresSaver`` (graph.py), so they are never in the metadata.
"""
from __future__ import annotations

# Created and owned by LangGraph's AsyncPostgresSaver, not by this app's models.
LANGGRAPH_TABLES: frozenset[str] = frozenset({
    "checkpoints", "checkpoint_blobs", "checkpoint_writes", "checkpoint_migrations",
})


def include_object(obj, name, type_, reflected, compare_to) -> bool:
    """Keep autogenerate out of tables this app does not own."""
    if type_ == "table" and name in LANGGRAPH_TABLES:
        return False
    # An index on a skipped table would otherwise still be proposed for dropping.
    if type_ == "index" and getattr(obj, "table", None) is not None:
        return obj.table.name not in LANGGRAPH_TABLES
    return True
