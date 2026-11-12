# CLAUDE.md — Claude Code project instructions

Follow [AGENTS.md](AGENTS.md) as the authoritative coding-agent contract. Read `IMPLEMENTATION_PLAN.md`, `TASKS.md`, and `SECURITY.md` before edits. If the docs are moved into `docs/`, use their corresponding `docs/` paths.

This is a **dedicated Kaseya analytics/reporting portal**, unrelated to the Managed Services Hub and the existing asset-management application. Vendor integrations remain read-only in v1. Do not implement an MCP server or AI features as an initial dependency.

When coding: use a short plan, finish the next testable vertical slice, run checks, and update task/status docs. Keep every customer-owned record, queryset, export, background job, and audit event correctly scoped. Never claim live API testing on fixtures.

For initial work, execute task `P0-01` from `TASKS.md`, then move sequentially through P0 and P1. Use `IMPLEMENTATION_PLAN.md` for milestones and review gates.
