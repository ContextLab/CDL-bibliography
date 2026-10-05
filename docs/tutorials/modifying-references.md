# Modify references

How to change an entry that is already in the library, and what happens to its
verification result.

The output shown was recorded with `cdlbib 2.0.0` on October 5, 2026, in a temporary copy
of the library chosen with `--library`. `~/demo` stands for that temporary folder.

## Terminal interface

1. Start [the terminal interface](terminal-interface.md) with `cdlbib tui`. In the
   Library view, press `/`, type a search, press `enter`, and move to the entry.
2. Press `e` and change the text.
3. Press `ctrl+p`. The preview shows the diff, the house-format findings, a key change,
   and the status the entry has now and will have after saving.
4. Press `ctrl+s` to save. `esc` closes the editor; when the text was changed, it asks
   first.

## Command line

1. Find the library's folder:

   ```bash
   cdlbib where
   ```

   ```text
   ~/demo/library
   chosen by: cdl.bib found in or above the current folder
   ```

   The first line is the folder. The second says how the library was chosen.

2. Open `cdl.bib` in that folder with a text editor, change the entry, and save.

3. Check the change:

   ```bash
   cdlbib verify
   ```

   `verify` first offers completion for new or changed entries, with the same
   accept, edit and skip choices as `cdlbib add`, then runs the format check and the
   citation check. [Check the library](checking.md) shows the output.

Editing an entry in any way invalidates its saved verification result and any human
approval of it; the entry is checked again the next time. Renaming its key does not.

## Web interface

Start [the web interface](web-interface.md) with `cdlbib web`.

1. In the **Library** view, find the entry ([Search the library](searching.md)) and
   select its row. The entry opens beside the list.
2. Press "Edit". The view shows a box with the entry's BibTeX text.
3. Change the text and press "Preview". The preview shows the key, the status now, the
   status after saving, the changed lines, and the house-format findings.
4. Press "Save". The page says under the "Save" button:

   ```text
   Save writes exactly the text that was previewed. Editing the text again needs a new preview.
   ```

For `MannEtal11`, with the last page changed from 12897 to 12899, the preview read:

```text
Key
MannEtal11
Status now
pending
Status after saving
pending
Changes
--- MannEtal11
+++ MannEtal11
@@ -3,7 +3,7 @@
 	Doi = {10.1073/pnas.1015174108},
 	Journal = {Proceedings of the National Academy of Sciences, {USA}},
 	Number = {31},
-	Pages = {12893--12897},
+	Pages = {12893--12899},
 	Title = {Oscillatory patterns in temporal lobe reveal context reinstatement during memory search},
 	Volume = {108},
 	Year = {2011}}
House format findings (0)
```

After "Save", the page reported the save and where the file as it was before the save is
kept:

```text
Saved MannEtal11.
The file as it was: ~/demo/library/.bibcheck/edits/20261005T094425.387353Z-cdl.bib
```

The screenshot shows a preview in which the entry `Game62` has the status "needs review"
now and "pending" after saving, and in which the format checker has one finding:

![The edit view of the web interface for Game62: the entry's BibTeX text in a box on the left with the buttons Preview, Save and Cancel; on the right the preview with "Status now: needs review", "Status after saving: pending", a diff in which "Pages = {1--11}" is replaced by "Pages = {1-11}", and one house-format finding that the format checker would write the pages as 1--11](../media/web-edit-preview.png)

The preview says of such findings:

```text
Format findings do not stop a save; they are checked again before a send.
```

"New entry", beside the search box of the **Library** view, opens the same view with an
empty box for one new entry with its key.

This recording shows a search, an entry and its issues, an edit and its preview:

![Recording of the web interface: typing "games factorial" in the search box leaves one entry, Game62; selecting it opens the entry, and the Issues tab shows "volume: missing evidence or mismatch" with a table comparing the entry with the Crossref record; "Edit" opens the entry's text, and "Preview" shows the changed pages line and one house-format finding](../media/web-demo.gif)

To make the recording again from a development checkout, run
`.venv/bin/python scripts/capture_web.py --gif`. It needs the development dependencies
`playwright` (with Chromium) and `pytest`, and `ffmpeg`.
