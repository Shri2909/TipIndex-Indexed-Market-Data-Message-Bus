#include "tiplog/trace/itch_walker.hpp"

#include <array>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>

int main(int argc, char** argv) {
  try {
    std::string input_path = "-";
    std::string output_path;
    bool have_input = false;
    for (int i = 1; i < argc; ++i) {
      const std::string arg = argv[i];
      if (arg == "--out" && i + 1 < argc) output_path = argv[++i];
      else if (!have_input && (arg == "-" || !arg.starts_with('-'))) {
        input_path = arg;
        have_input = true;
      } else throw std::runtime_error("usage: tiplog_walk [FILE|-] [--out JSON]");
    }
    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);
    std::ifstream input_file;
    std::istream* input = &std::cin;
    if (input_path != "-") {
      input_file.open(input_path, std::ios::binary);
      if (!input_file) throw std::runtime_error("cannot open input file");
      input = &input_file;
    }
    auto walker = std::make_unique<tiplog::trace::ItchWalker>();
    std::array<std::byte, 1024 * 1024> buffer{};
    while (*input) {
      input->read(reinterpret_cast<char*>(buffer.data()), static_cast<std::streamsize>(buffer.size()));
      walker->feed(std::span<const std::byte>(buffer).first(static_cast<std::size_t>(input->gcount())));
    }
    if (input->bad() || (!input->eof() && input->fail())) throw std::runtime_error("input read failed");
    walker->finish();
    if (output_path.empty()) walker->write_json(std::cout);
    else {
      std::ofstream output(output_path);
      if (!output) throw std::runtime_error("cannot open output file");
      walker->write_json(output);
      output.close();
      if (!output) throw std::runtime_error("output write failed");
    }
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "tiplog_walk: " << error.what() << '\n';
    return 2;
  }
}
