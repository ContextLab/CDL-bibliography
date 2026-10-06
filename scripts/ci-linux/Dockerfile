# A Linux machine like the `test` job of .github/workflows/autocheck.yml (ubuntu-latest):
# the same apt packages, Python 3.11 and 3.13 with the job's pip installs, and a user who is
# not root (GitHub's is `runner`). Build and run it with scripts/ci-linux/run.sh.
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8
# What the runner image already has and the job relies on (git, curl, sudo, gh), then the
# packages the workflow installs.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl git gh sudo \
      texlive-latex-base texlive-latex-recommended texlive-latex-extra \
      texlive-bibtex-extra texlive-luatex texlive-xetex biber \
      cm-super lmodern fonts-lmodern \
      ghostscript poppler-utils tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --shell /bin/bash runner \
    && echo 'runner ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/runner
# Pythons the user owns and installs into directly, as actions/setup-python gives.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv-bootstrap
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright
RUN mkdir -p /opt/python /opt/playwright /opt/seed && chown runner:runner /opt/python /opt/playwright /opt/seed
USER runner
RUN UV_PYTHON_INSTALL_DIR=/opt/python uv-bootstrap python install 3.11 3.13 \
    && for v in 3.11 3.13; do ln -s "$(ls -d /opt/python/cpython-$v.*-linux-* | head -n 1)" /opt/python/$v; \
         rm -f /opt/python/$v/lib/python$v/EXTERNALLY-MANAGED; done
# The job's pip installs (run.sh installs the package itself again, from the checkout).
COPY --chown=runner:runner pyproject.toml LICENSE /opt/seed/
COPY --chown=runner:runner docs/pypi.md /opt/seed/docs/pypi.md
COPY --chown=runner:runner src /opt/seed/src
RUN for v in 3.11 3.13; do /opt/python/$v/bin/python -m pip install --no-cache-dir --upgrade pip \
      && /opt/python/$v/bin/python -m pip install --no-cache-dir "/opt/seed[research,pdf,tui]" pytest pytest-asyncio uv playwright \
      || exit 1; done
USER root
RUN /opt/python/3.13/bin/python -m playwright install --with-deps chromium \
    && chown -R runner:runner /opt/playwright && rm -rf /var/lib/apt/lists/* /opt/seed
USER runner
WORKDIR /home/runner
