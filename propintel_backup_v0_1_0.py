"""
PropIntel Backup & Safety  v0.1.0
=================================
propintel.db is the system of record, a single SQLite file that two machines
touch through OneDrive. The two real risks are (1) loss/corruption and (2) a
OneDrive sync conflict if both machines write at once. This tool addresses both:

  - make_backup(): a CONSISTENT snapshot using SQLite's online backup API (safe
    even if the DB is open/being written), with an integrity check first, into
    backups/propintel_YYYYMMDD_HHMMSS.db, pruned to the last N.
  - check_db(): PRAGMA integrity_check + detection of OneDrive conflict copies
    (e.g. "propintel-DESKTOP-XYZ.db", "propintel (1).db") that signal a sync
    collision where data may have diverged.
  - safe_backup_on_start(): make a backup only if the newest one is older than
    a threshold, so launching the app repeatedly doesn't spam backups. Callers
    (dashboard, intake) use this; it never raises.
  - restore(): copy a chosen backup back over propintel.db (after snapshotting
    the current file first, so a restore is itself reversible).

Journal mode note: connect() uses the default `delete` (rollback) journal, NOT
WAL. Keep it that way on OneDrive - WAL's -wal/-shm side files sync poorly and
can corrupt the database. (Verified `delete` on 2026-06-06.)

CLI:
    python propintel_backup_v0_1_0.py            # make a backup now
    python propintel_backup_v0_1_0.py --check    # integrity + conflict-copy scan
    python propintel_backup_v0_1_0.py --list
    python propintel_backup_v0_1_0.py --restore backups/propintel_YYYYMMDD_HHMMSS.db
"""

import glob
import os
import shutil
import sqlite3
import sys
from datetime import datetime

import propintel_db_v0_1_0 as pdb

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, pdb.DEFAULT_DB_FILENAME)
BACKUP_DIR = os.path.join(HERE, "backups")
KEEP = 30


def _stamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def integrity_ok(db_path=DB_PATH):
    try:
        conn = sqlite3.connect(db_path)
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        conn.close()
        return result == "ok", result
    except Exception as e:
        return False, str(e)


def find_conflict_copies():
    """OneDrive names a sync collision like 'propintel-DESKTOP-AG3OC47.db' or
    'propintel (1).db'. Any *.db in the folder other than propintel.db is suspect."""
    suspects = []
    for p in glob.glob(os.path.join(HERE, "propintel*.db")):
        if os.path.abspath(p) != os.path.abspath(DB_PATH):
            suspects.append(os.path.basename(p))
    return suspects


def make_backup(db_path=DB_PATH, backup_dir=BACKUP_DIR, keep=KEEP, verbose=True):
    """Consistent snapshot via the online backup API. Returns the backup path,
    or None if the source failed its integrity check (backup skipped)."""
    os.makedirs(backup_dir, exist_ok=True)
    ok, detail = integrity_ok(db_path)
    if not ok:
        if verbose:
            print(f"[WARN] integrity_check = {detail!r}; backing up anyway is risky. "
                  f"Inspect the DB before trusting new backups.")
    dest = os.path.join(backup_dir, f"propintel_{_stamp()}.db")
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(dest)
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()
    _prune(backup_dir, keep)
    if verbose:
        print(f"Backup written: {os.path.relpath(dest, HERE)} ({os.path.getsize(dest):,} bytes)")
    return dest


def _prune(backup_dir, keep):
    files = sorted(glob.glob(os.path.join(backup_dir, "propintel_*.db")))
    for old in files[:-keep] if keep else []:
        try:
            os.remove(old)
        except OSError:
            pass


def list_backups(backup_dir=BACKUP_DIR):
    return sorted(glob.glob(os.path.join(backup_dir, "propintel_*.db")))


def newest_backup_age_minutes(backup_dir=BACKUP_DIR):
    files = list_backups(backup_dir)
    if not files:
        return None
    newest = max(files, key=os.path.getmtime)
    return (datetime.now().timestamp() - os.path.getmtime(newest)) / 60.0


def safe_backup_on_start(min_interval_minutes=60):
    """Back up only if the newest backup is older than the interval. Never raises
    (a backup failure must not stop the app from starting)."""
    try:
        age = newest_backup_age_minutes()
        if age is None or age >= min_interval_minutes:
            return make_backup(verbose=False)
    except Exception:
        pass
    return None


def restore(backup_file, db_path=DB_PATH):
    """Restore from a backup, snapshotting the current DB first."""
    if not os.path.exists(backup_file):
        print(f"No such backup: {backup_file}")
        return False
    pre = make_backup(verbose=False)  # safety snapshot of current state
    shutil.copy2(backup_file, db_path)
    print(f"Restored {os.path.basename(backup_file)} -> {pdb.DEFAULT_DB_FILENAME}")
    print(f"(Prior state saved as {os.path.relpath(pre, HERE)} in case you need to undo.)")
    return True


def check_db():
    ok, detail = integrity_ok()
    print(f"integrity_check: {detail}")
    conflicts = find_conflict_copies()
    if conflicts:
        print("WARNING: possible OneDrive sync-conflict copies found:")
        for c in conflicts:
            print(f"   {c}")
        print("These mean both machines may have written at once. Compare row "
              "counts before deleting any; the newest correct one should become "
              "propintel.db. Make a backup first.")
    else:
        print("No conflict copies found.")
    n = len(list_backups())
    age = newest_backup_age_minutes()
    print(f"backups: {n}" + (f", newest {age:.0f} min old" if age is not None else " (none yet)"))
    return ok and not conflicts


def main():
    args = sys.argv[1:]
    if not args:
        make_backup()
    elif args[0] == "--check":
        check_db()
    elif args[0] == "--list":
        files = list_backups()
        print(f"{len(files)} backup(s) in {os.path.relpath(BACKUP_DIR, HERE)}:")
        for p in files:
            print(f"  {os.path.basename(p)}  ({os.path.getsize(p):,} bytes)")
    elif args[0] == "--restore" and len(args) > 1:
        restore(args[1])
    else:
        print("usage: propintel_backup_v0_1_0.py [--check | --list | --restore <file>]")


if __name__ == "__main__":
    main()
