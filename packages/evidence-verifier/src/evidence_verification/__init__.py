"""Shared dependency-light source verification contract."""
from .models import (Source, Span, Claim, SourceReview, DimensionCheck, Calibration,
                     VerificationResult, BoundVerificationResult, EnumerationResult, CoverageResult, digest,
                     ENGINE_VERSION, METHOD_VERSION)
from .verifier import EvidenceVerifier
from .coverage import enumerate_source_assertions, align_coverage

__all__=['Source','Span','Claim','SourceReview','DimensionCheck','Calibration','VerificationResult',
         'BoundVerificationResult','EnumerationResult','CoverageResult','EvidenceVerifier','enumerate_source_assertions',
         'align_coverage','digest','ENGINE_VERSION','METHOD_VERSION']
