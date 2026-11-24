# 010. Record the decisions shown at the meeting

## Context

The confirmed draft must be fresh before the meeting is recorded. Later waiting changes belong in a future meeting.

## Decision

Prepare saves the shown waiting changes in `meeting_changes` in the existing meeting content file. Page and PDF use the same meeting view. Confirmation and a client copy before recording compare the complete live waiting list to the saved list. When recording, check that each shown decision is still waiting with the same facts. Use the saved order. After recording, the client copy uses the saved list and still checks the rendered page, project setup and saved finished-work evidence. Only draft fields enter the page fingerprint.

## Consequences

A new waiting change logged after confirmation leaves the saved answers usable and stays pending for the next meeting. For a client copy before recording, the owner still needs a fresh page covering the complete waiting list. A shown change that was edited, removed or decided prevents recording. The first meeting prepared by an earlier build must be prepared again to pick up Save and the decision snapshot. This extends ADR 001 for recording and copying a recorded meeting.
