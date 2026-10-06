# The CI job's Linux machine, on this computer

`Dockerfile` builds an image like the runner of the `test` job in
`.github/workflows/autocheck.yml`: Ubuntu 24.04 with the apt packages the job installs,
Python 3.11 and 3.13 with the job's pip installs and Playwright's Chromium, and a user
(`runner`) who is not root. `run.sh` runs a command there in a checkout made as
`actions/checkout` makes it: one commit deep (`git clone --depth 1`) of this repository's
HEAD, copied into the user's home, with the package installed from it and `CROSSREF_MAILTO`
read from `.github/actions/crossref-contact/mailto.txt`.

    scripts/ci-linux/run.sh                      # the job's two commands, Python 3.13, 2 CPUs
    scripts/ci-linux/run.sh -p 3.11              # the same with Python 3.11
    scripts/ci-linux/run.sh -w python -m pytest -q tests/test_writer_record.py
                                                 # one file, with the uncommitted changes too
    scripts/ci-linux/run.sh -e CDLBIB_TEST_TEX_INSTALL=1 python -m pytest -q -rs tests/test_texinstall.py
    scripts/ci-linux/run.sh -s some-script.sh    # a shell script of this computer, run there

The image is built on the first run (about 2.5 GB, mostly TeX Live); build it again after the
workflow's package lists change:

    docker build -t cdlbib-ci-linux -f scripts/ci-linux/Dockerfile .

Where it differs from GitHub's runner: the processor is this computer's (linux/arm64 on an
Apple-silicon Mac; GitHub's is x86_64), the Pythons are uv's standalone builds rather than
`actions/setup-python`'s, the file system is Docker's overlay rather than ext4 on a disk, and
none of the runner image's other programs are there. Nothing is written to this computer:
the checkout is a temporary clone, mounted read-only and removed afterwards.
