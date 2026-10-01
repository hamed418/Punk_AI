"""
graph/builder/
──────────────
Campaign-builder agent package (PR5 of the graph refactor) — the sole campaign
build+publish path after the four-wizard chain was removed.

``builder.executors`` holds the shared execution + presentation cores (geo /
maid / campaign / media), relocated out of the former wizard subgraphs. The
planner subgraph (builder_plan / builder_ask / builder_act / builder_finalize)
drives collection, discovery, brief/JSON generation, and publish.
"""
