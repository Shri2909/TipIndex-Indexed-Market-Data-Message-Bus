#include "tiplog/index/index.hpp"
#include <chrono>
#include <cstdint>
#include <iostream>
#include <variant>
using namespace tiplog;
int main() {
 index::Index pool({32,1024,0});
 auto append=[&](PartitionId p,LogPos pos,std::uint64_t live) {
  auto plan=pool.prepare_append(p,pos,0,2);
  pool.commit(std::move(std::get<index::PreparedAppend>(plan)),live);
 };
 for(unsigned i=0;i<1023;++i)append(0,16ULL*i,i+1);
 for(unsigned i=0;i<4000;++i)append(1,16ULL*(i+1023),i+1024);
 append(0,16ULL*5023,5024);
 for(const bool partial:{false,true}) {
  std::uint64_t total=0;
  auto start=std::chrono::steady_clock::now();
  for(std::uint64_t i=0;i<1000000;++i)
   total+=pool.estimate_count(0,partial?16ULL*1023:0,16ULL*5024);
  const auto elapsed=std::chrono::duration<double,std::nano>(std::chrono::steady_clock::now()-start).count()/1e6;
  std::cout << "{\"partial_boundary\":" << partial << ",\"mean_ns_per_call\":" << elapsed << ",\"sum\":" << total << "}\n";
 }
}
