# 026. Adjust colours for the meeting surfaces

## Context

One project colour can serve as a control or as text. Answer labels sit on tinted backgrounds. A light page and a dark card can also make a single readable text colour impossible.

## Decision

Blend a colour toward black or white and keep the smallest change that passes its contrast checks. Use separate shades where Main is used as small text or where a PDF answer label needs a stronger shade on its tint. Keep the existing Studio tint and make the solid background contribution explicit for project tints.

When a valid Background cannot support readable ink on a PDF badge tint, move it just enough to support that pair. When a valid Card and Background cannot share readable ink, move Card toward Background just enough to support both. Report each change before showing the draft and save the final values with the meeting.

## Consequences

A control can keep its project colour while a small label uses a more readable shade. Opposing surfaces can change when the text requirements demand it. The project design file stays the source for the next preparation.
