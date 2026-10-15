# syntax=docker/dockerfile:1
#
# edbo backend image — FastAPI + the edbo Bayesian-optimization core.
#
# Build context is the REPOSITORY ROOT (see webapp/docker-compose.yml), because
# this image installs the repository-root `edbo` algorithm package via setup.py.
#
#   docker build -f webapp/backend/Dockerfile -t edbo-backend .
#
FROM python:3.9-slim

# NOTE: there is deliberately no apt-get / build-essential step here. Every
# dependency below ships a self-contained manylinux wheel, so no system packages
# are required:
#   * PyTorch bundles its own OpenMP runtime (torch/lib/libgomp-*.so.1)
#   * matplotlib bundles FreeType; the Agg backend needs no X/GL libraries
#   * RDKit bundles its third-party libraries
#   * pyclustering declares no C extensions in setup.py (pure-Python install)
# This also means the build never contacts a Debian mirror — important on
# networks where deb.debian.org is blocked or unreachable.
#
# If you ever do need extra system libraries, add the block back — and on a
# restricted network point it at a reachable mirror first:
#
#   ARG APT_MIRROR=mirrors.aliyun.com
#   RUN for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.sources; do \
#         [ -f "$f" ] && sed -i "s|deb.debian.org|${APT_MIRROR}|g; s|http://|https://|g" "$f"; \
#       done; \
#       apt-get -o Acquire::Retries=5 update \
#       && apt-get -o Acquire::Retries=5 install -y --no-install-recommends libgomp1 libgl1 \
#       && rm -rf /var/lib/apt/lists/*

# Package indexes are overridable for slow or restricted networks, e.g.
#   docker compose build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=60 \
    PIP_RETRIES=5 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    MPLBACKEND=Agg

WORKDIR /srv

# pip downloads go into a BuildKit cache mount (outside the image layers), so a
# rebuild after a dependency change does not re-download everything.
#
# 1) CPU-only PyTorch first: pin the "+cpu" local build so pip cannot pick the
#    ~2.5 GB CUDA wheel that also exists on PyPI. Its dependencies still come
#    from the regular package index.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --index-url "${PIP_INDEX_URL}" --upgrade pip \
 && pip install --index-url "${TORCH_INDEX_URL}" \
                --extra-index-url "${PIP_INDEX_URL}" \
                "torch==2.2.2+cpu"

# 2) Web framework + the rest of the algorithm runtime.
COPY webapp/backend/requirements.docker.txt /tmp/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r /tmp/requirements.txt

# 3) Install edbo without its 2019-era pinned deps (already provided in step 1/2).
COPY edbo /srv/edbo
COPY setup.py /srv/setup.py
COPY README.md /srv/README.md
RUN pip install --no-deps /srv

# 4) The FastAPI application.
COPY webapp/backend /srv/backend
WORKDIR /srv/backend

# data/ holds the SQLite DB, dill pickles and descriptor CSVs; docker-compose
# mounts a named volume here so state survives rebuilds.
RUN mkdir -p /srv/backend/data

EXPOSE 8100

# Single worker on purpose: the optimizer LRU cache, per-project locks and the
# FastAPI BackgroundTasks all live inside this process. Do not add --workers N.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100", "--workers", "1"]
