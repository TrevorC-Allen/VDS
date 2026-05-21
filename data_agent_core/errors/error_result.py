"""Standard error result draft for all Data Agent modules.

TODO:
- Define a stable error result contract with error_type, error_message,
  failed_step, recoverable, and suggested_fix.
- Ensure all failures flow into the errors field of API and core responses.
- Keep this structure readable by Benchmark, Verifier, and Correction Loop.

Draft structure:
- ErrorResult: error_type, error_message, failed_step, recoverable,
  suggested_fix
"""
