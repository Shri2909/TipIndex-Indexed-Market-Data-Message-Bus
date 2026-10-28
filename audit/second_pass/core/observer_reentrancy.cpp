#include "tiplog/topics/registry.hpp"
#include <iostream>
#include <memory>

using namespace tiplog;

struct ReentrantObserver final : topics::TopicObserver {
  topics::Registry& registry;
  bool reentered{};
  struct Noop final : Update { void commit() noexcept override {} };
  explicit ReentrantObserver(topics::Registry& r) : registry(r) {}
  std::unique_ptr<Update> prepare(std::span<const topics::Topic>) override {
    if (!reentered) {
      reentered = true;
      registry.intern("r/s/inner");
    }
    return std::make_unique<Noop>();
  }
};
int main() {
  topics::Registry registry;
  const auto root = registry.intern("r/s");
  auto observer = std::make_shared<ReentrantObserver>(registry);
  auto handle = registry.observe(root, observer);
  const auto returned = registry.intern("r/s/outer");
  const auto found = *registry.find("r/s/outer");
  std::cout << "outer_returned=" << returned << " outer_find=" << found
            << " outer_get_path=" << registry.get(found).path
            << " topic_count=" << registry.topic_count() << '\n';
  for (const auto& topic : registry.all_topics()) {
    std::cout << "id=" << topic.id << " local_id=" << topic.local_id
              << " path=" << topic.path << '\n';
  }
}
