# 007. Stack running table cells on narrow screens

## Context

The Running Date table has five columns. Decision text and requester names can be long, and the page must fit a 320 px viewport.

## Decision

Keep one semantic table. On narrow screens, put each row's heading above a two-column grid, show a short field label with each value, and visually clip the original column headers. The original headers remain available to assistive technology.

## Consequences

The same row order, answers and dates fit without sideways scrolling. Screen readers can still use the table headings. The additional visual labels are hidden from the accessibility tree to avoid repeating the headings.
