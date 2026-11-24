# 014. Keep carry-over in the confirmed meeting content

## Context

Promise results and corrections can change or grow while meetings are being prepared. The page and PDF need one record of what the owner confirmed.

## Decision

Keep the results, missed dates and correction rows in the existing numbered content snapshot. Omit empty new fields so an earlier saved page and PDF still match. Before the first confirmation, compare promise results and corrections with what is currently due and ask for a fresh page if they differ. After confirmation, use the saved rows. If the same week is prepared again, mark its original correction selection as fixed in the new snapshot.

Select correction rows that have not appeared in an earlier held meeting's confirmed snapshot. Identify entries by their original correction IDs. A confirmed draft that is retired after a missed meeting leaves its corrections available for the next meeting.

After a restore, a missing historical snapshot provides no evidence that those corrections were shown. Keep corrections pending unless a surviving confirmed snapshot identifies them. The next confirmation records the selected corrections in its own snapshot.

## Consequences

Corrections logged after confirmation stay for a later meeting. Reading the historical page and making the PDF use the same saved facts. The existing sheet columns are sufficient.
