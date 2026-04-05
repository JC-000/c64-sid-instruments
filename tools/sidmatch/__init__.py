"""sidmatch: SID instrument rendering, feature extraction, and matching."""

__version__ = "0.1.0"

from .features import FeatureVec, extract
from .fitness import distance

__all__ = ["FeatureVec", "extract", "distance"]
