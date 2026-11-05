---
name: run-workflow
description: Execute a staged Syntra workflow with checkpoints and verified results.
---

# Run Workflow

Break a requested workflow into explicit stages and execute them sequentially with the tools actually available in Syntra. Keep a concise checkpoint record in the selected workspace for long workflows, including completed stages, exact outputs, failures and next steps. Inspect actual results before proceeding, stop on a blocking failure, and do not label skipped work successful. Use complete_task only once the requested stages are verified. This Syntra adaptation uses the local agent loop; it does not expose another product’s parallel-agent Python primitives or impersonate those tools.
