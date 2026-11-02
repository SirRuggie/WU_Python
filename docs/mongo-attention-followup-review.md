# Confirmed storage recovery and cursor context follow-up

Claude344 requested a small follow-up after accepting the Mongo lifecycle work.
A generic successful auth/me response no longer clears storage attention. The
backend checks the real owner again after awaiting visit recording, then returns
an explicit healthy header. The browser accepts that header only if no newer
storage error arrived since the request started. Unconfirmed recovery events do
not clear the notice. No extra polling, sign-out, write retry or copy redesign.

BudgetedCursor now supports async context management. Enter and exit receive
individual Mongo budgets; the caller's external waits do not hold a deadline.
with_options retains the native client and operation budget. Store-level schema
mismatch and actual renew-loop cases verify one CRITICAL record, a live renewal
task, preserved local data and no downgrade to automatic recovery wording. The
obsolete todo-diag documentation is corrected. Only the changed auth function
and added tests are formatted; no whole-file legacy formatting rewrite.

Validation: 117 affected backend/auth/visitor/access/bridge cases; six owned
native cursor cases including an external wait exceeding the Mongo budget;
1,432 frontend tests, TypeScript/build; five genuine mutants; read-only actual
App layouts at360/1440, session retained, no page errors/overflow. Narrow degraded
and wide recovered screenshots were reviewed. The initial mutation harness
looked for an unformatted string and stopped before mutation; the corrected
harness killed all five and restored source. Vite's chunk advisory remains.
Owned Mongo was stopped and removed. No production storage outage was induced,
and no live role, message, import or nickname action was performed.
