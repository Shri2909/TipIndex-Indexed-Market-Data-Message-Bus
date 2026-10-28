# Subscription compilation scaling repair — 2026-10-23

This is a repair needed to execute the already approved P100000 Tier B T3
matrix. It adds no workload or subscription semantics. The prior failed
Python integration run is retained in
[python-integrated-tests-20261023T143250.416668Z.json](python-integrated-tests-20261023T143250.416668Z.json):
132 tests passed and the 100000-partition case timed out.

## Finding → decision → task/code → validation → evidence

| Finding/contract | Decision and implementation | Executed evidence |
|---|---|---|
| Required T3 P=100000 exposed all-pairs normalization and topic-by-term initial compilation | `src/tiplog/subs/compiled.cpp::normalize` keeps validation, sorted order and de-duplication, then checks every actual slash-delimited ancestor against an owned subtree-root set. Same-path Exact is covered; same-path Subtree is retained | 512 deterministic random specifications match an independent all-pairs segment normalizer; normalized output is idempotent |
| Lexical order does not keep every subtree's descendants adjacent: `a`, `a-foo`, `a/b` | Check segment-boundary prefixes, rather than remembering only the last lexically encountered subtree | `V07Subscriptions.NormalizationHandlesLexicalInterleavingAndSamePathKinds` checks exact normalized terms and compiled/future-topic behavior against the independent segment matcher |
| Initial compilation and later registration must implement the identical union | Immutable `Matching` owns Exact, Subtree and shallow whole-partition root sets. `compile` and `CompiledState::prepare` use the same indexed membership decisions. Stored normalized terms, ordered partition filters, wide-term detection and observer hooks retain their prior contracts | Existing random path/late-topic tests, shallow/wide/exact tests and new 100000 mixed-term test passed |
| v1.1 transaction, lifetime and representation checks remain mandatory | No change to registry interning, observer prepare/commit staging, allocation rollback, filter reservation, local-ID limits or lifetime validation. Searches allocate no temporary prefix strings | Existing observer-allocation-failure, full uint16, exhausted-capacity, copy/move and retained-lifetime tests passed in release and ASan/UBSan |

The 100000-term functional test creates 100000 partitions, each with two event
topics, and mixes exact leaf subscriptions with whole-partition subtrees.
It checks all 200000 event matches, every filter's `all` bit, hook count and
later matching/nonmatching topics. It contains no timing threshold. The
independent scalar normalizer is restricted to small random cases and imports
no production matching or normalization helper.

Lookup count now depends on path depth rather than the number of subscription
terms. Sorting remains O(n log n); hashing depends on the prefix text length,
and hash-table lookup is not claimed worst-case constant. Sets own strings so
their lifetime does not depend on vector storage, and hash iteration order is
never used to determine normalized output or filter order.

No external algorithm or source code was reused. For the standard-library API
actually used, the installed GCC 15.2 libstdc++ original headers were inspected
on 2026-10-23: `/usr/include/c++/15/bits/unordered_set.h` lines 728–793
(C++20 heterogeneous const lookup/contains) and
`/usr/include/c++/15/string_view` lines 782–800 (noexcept string-view hashing).
Header SHA-256 identities are recorded in the adjacent evidence manifest.
This inspection establishes local API behavior; no unpublished Aria mechanism
or Jane Street performance claim is attributed to this independent repair.

## Executed checks

- [Release build](subscriptions-scale-release-build-20261023T143650.663894Z.json):
  complete preset build passed, exit 0.
- [ASan/UBSan build](subscriptions-scale-sanitizer-build-20261023T143650.677501Z.json):
  complete preset build passed, exit 0.
- [Fuzz build](subscriptions-scale-fuzz-build-20261023T143650.684936Z.json):
  complete preset build passed, exit 0.
- [Release topic/subscription tests](subscriptions-scale-release-tests-20261023T143717.259593Z.json):
  19/19 passed.
- [ASan/UBSan topic/subscription tests](subscriptions-scale-sanitizer-tests-20261023T143725.549974Z.json):
  19/19 passed outside tracing with leak checks and halt-on-UB retained.

No CMake or Engine source was edited. Since `compiled.cpp` is linked into the
engine, the phase controller must bind final-source acceptance to the affected
full differential, timed F3 and cross-compiler checks. Earlier evidence remains
historical; the local builds and 19-test suites above do not substitute for
those acceptance campaigns. No timing campaign was run during this repair.
