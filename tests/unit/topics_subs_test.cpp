#include "tiplog/subs/compiled.hpp"
#include "tiplog/topics/registry.hpp"

#include <gtest/gtest.h>

#include <algorithm>
#include <array>
#include <functional>
#include <limits>
#include <set>
#include <random>
#include <sstream>
#include <utility>

namespace {
using tiplog::PartitionId;
using tiplog::SubscriptionSpec;
using tiplog::Term;
using tiplog::TopicId;
using tiplog::subs::compile;
using tiplog::topics::Limits;
using tiplog::topics::Registry;
using tiplog::topics::RepresentationLimit;

// The reference splits into segments and compares segment sequences. It does
// not call registry normalization, prefix matching, or compiled filter helpers.
std::vector<std::string> segments(const std::string& path) {
  std::istringstream stream(path);
  std::vector<std::string> result;
  std::string segment;
  while (std::getline(stream, segment, '/')) result.push_back(segment);
  return result;
}
bool reference_match(const SubscriptionSpec& spec, const std::string& path) {
  const auto actual = segments(path);
  for (const auto& term : spec.terms) {
    const auto expected = segments(term.path);
    if (term.kind == Term::Exact) {
      if (actual == expected) return true;
    } else if (actual.size() >= expected.size() &&
               std::equal(expected.begin(), expected.end(), actual.begin())) {
      return true;
    }
  }
  return false;
}
SubscriptionSpec reference_normalize(SubscriptionSpec spec) {
  // Deliberately retain the small all-pairs algorithm as an independent
  // reference: split segments instead of using production prefix lookups.
  std::sort(spec.terms.begin(), spec.terms.end(), [](const Term& a, const Term& b) {
    return a.path != b.path ? a.path < b.path : a.kind < b.kind;
  });
  spec.terms.erase(std::unique(spec.terms.begin(), spec.terms.end()), spec.terms.end());
  SubscriptionSpec result;
  for (const auto& term : spec.terms) {
    const auto path = segments(term.path);
    bool covered = false;
    for (const auto& candidate : spec.terms) {
      if (candidate.kind != Term::Subtree) continue;
      if (term.kind == Term::Subtree && candidate.path == term.path) continue;
      const auto root = segments(candidate.path);
      if (path.size() >= root.size() &&
          std::equal(root.begin(), root.end(), path.begin())) {
        covered = true;
        break;
      }
    }
    if (!covered) result.terms.push_back(term);
  }
  return result;
}
void check_reference(const Registry& registry, const SubscriptionSpec& spec,
                     const tiplog::subs::CompiledSubscription& compiled) {
  for (const auto& topic : registry.all_topics()) {
    EXPECT_EQ(compiled.matches(topic.id), reference_match(spec, topic.path)) << topic.path;
  }
  const auto filters = compiled.filters();
  for (std::size_t i = 1; i < filters.size(); ++i) {
    EXPECT_LT(filters[i - 1].partition, filters[i].partition);
  }
}

TEST(V06Registry, AncestorsPartitionsAndDenseLocalIds) {
  Registry registry;
  EXPECT_EQ(registry.intern("itch/AAPL/add/anon"), 4U);
  ASSERT_EQ(registry.topic_count(), 4U);
  ASSERT_EQ(registry.partition_count(), 2U);
  const auto& root = registry.get(1);
  EXPECT_EQ(root.path, "itch");
  EXPECT_EQ(root.parent, 0U);
  EXPECT_EQ(root.depth, 1U);
  EXPECT_EQ(root.partition, 0U);
  EXPECT_EQ(root.local_id, 0U);
  for (TopicId id = 2; id <= 4; ++id) {
    const auto& topic = registry.get(id);
    EXPECT_EQ(topic.parent, id - 1);
    EXPECT_EQ(topic.depth, id);
    EXPECT_EQ(topic.partition, 1U);
    EXPECT_EQ(topic.local_id, id - 2);
  }
  EXPECT_EQ(registry.partition(0).root, 1U);
  EXPECT_EQ(registry.partition(0).topic_count, 1U);
  EXPECT_EQ(registry.partition(1).root, 2U);
  EXPECT_EQ(registry.partition(1).topic_count, 3U);
  EXPECT_EQ(registry.intern("itch/AAPL/add/anon"), 4U);
  EXPECT_EQ(registry.intern("itch/AAPL/add"), 3U);
  EXPECT_EQ(registry.intern("itch/MSFT"), 5U);
  EXPECT_EQ(registry.get(5).partition, 2U);
  EXPECT_EQ(registry.get(5).local_id, 0U);
  EXPECT_EQ(registry.intern("bnc"), 6U);
  EXPECT_EQ(registry.get(6).partition, 3U);
  EXPECT_EQ(registry.intern("bnc/BTC/trade"), 8U);
  EXPECT_EQ(registry.get(8).partition, 4U);
  EXPECT_EQ(registry.get(8).local_id, 1U);
}

TEST(V06Registry, PathValidationAndLookup) {
  Registry registry;
  const std::vector<std::string> invalid{"", "/", "/a", "a/", "a//b", std::string("a\0b", 3)};
  for (const auto& path : invalid) {
    EXPECT_THROW(registry.intern(path), std::invalid_argument);
    EXPECT_EQ(registry.topic_count(), 0U);
    EXPECT_EQ(registry.partition_count(), 0U);
  }
  const auto id = registry.intern("market/A%2FB/Δ");
  EXPECT_EQ(registry.find("market/A%2FB/Δ"), id);
  EXPECT_FALSE(registry.find("missing"));
  EXPECT_THROW((void)registry.get(0), std::out_of_range);
  EXPECT_THROW((void)registry.get(id + 1), std::out_of_range);
  EXPECT_THROW((void)registry.partition(999), std::out_of_range);
}

TEST(V07Subscriptions, DeterministicNormalizationPreservesUnion) {
  Registry registry;
  const SubscriptionSpec spec{{{Term::Exact, "itch/AAPL/add/A"},
                               {Term::Subtree, "itch/AAPL/add"},
                               {Term::Subtree, "itch/AAPL/add"},
                               {Term::Exact, "itch/AAPL/add"},
                               {Term::Subtree, "itch/AAPL/add/A"},
                               {Term::Exact, "itch/AAPLX/add/A"},
                               {Term::Exact, "itch/AAPL/add/A"}}};
  const auto normalized = tiplog::subs::normalize(spec);
  ASSERT_EQ(normalized.terms.size(), 2U);
  EXPECT_EQ(normalized.terms[0], (Term{Term::Subtree, "itch/AAPL/add"}));
  EXPECT_EQ(normalized.terms[1], (Term{Term::Exact, "itch/AAPLX/add/A"}));
  EXPECT_EQ(tiplog::subs::normalize(normalized), normalized);
  for (const auto* path : {"itch/AAPL/add/A", "itch/AAPL/add/F", "itch/AAPL/addition/A",
                           "itch/AAPLX/add/A", "itch/AAPL/exec/E"}) {
    (void)registry.intern(path);
  }
  auto compiled = compile(registry, spec);
  EXPECT_FALSE(compiled.wide());
  check_reference(registry, spec, compiled);
  const auto* filter = compiled.partition_filter(registry.get(*registry.find("itch/AAPL")).partition);
  ASSERT_NE(filter, nullptr);
  EXPECT_FALSE(filter->all);
}

TEST(V07Subscriptions, RandomPathsTermsAndLateTopicsAgainstSegmentMatcher) {
  for (std::uint64_t seed = 0; seed < 128; ++seed) {
    SCOPED_TRACE(seed);
    std::mt19937_64 random(seed);
    std::vector<std::string> paths;
    for (std::size_t i = 0; i < 72; ++i) {
      std::string path = "r" + std::to_string(random() % 3);
      const auto depth = random() % 5;
      for (std::uint64_t d = 0; d < depth; ++d) path += "/s" + std::to_string(random() % 7);
      paths.push_back(std::move(path));
    }
    Registry registry;
    for (std::size_t i = 0; i < 24; ++i) (void)registry.intern(paths[i]);
    std::vector<SubscriptionSpec> specs;
    std::vector<tiplog::subs::CompiledSubscription> compiled;
    for (std::size_t sub = 0; sub < 8; ++sub) {
      SubscriptionSpec spec;
      const auto terms = 1 + random() % 12;
      for (std::uint64_t term = 0; term < terms; ++term) {
        spec.terms.push_back({random() % 2 ? Term::Subtree : Term::Exact,
                              paths[static_cast<std::size_t>(random() % paths.size())]});
      }
      compiled.push_back(compile(registry, spec));
      specs.push_back(std::move(spec));
    }
    for (std::size_t i = 24; i < paths.size(); ++i) {
      (void)registry.intern(paths[i]);
      if (i % 12 == 0 || i + 1 == paths.size()) {
        for (std::size_t j = 0; j < compiled.size(); ++j) {
          check_reference(registry, specs[j], compiled[j]);
        }
      }
    }
  }
}

TEST(V07Subscriptions, NormalizationHandlesLexicalInterleavingAndSamePathKinds) {
  const SubscriptionSpec spec{{{Term::Subtree, "a"},
                               {Term::Subtree, "a-foo"},
                               {Term::Subtree, "a/b"},
                               {Term::Exact, "a/b/child"},
                               {Term::Exact, "a"},
                               {Term::Exact, "a-foo/child"},
                               {Term::Subtree, "a0/b"},
                               {Term::Exact, "a0/b"},
                               {Term::Exact, "a0/bc"}}};
  const auto normalized = tiplog::subs::normalize(spec);
  EXPECT_EQ(normalized, reference_normalize(spec));
  EXPECT_EQ(normalized.terms, (std::vector<Term>{{Term::Subtree, "a"},
                                                {Term::Subtree, "a-foo"},
                                                {Term::Subtree, "a0/b"},
                                                {Term::Exact, "a0/bc"}}));
  Registry registry;
  auto sub = compile(registry, spec);
  for (const auto* path : {"a/b/new", "a-foo/new", "a-foobar/new", "a0/b/new",
                           "a0/bc", "a0/bc/new", "a0/b-extra"})
    (void)registry.intern(path);
  check_reference(registry, spec, sub);
  EXPECT_TRUE(sub.wide());
}

TEST(V07Subscriptions, NormalizationMatchesIndependentAllPairs) {
  constexpr std::array<std::string_view, 7> roots{
      "a", "a-foo", "a0", "b", "market", "market-data", "Δ"};
  for (std::uint64_t seed = 0; seed < 512; ++seed) {
    SCOPED_TRACE(seed);
    std::mt19937_64 random(seed + 20191230);
    SubscriptionSpec spec;
    for (std::size_t i = 0; i < 64; ++i) {
      std::string path(roots[static_cast<std::size_t>(random() % roots.size())]);
      const auto depth = random() % 5;
      for (std::uint64_t d = 0; d < depth; ++d)
        path += "/" + std::string(roots[static_cast<std::size_t>(random() % roots.size())]);
      spec.terms.push_back({random() % 2 ? Term::Exact : Term::Subtree, std::move(path)});
      if (random() % 4 == 0) spec.terms.push_back(spec.terms.back());
    }
    std::shuffle(spec.terms.begin(), spec.terms.end(), random);
    const auto normalized = tiplog::subs::normalize(spec);
    EXPECT_EQ(normalized, reference_normalize(spec));
    EXPECT_EQ(tiplog::subs::normalize(normalized), normalized);
  }
}

TEST(V07Subscriptions, HundredThousandTermsCompileAndObserveWithoutTimingAssumptions) {
  constexpr std::uint32_t count = 100000;
  Registry registry;
  SubscriptionSpec spec;
  spec.terms.reserve(count);
  std::vector<TopicId> first, second;
  first.reserve(count);
  second.reserve(count);
  for (std::uint32_t i = 0; i < count; ++i) {
    const auto root = "x/p" + std::to_string(i);
    first.push_back(registry.intern(root + "/e0"));
    second.push_back(registry.intern(root + "/e1"));
    spec.terms.push_back(i % 2 ? Term{Term::Subtree, root}
                             : Term{Term::Exact, root + "/e0"});
  }
  auto sub = compile(registry, spec);
  ASSERT_EQ(sub.normalized_terms().size(), count);
  ASSERT_EQ(sub.filters().size(), count);
  EXPECT_FALSE(sub.wide());
  EXPECT_EQ(registry.observer_count(), count / 2);
  for (std::uint32_t i = 0; i < count; ++i) {
    ASSERT_TRUE(sub.matches(first[i])) << i;
    ASSERT_EQ(sub.matches(second[i]), i % 2 != 0) << i;
    const auto* filter = sub.partition_filter(registry.get(first[i]).partition);
    ASSERT_NE(filter, nullptr);
    ASSERT_EQ(filter->all, i % 2 != 0) << i;
  }
  EXPECT_FALSE(sub.matches(registry.intern("x/p0/e2")));
  EXPECT_TRUE(sub.matches(registry.intern("x/p1/e2/deep")));
  EXPECT_FALSE(sub.matches(registry.intern("x/p100000/e0")));
  EXPECT_EQ(registry.observer_count(), count / 2);
}

TEST(V07Subscriptions, InvalidSpecsDoNotRegisterEarlierValidTerms) {
  Registry registry;
  EXPECT_THROW((void)compile(registry, {}), std::invalid_argument);
  EXPECT_THROW((void)compile(registry, {{{Term::Exact, "valid/path"}, {Term::Subtree, "bad//path"}}}),
               std::invalid_argument);
  EXPECT_THROW((void)compile(registry, {{{Term::Exact, "valid"}, {Term::Exact, std::string("a\0b", 3)}}}),
               std::invalid_argument);
  EXPECT_THROW((void)compile(registry, {{{static_cast<Term::Kind>(7), "valid"}}}),
               std::invalid_argument);
  EXPECT_EQ(registry.topic_count(), 0U);
}

TEST(V08Subscriptions, FutureSubtreesRespectSegmentBoundaries) {
  Registry registry;
  auto sub = compile(registry, {{{Term::Subtree, "itch/AAPL/add"}}});
  const auto root = *registry.find("itch/AAPL/add");
  EXPECT_TRUE(sub.matches(root));
  EXPECT_TRUE(sub.matches(registry.intern("itch/AAPL/add/A")));
  EXPECT_TRUE(sub.matches(registry.intern("itch/AAPL/add/F/deep")));
  EXPECT_FALSE(sub.matches(registry.intern("itch/AAPL/additional/A")));
  EXPECT_FALSE(sub.matches(registry.intern("itch/AAPLX/add/A")));
  EXPECT_EQ(registry.observer_count(), 1U);
}

TEST(V08Subscriptions, WideTermsIncludeFuturePartitionsAndShallowExactStaysNarrow) {
  Registry registry;
  auto wide = compile(registry, {{{Term::Subtree, "itch"}}});
  auto shallow = compile(registry, {{{Term::Exact, "itch"}}});
  EXPECT_TRUE(wide.wide());
  EXPECT_FALSE(shallow.wide());
  const auto symbol = registry.intern("itch/NEW/add/A");
  EXPECT_TRUE(wide.matches(symbol));
  EXPECT_FALSE(shallow.matches(symbol));
  EXPECT_TRUE(shallow.matches(*registry.find("itch")));
  ASSERT_NE(wide.partition_filter(registry.get(symbol).partition), nullptr);
  EXPECT_TRUE(wide.partition_filter(registry.get(symbol).partition)->all);
  EXPECT_FALSE(wide.matches(registry.intern("bnc/NEW/trade")));
  auto partition = compile(registry, {{{Term::Subtree, "itch/NEW"}}});
  EXPECT_FALSE(partition.wide());
  ASSERT_EQ(partition.filters().size(), 1U);
  EXPECT_TRUE(partition.filters()[0].all);
}

TEST(V08Subscriptions, ExactPreinternedAndNoHookNeeded) {
  Registry registry;
  auto exact = compile(registry, {{{Term::Exact, "itch/AAPL/add/A"}}});
  ASSERT_TRUE(registry.find("itch/AAPL/add/A"));
  EXPECT_TRUE(exact.matches(*registry.find("itch/AAPL/add/A")));
  EXPECT_FALSE(exact.matches(registry.intern("itch/AAPL/add/F")));
  EXPECT_EQ(registry.observer_count(), 0U);
}

TEST(V08Subscriptions, CopyMoveAndDestructionReleaseHooks) {
  Registry registry;
  {
    auto original = compile(registry, {{{Term::Subtree, "itch/AAPL/add"},
                                        {Term::Subtree, "itch/MSFT/exec"}}});
    EXPECT_EQ(registry.observer_count(), 2U);
    auto copy = original;
    auto moved = std::move(original);
    EXPECT_FALSE(original.matches(1));
    const auto id = registry.intern("itch/MSFT/exec/E");
    EXPECT_TRUE(copy.matches(id));
    EXPECT_TRUE(moved.matches(id));
    EXPECT_TRUE(copy.belongs_to(registry));
    Registry other;
    EXPECT_FALSE(copy.belongs_to(other));
    copy = {};
    EXPECT_EQ(registry.observer_count(), 2U);
  }
  EXPECT_EQ(registry.observer_count(), 0U);
  // Repeated creation/destruction cannot accumulate weak slots at quiet roots.
  for (int i = 0; i < 100; ++i) {
    auto transient = compile(registry, {{{Term::Subtree, "itch/AAPL/add"}}});
    EXPECT_EQ(registry.observer_count(), 1U);
  }
  EXPECT_EQ(registry.observer_count(), 0U);
  (void)registry.intern("itch/AAPL/add/F");
}

TEST(V08Subscriptions, RegistryLifetimeSafeEvenWithExternallyRetainedAnchor) {
  tiplog::subs::CompiledSubscription sub;
  std::shared_ptr<const Registry::Lifetime> retained;
  TopicId topic = 0;
  {
    Registry registry;
    sub = compile(registry, {{{Term::Subtree, "a/b"}}});
    topic = registry.intern("a/b/c");
    retained = registry.identity().lock();
    ASSERT_TRUE(retained);
    EXPECT_TRUE(retained->alive());
    EXPECT_TRUE(sub.matches(topic));
  }
  EXPECT_FALSE(retained->alive());
  EXPECT_FALSE(sub.matches(topic));
  sub = {};  // Handles also tolerate the registry already being destroyed.
}

TEST(V38Registry, TopicLimitPreflightsEntireAncestorChain) {
  Registry registry(Limits{3, 10, 65536});
  const auto root = registry.intern("r");
  const auto before = registry.get(root);
  EXPECT_THROW(registry.intern("r/s/a/b"), RepresentationLimit);
  EXPECT_EQ(registry.topic_count(), 1U);
  EXPECT_EQ(registry.partition_count(), 1U);
  EXPECT_EQ(registry.get(root), before);
  EXPECT_FALSE(registry.find("r/s"));
  EXPECT_EQ(registry.intern("r/s/a"), 3U);
}

TEST(V38Registry, PartitionLimitAndReservedOwnerSentinel) {
  Registry registry(Limits{100, 1, 65536});
  (void)registry.intern("r");
  EXPECT_THROW(registry.intern("r/s/a"), RepresentationLimit);
  EXPECT_EQ(registry.topic_count(), 1U);
  EXPECT_EQ(registry.partition_count(), 1U);
  EXPECT_FALSE(registry.find("r/s"));
  EXPECT_THROW((void)Registry(Limits{100, std::uint64_t{1} << 32, 65536}), std::invalid_argument);
  EXPECT_THROW((void)Registry(Limits{std::uint64_t{1} << 32, 100, 65536}), std::invalid_argument);
  EXPECT_THROW((void)Registry(Limits{100, 100, 65537}), std::invalid_argument);
}

TEST(V38Registry, LocalLimitRejectsMissingAncestorsAndLeavesCompiledBitsUnchanged) {
  Registry registry(Limits{100, 100, 3});
  auto sub = compile(registry, {{{Term::Subtree, "r/s/a"}}});
  const auto selected = *registry.find("r/s/a");
  const auto filters_before = sub.filters()[0].bits;
  EXPECT_THROW(registry.intern("r/s/b/c"), RepresentationLimit);
  EXPECT_EQ(registry.topic_count(), 3U);
  EXPECT_EQ(registry.partition_count(), 2U);
  EXPECT_FALSE(registry.find("r/s/b"));
  EXPECT_EQ(sub.filters()[0].bits, filters_before);
  EXPECT_TRUE(sub.matches(selected));
  EXPECT_TRUE(sub.matches(registry.intern("r/s/a/leaf")));
  EXPECT_THROW(registry.intern("r/s/a/extra"), RepresentationLimit);
  EXPECT_EQ(registry.partition(1).topic_count, 3U);
}

TEST(V38Registry, FullUint16BoundaryAndLateBitsetGrowth) {
  Registry registry;
  auto sub = compile(registry, {{{Term::Subtree, "r/s/selected"}}});
  for (std::uint32_t i = 0; i < 65533; ++i) {
    (void)registry.intern("r/s/unselected" + std::to_string(i));
  }
  const auto last = registry.intern("r/s/selected/last");
  EXPECT_EQ(registry.get(last).local_id, std::numeric_limits<std::uint16_t>::max());
  EXPECT_EQ(registry.partition(1).topic_count, 65536U);
  EXPECT_TRUE(sub.matches(last));
  const auto* filter = sub.partition_filter(1);
  ASSERT_NE(filter, nullptr);
  ASSERT_EQ(filter->bits.size(), 1024U);
  EXPECT_EQ(filter->bits.back(), std::uint64_t{1} << 63);
  const auto before = registry.topic_count();
  EXPECT_THROW(registry.intern("r/s/new/child"), RepresentationLimit);
  EXPECT_EQ(registry.topic_count(), before);
  EXPECT_FALSE(registry.find("r/s/new"));
}

TEST(V38Registry, ZeroCapacityRejectsWithoutMutation) {
  Registry no_topics(Limits{0, 10, 10});
  EXPECT_THROW(no_topics.intern("r/s"), RepresentationLimit);
  EXPECT_EQ(no_topics.topic_count(), 0U);
  Registry no_partitions(Limits{10, 0, 10});
  EXPECT_THROW(no_partitions.intern("r/s"), RepresentationLimit);
  EXPECT_EQ(no_partitions.topic_count(), 0U);
  Registry no_local(Limits{10, 10, 0});
  EXPECT_THROW(no_local.intern("r/s"), RepresentationLimit);
  EXPECT_EQ(no_local.topic_count(), 0U);
}

class ThrowingObserver final : public tiplog::topics::TopicObserver {
 public:
  std::size_t prepared{};
  std::unique_ptr<Update> prepare(std::span<const tiplog::topics::Topic>) override {
    ++prepared;
    throw std::bad_alloc();
  }
};
TEST(V08Subscriptions, ObserverAllocationFailurePrecedesAllRegistrationCommit) {
  Registry registry;
  auto sub = compile(registry, {{{Term::Subtree, "r/s/selected"}}});
  auto throwing = std::make_shared<ThrowingObserver>();
  auto handle = registry.observe(*registry.find("r"), throwing);
  const auto count = registry.topic_count();
  const auto original_bits = sub.filters()[0].bits;
  EXPECT_THROW(registry.intern("r/s/selected/new/deeper"), std::bad_alloc);
  EXPECT_EQ(throwing->prepared, 1U);
  EXPECT_EQ(registry.topic_count(), count);
  EXPECT_EQ(registry.partition(1).topic_count, 2U);
  EXPECT_FALSE(registry.find("r/s/selected/new"));
  EXPECT_EQ(sub.filters()[0].bits, original_bits);
  handle.reset();
  EXPECT_TRUE(sub.matches(registry.intern("r/s/selected/new/deeper")));
}

TEST(V38Registry, TopicPathBoundsRejectBeforeMutationAndAcceptExactBounds) {
  Registry registry;
  const auto sub = compile(registry, {{{Term::Subtree, "r/s"}}});
  const auto original = std::vector<tiplog::topics::Topic>(registry.all_topics().begin(), registry.all_topics().end());
  std::string deep = "r";
  for (std::size_t i = 1; i < tiplog::max_topic_depth; ++i) deep += "/s";
  EXPECT_NO_THROW(Registry::validate_path(deep));
  EXPECT_THROW(registry.intern(deep + "/extra"), RepresentationLimit);
  EXPECT_THROW(registry.intern(std::string(tiplog::max_topic_path_bytes + 1, 'x')), RepresentationLimit);
  // Every term is validated before compile interns even a valid earlier term.
  EXPECT_THROW((void)compile(registry, {{{Term::Exact, "a/new"}, {Term::Exact, deep + "/extra"}}}), RepresentationLimit);
  EXPECT_EQ(std::vector<tiplog::topics::Topic>(registry.all_topics().begin(), registry.all_topics().end()), original);
  EXPECT_EQ(registry.partition_count(), 2U);
  EXPECT_EQ(registry.observer_count(), 1U);
  EXPECT_EQ(sub.filters().size(), 1U);
  const auto deepest = registry.intern(deep);
  EXPECT_EQ(registry.get(deepest).depth, tiplog::max_topic_depth);
  EXPECT_EQ(registry.get(registry.intern(std::string(tiplog::max_topic_path_bytes, 'x'))).path.size(), tiplog::max_topic_path_bytes);
  check_reference(registry, {{{Term::Subtree, "r/s"}}}, sub);
}

class RecordingObserver final : public tiplog::topics::TopicObserver {
 public:
  std::size_t preparations{}, commits{}, pending_count{};
  std::function<void()> callback;
  std::function<void()> commit_callback;
  struct Prepared final : Update {
    RecordingObserver& observer;
    explicit Prepared(RecordingObserver& source) : observer(source) {}
    void commit() noexcept override {
      ++observer.commits;
      if (observer.commit_callback) observer.commit_callback();
    }
  };
  std::unique_ptr<Update> prepare(std::span<const tiplog::topics::Topic> pending) override {
    ++preparations;
    pending_count = pending.size();
    if (callback) callback();
    return std::make_unique<Prepared>(*this);
  }
};

TEST(V08Subscriptions, FanoutNotifiesEachObserverOnceAcrossOverlappingRoots) {
  Registry registry;
  const auto root = registry.intern("r");
  const auto child = registry.intern("r/s");
  std::vector<std::shared_ptr<RecordingObserver>> observers;
  std::vector<tiplog::topics::ObserverHandle> handles;
  for (std::size_t i = 0; i < 8000; ++i) {
    auto observer = std::make_shared<RecordingObserver>();
    handles.push_back(registry.observe(root, observer));
    handles.push_back(registry.observe(child, observer));
    observers.push_back(std::move(observer));
  }
  (void)registry.intern("r/s/a/b/c");
  for (const auto& observer : observers) {
    EXPECT_EQ(observer->preparations, 1U);
    EXPECT_EQ(observer->commits, 1U);
    EXPECT_EQ(observer->pending_count, 3U);
  }
}

TEST(V08Subscriptions, ObserverReentrantMutationRejectsWithConsistentCommitAndRollback) {
  for (const bool propagate : {false, true}) {
    Registry registry;
    const auto root = registry.intern("r/s");
    const auto sub = compile(registry, {{{Term::Subtree, "r/s"}}});
    auto observer = std::make_shared<RecordingObserver>();
    auto handle = registry.observe(root, observer);
    const auto before_topics = registry.topic_count();
    const auto before_partitions = registry.partition_count();
    const auto before_local = registry.partition(1).topic_count;
    observer->callback = [&] {
      if (propagate) { (void)registry.intern("r/s/inner"); return; }
      EXPECT_THROW(registry.intern("r/s/inner"), std::logic_error);
      EXPECT_THROW(registry.intern("r"), std::logic_error);
      EXPECT_THROW(registry.observe(root, observer), std::logic_error);
    };
    if (propagate) {
      EXPECT_THROW(registry.intern("r/s/outer/deep"), std::logic_error);
      EXPECT_EQ(registry.topic_count(), before_topics);
      EXPECT_EQ(registry.partition_count(), before_partitions);
      EXPECT_EQ(registry.partition(1).topic_count, before_local);
      EXPECT_EQ(observer->commits, 0U);
      EXPECT_FALSE(registry.find("r/s/outer"));
    } else {
      EXPECT_TRUE(sub.matches(registry.intern("r/s/outer/deep")));
      EXPECT_EQ(observer->commits, 1U);
    }
    EXPECT_FALSE(registry.find("r/s/inner"));
    observer->callback = {};
    EXPECT_TRUE(sub.matches(registry.intern("r/s/after")));
    std::set<TopicId> ids;
    std::set<std::pair<PartitionId, std::uint16_t>> locals;
    for (const auto& topic : registry.all_topics()) {
      EXPECT_EQ(registry.find(topic.path), topic.id);
      EXPECT_EQ(registry.get(topic.id), topic);
      EXPECT_TRUE(ids.insert(topic.id).second);
      EXPECT_TRUE(locals.emplace(topic.partition, topic.local_id).second);
    }
    for (const auto& partition : registry.all_partitions()) {
      EXPECT_EQ(partition.topic_count, static_cast<std::uint32_t>(std::count_if(
          registry.all_topics().begin(), registry.all_topics().end(),
          [&](const auto& topic) { return topic.partition == partition.id; })));
    }
    check_reference(registry, {{{Term::Subtree, "r/s"}}}, sub);
  }
}

TEST(V08Subscriptions, ObserverCommitMayReadAndUnregisterButCannotReenterMutation) {
  Registry registry;
  const auto root = registry.intern("r/s");
  auto observer = std::make_shared<RecordingObserver>();
  auto handle = registry.observe(root, observer);
  observer->commit_callback = [&] {
    const auto outer = registry.find("r/s/outer");
    ASSERT_TRUE(outer);
    EXPECT_EQ(registry.get(*outer).path, "r/s/outer");
    EXPECT_THROW(registry.intern("r/s/inner"), std::logic_error);
    EXPECT_THROW(registry.observe(root, observer), std::logic_error);
    handle.reset();
  };
  EXPECT_EQ(registry.get(registry.intern("r/s/outer")).path, "r/s/outer");
  EXPECT_FALSE(registry.find("r/s/inner"));
  EXPECT_EQ(registry.observer_count(), 0U);
  (void)registry.intern("r/s/after");
  EXPECT_EQ(observer->commits, 1U);
}
}  // namespace
