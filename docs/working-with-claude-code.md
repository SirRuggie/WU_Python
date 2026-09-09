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
and a short system prompt. The builder's prompt says "implement exactly the
spec, nothing more" and names the repo editing rules; the refuter's says
"re-run the verification yourself, report only correctness findings". Copy
the five files into another repo and edit the description lines; that is the
whole install.

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

1. Copy `.claude/rules/orchestration.md` and `.claude/agents/` into the new
   repo. Adjust the model column if the pricing changes.
2. Write the new repo's `docs/editing-this-repo.md`: the editing rules plus
   whatever verification command the project has (test suite, linters).
3. Add a one-line CLAUDE.md or rule that says "Ultracode off; delegate per
   the orchestration rule".
4. Keep a handoff doc per piece of work with a prioritised checklist; every
   session reads it first.

## Related

- docs/agent-orchestration.md (reasoning, pricing sources, mechanics)
- docs/editing-this-repo.md (editing rules and the verification greps)
- docs/handoff-ticket-console-review.md (an example handoff in use)
