"""Persistent high-score table for the timed 6-7 round.

One tiny JSON file, kept OUTSIDE the repo (`SIXSEVEN_SCORES_FILE`, default
`~/hall-scores.json`). The Jetson updates itself with `git reset --hard`
(see `deploy/hall-app/hall-update.sh`), so anything stored in the working
tree is deleted the next time somebody pushes to `main`; the scoreboard is
the one piece of exhibit state that has to outlive both an update and a
reboot.

Nothing here can take the exhibit down. A missing file, a corrupt file, a
read-only home directory: each degrades to "the board is empty" or "the
board is in memory only" and the game keeps running. An unattended kiosk
crashing because a JSON file lost a brace would be a much worse bug than
losing five numbers.

There are no player names — the exhibit is touchless and has no keyboard,
so an entry is a score and the moment it was set.
"""

import json
import os
import tempfile
import time


class Scoreboard:
    """Top-`size` scores, newest submission last on a tie.

    Ties rank the EARLIER entry higher: matching somebody's record does not
    take their row, you have to beat it. That is the usual arcade rule and
    it keeps a busy afternoon from churning the table.
    """

    def __init__(self, path, size):
        self.path = path
        self.size = size
        self.entries = []          # [{"score": int, "t": float epoch}], ranked
        self._writable = True      # flips off after one failed write
        self._load()

    # --- disk ----------------------------------------------------------

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, ValueError):
            # Missing (first run) or unreadable/corrupt — start empty.
            return
        entries = []
        for item in (raw.get("scores") if isinstance(raw, dict) else raw) or []:
            try:
                score = int(item["score"])
                stamp = float(item.get("t", 0.0))
            except (TypeError, ValueError, KeyError, IndexError):
                continue       # skip the bad row, keep the good ones
            if score > 0:
                entries.append({"score": score, "t": stamp})
        self.entries = self._ranked(entries)

    def _save(self):
        """Atomic replace, so a kill mid-write cannot leave a half file.

        The kiosk is power-cycled by whoever closes the hall, and a partial
        write is exactly how a JSON file ends up corrupt.
        """
        if not self._writable:
            return
        try:
            directory = os.path.dirname(self.path) or "."
            os.makedirs(directory, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=directory, prefix=".scores-")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump({"scores": self.entries}, fh)
                os.replace(tmp, self.path)
            except BaseException:
                # Never leave the temp file behind on a failed write.
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except OSError as exc:
            self._writable = False
            print(f"scoreboard: cannot write {self.path} ({exc}) — "
                  "records are in memory only for this session", flush=True)

    # --- table ---------------------------------------------------------

    def _ranked(self, entries):
        return sorted(entries, key=lambda e: (-e["score"], e["t"]))[:self.size]

    def submit(self, score, now=None):
        """Record a finished round; return its 0-based rank, or None.

        `None` means the score did not make the table — the caller shows the
        board without a "you" marker rather than a rank nobody reached.
        """
        if score <= 0:
            return None
        entry = {"score": int(score),
                 "t": float(time.time() if now is None else now)}
        self.entries = self._ranked(self.entries + [entry])
        try:
            rank = self.entries.index(entry)
        except ValueError:
            return None            # bumped straight off the bottom
        self._save()
        return rank

    def to_state(self):
        """Just the scores, ranked — the frontend renders the row numbers."""
        return [e["score"] for e in self.entries]
