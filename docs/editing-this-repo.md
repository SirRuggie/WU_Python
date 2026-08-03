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

None of these prove the file parses. **There is no Python on the development
machine**, so a real syntax check happens on the box at deploy. These greps
catch the two failure modes that have actually occurred; they are a floor, not
a guarantee.

## Recovery

`git checkout -- <file>` and redo the work with the editing tools. That is what
was done after the encoding incident, and it cost one rebuild of about a dozen
edits — far less than shipping the corruption.

**Do not attempt to reverse a double-encode in place** if any subsequent edit
has already written correct UTF-8 into the file. The file is then mixed-encoding
and a blanket re-encode corrupts the good parts. Revert instead.
