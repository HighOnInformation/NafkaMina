# ─────────────────────────────────────────────────────────────────────────────
# dirdiff — air-gap export image
#
# Build:
#   docker build -t dirdiff .
#
# Export to tar (for transfer to air-gapped machine):
#   docker save dirdiff | gzip > dirdiff.tar.gz
#
# Load on air-gapped machine:
#   docker load < dirdiff.tar.gz
#
# Run:
#   docker run --rm \
#     -v /path/to/dir_a:/work/a:ro \
#     -v /path/to/dir_b:/work/b:ro \
#     -v /path/to/config.json:/work/config.json:ro \
#     -v /path/to/output:/out \
#     dirdiff /work/a /work/b -c /work/config.json -o /out/report.md -H /out/report.html
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.11-slim

# Install git (required), clang-format and gcc (optional normalizers).
# All installed here so the image is self-contained with no outbound requests.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      git \
      clang-format \
      gcc \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# Create a non-root user for safer execution inside the container.
RUN useradd --create-home --shell /bin/bash dirdiff
USER dirdiff
WORKDIR /home/dirdiff

# Copy only the package and the example config — nothing else.
COPY --chown=dirdiff:dirdiff dirdiff/ ./dirdiff/
COPY --chown=dirdiff:dirdiff config.json ./config.json

# Smoke-test: verify the package imported and the help text prints.
RUN python -m dirdiff --help

# Default output directory; callers mount their own volume here.
VOLUME ["/out"]

ENTRYPOINT ["python", "-m", "dirdiff"]
CMD ["--help"]
