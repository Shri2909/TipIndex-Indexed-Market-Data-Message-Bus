# Documentation audit

## DOC-01 — Prospective and historical statements describe obsolete current state

- Severity: **low**; status before edits: **confirmed**.
- Locations: `docs/report/POLL_BUDGET.md` calls its previous source freeze current; `README.md` directs current closeout to the earlier remediation gate; `docs/plan/ARCHITECTURE.md:555,583` says no optimizer check has run despite P7 acceptance. The dated earlier remediation report's deferred-F-01 statement describes that earlier phase and remains preserved.
- Impact: a reader can mistake historical validation or prospective plan wording for the current implementation/acceptance status. Historical measured values themselves are not invalidated by these wording issues.
- Correction: explicitly date and scope prior freezes, link the subsequent F-01 and independent audit records, and point current closeout at this audit's separate current-source evidence. Keep historical reports, accepted results and gates unchanged. Architecture requirement descriptions will cite the executed P7 checks without broadening exact coverage.
- Validation: inspect linked artifacts and final current-source acceptance; historical audit/remediation reports and evidence hashes remain preserved.

Closure: **fixed and verified** by contextual README/contract links, corrected architecture validation statements, the current report/acceptance, and fresh historical-identity verification. Earlier dated audit/remediation reports were left untouched.
