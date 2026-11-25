"""Find Poppler's pdftotext and run it on PDF bytes.

The PDF text tests rely on Poppler's options and layout. Git for Windows
ships xpdf's pdftotext under the same name, which has no -bbox, lays text
out differently and cannot read standard input, so the tests skip with it.
They pass a file path instead of "-" and ask for UTF-8 text explicitly.
"""
import os
import shutil
import subprocess
import tempfile


def poppler_pdftotext():
    path = shutil.which("pdftotext")
    if path is None:
        return None
    try:
        version = subprocess.run([path, "-v"], capture_output=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    return path if b"poppler" in (version.stdout + version.stderr).lower() else None


def pdftotext_bytes(pdftotext, pdf, *options, timeout=15):
    descriptor, path = tempfile.mkstemp(suffix=".pdf")
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(pdf)
        return subprocess.run([pdftotext, "-enc", "UTF-8", *options, path, "-"], capture_output=True,
                              check=True, timeout=timeout).stdout
    finally:
        os.unlink(path)
