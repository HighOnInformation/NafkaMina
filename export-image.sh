#!/usr/bin/env bash
# export-image.sh — build the dirdiff image and export it for air-gap transfer
#
# Usage:
#   bash export-image.sh               # builds + saves dirdiff.tar.gz
#   bash export-image.sh --load        # loads dirdiff.tar.gz on target machine

set -euo pipefail

IMAGE="dirdiff"
TARBALL="dirdiff.tar.gz"

if [[ "${1:-}" == "--load" ]]; then
    echo "Loading $TARBALL into Docker..."
    docker load < "$TARBALL"
    echo "Done. Run with:"
    echo "  docker run --rm \\"
    echo "    -v /path/to/dir_a:/work/a:ro \\"
    echo "    -v /path/to/dir_b:/work/b:ro \\"
    echo "    -v /path/to/config.json:/work/config.json:ro \\"
    echo "    -v /path/to/output:/out \\"
    echo "    $IMAGE /work/a /work/b -c /work/config.json -o /out/report.md -H /out/report.html"
    exit 0
fi

echo "Building Docker image: $IMAGE"
docker build --no-cache -t "$IMAGE" .

echo "Exporting to $TARBALL (this may take a moment)..."
docker save "$IMAGE" | gzip > "$TARBALL"

SIZE=$(du -sh "$TARBALL" | cut -f1)
echo ""
echo "Done. Transfer $TARBALL ($SIZE) to the air-gapped machine, then run:"
echo "  bash export-image.sh --load"
