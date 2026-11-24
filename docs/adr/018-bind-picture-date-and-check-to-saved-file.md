# 018. Bind picture dates and owner checks to the saved file

## Context

The Screens sheet has ten approved columns. A comparison may show a picture that is no longer current, and a removed file must stay removed while an old picture must never get a newer date.

## Decision

Strip metadata before hashing the saved PNG or JPEG. In the ignored `screens/` folder, encode the meeting number, capture date or design mark, digest and a free sequence number in the filename. Record the earliest known date per digest in the local picture history and keep the history after a picture is removed. Save a check receipt by filename and digest when the owner confirms a picture. The Screens sheet keeps the current check date in its approved column.

Accept 8-bit baseline and progressive Huffman JPEGs. Ask for an upright copy when PNG or JPEG orientation metadata calls for a rotation or reflection. Accepted pictures still have their metadata removed.

Use `screen-check --id <id> --file screens/<saved-picture>` to check an exact saved file after the owner reviews it. The default is the current picture. Check the screen ID and file digest before recording the receipt. If the ignored date history is lost, use the dates in the current and earlier Screens filenames as surviving evidence.

## Consequences

Changing only metadata cannot make identical saved picture bytes new. An earlier picture keeps its check when a new file becomes current. The receipts and date history store facts about picture files. They contain no image bytes and stay out of Git with the pictures.
