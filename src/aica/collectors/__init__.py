"""Evidence collectors for Azure, GitHub, telemetry, and replay fixtures."""

from aica.collectors.azure import AzureRestClient
from aica.collectors.base import CollectedEvidence, CollectionRequest, Collector

__all__ = ["AzureRestClient", "CollectedEvidence", "CollectionRequest", "Collector"]
