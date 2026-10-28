# Final independent peer review — 2026-10-28

The core production and polling-test files remain identical to the identities
in `core/manifest.json`: all 16 recorded entries match. No additional C++ tests,
campaigns or timing runs were required or executed for this peer review.

## F-01 resource accounting

Reviewed `scripts/f01_summary.py` against C++ fixture construction and
`Index::sizing_blocks`. For the fixed 1,024-entry block size, the independently
computed count `ceil(ring_bytes/16384) + 2*(K+5) + 1` exactly matches the C++
pool sizing. Checkpoints consume `(ring_bytes/4096+2)*8` bytes; each pool block
reserves at least `32+4096+1+16` bytes. The preflight also includes the same
`(K+5)*128` control estimate and `(K+5)*4096` topic allowance. The reported exact
subtotal is separately checked against ring/checkpoint/topic/index components,
with a guaranteed lower bound for index storage whose remaining capacity
depends on standard-library allocation behavior.

All three preserved K8192 positive rows validate, including their 101,851,965
reported subtotal. Forged K12288/K65535 rows with understated reserve reject
before fixture reconstruction. Results and source identities are in
`f01-resource-review.json`. No blocking issue was found in this correction.

## EVID-01 configuration suppression

The initial peer reproduction showed that required sanitizer tokens plus an
indirect response file containing `-fno-sanitize=all` passed validation while
Clang emitted an uninstrumented object. Its directly instrumented positive
control retained ASan and UBSan references. The pre-correction flags, object
hashes and symbols are in `sanitizer-response-review-before.json`.

Reviewed the owner's final fail-closed guard for response files, unbound forced
inputs, sanitizer suppression/configuration switches and compiler/backend
pass-throughs. It rejects the exact response counterexample plus ignorelists,
blacklists, `-Xclang=`, `-mllvm`, forced headers, linker response files, and
separated `-D NDEBUG`. Ordinary warning extensions and all four actual recorded
preset configurations still validate. Independently executed the helper suite:
**89 tests passed**. The guard source hash, eight negative controls, positive
controls and test output are in `evid01-suppression-review-after.json` and
`evid01-suppression-review-pytest.log`. No blocking issue was found in the final
reviewed guard. This is local provenance validation, not an attestation against
a malicious compiler/host or arbitrary fabricated observations.

## Audit acceptance composition

Reviewed the corrected `acceptance.py` composition and related checker methods.
The gate binds exact standalone layout argv/output paths and CC5 stdout, both
primary Release and sanitizer executions, normalization to the actually
executed benchmark destination and repetition, unique canonical historical
paths, and exact private-corpus fuzz commands. The matched-seed comparison now
requires the intended Release command and binds the sanitizer summary to its
executed result before comparing all counters. Layout agent independently
re-reviewed its four earlier composition findings and confirmed closure.

No further blocking misbinding was found in these reviewed paths. Root owns
the final whole-suite Python execution, frozen-source inventory, performance
follow-up, report totals and final acceptance execution; this review does not
claim those still-pending actions already passed.
