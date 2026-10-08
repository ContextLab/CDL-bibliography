# Release checklist

The manual steps for building `cdlbib` and uploading it to PyPI. Every step is run by
hand; nothing here is automated. The version number is the `version` line in
`pyproject.toml`.

The output shown was recorded on October 2, 2026 with `build 1.6.1` and `twine 7.0.0`.
Version 2.0.0 was built and uploaded by these steps on October 7, 2026 (in a private
temporary folder in place of `/tmp`), from the commit tagged `v2.0.0`.

- [ ] **Start from a clean checkout of the commit to release.** `git status --short`
  prints nothing.

- [ ] **Check the version.** `grep '^version' pyproject.toml` prints the version to
  release:

  ```
  version = "2.0.0"
  ```

- [ ] **Install the build tools** in a virtual environment:

  ```bash
  python3.11 -m venv /tmp/cdlbib-release
  /tmp/cdlbib-release/bin/python -m pip install --upgrade pip build twine
  ```

- [ ] **Build** the source archive and the wheel. Remove any earlier `dist/` first.

  ```bash
  rm -rf dist
  /tmp/cdlbib-release/bin/python -m build
  ```

  The last line of output:

  ```
  Successfully built cdlbib-2.0.0.tar.gz and cdlbib-2.0.0-py3-none-any.whl
  ```

- [ ] **Check the archives.**

  ```bash
  /tmp/cdlbib-release/bin/python -m twine check dist/*
  ```

  ```
  Checking dist/cdlbib-2.0.0-py3-none-any.whl: PASSED
  Checking dist/cdlbib-2.0.0.tar.gz: PASSED
  ```

- [ ] **Install the wheel in an empty environment and run it** from outside the
  checkout:

  ```bash
  python3.11 -m venv /tmp/cdlbib-wheel
  /tmp/cdlbib-wheel/bin/python -m pip install dist/*.whl
  checkout="$PWD"
  cd /tmp
  /tmp/cdlbib-wheel/bin/cdlbib --version
  /tmp/cdlbib-wheel/bin/cdlbib --library "$checkout" verify --no-citations
  cd "$checkout"
  ```

  ```
  cdlbib 2.0.0
  ```

  The second command ends with:

  ```
  format: looks good!
  looks good!
  ```

- [ ] **Upload.** `twine` asks for a PyPI API token. With the user name `__token__`, it reads
  a token stored in the system keychain under the service `https://upload.pypi.org/legacy/`
  and the account `__token__` instead of asking.

  ```bash
  /tmp/cdlbib-release/bin/python -m twine upload dist/*
  ```

  A version can be uploaded once: PyPI refuses a second upload of the same file name, and
  the project page shows `docs/pypi.md` as it was in the uploaded files.

- [ ] **Install from PyPI in an empty environment** and run it:

  ```bash
  python3.11 -m venv /tmp/cdlbib-pypi
  /tmp/cdlbib-pypi/bin/python -m pip install --no-cache-dir cdlbib
  /tmp/cdlbib-pypi/bin/cdlbib --version
  ```

- [ ] **Remove the build output**: `rm -rf dist build`.
