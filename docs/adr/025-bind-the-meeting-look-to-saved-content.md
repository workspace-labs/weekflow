# 025. Bind the meeting look to saved content

## Context

The project design may change while a meeting is open. Each page and PDF needs to use the design that was prepared for that meeting. Older Studio copies already have fingerprints and PDF receipts.

## Decision

Save the resolved design with the numbered meeting content. Store copies of project fonts by SHA-256 under `docs/weekly/pages/fonts/`. Publish them in the same recoverable write as the meeting. The undo record notes when that write created the font folder, so recovery can remove it if it is empty. A saved font reference names a digest and a source. A project copy must match the digest before use. A bundled font uses the same digest check against the skill's files. Reuse an existing verified copy of the same bytes.

Keep the existing fingerprint for an effective Studio design. Include a custom design in the fingerprint. To verify an older build page without embedded fonts, match the complete HTML from the earlier renderer settings. Keep a digest of each design message already shown for the draft, outside the fingerprint.

Use fixed font role names in the HTML and digest-based names in the PDF renderer. The role names keep stylesheet text independent of the project file. The digest names keep separate PDF fonts from colliding when their internal names match.

When recording a first or revised answer or closing a meeting, restore missing or damaged frozen fonts from regular TrueType files in `docs/fonts/` or from the confirmed page. Verify the saved digest and font structure before using either source. Publish the recovered fonts with the record change through the weekly recovery write. Links and unsafe output paths still fail validation.

If a project face cannot be restored, keep its saved digest in the meeting fingerprint, tell the owner and use the corresponding Studio face when drawing a replacement. The original answers and text are still recorded. Name removal updates the records, content and any surviving HTML and redraws the PDF with Studio faces for unavailable roles. If saved content is missing or the renderer needed for the fallback is unavailable, keep the affected PDF and warn that it may retain the name. A redacted HTML page with substituted faces records those roles so later checks can recognise the exact HTML.

## Consequences

Editing the live design or its fonts affects the next preparation. Saved custom meetings recover the exact fonts when a verified source survives. Earlier Studio pages and PDFs keep their existing confirmation and record receipts. A new preparation can reuse the same project fonts across meetings.
