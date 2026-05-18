#!/usr/bin/env bash
# Regenerate gRPC Python stubs from proto/doccontext.proto
# into src/doccontext/proto_gen/.
#
# Usage: ./scripts/generate_proto.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

OUT="src/doccontext/proto_gen"
mkdir -p "$OUT"

uv run python -m grpc_tools.protoc \
    --proto_path=proto \
    --python_out="$OUT" \
    --grpc_python_out="$OUT" \
    --pyi_out="$OUT" \
    proto/doccontext.proto

# grpc_tools emits imports as "import doccontext_pb2" which breaks when the
# generated files live inside a package. Rewrite to a package-relative import.
python - <<'PY'
import pathlib, re
p = pathlib.Path("src/doccontext/proto_gen/doccontext_pb2_grpc.py")
src = p.read_text()
src = re.sub(
    r"^import doccontext_pb2 as doccontext__pb2$",
    "from doccontext.proto_gen import doccontext_pb2 as doccontext__pb2",
    src,
    flags=re.MULTILINE,
)
p.write_text(src)
PY

echo "Generated stubs in $OUT"
