"""Keep the test suite away from a display the user may be playing on.

Scripts post to the live display at localhost:5001 (stats, conditions, dice,
battlemap). Point them at a closed port instead, so running tests mid-game can
never add test characters to a real party. The opt-in live render tests
(DISPLAY_RENDER_TESTS=1) keep the real address.
"""
import os

if os.environ.get("DISPLAY_RENDER_TESTS") != "1":
    os.environ["DNE_DISPLAY_HOST"] = "127.0.0.1:9"

# Runtime and campaign data go to a throwaway folder unless a test sets its own:
# some tests import the display app in-process, and it saves stats.json to the
# runtime dir; the live display reads that same file.
import atexit
import shutil
import tempfile

_SANDBOX = tempfile.mkdtemp(prefix="dne-tests-")
atexit.register(shutil.rmtree, _SANDBOX, True)
os.environ.setdefault("DNE_RUNTIME_DIR", os.path.join(_SANDBOX, "runtime"))
os.environ.setdefault("DNE_CAMPAIGN_ROOT", os.path.join(_SANDBOX, "data"))
