# Project Instructions

> REPLACE: Customize this file for your project. Delete sections that don't apply. Every line costs tokens. Code style lives in `.claude/rules/code-quality.md`, don't duplicate here. Run `/setupdotclaude` to auto-customize, or edit manually and delete all `> REPLACE:` blocks when done. Target: under 25 non-blank lines after customization. Hard cap: 50.

## Commands

```bash
# Build
npm run build            # or: cargo build, go build ./..., make build

# Test
npm test                 # run full suite
npm test -- path/to/file # run single test file

# Lint & Format
npm run lint             # check style
npm run lint:fix         # auto-fix style
npm run typecheck        # type checking

# Dev
npm run dev              # start dev server
```

## Architecture

> REPLACE: Describe non-obvious architectural decisions and boundaries — e.g. "controllers never touch the DB directly, go through services"; "billing is a separate module for audit independence". Don't list files or directories; Claude can explore those.

## Key Decisions

> REPLACE: Record WHY non-obvious choices were made. This is the most valuable section. Examples: "Auth tokens in httpOnly cookies because XSS risk", "Billing is a separate module for audit independence".

## Domain Knowledge

> REPLACE: Terms, abbreviations, or concepts that aren't obvious from the code. Example: "SKU" = Stock Keeping Unit, the unique product identifier from our warehouse system.

## Imports (optional)

> REPLACE or delete: pull files into context instead of restating them — `@README.md` for the overview, `@package.json` for scripts, `@CLAUDE.local.md` for your gitignored personal notes. Each `@path` inlines that file when this CLAUDE.md loads.

## Don'ts

> REPLACE: Project-specific traps only. Generated files, secrets, and lock files are already blocked by the safety hooks — don't restate hook-enforced rules here.
