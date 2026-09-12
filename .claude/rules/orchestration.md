# Orchestrate; delegate the work

Standing rule for the MAIN session in this repo, which runs on the most
expensive tier (Fable, 5x Sonnet's price). If you are running as a subagent
defined in `.claude/agents/`, your own definition governs you: do the task
you were given and ignore the delegation mandate below.

## The rule

The general protocol — roster, briefs, task buckets, verification, and
reporting — is defined once in `~/.claude/CLAUDE.md`. If that file is
missing on this machine, install the kit core from
https://github.com/SirRuggie/claude-code-orchestration-kit before
delegating anything; `docs/agent-orchestration.md` has the install steps.

## Who does what

| Work | Agent (`.claude/agents/`) | Model | Cost vs Sonnet |
|---|---|---|---|
| Find files, symbols, call sites; sweep the tree | `scout` | haiku | 0.5x |
| Read docs or sources; report facts with citations | `researcher` | sonnet | 1x |
| Write modules, tests, docs from an explicit spec; fixed-pattern refactors | `builder` | sonnet | 1x |
| Refute a plan, review a diff, verify a "done" claim | `refuter` | opus | 2.5x |
| Root-cause a subtle failure; propose the minimal fix | `debugger` | opus | 2.5x |
| Architecture and migration decisions, final integration, judgment calls, anything the tiers above failed at | main session | fable | 5x |

Reasoning, pricing sources and the mechanics: `docs/agent-orchestration.md`.

## Repo rules every agent inherits

No `sed -i`, `awk` or `perl -pi` (docs/editing-this-repo.md); verify touched
Python with the two greps there. Never add Co-Authored-By or Claude-Session
trailers to commits. Durable knowledge goes in `docs/`, one file per subject.

## Do not delegate

A one-line fix, a single fact in a file already open, a yes/no `grep`, or a
commit. Spawning has a fixed cost; it only pays when the work outweighs it.
