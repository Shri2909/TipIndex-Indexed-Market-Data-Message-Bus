#include "tiplog/subs/compiled.hpp"
#include <chrono>
#include <iostream>
#include <vector>
int main(){
 for(const std::size_t count:{2000,8000}){
  tiplog::topics::Registry registry;
  std::vector<tiplog::subs::CompiledSubscription> keep;
  for(std::size_t i=0;i<count;++i)keep.push_back(tiplog::subs::compile(registry,{{{tiplog::Term::Subtree,"s/X"}}}));
  const auto start=std::chrono::steady_clock::now();
  for(int i=0;i<20;++i)(void)registry.intern("s/X/new"+std::to_string(i));
  const auto ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count()/20;
  std::cout<<"{\"subscriptions\":"<<count<<",\"mean_ms_per_intern\":"<<ms<<"}\n";
 }
}
