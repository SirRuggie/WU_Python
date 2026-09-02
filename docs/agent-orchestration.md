# Agent orchestration: who does what, on which model, and why

The standing rule that every session loads is
[`.claude/rules/orchestration.md`](../.claude/rules/orchestration.md); the
agents it names live in [`.claude/agents/`](../.claude/agents). This file is
the reasoning behind both, with the pricing and the Claude Code mechanics
they depend on. Checked against the live pricing and Claude Code docs on
2026-09-02.

## Why

The main session runs on Fable 5.1, the most expensive tier. Everything it
reads, every file it opens and every tool result it gets back is billed at
that rate, and it stays in context for the rest of the session. A subagent
gets a fresh, isolated context, does the work at a cheaper rate, and hands
back only a short report. The main session's job is therefore to plan,
write precise delegations, run agents in parallel, have a second agent
check the first, and integrate. Research, reading, building, refactoring,
reviewing and documentation are delegated whenever a cheaper tier can do
them.

## The models

| Model | ID | Input / output per MTok | Context | Cost vs Sonnet | Positioning in the docs |
|---|---|---|---|---|---|
| Haiku 4.5 | `claude-haiku-4-5` | $1 / $5 | 200K | 0.5x | fastest, near-frontier; manual thinking only |
| Sonnet 5 | `claude-sonnet-5` | $2 / $10 | 1M | 1x | best combination of speed and intelligence; this price is now permanent |
| Opus 5 | `claude-opus-5` | $5 / $25 | 1M | 2.5x | complex agentic coding; the docs' recommended default for most workloads |
| Fable 5.1 | `claude-fable-5-1` | $10 / $50 | 1M | 5x | demanding reasoning and long-horizon agentic work; reach for it when Opus 5 at higher effort still falls short; thinking cannot be disabled; cache hits are the cheapest of any model |

Sources: the `claude-api` reference skill, and the models overview and
pricing pages at `platform.claude.com/docs/en/about-claude/` (reached via
the `docs.claude.com` redirect).

## Task to model

| Task | Agent | Model | Why |
|---|---|---|---|
| Codebase search, file-location sweeps | `scout` | Haiku 4.5 | mechanical retrieval at the lowest rate; volume matters more than depth |
| Reading docs or library source, summarising with citations | `researcher` | Sonnet 5 | technical reading needs judgment; Haiku is fine for plain summaries |
| New modules and tests from an explicit spec | `builder` | Sonnet 5 | production coding quality at 1x; a fully specified task needs no frontier reasoning |
| Refactors across many files following a fixed pattern | `builder` | Sonnet 5 | per-file correctness judgment at volume; Haiku only for near-mechanical replacements |
| User-facing documentation | `builder` | Sonnet 5 | writing quality, not reasoning-bound |
| Adversarial review of a plan or diff; verifying a "done" claim | `refuter` | Opus 5 | needs deeper reasoning than Sonnet without Fable's 5x premium; the docs themselves recommend a fresh-context adversarial review step |
| Debugging a subtle failure | `debugger` | Opus 5 | escalate to Fable only when Opus at high effort stalls, which is the documented escalation path |
| Architecture and migration planning | main session | Fable 5.1 | verbatim Fable's documented use case, and a bad architecture call costs more than the premium |
| Final integration, judgment calls, cleanup after cheaper tiers failed | main session | Fable 5.1 | by definition above the tiers below |

Not worth delegating: a one-line fix, a fact in a file already open, a
yes/no `grep`, a commit. Spawning has a fixed cost (write the prompt, wait,
read the report) that only pays when the work outweighs it.

## The delegation contract

Every prompt to an agent contains: the goal; the exact files, paths or
URLs in scope; the output format and a length cap; what to verify before
reporting; what not to do. It also states what is already known, so the
agent does not spend its budget rediscovering it. Independent agents run in
parallel, in the background. A builder's diff, a "tests pass" claim or a
migration plan goes to `refuter` before it is trusted, and a debugging
result goes to `builder` to apply, so no agent both makes and grades its
own claim.

## Claude Code mechanics this relies on

All from `code.claude.com/docs/en/` (memory, sub-agents, best-practices,
settings, hooks), verified 2026-09-02.

- **Memory files.** `./CLAUDE.md` or `./.claude/CLAUDE.md` is project
  memory; `./CLAUDE.local.md` is personal and meant to be gitignored;
  `~/.claude/CLAUDE.md` is per user. A gitignored file still loads locally,
  which is why the owner's root `CLAUDE.md` works on the PC and is absent
  in a fresh remote clone.
- **Rules.** `.claude/rules/*.md` files without `paths:` frontmatter load
  automatically in every session at the same priority as project memory;
  with `paths: [globs]` they load only when a matching file is read. This
  is the committed, always-loaded home for the standing rule.
- **Gitignore gotcha.** This repo's `.gitignore` has a bare `CLAUDE.md`
  line, which matches at every depth, so `.claude/CLAUDE.md` would be
  ignored too. `.claude/rules/` and `.claude/agents/` are not matched. If
  a committed `.claude/CLAUDE.md` is ever wanted, anchor the ignore line
  as `/CLAUDE.md`.
- **Subagents.** Project agents are `.claude/agents/<name>.md` with
  frontmatter `name`, `description` (what Claude matches a task against;
  "use proactively" encourages automatic use), optional `tools`,
  `disallowedTools`, `model` (`haiku`, `sonnet`, `opus`, `fable`, a full
  ID, or `inherit`), `permissionMode`, `maxTurns`, `effort`, `skills`,
  `memory`, `background`, `isolation: worktree`. Non-fork subagents get a
  fresh context: their definition, the task, and the CLAUDE.md hierarchy,
  not the parent conversation. They can run in the background and can
  spawn subagents (`CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` limits it). The
  Agent tool's `model` parameter overrides per call.
- **Forcing and preventing.** `@agent-<name>` forces an agent; `agent` in
  settings makes one the session's main agent; `permissions.deny:
  ["Agent(<name>)"]` blocks one.
- **No hook can mandate delegation.** `SubagentStart`/`SubagentStop` fire
  around subagents and `SessionStart` can inject a message, but nothing
  gates whether the main session chooses to delegate. The rule is
  therefore advisory text, re-read after `/compact` like all memory.
- **Best-practice guidance** the docs give directly: use subagents for
  investigation so the main conversation stays clean; add an adversarial
  review step in a fresh context; use a writer/reviewer pair for larger
  changes.

## Maintaining this

Prices and model IDs change. When they do, update the table here and the
cost column in the rule, in the same commit. When a new kind of recurring
work appears, add an agent definition rather than widening an existing
one; each agent's description is what routes work to it.
