"""The World: a spatial model of the swarm where position is a measurement (docs/WORLD_PLAN.md).

features.py   what this stream can tell us, graded observed / derived / inferred / absent, plus cohort labels
layout.py     the two-level embedding (deterministic cohort anchors + bounded forces), spatial features, null model
spec.py       WorldSpec: the fixed primitive library, the encoding grammar, validation, ops, presets, versioned store
engine.py     WorldEngine: runs the layout every window, serialises compact state for the renderer, previews
designer.py   the free composer (fixed rules from the availability table) and the Claude world-designer session
"""
