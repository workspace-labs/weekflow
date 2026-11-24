# 008. Open meeting steps with in-page links

## Context

The named disclosures in ADR 004 could close on a repeated key before the browser released focus. That changed the visible step after a successful activation.

## Decision

Use native links to the five meeting panel IDs. CSS shows the targeted panel and marks its tab as current. The first panel is the default when no meeting panel is targeted.

Make each panel a fragment focus destination so the next Tab can enter its controls. Leave scroll space above the destination for the meeting header. Enter follows the link and Space scrolls.

Delay pointer hit testing within a newly targeted panel for 500 milliseconds. This keeps a quick second click at the old Back or Next position from activating a control revealed underneath it. The guard has no visual motion and keyboard controls are available immediately.

## Consequences

Following the same link repeatedly keeps its destination selected. Browser history can revisit the same-document fragments with the decision radios and live dates still in place. The page keeps the existing Content Security Policy and generates navigation links only to its own five panels.

This decision supersedes the step navigation in ADR 004. The decision radio groups remain as described there.
