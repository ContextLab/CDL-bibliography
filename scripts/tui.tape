# Screencast "tui": the terminal interface. A search, an entry's evidence, an edit with
# its preview, and an addition by DOI. Run by scripts/make_screencasts.sh inside a
# temporary folder: CDLBIB_LIBRARY names a small library there whose response cache
# holds saved lookup responses, HOME is a folder there, and the network is refused.

Set Shell bash
Set FontSize 13
Set Width 1160
Set Height 620
Set Padding 8
Set Framerate 5
Set TypingSpeed 80ms

Hide
Type "clear && cdlbib tui"
Enter
Wait+Screen@120s /idle/
Show
Sleep 1.5s

# search
Type "/"
Type "zoller"
Sleep 1.5s
Enter

# the entry's evidence
Type "dd"
Sleep 3s

# edit: volume 28 -> 27, previewed, closed without saving
Type "e"
Sleep 1s
PageDown
Up
Ctrl+E
Left 2
Backspace
Type "7"
Ctrl+P
Wait+Screen@60s /Previewed/
Sleep 3s
Escape
Sleep 1s
Type "y"
Sleep 500ms

# add by DOI
Type "3"
Sleep 1s
Escape
Sleep 700ms
Right
Sleep 500ms
Enter
Sleep 500ms
Type "10.1037/h0041332"
Enter
Wait+Screen@120s /Proposal 1 of 1/
Sleep 3s
Type "a"
Wait+Screen@60s /Added: Game62/
Sleep 1s
Escape
Sleep 700ms
Type "1"
Sleep 3s
Ctrl+Q
Sleep 500ms
