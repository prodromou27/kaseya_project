from rest_framework.authentication import SessionAuthentication
from rest_framework.request import Request


class SessionAuthentication401(SessionAuthentication):
    """Server-side session auth (CSRF enforced for authenticated unsafe methods).

    Supplying an ``authenticate_header`` makes DRF return 401 (not 403) for anonymous requests.
    """

    def authenticate_header(self, request: Request) -> str:
        return 'Session realm="api"'
