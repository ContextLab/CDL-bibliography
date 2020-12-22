FROM contextlab/cdl-jupyter:3.7

LABEL maintainer="contextualdynamics@gmail.com"

ARG PORT=8888

ENV NOTEBOOK_PORT $PORT

RUN apt-get update --fix-missing \
    && eatmydata apt-get install -y --no-install-recommends \
        g++ \
        git \
        unzip \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && pip install \
        unidecode==1.1.1 \
        bibtexparser==1.2.0 \
        numpy \
        scholarly \
    && rm -rf ~/.cache/pip