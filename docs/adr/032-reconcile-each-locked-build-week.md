# 032. Reconcile each locked build week

## Context

The latest locked delivery date can match the total days even when two earlier weeks have offsetting errors. A missed week can appear at the end of the record. Older missed weeks can carry the unchanged date in `end_before` alone.

## Decision

Require a locked build week as evidence for the final agreed delivery date. Start at the first planned end and check each locked build week's opening date, recorded answers and closing date in week-number order. Each approved Change must have its matching approval and days in the recorded decision week. A missed build week adds zero days and can use its opening date if there is no saved closing date. Docs weeks still have to be locked.

## Consequences

The handoff names the week or change when the records disagree. A project with no locked build week needs a build record before the handoff can check its planned date history. The owner supplies the real end independently of that history.
