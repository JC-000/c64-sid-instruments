"""sidmatch: audio feature extraction and fitness for SID instrument matching."""

from .features import FeatureVec, extract
from .fitness import distance

__all__ = ["FeatureVec", "extract", "distance"]
