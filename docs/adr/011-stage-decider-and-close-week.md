# 011. Stage the decider on waiting changes

## Context

The owner supplies the decider when recording. The Changes sheet already has that field, and the recorded answers in Weeks hold change IDs, answers and days.

## Decision

Record writes the decider in `Changes.decided_by` while the change is waiting. Re-recording replaces the decider on answered changes and clears it on answers removed from this week. Lock rechecks each answered change against its original days, then writes the final status and decision week alongside the locked week.

For a lock updating both sheets, save the two previous file contents to a temporary undo record before publishing. The transaction is committed when the undo record is removed. On a write error, or before the next command after an interruption, restore both original files.

## Consequences

The Weeks and Changes sheet columns stay as approved. CLI commands on POSIX use the project lock from ADR 002 and recover before taking action. The files live at separate paths. A reader that bypasses the CLI can see the two replacements in progress. Run commands one at a time on Windows.
