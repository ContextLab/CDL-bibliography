# Recorded by scripts/record_add.py in an isolated library with frozen responses.
# The real EDITOR executable omits the optional Number field before acceptance.
Set Shell bash
Set FontSize 15
Set Width 1320
Set Height 960
Set Padding 20
Set TypingSpeed 45ms
Set PlaybackSpeed 0.8
Type "cdlbib add 10.1002/tea.3660271011"
Enter
Wait+Line@60s /Your choice \[a\/e\/s\/A\/q\]/
Sleep 3s
Type "e"
Enter
Wait+Screen@60s /Unfilled number: Removed in editor/
Wait+Line@60s /Your choice \[a\/e\/s\/A\/q\]/
Sleep 3s
Type "a"
Enter
Wait+Screen@60s /Added: Zoll90/
Sleep 4s
