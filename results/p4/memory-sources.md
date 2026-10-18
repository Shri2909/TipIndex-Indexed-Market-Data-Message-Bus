# P4 allocator measurement source and evidence — 2026-10-18

This satisfies the separate allocator-observation requirement without changing the portable index storage model or adding a dependency. It is an allocation diagnostic, not a throughput benchmark.

Original material actually inspected: installed glibc2.43 `/usr/include/malloc.h` lines83–118 (all `mallinfo2` fields/declaration), plus the official [glibc manual §3.2.3.10, Statistics for Memory Allocation](https://sourceware.org/glibc/manual/latest/html_node/Statistics-of-Malloc.html), complete current page on 2026-10-18. The manual is moving documentation; local header SHA-256 is **69214d4b692453c30bbb46dfa477acf9e109f630c51251abc8542a1933048f2b**. No glibc implementation code was reused. The reviewer also inspected the official allocator-tunables discussion to qualify default tcache behavior; no tunable was changed.

Existing finding28 → V17/full index-byte accounting → P4.4 → `tools/tiplog_index_memory.cpp::main` → fresh single-thread release child with raw before/after `mallinfo2`. Only the heap-owned Index object and its own prepared append allocations occur inside the boundary. Parsing/output setup precedes baseline; stats, recount and serialization follow the ending snapshot. No Ring, Registry, input schedule container, process RSS or sanitizer allocator is included. The tool rejects preloaded alternate allocators and is unavailable under ASan.

Report Δ(uordblks+hblkhd), separately Δ(arena+hblkhd), and the signed difference between allocator-charged bytes and Index's exact requested/reserved subtotal. Preserve raw fields and any negative result. Chunk rounding, retained freed/tcache chunks and baseline reuse affect this process-level observation; it is not a universal measurement of per-object headers. The portable `index::Memory::allocator_overhead_measured=false` stays honest: the diagnostic is separate.

Executed release observations (C1MiB,100partitions,100000 synthetic DATA positions):

| B | Exact requested/reserved B | Allocator-charged delta B | Observed signed difference B | Raw command/result |
|---|---:|---:|---:|---|
|256|495497|500256|4759|`memory-allocator-B256-20261018T102300.009793Z.*`|
|1024|1103561|1109344|5783|`memory-allocator-B1024-20261018T102300.026336Z.*`|

Each child verified structural invariants after the allocator snapshot. glibc2.43 and no GLIBC_TUNABLES were recorded in both. These are observations at this boundary, not extrapolated totals for real ITCH workloads. Required benchmark measurements still belong to P5/P6.
