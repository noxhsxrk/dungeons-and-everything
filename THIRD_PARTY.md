# Third-party material

Dungeons & Everything's own code is AGPL-3.0-or-later (see [LICENSE](LICENSE) and [NOTICE](NOTICE)).
This file lists the outside sources credited in this release: the credit each requires (quoted word
for word from the source), its licence, the files that use it, and the date it was last checked
against the source.

Rules for adding a source:

- Copied text or data from another open licence lives in `skills/dne/data/third_party/<source>/`,
  next to that source's own licence file, and gets a section here and a credit line in NOTICE.
- Share-alike sources (CC BY-SA, ORC) stay in their own folder and are never merged into our files.
- Mechanics are not copyrightable; a game we only learn from, written up in our own words, is not
  listed here. Game names and trademarks are never used as feature names.

## System Reference Document 5.1 (Wizards of the Coast)

- **Licence:** Creative Commons Attribution 4.0 International, https://creativecommons.org/licenses/by/4.0/legalcode
- **Required credit** (SRD 5.1 PDF, "Legal Information", p. 1):

  > This work includes material taken from the System Reference Document 5.1 (“SRD 5.1”) by Wizards of the Coast LLC and available at https://dnd.wizards.com/resources/systems-reference-document. The SRD 5.1 is licensed under the Creative Commons Attribution 4.0 International License available at https://creativecommons.org/licenses/by/4.0/legalcode.

  The SRD also asks: "Please do not include any other attribution regarding Wizards other than that provided above."
- **Files:** `skills/dne/data/dnd5e_srd.json` (2014 rules), `skills/dne/data/monster_stats_by_cr.json`
  (derived from the SRD 5.1 monsters), and `skills/dne/data/dnd5e_srd_2024.json`, which carries this
  credit too because `build_srd.py` always writes it.
  The credit is also stored in each SRD file's `_meta.license_attribution`, written by
  `skills/dne/scripts/build_srd.py`.
- **Checked:** 2026-11-26, against https://media.wizards.com/2023/downloads/dnd/SRD_CC_v5.1.pdf.

## System Reference Document 5.2.1 (Wizards of the Coast)

- **Licence:** Creative Commons Attribution 4.0 International, https://creativecommons.org/licenses/by/4.0/legalcode
- **Required credit** (SRD 5.2.1 PDF, "Legal Information", p. 1):

  > This work includes material from the System Reference Document 5.2.1 (“SRD 5.2.1”) by Wizards of the Coast LLC, available at https://www.dndbeyond.com/srd. The SRD 5.2.1 is licensed under the Creative Commons Attribution 4.0 International License, available at https://creativecommons.org/licenses/by/4.0/legalcode.

  The SRD also asks: "Please do not include any other attribution to Wizards or its parent or affiliates other than that provided above."
- **Files:** `skills/dne/data/dnd5e_srd_2024.json` (2024 rules).
- **Version note:** the 2024 data was built on 2026-11-22 from the upstream projects below, which
  do not record which SRD 5.2 revision they used (the `sha` fields in `_meta.sources` are blank),
  so the revision is not pinned. We credit 5.2.1, the revision whose legal page we read.
- **Checked:** 2026-11-26, against https://media.dndbeyond.com/compendium-images/srd/5.2/SRD_CC_v5.2.1.pdf.

## SRD data intermediaries (5e-bits, Foundry VTT)

The SRD records above were not typed from the PDFs; `build_srd.py` pulls them from:

- **5e-bits/5e-database** (https://github.com/5e-bits/5e-database): spells, equipment, magic items,
  conditions, monsters. Repository licence: MIT, `LICENSE.md`, "Copyright (c) [2018-2020] [Adrian
  Padua, Christopher Ward]".
- **foundryvtt/dnd5e** (https://github.com/foundryvtt/dnd5e): class features, species traits, 2024
  spells and monsters. Repository licence: MIT, `LICENSE.txt`, "Copyright 2021 Andrew Clayton".

We ship records extracted from their data files, not their code. The MIT condition is that "the
above copyright notice and this permission notice shall be included in all copies or substantial
portions of the Software"; the copyright lines are quoted above. The rules text inside the records
is SRD material, credited above. `dnd5e_srd_2024.json` names both projects in
`_meta.license_attribution`.

- **Checked:** 2026-11-26, the licence files on each repository's default branch (GitHub API).

## Ironsworn (Shawn Tomkin)

- **Licence:** Creative Commons Attribution 4.0 International, https://creativecommons.org/licenses/by/4.0/
- **Required credit** (Ironsworn SRD v.09, updated 01/14/23, "How to Provide Credit"):

  > This work is based on Ironsworn (found at www.ironswornrpg.com), created by Shawn Tomkin, and licensed for our use under the Creative Commons Attribution 4.0 International License (https://creativecommons.org/licenses/by/4.0/).

  The licence page adds: "You cannot state or imply that your work is an official Ironsworn
  product." Dungeons & Everything is not an official Ironsworn product.
- **What we use:** the Action Oracle and Theme Oracle tables (100 words each, in their d100 order,
  lower-cased) for the scene-meaning word pair.
- **Files:** `skills/dne/scripts/oracle.py` (`_ACTIONS`, `_SUBJECTS`; kept inline because they are
  two short word lists, credited in the module docstring).
- **Changes:** words lower-cased; nothing else.
- **Checked:** 2026-11-26, against the Ironsworn SRD text from https://www.ironswornrpg.com.

## Oracle chaos factor and event focus (no third-party text)

`skills/dne/scripts/oracle.py`'s chaos factor and event focus: mechanic inspired by solo-oracle tools;
wording our own. The event-focus labels and their descriptions were rewritten in our own words on
2026-11-26 (they had been credited to a CC BY-NC source, which cannot ship in AGPL code). Nothing
here needs a credit line in NOTICE.

## Reference only (no content shipped)

These were read for research only. None of their text, tables or names ship here, and none may be
added: an AI game master cannot meet their no-AI terms.

- **Trophy** (Jesse Ross / Hedgemaze Press): the SRD is CC BY 4.0, but the grant carries a no-AI
  condition; the free sheets have no licence.
- **Liminal Horror** (Goblin Archives): the SRD v3.0 is CC BY 4.0, but its Third Party License has a
  no-AI clause, and the writing resources carry no licence.
