# Screencast "check": the format check, then the offline verification status.
# Run by scripts/make_screencasts.sh from inside a scratch copy of the library
# whose saved results have already been restored. cdlbib must be on PATH.

Set Shell bash
Set FontSize 16
Set Width 1100
Set Height 560
Set Padding 20
Set TypingSpeed 40ms

Type "cdlbib verify --no-citations"
Enter
Wait+Screen@120s /looks good!\n.*looks good!/
Sleep 2s

Type "cdlbib crossref status cdl.bib"
Enter
Wait+Screen@120s /entries: /
Sleep 4s
