# 012. Bind the client PDF to the meeting record

## Context

Signing and locking need the current PDF. The approved Weeks sheet has no PDF tracking field. These commands must run without ReportLab.

## Decision

Draw with a deterministic ReportLab canvas and include a PDF comment with a digest of the meeting facts and a checksum of the drawn bytes. Check those values before recording a paper signature or locking. Keep the signature line on an otherwise unchanged PDF as the place for the client to sign on paper. Re-recording retires the previous PDF and clears the recorded signature.

Check text before it is saved against the character maps of the bundled fonts used for that field. This check uses the Python standard library. Drawing still checks the glyphs with ReportLab.

When the confirmed page and content are available, remake a missing locked PDF from those saved facts. For an existing locked PDF, require byte equality with the copy drawn from the confirmed view. For old pages that used ISO dates in the carry-over sections, match the saved HTML and use its original date wording for deterministic recreation.

When recorded meeting fonts are lost, keep an existing PDF whose record digest and checksum still match. A replacement PDF uses Studio faces for the unavailable roles and identifies unsupported characters by their Unicode codes. The command reports this substitution, and the PDF receipt records it so the locked copy can remain in use if the original fonts return. Locking still requires the paper signature when the delivery date moved.

## Consequences

The local client copy can be checked without a PDF package or extra Weeks fields. The checksum detects accidental replacement or damage. The signature stays on paper.
