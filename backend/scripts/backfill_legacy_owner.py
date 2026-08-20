"""One-off backfill: assign existing ownerless documents to a single legacy
user, so the multi-tenant ownership model (documents.owner_id) has no NULL
values left before it becomes NOT NULL.

Deliberately NOT an Alembic migration - this is a data decision (who owns
these pre-existing documents), not a schema change, and must be reviewed and
run explicitly by a human rather than applied silently as part of
`alembic upgrade`.

Idempotent: running it again after a successful backfill reports zero
unowned documents and makes no changes.

Usage (from backend/):
    .venv/Scripts/python.exe -m scripts.backfill_legacy_owner --dry-run
    .venv/Scripts/python.exe -m scripts.backfill_legacy_owner
"""
from __future__ import annotations

import argparse

from app.database import SessionLocal
from app.models import Document, User

LEGACY_EXTERNAL_AUTH_ID = "legacy-import"


def run(dry_run: bool) -> None:
    db = SessionLocal()
    try:
        total_documents = db.query(Document).count()
        unowned = db.query(Document).filter(Document.owner_id.is_(None)).count()
        owned = total_documents - unowned

        print(f"Documents total:            {total_documents}")
        print(f"Already owned:              {owned}")
        print(f"Unowned (owner_id IS NULL): {unowned}")

        legacy_user = (
            db.query(User).filter(User.external_auth_id == LEGACY_EXTERNAL_AUTH_ID).first()
        )
        if legacy_user is None:
            print(
                f"Legacy user does not exist yet - would create one "
                f"(external_auth_id={LEGACY_EXTERNAL_AUTH_ID!r})."
            )
        else:
            print(f"Legacy user already exists: id={legacy_user.id}, email={legacy_user.email!r}")

        if unowned == 0:
            print("Nothing to backfill.")
            return

        if dry_run:
            print(f"[DRY RUN] Would assign {unowned} document(s) to the legacy user. No changes made.")
            return

        if legacy_user is None:
            legacy_user = User(external_auth_id=LEGACY_EXTERNAL_AUTH_ID, email=None)
            db.add(legacy_user)
            db.flush()  # assigns legacy_user.id without committing yet
            print(f"Created legacy user: id={legacy_user.id}")

        updated = (
            db.query(Document)
            .filter(Document.owner_id.is_(None))
            .update({Document.owner_id: legacy_user.id}, synchronize_session=False)
        )
        db.commit()

        remaining = db.query(Document).filter(Document.owner_id.is_(None)).count()
        print(f"Backfilled {updated} document(s) to legacy user id={legacy_user.id}.")
        print(f"Remaining unowned documents: {remaining}")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Report what would change without writing anything."
    )
    args = parser.parse_args()
    run(dry_run=args.dry_run)
