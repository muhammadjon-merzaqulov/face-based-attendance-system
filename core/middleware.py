import time
import logging

logger = logging.getLogger(__name__)

class MetricsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start_time = time.time()
        response = self.get_response(request)
        delay_ms = (time.time() - start_time) * 1000
        
        if "mark_attendance" in request.path or "join" in request.path:
            logger.info(f"[NETWORK METRIC] Request to {request.path} took {delay_ms:.2f} ms")
            
        return response
