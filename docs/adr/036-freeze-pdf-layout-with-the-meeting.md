# 036. Freeze PDF layout with the meeting

## Context

The client PDF uses Layout C for new meetings. A meeting prepared before the change still needs its original layout when it is copied, recorded, locked or redrawn after a removal. Earlier PDF receipts already bind the meeting facts and, where needed, the paper palette.

## Options

- Switch every rendering to Layout C and keep only the old copies still on disk.
- Save the layout with the prepared design and select the renderer from that snapshot.

## Decision

Save the Layout C marker in the PDF settings of the numbered meeting's design snapshot. Start each new draft with Layout C. Refreshing an existing draft retains its saved layout, including when the owner had already confirmed it. A saved draft with no layout marker uses the original single-column renderer. A missing marker also covers the older snapshots without paper settings.

Keep the layout in the PDF settings so the meeting page and downloaded answers retain their fingerprints. Include the marker in new PDF receipts. For unmarked meetings, leave the receipt inputs and PDF renderer unchanged.

## Consequences

There is no migration of prepared, recorded or locked weeks. Client copy, font recovery during lock, and name or picture removal all use the same layout from the saved design. A removal can change affected content and its receipt while keeping the layout. Rebuilding an intact old meeting with its original fonts keeps its existing PDF bytes.

Build 13 Fix 1 uses `c-2` for newly prepared build meetings. The `c` marker keeps the first Layout C renderer for saved build meetings and remains the default for docs meetings. A refresh keeps the saved marker, which the PDF receipt already includes.
