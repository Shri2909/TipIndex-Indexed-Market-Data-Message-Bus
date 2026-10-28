// Red-team probe (AUD-001): cost of interning one deep topic path and of
// compiling an unrelated subscription afterwards. Usage: depth_probe DEPTH [hook]
#include "tiplog/engine/engine.hpp"

#include <malloc.h>

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <optional>
#include <string>

int main(int argc, char** argv) {
  if (argc < 2) return 2;
  const std::size_t depth = std::strtoull(argv[1], nullptr, 10);
  std::string path = "a";
  for (std::size_t i = 1; i < depth; ++i) path += "/a";
  tiplog::Engine engine;
  std::optional<tiplog::subs::CompiledSubscription> hook;
  if (argc > 2) hook.emplace(engine.compile({{{tiplog::Term::Subtree, "a"}}}));
  const auto before = mallinfo2().uordblks + mallinfo2().hblkhd;
  auto t = std::chrono::steady_clock::now();
  (void)engine.intern(path);
  const double intern_s = std::chrono::duration<double>(std::chrono::steady_clock::now() - t).count();
  const auto heap = mallinfo2().uordblks + mallinfo2().hblkhd - before;
  t = std::chrono::steady_clock::now();
  (void)engine.compile({{{tiplog::Term::Subtree, "zz/q"}}});
  const double compile_s = std::chrono::duration<double>(std::chrono::steady_clock::now() - t).count();
  std::printf("depth=%zu path_bytes=%zu hook=%d intern_s=%.3f compile_s=%.3f heap_bytes=%zu\n", depth,
              path.size(), argc > 2, intern_s, compile_s, heap);
}
