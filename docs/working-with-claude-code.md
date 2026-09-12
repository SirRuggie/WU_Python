# Working with Claude Code in this repo

A one-page summary of how this repository keeps Claude Code cheap, safe, and
useful. Written 2026-09-09 so the setup can be copied to other projects and
explained to other people. The full versions live in the files named below.

## 1. Never use Ultracode for this kind of work

Ultracode (the "ultracode" keyword or the session toggle) tells Claude to run a
multi-agent Workflow on every substantive task with cost treated as no object.
On this repo one review under Ultracode spawned 227 agents and hit the session
limit. Keep it off. Ask for agents by name instead ("spin up a scout to find
X"). If you ever want a fan-out, say "use a workflow" explicitly and cap it in
the same sentence ("at most 10 agents").

## 2. The orchestration rule (`.claude/rules/orchestration.md`)

The main session is the most expensive model. It plans, writes specs,
delegates, reads compact reports, and integrates. It does not read bulk code,
build, refactor, review, or write docs itself when a cheaper agent can.

The general protocol behind this — the agent roster, how to write a brief,
task buckets, verification, reporting — is now defined once, per machine, in
`~/.claude/CLAUDE.md` as part of the
[orchestration kit](https://github.com/SirRuggie/claude-code-orchestration-kit).
This repo's rule only carries what is repo-specific: the cost table below
and the repo editing rules. See `docs/agent-orchestration.md` for the kit's
install steps and its task-bucket layout.

| Work | Agent | Model | Cost vs Sonnet |
|---|---|---|---|
| Find files, symbols, call sites | `scout` | Haiku | 0.5x |
| Read docs or source, report facts with citations | `researcher` | Sonnet | 1x |
| Implement from an explicit spec, with tests | `builder` | Sonnet | 1x |
| Refute a diff, a plan, or a "done" claim | `refuter` | Opus | 2.5x |
| Root-cause a subtle failure | `debugger` | Opus | 2.5x |
| Architecture, judgment, integration | main session | Fable | 5x |

Every builder diff and every "tests pass" claim goes to a refuter before it is
trusted. One-line fixes and single greps stay in the main session because
spawning costs more than the fix.

## 3. The delegation contract

Every agent prompt states: the goal; the exact files or URLs in scope; the
output format with a length cap; what to verify before reporting; what not to
do (no unrelated refactors, no new files unless named, no commits, no
`pip install`). Say what is already known so the agent does not rediscover it.
Ask for a compact report, never a raw dump. Agents that produce a lot write to
a scratch file and the next agent reads the file; the content never passes
through the main session.

## 4. Agent definitions (`.claude/agents/*.md`)

Five small files, one per agent, each with `name`, `description`, `model`,
`effort`, `tools`, `color` and a system prompt with an output contract. Each
is the kit's agent text verbatim plus a trailing "Repo rules" section
carrying this repo's constraints (editing rules, hikari conventions, the
pytest command). Two frontmatter deltas from the kit: scout and researcher
also get `Bash`, limited by their repo-rules section to read-only commands. Project agents override the global ones in
`~/.claude/agents/` by name, so the repo copy must stay a superset of the
kit copy. To use the workflow in another repo, install the kit core to
`~/.claude/` once per machine and copy only the kit agents, not these repo
copies; see section 7.

## 5. Editing rules (`docs/editing-this-repo.md`)

No `sed -i`, `awk -i`, or `perl -pi` on source files (they have corrupted
UTF-8 and left empty blocks before); use the editor tools or a scripted
whole-file rewrite. Run the two verification greps on every touched Python
file. Never add `Co-Authored-By` or any AI attribution to commits. Durable
knowledge goes in `docs/`, one file per subject; scratch stays out of the
repo.

## 6. Session habits that keep tokens down

- Tell Claude at the start: "token-saving mode, orchestrate, do not build
  yourself." It reads the rule anyway, but saying it removes doubt.
- Stop a run you did not ask for. Interrupting is cheaper than letting it
  finish.
- Keep replies short and ask for short replies. Long explanations cost on both
  sides.
- Batch related fixes into one builder so the big files are read once, and
  run batches serially when they touch the same files.
- Let refuters run in a detached git worktree while the builder keeps editing;
  read-only checks parallelise, edits do not.
- Record decisions in a handoff doc as they are made, so a context reset or a
  new session starts from the file, not from memory.

## 7. Copying this to another project

1. Install the kit core once per machine (not per repo): `~/.claude/CLAUDE.md`,
   `~/.claude/agents/*.md`, and the `/task-session`, `/brief`, `/task-status`,
   `/task-close` commands — see `docs/agent-orchestration.md` for the exact
   copy commands.
2. Copy `.claude/rules/orchestration.md` and `.claude/agents/` into the new
   repo. Each project agent file is the kit's agent text plus a trailing
   repo-rules section, because a project agent overrides its global
   counterpart by name and must be a superset, not a replacement. Adjust the
   cost table if pricing changes.
3. Write the new repo's `docs/editing-this-repo.md`: the editing rules plus
   whatever verification command the project has (test suite, linters).
4. Add the kit's `.gitignore` snippet (`.claude/scratch/`) so task buckets
   never get tracked, and the settings additions noted in
   `docs/agent-orchestration.md` (spawn depth, briefs read-only, push/reset/
   clean under ask).
5. Add a one-line CLAUDE.md or rule that says "Ultracode off; delegate per
   the orchestration rule".
6. Keep a handoff doc per piece of work with a prioritised checklist; every
   session reads it first.

## Related

- docs/agent-orchestration.md (reasoning, pricing sources, mechanics)
- docs/editing-this-repo.md (editing rules and the verification greps)
- docs/handoff-ticket-console-review.md (an example handoff in use)
