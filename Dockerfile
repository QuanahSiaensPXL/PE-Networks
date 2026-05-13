# syntax=docker/dockerfile:1.6
# ============================================================================
# Network as Code — reproduceerbare runtime voor builder.py (en straks deploy.py)
# ============================================================================
# Build:  docker build -t network-as-code .
# Run:    docker run --rm network-as-code R1                       # default = builder
#         docker run --rm network-as-code src.builder R1 --print   # explicit module
# ----------------------------------------------------------------------------

FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="Network as Code" \
      org.opencontainers.image.description="IOS-XE baseline pipeline via SQLite, GitHub & NETCONF" \
      org.opencontainers.image.authors="Andries Soons, Quanah Siaens" \
      org.opencontainers.image.source="https://github.com/QuanahSiaensPXL/PE-Networks" \
      org.opencontainers.image.licenses="MIT"

# ---------------------------------------------------------------------------
# Systeempackages — sqlite-CLI om de DB op te bouwen, libxml2/libxslt voor lxml
# Build-only deps (gcc, dev-headers) worden in dezelfde laag verwijderd.
# ---------------------------------------------------------------------------
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        sqlite3 \
        libxml2 \
        libxslt1.1 \
        ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Non-root user voor security best-practice
# ---------------------------------------------------------------------------
RUN useradd --create-home --shell /bin/bash --uid 1000 penet
WORKDIR /app

# ---------------------------------------------------------------------------
# Dependencies eerst — eigen laag voor cache-effectiviteit
# (PyPI-wheels van lxml werken ondertussen wel met Python 3.12)
# ---------------------------------------------------------------------------
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------------------------------------
# Project-bestanden (code + payload-bronnen + DB-schema)
# .env mag NIET in de image (staat in .dockerignore)
# ---------------------------------------------------------------------------
COPY src/         ./src/
COPY fragments/   ./fragments/
COPY templates/   ./templates/
COPY db/          ./db/

# ---------------------------------------------------------------------------
# inventory.db tijdens build opbouwen → image is direct runklaar.
# Voor productie zou je dit via een volume mounten, maar voor de demo is dit
# het simpelst.
# ---------------------------------------------------------------------------
RUN sqlite3 inventory.db < db/schema.sql \
 && sqlite3 inventory.db < db/seed.sql \
 && chown -R penet:penet /app

USER penet

# ---------------------------------------------------------------------------
# ENTRYPOINT = `python -m`  → flexibel: zowel src.builder als straks src.deploy
# CMD bevat de defaults; overschrijfbaar bij `docker run`.
# ---------------------------------------------------------------------------
ENTRYPOINT ["python", "-m"]
CMD ["src.builder", "R1"]