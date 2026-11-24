# 037. Freeze the page layout and owner colours with the meeting

## Context

New meeting pages use Layout A. Earlier pages must still verify against their saved content. Projects without a usable design need a colour choice the owner makes once and can revisit at preparation.

## Decision

Store the explicit standard or custom choice in `docs/weekly/project.json` and resolve it only when the project has no usable design. Save the resolved colours, fonts, paper and layout in the prepared content. The project choice and paper preference are live settings that stay out of the meeting facts used for receipts.

Save `page_layout: "a"` on newly numbered meetings. A saved design without that marker uses the original page. Refreshing a confirmed draft reloads its saved design and keeps its page layout, colours and paper. The next prepared week takes its appearance from the active project design or the owner's chosen colours.

## Consequences

Preparing a meeting publishes the colour choice and the meeting data in the same transaction. Existing snapshots keep their renderer without a migration. New colour choices leave the bytes and receipts of recorded or locked weeks intact, including when a client copy must be made again from saved content.
