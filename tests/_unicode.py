"""Skip marker for tests that need non-ASCII file names or command-line arguments.

The CI job `ascii-locale` runs with LC_ALL=C and UTF-8 coercion off, so the filesystem and
argv encoding is ASCII: a Thai file name or argument cannot exist there at all (the OS layer
refuses it before our code runs). Those tests skip in that job and run everywhere else; every
other test still checks that the scripts themselves survive an ASCII console.
"""
import sys
import unittest


def _unicode_fs() -> bool:
    try:
        "ทองดี é".encode(sys.getfilesystemencoding())
    except UnicodeEncodeError:
        return False
    return True


needs_unicode_fs = unittest.skipUnless(
    _unicode_fs(), "filesystem/argv encoding is ASCII: non-ASCII names cannot be passed or created")
