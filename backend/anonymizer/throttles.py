from rest_framework.throttling import AnonRateThrottle


class LocalUploadThrottle(AnonRateThrottle):
    """Protect CPU-heavy local processing endpoints from accidental bursts."""

    scope = "uploads"

    def get_cache_key(self, request, view):
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return None
        return super().get_cache_key(request, view)
