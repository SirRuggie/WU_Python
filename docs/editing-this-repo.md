# Standing rule: no in-place byte-level edits

**Never use `sed -i`, `awk`, or `perl -pi` to edit files in this repo. Use the
editing tools.**

Three incidents, all silent at the moment of damage.

## Why — the two failure modes

### 1. Removing the only statement leaves an empty block

Twice, a line-based delete removed the sole body of an `if`/`for`, leaving a
header with nothing under it. Python raises `SyntaxError` at **import**, so the
extension fails to load and — depending on what else lives in the module — takes
unrelated features down with it.

The documented instance: stripping `[todo-diag]` lines from `utils/todo_data.py`
removed three `_d(...)` calls that were the entire body of
`if key.startswith("cwl:"):` blocks. See
[todo-dashboard.md](todo-dashboard.md), which notes it "would have taken the
whole bot down on boot."

A line-oriented tool cannot see that a line is load-bearing structure. It
matches text.

### 2. An encoding round-trip corrupts every non-ASCII character

A `perl -0pi` edit on `extensions/commands/fwa/lazy_cwl.py` read raw bytes and
wrote through a UTF-8 encoding layer. Every multi-byte character was reinterpreted
as Latin-1 and re-encoded, **double-encoding 97 lines** of emoji and `•`
separators to mojibake in a single command.

This file is dense with user-facing emoji, so the damage was total and would have
shipped garbled text throughout the LazyCWL commands. It was caught only because
a later edit failed to match on a string containing `⏱️`.

## The two verification greps

Run both after any bulk change, and always before committing.

**Encoding** — must return 0:

```bash
grep -c 'Ã\|â' path/to/file.py
```

`Ã` and `â` are the leading bytes of double-encoded UTF-8. `â€` is the common
tail. Zero hits means clean; any hits mean re-encode or revert.

**Structure** — must print nothing:

```bash
awk '
/^[[:space:]]*(if|elif|else|for|while|try|except|finally|with|def|class|async def).*:[[:space:]]*$/ { hdr=NR; hi=match($0,/[^ ]/); p=1; next }
p { if ($0 ~ /^[[:space:]]*$/) next; i=match($0,/[^ ]/); if (i <= hi) print FILENAME" SUSPECT "hdr" -> "NR; p=0 }
' path/to/file.py
```

It flags any block header whose next non-blank line is not more indented — i.e.
an empty block. Add a bracket-balance check alongside it when a change was large:

```bash
f=path/to/file.py
echo "parens $(grep -o '(' $f|wc -l)/$(grep -o ')' $f|wc -l) brackets $(grep -o '\[' $f|wc -l)/$(grep -o '\]' $f|wc -l)"
```

None of these prove the file parses. They catch the two failure modes that have
actually occurred; they are a floor, not a guarantee.

## Whether a real syntax check is available

**Check the machine first. Only `LAPTOP-NFGO6M7M` has Python. Assume every other
machine does not.**

```bash
echo "$COMPUTERNAME"      # PowerShell: $env:COMPUTERNAME
```

**On `LAPTOP-NFGO6M7M`** Python is installed and on `PATH` as `py`. Prefer real
verification over the greps above, because it actually proves the file parses:

```bash
py -m compileall -q extensions utils main.py
```

```bash
py -m pytest -q
```

The suite is 503 tests and finishes in about 35 seconds. Dependencies are
installed globally; there is no venv. Two cautions specific to this box:

- Do **not** run a blanket `pip install -r requirements.txt`. It would downgrade
  the installed hikari and lightbulb to the pinned `2.3.5` / `3.0.3`. See
  [hikari-lightbulb-versions.md](hikari-lightbulb-versions.md).
- `Pillow` must be **12 or newer**. `utils/card_scan.py` handles older Pillow
  correctly, but `tests/test_card_board.py` and `tests/test_card_scan.py` use
  `Image.get_flattened_data` directly, so Pillow 11 fails those two files for
  environment reasons rather than product ones. Pillow is unpinned, so a fresh
  install can land on 11.
- Never run `main.py` here while production is up. It opens a second gateway
  session on the same `DISCORD_TOKEN` and every command answers twice.

**On any other machine**, assume there is no Python. The greps above are then
the only pre-commit check, and a real syntax check happens on the box at deploy.

## Recovery

`git checkout -- <file>` and redo the work with the editing tools. That is what
was done after the encoding incident, and it cost one rebuild of about a dozen
edits — far less than shipping the corruption.

**Do not attempt to reverse a double-encode in place** if any subsequent edit
has already written correct UTF-8 into the file. The file is then mixed-encoding
and a blanket re-encode corrupts the good parts. Revert instead.
