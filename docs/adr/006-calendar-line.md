# 006. Start the week line at scope approval

## Context

The progress step needs a week line, and the records supply approval, delivery and meeting dates.

## Decision

Place week boundaries every seven calendar days from the approval date. Count any remaining days as a partial final week. Place the marker by elapsed days and include both endpoints, with a meeting on the delivery date in the final week. Omit the line for a zero-length or reversed interval or a meeting outside the interval.

## Consequences

The line comes from the existing dates. Meeting numbers retain their separate meaning.
