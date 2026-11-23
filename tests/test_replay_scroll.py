"""Coming back to the display must not leave the reader at the start of the history.

The server replays the recent log on every (re)connect, and a phone reconnects each time the
player returns from another tab. The page used to append that replay under the transcript it
already showed and smooth-scroll across it. Driven through node with a stub DOM, like
test_block_deferral.py.
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

HTML = pathlib.Path(__file__).resolve().parent.parent / "skills" / "dne" / "display" / "templates" / "index.html"
NODE = shutil.which("node")
_SLICE = re.compile(r"(function _wipeTranscript\(\).*?)\nfunction clearDisplay", re.S)

PRELUDE = """
let charQueue = [], isTyping = false, _currentInlineEl = null, currentCursor = null, currentEl = null;
let idleTimer = null, userScrolledUp = false;
const kids = [];
const textContent = { appendChild(n) { kids.push(n); }, set innerHTML(v) { kids.length = 0; } };
const textScroll = { scrollTop: 0, style: {}, get scrollHeight() { return kids.length * 100; } };
const document = { createElement: () => ({ style: {}, appendChild() {} }), getElementById: () => null };
const _mdParse = () => [], _appendInlineSegments = () => {}, _addTtsBar = () => {}, _hideNewPill = () => {};
function scrollToBottom() { if (!userScrolledUp) textScroll.scrollTop = textScroll.scrollHeight; }
function renderPlayerBlock(who, text) { kids.push(text); scrollToBottom(); }
const log = [{ text: 'one' }, { player: 'Mira', text: 'opens the door' }, { text: 'three' }];
"""


def _run(script: str) -> dict:
    m = _SLICE.search(HTML.read_text(encoding="utf-8"))
    if not m:
        raise AssertionError("replay code not found in the template")
    with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False, encoding="utf-8") as f:
        f.write(PRELUDE + m.group(1) + "\n" + script)
    out = subprocess.run([NODE, f.name], capture_output=True, encoding="utf-8", timeout=60)
    pathlib.Path(f.name).unlink()
    if out.returncode != 0:
        raise AssertionError(out.stderr[:2000])
    return json.loads(out.stdout.strip().splitlines()[-1])


@unittest.skipUnless(NODE, "node not available")
class ReplayScrollTests(unittest.TestCase):

    def test_a_reconnect_replaces_the_transcript_and_lands_on_the_latest_text(self):
        r = _run("""
        renderReplayBatch(log);
        const first = kids.length;
        renderReplayBatch(log);                       // back from another tab: the stream reconnects
        console.log(JSON.stringify({ first, second: kids.length, top: textScroll.scrollTop,
          end: textScroll.scrollHeight, up: userScrolledUp, behavior: textScroll.style.scrollBehavior }));
        """)
        self.assertEqual(r["second"], r["first"])     # not a second copy under the first
        self.assertEqual(r["top"], r["end"])
        self.assertFalse(r["up"])
        self.assertEqual(r["behavior"], "")           # smooth scrolling is back for live text

    def test_a_reader_who_scrolled_up_stays_where_they_were(self):
        r = _run("""
        renderReplayBatch(log);
        userScrolledUp = true; textScroll.scrollTop = 120;
        renderReplayBatch(log);
        console.log(JSON.stringify({ top: textScroll.scrollTop, up: userScrolledUp }));
        """)
        self.assertEqual(r["top"], 120)
        self.assertTrue(r["up"])


if __name__ == "__main__":
    unittest.main()
