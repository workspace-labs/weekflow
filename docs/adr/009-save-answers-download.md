# 009. Download selections from the confirmed page

## Context

The offline page previews decisions with native controls. The owner needs to pass those selections to the agent after the meeting.

## Decision

Show Save answers when the one hash-allowed inline script can run. It reads checked radio buttons and downloads a local blob. The file contains only the meeting number (`week`), the draft fingerprint (`fingerprint`) and the selected answers keyed by change ID (`answers`).

The command reads at most 64 KiB and accepts unique keys and known answers. A bare `--answer` records an empty selection in the manual route.

## Consequences

Tabs and decisions still work with scripts off. The owner can relay the answers in that case. The downloaded file gives the command choices, while saved project changes supply the days.
