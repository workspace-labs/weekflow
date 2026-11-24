# 027. Freeze PDF paper with the meeting

## Context

The owner chooses project colours or white paper. The meeting page keeps the project design. Copies made after recording or removal need the PDF colours that were prepared with the week.

## Decision

An explicit paper choice updates the project setup in the same recovery write as the numbered meeting. Save the chosen paper and resolved palette inside the saved meeting design. An earlier snapshot without PDF settings uses its saved design as before. An earlier meeting without a design uses Studio as before.

Start the white palette from Studio and the project's Main before any adjustments for the meeting page. Resolve contrast against white and the Studio card with the existing rules. Report a Main adjustment once per draft for each pair of values. Use the saved fonts and corners when rendering either palette.

Keep the PDF settings out of the page and answer fingerprint. Bind the PDF receipt to its palette when that palette differs from the meeting design. A Studio PDF keeps its earlier receipt and bytes for either paper choice.

## Consequences

A readable confirmed draft keeps its paper when refreshed. The owner can change the paper on an unconfirmed draft or the next week. If the confirmed draft's design snapshot is missing or damaged, preparation uses the owner's saved or given choice and the rebuilt draft needs confirmation again. Rebuilds of recorded or locked PDFs read the saved palette and reuse the existing Studio font fallback when needed.
