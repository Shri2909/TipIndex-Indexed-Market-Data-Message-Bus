# P7 timing interpretation

The frozen protocol's phrase "excluding prepare and independent reconstructed
evaluation" refers to preparation and the CLI's separate formula/materialized
verification after a solver returns. `ExactResult.seconds` includes everything
inside the exact solver, including reconstruction and its internal formula cost
consistency check. H-KM timing includes the heuristic's own formula evaluation.
The CLI's independent full-metric verification is excluded from `seconds` and
included in `verified_seconds`. This clarification changes no source, timing
boundary, cap, input, count domain or acceptance criterion. Solver times are
diagnostics on a nonexclusive laptop, not engine latency or disk recovery time.
