# 030. Measure joined Arabic PDF lines

## Context

ReportLab can draw local TrueType faces with no online access. Weekflow must render Arabic in its existing PDF layout on the supported Python versions.

## Decision

Keep Arabic text in reading order in the record. For the PDF, shape each candidate line with Unicode presentation forms, measure its mixed font runs, then right-align the line and draw it. Reverse the table column order for Arabic at the renderer boundary. Use the selected Arabic TrueType pair when it has the forms needed for joining and use the existing Studio fallback otherwise.

## Consequences

Widths and page breaks are calculated before drawing. Arabic PDF search depends on the viewer's treatment of presentation forms. English keeps its existing paragraph and font path.
