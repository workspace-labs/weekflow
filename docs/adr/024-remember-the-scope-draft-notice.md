# 024. Remember when the Draft notice was shown

## Context

A PRD can go back to Draft during build mode. The owner needs one notice, and the build-mode setup and confirmed meeting files must stay usable.

## Decision

Save a local notice receipt under `docs/weekly/pages/` alongside the next successfully prepared build meeting. Clear it when a later preparation no longer finds a Draft stamp. Keep the receipt outside the Project and Weeks sheets and outside the meeting fingerprint.

## Consequences

Repeated commands in the observed Draft period keep the saved delivery date and show the notice once. A failed preparation can be retried before the notice is recorded.
