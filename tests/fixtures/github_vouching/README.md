# Answers of api.github.com for `tests/test_pull_request_vouching.py`

Every file here is an answer GitHub gave, recorded on October 8, 2026 with `gh api` for the
repository `ContextLab/CDL-bibliography`, and is stored as it was received.

|File|Request|What it shows|
|-|-|-|
|`permission-jeremymanning.json`|`GET /repos/ContextLab/CDL-bibliography/collaborators/jeremymanning/permission`|`permission: admin`|
|`permission-octocat.json`|the same for `octocat`|`permission: read` (no access beyond what anyone has to a public repository)|
|`permission-paxtonfitzpatrick.json`|the same for `paxtonfitzpatrick`|`permission: read`|
|`reviews-pull-107.json`|`GET /repos/ContextLab/CDL-bibliography/pulls/107/reviews?per_page=100`|no reviews (`[]`)|
|`reviews-pull-16.json`|the same for pull request 16|one `APPROVED` review by `jeremymanning`, for the head commit|
|`reviews-pull-14.json`|the same for pull request 14|`CHANGES_REQUESTED` by `jeremymanning` for an earlier commit, fifteen `COMMENTED` reviews by the author, then `APPROVED` by `jeremymanning` for the head commit|
|`reviews-pull-51.json`|the same for pull request 51|one `CHANGES_REQUESTED` review|
|`reviews-pull-54.json`|the same for pull request 54|three `COMMENTED` reviews, none that decides|
|`pull-N.json`|`GET /repos/ContextLab/CDL-bibliography/pulls/N`, reduced with `--jq` to `number`, `author` (`.user.login`), `head_sha` (`.head.sha`) and `state`|the author and head commit of each of those pull requests|

Recorded cases: an approval of the present head; an approval that followed a request for
changes; a request for changes alone; comments alone; no reviews; an approval judged against a
commit that is not the one it was given for (the reviews of pull request 14, asked about the
commit of its earlier review); admin and read permissions.

Constructed cases. The repository has no dismissed review, no approval that a later request
for changes by the same account followed, and no approval by an account without write access.
The tests build those three in memory from the recorded approval of pull request 16, changing
only what the case is about: the `state` (to `DISMISSED`, the state GitHub gives a dismissed
review); a second review appended as a copy of the first with the state `CHANGES_REQUESTED`
and a later `submitted_at`; and the `user` replaced by the `user` object of
`permission-paxtonfitzpatrick.json`. No file here holds a constructed answer.
