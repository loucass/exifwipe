import sys
from pathlib import Path

# make the exifwipe package (parent dir) importable from tests
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
