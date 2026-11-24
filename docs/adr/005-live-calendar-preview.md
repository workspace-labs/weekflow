# 005. Calculate the live dates in CSS

## Context

The meeting shows each decision's impact immediately with scripts off. It needs one running date for each decision and the final date. Enumerating answer combinations would quickly make the file too large.

## Decision

Render one CSS value for each decision's selected days and one for the sum through that decision. Only a checked Yes, now contributes days. The header and closing row share the final sum. CSS calculates a Gregorian date from the planned day's ordinal and the applicable sum, then formats that one date with counters.

Expose the live header as one polite, atomic status. Label the running days and date cells with their respective generated values so the browser accessibility tree exposes the same value as the screen. Each live value has one text source. The starting date is plain text in the row labelled Planned delivery date.

## Consequences

The file grows by a fixed amount per decision apart from differences in content and identifier length. Dates outside the record calendar of years 1 through 9999 display “Date outside preview range.” Day totals beyond the browser counter's limit of 2,147,483,647 display “Days outside preview range.” The decision card retains the exact requested number.

Draft confirmation still compares the whole HTML file with a fresh render. An older draft must be prepared and shown to the owner again before confirmation.
