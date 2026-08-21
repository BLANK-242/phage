"""ARCHIVIST — semantic signature memory (recognition + signature write).

Public API:
    recognize(...) -> RecognitionResult   # pre-fire gate
    record(...) -> Optional[str]          # post-triage signature write

See memory.py for the mechanism and the non-obvious signature-text symmetry
constraint (3.1 of the build brief).
"""

from phage.archivist.memory import (
    RECOGNITION_DISTANCE_THRESHOLD,
    RecognitionResult,
    record,
    recognize,
)

__all__ = [
    "RECOGNITION_DISTANCE_THRESHOLD",
    "RecognitionResult",
    "record",
    "recognize",
]
