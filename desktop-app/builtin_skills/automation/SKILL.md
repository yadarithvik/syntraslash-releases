---
name: automation
description: Schedule and inspect one-shot local Syntra tasks with explicit time zones.
---

# Automation

Use schedule_task with a self-contained prompt, name and ISO-8601 run_at containing a UTC offset, such as +05:30. The current selected workspace is used. Resolve missing date/time details before creating the task. Use list_scheduled_tasks to verify the stored schedule and report its ID. Use cancel_scheduled_task only for a requested pending task. Syntra must be open when the task is due; missed pending tasks run when the app next opens. A claimed or interrupted task is not silently retried. This is a one-shot local scheduler, not a cloud recurring-job service. Do not create unsupported sidecar or cron configuration files.
