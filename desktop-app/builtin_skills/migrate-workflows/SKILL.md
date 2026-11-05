---
name: migrate-workflows
description: Convert legacy workspace Markdown workflows into Syntra SKILL.md bundles.
---

# Migrate Workflows

Inspect the selected workspace’s .agent/workflows or .agents/workflows folders. Read each relevant Markdown workflow, identify its task and write .agents/skills/<name>/SKILL.md with name and description frontmatter. Preserve scripts/resources and repair relative paths within the workspace. Do not overwrite an existing different skill or delete the original workflow. Make migration idempotent: skip matching generated skills and report conflicts. Validate the new files, then use manage_extensions discover/import/enable only for the migrated skills the user requested. Never claim a migrated instruction supplies unavailable tools.
