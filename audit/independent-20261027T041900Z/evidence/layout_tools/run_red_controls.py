#!/usr/bin/env python3
"""Run current regression assertions against binaries built from the frozen source."""
import json,runpy,sys,unittest
from pathlib import Path
binary=Path(sys.argv[1]).resolve(); output=Path(sys.argv[2]); log=Path(sys.argv[3])
sys.argv=["tool_contracts.py",str(binary)]
namespace=runpy.run_path("tests/layout/tool_contracts.py",run_name="tool_contracts_import")
selected=["test_output_aliases_preserve_all_source_inputs",
          "test_microbenchmark_outputs_preserve_inputs_and_remain_distinct",
          "test_request_read_errors_fail_before_output_creation",
          "test_microbenchmark_verification_rejects_ignored_and_malformed_arguments",
          "test_request_id_named_id_is_not_mistaken_for_a_header",
          "test_m3_filtering_precedes_input_preparation"]
suite=unittest.TestSuite(namespace["ToolContracts"](name) for name in selected)
with log.open('w') as stream: result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
output.write_text(json.dumps(dict(binary_directory=str(binary),selected=selected,tests=result.testsRun,
 failures=[str(test) for test,_ in result.failures],errors=[str(test) for test,_ in result.errors],
 expected_all_failures=len(result.failures)==len(selected) and not result.errors),indent=2)+'\n')
if len(result.failures)!=len(selected) or result.errors: raise SystemExit('unexpected red-control result')
