---
name: spec_driven_dev
description: Universal project-agnostic Spec-Driven Engineering Workflow (Recon -> Spec Freeze -> Task DAG -> Polyglot Build & Verify -> Visual/Gate Review) enforced by Baize V46 hard-gate.
version: 1.0.0
tags:
  - workflow
  - spec-driven
  - architecture
  - polyglot
  - quality-gate
---

# Universal Spec-Driven Engineering Workflow (`spec_driven_dev`)

Use this skill for **any** software engineering project (Python, TypeScript/React, Go, Rust, Java, Flutter/Dart, C/C++, CLI tools, APIs, test frameworks, or consumer web/mobile apps).

## Phase 1: Reconnaissance (`explore` — Read-Only Locked)
1. Inspect the auto-injected **Project Fingerprint** (detected languages, package manager, test/build/lint commands).
2. Use read-only tools (`list_dir`, `find_files`, `grep_search`, `read_file`, `lsp_definition`, `lsp_references`, `lsp_hover`, `blast_radius`) to map existing modules, conventions, and entry points.
3. Identify any ambiguous product, data-model, or UX decisions before writing a single line of code.

## Phase 2: Specification Freeze (`spec_draft` -> `approved`)
1. Draft a concise, actionable specification covering:
   - **Goal & Non-Goals** (clear scope boundary)
   - **Architecture & File Plan** (exact modules to create/modify)
   - **Interfaces & Data Models** (APIs, schemas, CLI commands, UI states)
   - **Verification Plan** (unit/integration tests, polyglot build/lint gate, and UI visual checks if frontend)
2. Present the spec to the user and wait for explicit approval (`baize spec approve`, `/spec approve`, or Studio Spec Gate Approve).
3. **Hard-Gate Rule**: While Spec Mode is enabled in `explore` or `spec_draft`, all mutating tools (`write_file`, `patch_file`, `bash`, `git`, `run_python`, `lsp_rename`) are mechanically blocked by `SpecWorkflowManager`.

## Phase 3: Task Decomposition & Execution (`executing`)
1. Once approved, execute changes in small, atomic, verifiable increments.
2. Rely on immediate post-edit polyglot diagnostics (`write_file`/`patch_file` auto-diagnose) and `lsp_*` semantic tools to keep types and imports green at every step.
3. For independent parallel workstreams, isolate edits in Git worktrees (`baize worktree`).

## Phase 4: Polyglot Gate & Visual Self-Healing (`verified`)
1. Run the project's native test, typecheck, and lint commands (or `run_polyglot_gate`).
2. For web/frontend apps, start the dev server and run `verify_ui(url, viewports="desktop,mobile", check_visual=True)` to verify zero console errors, zero broken images, zero horizontal overflow, and clean responsive visual layout.
3. Mark the spec `verified` only after real command output confirms passing tests and gates (NO FAKE DONE).
