# Contributing to Dungeons & Everything

Pull requests are welcome.

## License of contributions

By submitting a pull request, you agree that your contribution is licensed under the [GNU Affero General Public License v3.0 or later](LICENSE), the same license as the rest of the project. You retain copyright on your own contributions.

## What's most useful

- **World Kit** improvements — better validation, new fields, example worlds in `skills/dne/templates/`
- **Bug fixes** in the display companion, dice mechanics, or anything in `skills/dne/scripts/`
- **Language packs** for SFX triggers (see `skills/dne/display/audio.py`)
- **Performance and cleanup** in the Python helpers

## Process

1. For substantive changes, open an issue first to agree on scope.
2. Small fixes and doc improvements can go straight to a PR.
3. Explain the *why* in the PR description.
4. Run the tests before opening the PR:

```
python3 -m pip install pytest flask flask-cors pyyaml
python3 -m pytest tests/ -q
```

Optional pre-release scan: `python3 scripts/scan_plugin.py`.
