"""Reset the new (thread) ticket system's numbering and test data.

One-off tool for the numbering fix described in docs/ticket-console.md: the
new thread ticket system now allocates its own numbers starting at 1 and no
longer reads or writes anything the legacy channel system owns. Run this
once, right before go-live, to wipe out whatever smoke-test tickets were
created during the pilot so the first real thread ticket is numbered 1.

Run it on the box (anywhere with the repo's .env and Mongo access):

    venv/bin/python tools/reset_thread_ticket_test_data.py            # dry run, prints counts
    venv/bin/python tools/reset_thread_ticket_test_data.py --confirm  # deletes for real

It touches ONLY new-system (thread) data:

  * `tickets` documents with `venue: "thread"`
  * `ticket_creation_state` documents whose `_id` starts with `thread:`
  * `ticket_open_slots` documents with `route: "thread"`
  * `ticket_automation_state` documents whose `kind` starts with `ticket_`
    (for example `ticket_staff_context`) -- the legacy system's own
    automation-state rows are keyed by a bare channel id and carry no such
    `kind`, so they never match
  * the `ticket_rollout` counter document (`ticket_runtime_counters`):
    `main_ticket_counter` and `fwa_ticket_counter` are reset to 0

It deliberately does NOT touch `button_store`, `ticket_setup`, the
`ticket_rollout` rollout document (`ticket-runtime`), or any `venue:
"channel"` row -- those are legacy-owned or shared rollout state, never
smoke-test data.

`ticket_flags` (staff-authored applicant blacklist/history flags) is
intentionally left alone: those documents are keyed by applicant identity
(Discord ID / player tag), not by ticket id, and persist deliberately across
tickets, so there is no field that identifies "flags created by a thread
smoke-test ticket" to delete.

Exit status is 2 when MONGODB_URI is not set.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402
from pymongo import MongoClient  # noqa: E402

from extensions.commands import ticket_runtime  # noqa: E402

THREAD_VENUE_QUERY = {"venue": "thread"}
THREAD_CREATION_STATE_QUERY = {"_id": {"$regex": "^thread:"}}
THREAD_OPEN_SLOT_QUERY = {"route": ticket_runtime.ROUTE_THREAD}
THREAD_AUTOMATION_STATE_QUERY = {"kind": {"$regex": "^ticket_"}}

COUNTER_FIELDS = ("main_ticket_counter", "fwa_ticket_counter")


def _count_and_report(db, collection_name: str, query: dict) -> int:
    count = db[collection_name].count_documents(query)
    print(f"  {collection_name}: {count} document(s) match {query}")
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="actually delete and reset; default is a dry run",
    )
    args = parser.parse_args(argv)

    load_dotenv()
    uri = os.getenv("MONGODB_URI", "")
    if not uri:
        print("MONGODB_URI is not set")
        return 2

    db = MongoClient(uri)["settings"]  # the database utils/mongo.py uses

    if args.confirm:
        print("DELETING new-system thread ticket test data\n")
    else:
        print("DRY RUN: nothing will be deleted or reset\n")

    print("Collections:")
    tickets_count = _count_and_report(db, "tickets", THREAD_VENUE_QUERY)
    creation_count = _count_and_report(
        db, "ticket_creation_state", THREAD_CREATION_STATE_QUERY
    )
    slots_count = _count_and_report(
        db, "ticket_open_slots", THREAD_OPEN_SLOT_QUERY
    )
    automation_count = _count_and_report(
        db, "ticket_automation_state", THREAD_AUTOMATION_STATE_QUERY
    )

    counter_doc = db.ticket_rollout.find_one(
        {"_id": ticket_runtime.COUNTER_DOCUMENT_ID}
    ) or {}
    print("\nCounter document (ticket_rollout / ticket_runtime_counters):")
    for field in COUNTER_FIELDS:
        print(f"  {field}: {counter_doc.get(field, 0)} -> 0")

    # Migration rows are never deleted here (their unique source index is the
    # migration idempotency guard), but their destination numbers still raise
    # the thread floor, so a reset would not give the next ticket number 1.
    migration_rows = list(
        db.ticket_migrations.find(
            {"destination.ticket_number": {"$exists": True}},
            {"destination.ticket_number": 1},
        )
    )
    migration_max = max(
        (int((row.get("destination") or {}).get("ticket_number") or 0)
         for row in migration_rows),
        default=0,
    )
    print(
        f"  ticket_migrations: {len(migration_rows)} document(s) hold a "
        f"destination ticket number (max {migration_max}); never deleted here"
    )

    if not args.confirm:
        print(
            "\nDry run only. Re-run with --confirm to delete these documents "
            "and reset the counters."
        )
        return 0

    if migration_rows:
        print(
            "\nRefusing: ticket_migrations already holds destination ticket "
            "numbers, so numbering cannot restart at 1. Nothing was changed."
        )
        return 3

    db.tickets.delete_many(THREAD_VENUE_QUERY)
    db.ticket_creation_state.delete_many(THREAD_CREATION_STATE_QUERY)
    db.ticket_open_slots.delete_many(THREAD_OPEN_SLOT_QUERY)
    db.ticket_automation_state.delete_many(THREAD_AUTOMATION_STATE_QUERY)
    db.ticket_rollout.update_one(
        {"_id": ticket_runtime.COUNTER_DOCUMENT_ID},
        {"$set": {field: 0 for field in COUNTER_FIELDS}},
        upsert=True,
    )

    print(
        f"\nDeleted: tickets={tickets_count} "
        f"ticket_creation_state={creation_count} "
        f"ticket_open_slots={slots_count} "
        f"ticket_automation_state={automation_count}"
    )
    print("Reset main_ticket_counter and fwa_ticket_counter to 0.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
