from drf_spectacular.extensions import OpenApiAuthenticationExtension


class SessionAuthentication401Scheme(OpenApiAuthenticationExtension):
    target_class = "apps.accounts.authentication.SessionAuthentication401"
    name = "sessionAuth"

    def get_security_definition(self, auto_schema):  # type: ignore[no-untyped-def]
        return {"type": "apiKey", "in": "cookie", "name": "okp_session"}
