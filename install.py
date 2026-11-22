#!/usr/bin/env python3
"""Install Dungeons & Everything into every AI coding agent on this machine.

    python3 install.py              # every agent detected on this machine
    python3 install.py codex gemini # only these
    python3 install.py --list       # what is supported / detected / installed
    python3 install.py --uninstall [agent …]

Agents that read skill folders get a link to skills/dne (so `git pull` updates them).
Agents that only read a rules file get a short block that points them at SKILL.md.
Claude Code can also use the plugin (`/plugin install dne@dungeons-and-everything`).
"""
from __future__ import annotations

import pathlib
import re
import shutil
import sys

SKILL = pathlib.Path(__file__).resolve().parent / "skills" / "dne"
H = pathlib.Path.home()
START, END = "<!-- dne:start -->", "<!-- dne:end -->"

# name: (detect dir, skills dir or None, rules file or None, rules file is ours alone)
AGENTS = {
    "claude":      (H / ".claude",              H / ".claude/skills",                   None, False),
    "codex":       (H / ".codex",               H / ".codex/skills",                    None, False),
    "gemini":      (H / ".gemini",              H / ".gemini/skills",                   None, False),
    "antigravity": (H / ".gemini/antigravity-cli", H / ".gemini/antigravity-cli/skills", None, False),
    "antigravity-ide": (H / ".gemini/config",   H / ".gemini/config/skills",            None, False),
    "opencode":    (H / ".config/opencode",     H / ".config/opencode/skills",          None, False),
    "copilot":     (H / ".copilot",             H / ".copilot/skills",                  None, False),
    "crush":       (H / ".config/crush",        H / ".config/crush/skills",             None, False),
    "droid":       (H / ".factory",             H / ".factory/skills",                  None, False),
    "dsh":         (H / ".dsh",                 H / ".dsh/skills",                      None, False),
    "cursor":      (H / ".cursor",              None, H / ".cursor/rules/dne.mdc",            True),
    "kiro":        (H / ".kiro",                None, H / ".kiro/steering/dne.md",            True),
    "cline":       (H / "Documents/Cline",      None, H / "Documents/Cline/Rules/dne.md",     True),
    "continue":    (H / ".continue",            None, H / ".continue/rules/dne.md",           True),
    "kilocode":    (H / ".kilocode",            None, H / ".kilocode/rules/dne.md",           True),
    "amp":         (H / ".config/amp",          None, H / ".config/amp/AGENTS.md",            False),
    "qwen":        (H / ".qwen",                None, H / ".qwen/QWEN.md",                    False),
    "goose":       (H / ".config/goose",        None, H / ".config/goose/.goosehints",        False),
    "kimi":        (H / ".kimi",                None, H / ".kimi/AGENTS.md",                  False),
}


def rules_block() -> str:
    return (f"{START}\n## Dungeons & Everything (tabletop Game Master)\n"
            f"When the user asks to play Dungeons & Everything, run a tabletop RPG campaign, or types `/dne …`,\n"
            f"read `{SKILL}/SKILL.md` and follow it exactly. Wherever it writes `${{CLAUDE_SKILL_DIR}}`, use `{SKILL}`.\n"
            f"Command procedures: `{SKILL}/SKILL-commands.md`; script reference: `{SKILL}/SKILL-scripts.md`.\n{END}\n")


def _strip_block(text: str) -> str:
    return re.sub(rf"\n*{re.escape(START)}.*?{re.escape(END)}\n?", "\n", text, flags=re.S).strip("\n") + "\n"


def install(name: str) -> str:
    _, skills, rules, own = AGENTS[name]
    if skills:
        dest = skills / "dne"
        if dest.is_symlink():
            dest.unlink()          # re-point an old link (e.g. a moved checkout)
        elif dest.exists():
            return f"{name}: SKIPPED — {dest} exists and is not ours (move it away first)"
        skills.mkdir(parents=True, exist_ok=True)
        try:
            dest.symlink_to(SKILL, target_is_directory=True)
            return f"{name}: linked {dest} → {SKILL}"
        except OSError:  # shortcut: Windows without symlink rights gets a copy; re-run after `git pull`
            shutil.copytree(SKILL, dest)
            return f"{name}: copied to {dest} (re-run after updating)"
    rules.parent.mkdir(parents=True, exist_ok=True)
    if own:
        rules.write_text(rules_block(), encoding="utf-8")
    else:
        old = rules.read_text(encoding="utf-8") if rules.exists() else ""
        body = _strip_block(old)
        rules.write_text((body.rstrip("\n") + "\n\n" if body.strip() else "") + rules_block(), encoding="utf-8")
    return f"{name}: rules → {rules}"


def uninstall(name: str) -> str:
    _, skills, rules, own = AGENTS[name]
    if skills:
        dest = skills / "dne"
        if dest.is_symlink():
            dest.unlink()
            return f"{name}: removed {dest}"
        return f"{name}: nothing to remove" if not dest.exists() else f"{name}: {dest} is a copy — delete it by hand"
    if rules.exists():
        if own:
            rules.unlink()
        else:
            rules.write_text(_strip_block(rules.read_text(encoding="utf-8")), encoding="utf-8")
        return f"{name}: removed block from {rules}"
    return f"{name}: nothing to remove"


def installed(name: str) -> bool:
    _, skills, rules, _ = AGENTS[name]
    if skills:
        return (skills / "dne").exists()
    return rules.exists() and START in rules.read_text(encoding="utf-8")


def main(argv: list[str]) -> int:
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    if "--list" in argv:
        for n, (detect, skills, rules, _) in AGENTS.items():
            where = skills / "dne" if skills else rules
            print(f"{n:16} {'detected' if detect.exists() else '-':9} {'installed' if installed(n) else '':10} {where}")
        print("aider            (no config dir) run: aider --read " + str(SKILL / "SKILL.md"))
        return 0
    names = [a for a in argv if not a.startswith("-")]
    unknown = [n for n in names if n not in AGENTS]
    if unknown:
        print(f"Unknown agent(s): {', '.join(unknown)}. Known: {', '.join(AGENTS)}", file=sys.stderr)
        return 2
    if not names:
        names = [n for n, (detect, *_rest) in AGENTS.items() if detect.exists()]
        if not names:
            print("No supported agent found. Name one: python3 install.py <agent>", file=sys.stderr)
            return 1
    act = uninstall if "--uninstall" in argv else install
    for n in names:
        print(act(n))
    if act is install:
        print("\nThen start your agent and type /dne (or say: let's play Dungeons & Everything).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
