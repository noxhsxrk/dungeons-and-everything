"""
paths.py — canonical path resolution for DND campaign and character data.

All scripts that need to locate campaign or character files should import from
here rather than hardcoding ~/.dne/. Set DNE_CAMPAIGN_ROOT to move your
data anywhere — iCloud, Dropbox, network share, etc. Defaults to ~/.dne.
Nothing is read from or written to ~/.claude.

Usage:
    from paths import campaigns_dir, characters_dir, campaign_dir, find_campaign

Environment:
    DNE_CAMPAIGN_ROOT   Root of campaign data tree. Default: ~/.dne
                        Example: export DNE_CAMPAIGN_ROOT=~/iCloud/dnd
    CLAUDE_SKILL_DIR    Set by Claude Code for plugin/installed skills. Points at
                        the directory containing SKILL.md (the skill's own dir,
                        NOT the plugin root). When unset (ad-hoc subprocess, dev
                        checkout) the code root is resolved from this file's
                        location — see skill_root().

Two distinct roots:
    * DATA root  — where campaigns/characters live (DNE_CAMPAIGN_ROOT). User data.
    * CODE root  — where scripts/data/display assets live (skill_root()). Read the
                   bundled SRD, the display companion, and sibling scripts from here.
                   For a plugin this is <plugin>/skills/dne/, so we resolve to the
                   skill dir — never CLAUDE_PLUGIN_ROOT (wrong granularity).
"""

import os
import pathlib
import sys

# Windows CJK fix: piped stdout defaults to the system codepage (cp936/GBK).
# Every script imports this module, so UTF-8 is forced once here.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

_DEFAULT_ROOT = pathlib.Path("~/.dne").expanduser()


def _root() -> pathlib.Path:
    """Return the configured data root, expanded and absolute."""
    raw = os.environ.get("DNE_CAMPAIGN_ROOT", "")
    if raw.strip():
        return pathlib.Path(raw.strip()).expanduser().resolve()
    return _DEFAULT_ROOT


# ── Code root (scripts / data / display assets) ───────────────────────────
# Distinct from the DATA root above. This locates the *installed code* — the
# bundled SRD JSON, the display companion, and sibling scripts. paths.py lives
# at <code-root>/scripts/paths.py, so the root is parent.parent. Works in every
# install mode:
#   1. Plugin     — code lives at <plugin>/skills/dne/; CLAUDE_SKILL_DIR points
#                   there when exported. (CLAUDE_PLUGIN_ROOT would be the plugin
#                   root — the wrong level — so we deliberately do not use it.)
#   2. Standalone — copied into an agent skills dir (e.g. ~/.gemini/config/skills/dne).
#   3. Dev clone  — anywhere on disk.
# In all three, __file__ resolution is correct and needs no env var; the
# CLAUDE_SKILL_DIR check is a belt-and-suspenders fast path for plugin contexts
# that export it into the subprocess environment.

def skill_root() -> pathlib.Path:
    """Return the skill's own directory (holds scripts/, data/, display/)."""
    env = os.environ.get("CLAUDE_SKILL_DIR", "").strip()
    if env:
        return pathlib.Path(env).expanduser().resolve()
    return pathlib.Path(__file__).resolve().parent.parent


def data_dir() -> pathlib.Path:
    """Bundled dataset directory (SRD JSON, supplemental, external corpus)."""
    return skill_root() / "data"


def scripts_dir() -> pathlib.Path:
    """Directory holding the helper scripts (this file's directory)."""
    return skill_root() / "scripts"


def display_dir() -> pathlib.Path:
    """Display-companion CODE directory (Flask app, send.py, push_stats.py, …)."""
    return skill_root() / "display"


# ── Runtime state (writable, update-safe) ─────────────────────────────────
# Distinct from both roots above. The display companion writes session state,
# auth tokens, device approvals, and TLS certs while running. These must NOT
# live in the CODE root: a plugin's code dir is refreshed/replaced on
# `/plugin update` (which would wipe device approvals + certs) and may be
# read-only. Keep them beside the user's campaign data, which is stable across
# installs and updates. Override with DNE_RUNTIME_DIR; default <data-root>/.runtime.

def runtime_dir() -> pathlib.Path:
    """Return the writable runtime-state directory, creating it if needed."""
    raw = os.environ.get("DNE_RUNTIME_DIR", "").strip()
    d = pathlib.Path(raw).expanduser() if raw else (_root() / ".runtime")
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return d


def campaigns_dir() -> pathlib.Path:
    """Return the campaigns directory under the configured root."""
    return _root() / "campaigns"


def characters_dir() -> pathlib.Path:
    """Return the global characters directory under the configured root."""
    return _root() / "characters"


def campaign_dir(name: str) -> pathlib.Path:
    """Return the directory for a specific campaign under the configured root."""
    return campaigns_dir() / name


def find_campaign(name: str) -> pathlib.Path:
    """Return the campaign directory under the configured root (may not exist)."""
    return campaign_dir(name)


def _names_word(name: str, display: str) -> bool:
    """True when `name` is one word of `display` or `display` minus a title (Thai or English)."""
    want = norm_key(name)
    words = [norm_key(w) for w in display.split()]
    if want in words:
        return True
    try:
        from name_registry import slug
        return slug(name) in {slug(display), *(slug(w) for w in display.split())}
    except Exception:
        return False


def find_character_file(campaign: str, name: str) -> pathlib.Path:
    """Resolve a sheet by filename, display name, slug, or unique given name."""
    cdir = find_campaign(campaign) / "characters"
    target = norm_key(name)
    files = sorted(cdir.glob("*.md"))
    for path in files:
        if path.stem == name:
            return path
    first_names = []
    for path in files:
        if norm_key(path.stem) == target:
            return path
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        headings = [line[2:].strip() for line in lines if line.startswith("# ") and line[2:].strip()]
        if any(norm_key(display) == target for display in headings):
            return path
        if headings and _names_word(name, headings[0]):
            first_names.append((path, headings[0]))
    if len(first_names) == 1:
        return first_names[0][0]
    if first_names:
        candidates = ", ".join(display for _, display in first_names)
        raise FileNotFoundError(f"Ambiguous character name {name!r}. Candidates: {candidates}")
    raise FileNotFoundError(f"Character sheet not found for '{name}' in {cdir}")


# ── Name keys ─────────────────────────────────────────────────────────────
import unicodedata as _ud


def norm_key(name) -> str:
    """Lookup key for a name: lowercase, every run of non-letter/digit chars → '-'.

    Unicode-aware so Thai (and other scripts with combining marks) keep their
    letters; for ASCII it equals the SRD index form ("Hill Dwarf" → "hill-dwarf").
    """
    s = str(name or "").strip().lower()
    out = "".join(c if _ud.category(c)[0] in "LMN" else "-" for c in s)
    import re
    return re.sub(r"-+", "-", out).strip("-")


# ── Ruleset selection ─────────────────────────────────────────────────────
# A campaign declares its ruleset on the state.md header line,
# e.g.: "**Ruleset:** 2024". When unset (legacy campaigns) we default
# to 2014 — the historical ruleset of this skill.

import re as _re

CHARACTER_LEVEL_RE = _re.compile(r"\*\*(?:Level|等级):\*\*\s*(\d+)", _re.IGNORECASE)

VALID_RULESETS = ("2014", "2024")
DEFAULT_RULESET = "2014"

_RULESET_PAT = _re.compile(r"\*\*Ruleset:\*\*\s*(\d{4})", _re.IGNORECASE)


def campaign_ruleset(name: str) -> str:
    """Return the campaign's declared ruleset (e.g. '2014', '2024').

    Reads the state.md header. Falls back to DEFAULT_RULESET when the
    file is missing or the field is unset (legacy campaigns predating
    the ruleset field — they were 2014 by definition).
    """
    state = find_campaign(name) / "state.md"
    if not state.exists():
        return DEFAULT_RULESET
    try:
        text = state.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return DEFAULT_RULESET
    m = _RULESET_PAT.search(text)
    if not m:
        return DEFAULT_RULESET
    val = m.group(1).strip()
    return val if val in VALID_RULESETS else DEFAULT_RULESET


def srd_path(ruleset=None):
    """Return path to the SRD JSON for the given ruleset.

    `ruleset=None` returns the default (2014) path. The 2024 path is
    `dnd5e_srd_2024.json`. Caller is responsible for handling missing
    files (e.g. a campaign declares 2024 but the dataset hasn't been
    built yet — in that case, suggest `/dne data sync --ruleset 2024`).
    """
    rs = ruleset or DEFAULT_RULESET
    if rs not in VALID_RULESETS:
        rs = DEFAULT_RULESET
    fname = "dnd5e_srd_2024.json" if rs == "2024" else "dnd5e_srd.json"
    return data_dir() / fname


# ── CLI passthrough ───────────────────────────────────────────────────────
# A few helpers are useful from shell too. Keep this minimal — paths.py is
# primarily an import surface.
if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "campaign-ruleset":
        print(campaign_ruleset(sys.argv[2]))
        sys.exit(0)
    if len(sys.argv) >= 2 and sys.argv[1] == "srd-path":
        rs = sys.argv[2] if len(sys.argv) >= 3 else None
        print(srd_path(rs))
        sys.exit(0)
    if len(sys.argv) >= 2 and sys.argv[1] == "runtime-dir":
        print(runtime_dir())
        sys.exit(0)
    if len(sys.argv) >= 3 and sys.argv[1] == "campaign-dir":
        print(find_campaign(sys.argv[2]))
        sys.exit(0)
    print(
        "usage:\n"
        "  python3 paths.py campaign-ruleset <campaign-name>\n"
        "  python3 paths.py srd-path [2014|2024]\n"
        "  python3 paths.py runtime-dir\n"
        "  python3 paths.py campaign-dir <campaign-name>",
        file=sys.stderr,
    )
    sys.exit(2)
