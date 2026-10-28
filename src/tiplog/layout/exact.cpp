#include "tiplog/layout/exact.hpp"

#include <algorithm>
#include <bit>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <new>
#include <stdexcept>
#include <utility>
#include <vector>

namespace tiplog::layout {
namespace {
using Clock = std::chrono::steady_clock;

struct Stop { const char* status; };

// Work is deterministic; the clock is an additional wall-time guard. ENUM work
// counts node/incidence visits, while DP work counts scanned states/transitions.
struct Run {
  const Limits& limits;
  ExactResult& result;
  Clock::time_point started{Clock::now()};

  void poll() const {
    const auto elapsed = std::chrono::duration<double, std::milli>(Clock::now() - started).count();
    if (elapsed >= static_cast<double>(limits.time_limit_ms)) throw Stop{"timeout"};
  }
  void work(std::uint64_t amount = 1) {
    if (amount > limits.max_work - result.work) throw Stop{"state_limit"};
    const auto previous = result.work;
    result.work += amount;
    if ((previous >> 10U) != (result.work >> 10U) || previous == 0) poll();
  }
  void states(std::uint64_t amount) {
    if (amount > limits.max_states - result.states) throw Stop{"state_limit"};
    result.states += amount;
  }
  void finish() {
    result.seconds = std::chrono::duration<double>(Clock::now() - started).count();
  }
};

std::uint64_t size_product(std::uint64_t a, std::uint64_t b) {
  if (b != 0 && a > std::numeric_limits<std::uint64_t>::max() / b)
    throw Stop{"representation_limit"};
  return a * b;
}

std::uint64_t size_sum(std::uint64_t a, std::uint64_t b) {
  if (a > std::numeric_limits<std::uint64_t>::max() - b)
    throw Stop{"representation_limit"};
  return a + b;
}

template<class T>
void allocation_check(std::uint64_t entries) {
  if (entries > std::numeric_limits<std::size_t>::max() / sizeof(T) ||
      entries > std::vector<T>().max_size()) throw Stop{"representation_limit"};
}

bool trivial(const Prepared& problem, std::uint32_t maximum_stores, const Limits& limits,
             ExactResult& result) {
  // Count indexes beyond the number of positive nodes are provably infeasible;
  // do not allocate a user-supplied, potentially UINT32_MAX-sized budget array.
  const auto cap = std::min(maximum_stores, problem.positive_nodes);
  if (problem.positive_nodes != 0 && maximum_stores != 0 &&
      static_cast<std::uint64_t>(cap) + 1 > limits.max_states) throw Stop{"state_limit"};
  allocation_check<ExactCount>(static_cast<std::uint64_t>(cap) + 1);
  result.curve.resize(static_cast<std::size_t>(cap) + 1);
  if (problem.positive_nodes == 0) {
    result.curve[0] = {true, 0, Layout(problem.input.nodes.size(), 0)};
    result.status = "solved";
    result.complete_domain = true;
    return true;
  }
  if (maximum_stores == 0) {
    result.status = "infeasible";
    return true;
  }
  return false;
}

std::uint32_t representative(std::vector<std::uint32_t>& parent, std::uint32_t v) {
  auto root = v;
  while (parent[root] != root) root = parent[root];
  while (parent[v] != v) {
    const auto next = parent[v];
    parent[v] = root;
    v = next;
  }
  return root;
}

struct Back {
  std::uint32_t child_k{0};
  std::uint32_t child_mask{0};
  std::uint8_t previous_z{0};
  std::uint8_t child_z{0};
  bool cut{false};
};
struct Cell {
  Cost value{infinity};
  Back back;
};
struct Stage {
  std::uint32_t cap{0};
  std::vector<Cell> cells;

  Stage(std::uint32_t count_cap, std::size_t masks) : cap(count_cap) {
    const auto count = size_product(size_product(static_cast<std::uint64_t>(cap) + 1, masks), 2);
    allocation_check<Cell>(count);
    cells.resize(static_cast<std::size_t>(count));
  }
  Cell& at(std::uint32_t k, std::uint32_t mask, unsigned z) {
    return cells[(static_cast<std::size_t>(mask) * (static_cast<std::size_t>(cap) + 1) + k) * 2 + z];
  }
  const Cell& at(std::uint32_t k, std::uint32_t mask, unsigned z) const {
    return cells[(static_cast<std::size_t>(mask) * (static_cast<std::size_t>(cap) + 1) + k) * 2 + z];
  }
};
struct Closed {
  Cost value{infinity};
  std::uint32_t k{0}, mask{0};
  std::uint8_t z{0};
};

void improve(Cell& target, Cost value, const Back& back) {
  // Iteration order supplies stable ties, including zero-node attachments.
  if (value < target.value) {
    target.value = value;
    target.back = back;
  }
}

struct Trace {
  std::uint32_t node, stage, k, mask;
  std::uint8_t z;
};

Layout reconstruct(const Prepared& problem, const std::vector<std::vector<Stage>>& stages,
                   const Closed& root, Run& run) {
  Layout cuts(problem.input.nodes.size(), 0);
  std::vector<Trace> pending;
  pending.push_back({0, static_cast<std::uint32_t>(stages[0].size() - 1), root.k, root.mask, root.z});
  while (!pending.empty()) {
    run.work();
    auto state = pending.back();
    pending.pop_back();
    if (state.stage == 0) continue;
    const auto& back = stages[state.node][state.stage].at(state.k, state.mask, state.z).back;
    const auto child = problem.children[state.node][state.stage - 1];
    cuts[child] = static_cast<std::uint8_t>(back.cut);
    const auto consumed = back.child_k + (back.cut ? back.child_z : 0U);
    if (consumed > state.k) throw std::logic_error("invalid DP reconstruction count");
    pending.push_back({state.node, state.stage - 1, state.k - consumed, state.mask, back.previous_z});
    pending.push_back({child, static_cast<std::uint32_t>(stages[child].size() - 1),
                       back.child_k, back.child_mask, back.child_z});
  }
  return cuts;
}
} // namespace

ExactResult enumerate(const Prepared& problem, std::uint32_t maximum_stores, const Limits& limits) {
  ExactResult result;
  Run run{limits, result};
  try {
    if (trivial(problem, maximum_stores, limits, result)) { run.finish(); return result; }
    run.poll();
    const auto n = problem.input.nodes.size();
    const auto edges = n - 1;
    // Gray-code representation is separate from the arbitrary-size class list.
    if (edges > limits.enum_max_edges || edges >= 64 || n >= no_parent)
      throw Stop{"representation_limit"};
    const auto candidates = std::uint64_t{1} << edges;
    if (candidates > limits.max_states) throw Stop{"state_limit"};

    // An incidence list, sorted by class, supports more than 64 classes without
    // sharing masks, component construction, or read-cost helpers with the DP.
    std::uint64_t incidence_count = 0;
    for (std::size_t v = 0; v < n; ++v) {
      if (problem.input.nodes[v].bytes != 0)
        incidence_count = size_sum(incidence_count, problem.node_classes[v].size());
    }
    const auto visits = size_sum(size_sum(n, incidence_count), 1);
    const auto required_work = size_product(candidates, visits);
    if (required_work > limits.max_work) throw Stop{"state_limit"};
    using Incidence = std::pair<std::uint32_t, std::uint32_t>;
    allocation_check<Incidence>(incidence_count);
    std::vector<Incidence> incidences;
    incidences.reserve(static_cast<std::size_t>(incidence_count));
    for (std::uint32_t v = 0; v < n; ++v) {
      if (problem.input.nodes[v].bytes == 0) continue;
      for (const auto consumer : problem.node_classes[v]) incidences.emplace_back(consumer, v);
    }
    std::sort(incidences.begin(), incidences.end());
    run.poll();

    std::vector<std::uint32_t> parent(n), roots(n), seen(n);
    std::vector<std::uint64_t> volume(n);
    std::vector<Cost> component_weight(n);
    Layout cuts(n, 0);
    std::uint64_t previous_gray = 0;
    for (std::uint64_t index = 0; index < candidates; ++index) {
      run.work(visits);
      const auto gray = index ^ (index >> 1U);
      if (index != 0) {
        const auto bit = static_cast<unsigned>(std::countr_zero(gray ^ previous_gray));
        cuts[static_cast<std::size_t>(bit) + 1] ^= 1U;
      }
      previous_gray = gray;
      for (std::uint32_t v = 0; v < n; ++v) parent[v] = v;
      for (std::uint32_t v = 1; v < n; ++v) {
        if (cuts[v] == 0)
          parent[representative(parent, v)] = representative(parent, problem.input.nodes[v].parent);
      }
      std::fill(volume.begin(), volume.end(), 0);
      std::fill(component_weight.begin(), component_weight.end(), Cost{0});
      for (std::uint32_t v = 0; v < n; ++v) {
        roots[v] = representative(parent, v);
        const auto bytes = problem.input.nodes[v].bytes;
        if (bytes > std::numeric_limits<std::uint64_t>::max() - volume[roots[v]])
          throw Stop{"representation_limit"};
        volume[roots[v]] += bytes;
      }
      std::fill(seen.begin(), seen.end(), no_parent);
      for (const auto& [consumer, v] : incidences) {
        const auto root = roots[v];
        if (seen[root] != consumer) {
          seen[root] = consumer;
          component_weight[root] = checked_add(component_weight[root], problem.weights[consumer]);
        }
      }
      std::uint32_t count = 0;
      Cost objective = 0;
      for (std::size_t root = 0; root < n; ++root) {
        if (volume[root] == 0) continue;
        ++count;
        const auto byte_and_read_fee = checked_add(checked_mul(problem.alpha, volume[root]), problem.beta);
        objective = checked_add(objective,
                    checked_add(checked_mul(byte_and_read_fee, component_weight[root]), problem.gamma));
      }
      ++result.states;
      if (count < result.curve.size() && objective < result.curve[count].objective)
        result.curve[count] = {true, objective, cuts};
    }
    run.poll();
    result.status = "solved";
    result.complete_domain = maximum_stores >= problem.positive_nodes;
  } catch (const Stop& stop) {
    result.status = stop.status;
  } catch (const std::overflow_error&) {
    result.status = "representation_limit";
  } catch (const std::length_error&) {
    result.status = "representation_limit";
  } catch (const std::bad_alloc&) {
    result.status = "state_limit";
  }
  run.finish();
  return result;
}

ExactResult mask_dp(const Prepared& problem, std::uint32_t maximum_stores, const Limits& limits) {
  ExactResult result;
  Run run{limits, result};
  try {
    if (trivial(problem, maximum_stores, limits, result)) { run.finish(); return result; }
    run.poll();
    const auto n = problem.input.nodes.size();
    const auto b = problem.weights.size();
    const auto budget = std::min(maximum_stores, problem.positive_nodes);
    // Backpointers use uint32 masks; check before any shift or exponential array.
    if (b > limits.dp_max_classes || b >= 32 || b >= std::numeric_limits<std::size_t>::digits ||
        n >= no_parent || budget == std::numeric_limits<std::uint32_t>::max())
      throw Stop{"representation_limit"};
    const auto masks = std::uint64_t{1} << b;
    if (masks > limits.max_states || n > limits.max_states) throw Stop{"state_limit"};
    allocation_check<Cost>(masks);

    // Each child merge is capped by the positive cardinality processed so far,
    // rather than a full K-by-K convolution at every merge. Count all retained
    // child stages (values and backpointers) before allocating their tables.
    std::vector<std::uint32_t> cardinality(n, 0);
    std::uint64_t entries = 0;
    for (const auto v : problem.postorder) {
      run.work();
      std::uint64_t processed = problem.input.nodes[v].bytes != 0 ? 1 : 0;
      entries = size_sum(entries, size_product(2, masks)); // k=0 initialization
      if (entries > limits.max_states) throw Stop{"state_limit"};
      for (const auto child : problem.children[v]) {
        processed = size_sum(processed, cardinality[child]);
        const auto cap = std::min<std::uint64_t>(budget, processed);
        entries = size_sum(entries, size_product(size_product(cap + 1, masks), 2));
        if (entries > limits.max_states) throw Stop{"state_limit"};
      }
      if (processed > std::numeric_limits<std::uint32_t>::max()) throw Stop{"representation_limit"};
      cardinality[v] = static_cast<std::uint32_t>(processed);
    }
    allocation_check<Cell>(entries);
    run.states(entries);
    run.poll();

    std::vector<Cost> weight(static_cast<std::size_t>(masks), 0);
    std::vector<Cost> byte_price(static_cast<std::size_t>(masks), 0);
    std::vector<Cost> closing_fee(static_cast<std::size_t>(masks), problem.gamma);
    for (std::uint32_t mask = 0; mask < masks; ++mask) {
      run.work();
      if (mask != 0) {
        const auto bit = static_cast<unsigned>(std::countr_zero(mask));
        weight[mask] = checked_add(weight[mask & (mask - 1U)], problem.weights[bit]);
      }
      byte_price[mask] = checked_mul(problem.alpha, weight[mask]);
      closing_fee[mask] = checked_add(checked_mul(problem.beta, weight[mask]), problem.gamma);
    }
    std::vector<std::vector<Stage>> stages(n);
    for (const auto v : problem.postorder) {
      run.poll();
      auto& node_stages = stages[v];
      node_stages.reserve(problem.children[v].size() + 1);
      node_stages.emplace_back(0, static_cast<std::size_t>(masks));
      std::uint32_t local_mask = 0;
      const auto local_positive = problem.input.nodes[v].bytes != 0;
      if (local_positive) {
        for (const auto consumer : problem.node_classes[v]) {
          if (consumer >= b) throw Stop{"representation_limit"};
          local_mask |= std::uint32_t{1} << consumer;
        }
      }
      for (std::uint32_t mask = 0; mask < masks; ++mask) {
        run.work();
        if ((local_mask & mask) == local_mask)
          node_stages.back().at(0, mask, local_positive ? 1U : 0U).value =
              checked_mul(byte_price[mask], problem.input.nodes[v].bytes);
      }
      std::uint32_t processed = local_positive ? 1U : 0U;
      for (const auto child : problem.children[v]) {
        const auto& child_stage = stages[child].back();
        const auto close_cap = std::min(budget, cardinality[child]);
        std::vector<Closed> close(static_cast<std::size_t>(close_cap) + 1);
        for (std::uint32_t mask = 0; mask < masks; ++mask) {
          for (std::uint32_t k = 0; k <= child_stage.cap; ++k) {
            for (unsigned z = 0; z != 2; ++z) {
              run.work();
              const auto value = child_stage.at(k, mask, z).value;
              if (value == infinity || k + z > close_cap) continue;
              const auto final_value = z != 0 ? checked_add(value, closing_fee[mask]) : value;
              if (final_value < close[k + z].value)
                close[k + z] = {final_value, k, mask, static_cast<std::uint8_t>(z)};
            }
          }
        }
        const auto previous_index = node_stages.size() - 1;
        processed += cardinality[child];
        node_stages.emplace_back(std::min(budget, processed), static_cast<std::size_t>(masks));
        const auto& previous = node_stages[previous_index];
        auto& next = node_stages.back();
        for (std::uint32_t mask = 0; mask < masks; ++mask) {
          for (std::uint32_t k1 = 0; k1 <= previous.cap; ++k1) {
            for (unsigned z1 = 0; z1 != 2; ++z1) {
              run.work();
              const auto value = previous.at(k1, mask, z1).value;
              if (value == infinity) continue;
              const auto child_k_cap = std::min(child_stage.cap, budget - k1);
              for (std::uint32_t k2 = 0; k2 <= child_k_cap; ++k2) {
                for (unsigned z2 = 0; z2 != 2; ++z2) {
                  run.work();
                  const auto child_value = child_stage.at(k2, mask, z2).value;
                  if (child_value == infinity) continue;
                  const Back back{k2, mask, static_cast<std::uint8_t>(z1), static_cast<std::uint8_t>(z2), false};
                  improve(next.at(k1 + k2, mask, z1 | z2), checked_add(value, child_value), back);
                }
              }
              const auto child_t_cap = std::min(close_cap, budget - k1);
              for (std::uint32_t t = 0; t <= child_t_cap; ++t) {
                run.work();
                if (close[t].value == infinity) continue;
                const Back back{close[t].k, close[t].mask, static_cast<std::uint8_t>(z1), close[t].z, true};
                improve(next.at(k1 + t, mask, z1), checked_add(value, close[t].value), back);
              }
            }
          }
        }
      }
    }

    // Finalize the root's open component before indexing by actual store count.
    std::vector<Closed> roots(static_cast<std::size_t>(budget) + 1);
    const auto& root_stage = stages[0].back();
    for (std::uint32_t mask = 0; mask < masks; ++mask) {
      for (std::uint32_t k = 0; k <= root_stage.cap; ++k) {
        for (unsigned z = 0; z != 2; ++z) {
          run.work();
          const auto value = root_stage.at(k, mask, z).value;
          if (value == infinity || k + z > budget) continue;
          const auto final_value = z != 0 ? checked_add(value, closing_fee[mask]) : value;
          if (final_value < roots[k + z].value)
            roots[k + z] = {final_value, k, mask, static_cast<std::uint8_t>(z)};
        }
      }
    }
    for (std::uint32_t count = 0; count <= budget; ++count) {
      if (roots[count].value == infinity) continue;
      auto cuts = reconstruct(problem, stages, roots[count], run);
      // Independent component reconstruction/pricing validates the relaxed
      // multipliers and empty components. Raw materialization is additionally
      // exercised by external exact/evaluator tests, without its O(n*height)
      // parent walks inside the solver's capped recurrence.
      const auto evaluated = evaluate_formula(problem, cuts);
      if (evaluated.objective != roots[count].value || evaluated.stores != count)
        throw std::logic_error("DP reconstruction disagrees with component cost");
      result.curve[count] = {true, roots[count].value, std::move(cuts)};
      run.poll();
    }
    result.status = "solved";
    result.complete_domain = maximum_stores >= problem.positive_nodes;
  } catch (const Stop& stop) {
    result.status = stop.status;
  } catch (const std::overflow_error&) {
    result.status = "representation_limit";
  } catch (const std::length_error&) {
    result.status = "representation_limit";
  } catch (const std::bad_alloc&) {
    result.status = "state_limit";
  }
  run.finish();
  return result;
}

ExactCount at_most(const ExactResult& result, std::uint32_t budget) {
  ExactCount best;
  if (result.status != "solved") return best;
  const auto end = static_cast<std::size_t>(
      std::min<std::uint64_t>(result.curve.size(), static_cast<std::uint64_t>(budget) + 1));
  for (std::size_t count = 0; count < end; ++count) {
    const auto& candidate = result.curve[count];
    // Ascending counts and strict improvement choose the fewest actual stores
    // when objectives tie; the solver's first cut-set tie stays unchanged.
    if (candidate.feasible && candidate.objective < best.objective) best = candidate;
  }
  return best;
}
} // namespace tiplog::layout
