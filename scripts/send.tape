# Screencast "send": check a change and send it as a pull request.
#
# This tape runs a real `cdlbib send`. It pushes a branch to the fork of the
# logged-in GitHub user and opens a pull request into the repository the
# checkout was cloned from (or its parent, when that is a fork).
# scripts/make_screencasts.sh records it only when asked for by name, with its
# confirmation flag, from the checkout named in CDLBIB_SCREENCAST_CHECKOUT,
# which must already hold the edit to cdl.bib that is to be sent.

Set Shell bash
Set FontSize 16
Set Width 1100
Set Height 640
Set Padding 20
Set TypingSpeed 40ms

Type 'cdlbib send --summary "Fix the page range of one entry"'
Enter
Wait+Screen@600s /(you are now on branch|not sent|Create one now)/
Sleep 5s
