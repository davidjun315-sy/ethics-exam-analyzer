"""Single-owner deployment gate; replace with multi-user auth before sharing accounts."""
import base64
import os
import secrets
from starlette.responses import JSONResponse


def setup_security(app):
    @app.middleware('http')
    async def owner_access(request, call_next):
        if request.url.path == '/health':
            return await call_next(request)
        password = os.getenv('ACCESS_PASSWORD')
        if not password:
            if os.getenv('APP_ENV') == 'production':
                return JSONResponse({'detail': 'Configure ACCESS_PASSWORD before production access.'}, status_code=503)
            return await call_next(request)
        expected_user = os.getenv('ACCESS_USERNAME', 'owner')
        supplied_user, supplied_password = '', ''
        try:
            scheme, token = request.headers.get('authorization', '').split(' ', 1)
            if scheme.lower() == 'basic':
                supplied_user, supplied_password = base64.b64decode(token, validate=True).decode().split(':', 1)
        except (ValueError, UnicodeError):
            pass
        if not (secrets.compare_digest(supplied_user.encode(), expected_user.encode()) and
                secrets.compare_digest(supplied_password.encode(), password.encode())):
            return JSONResponse({'detail': '로그인이 필요합니다.'}, status_code=401,
                                headers={'WWW-Authenticate': 'Basic realm="Ethics exam review", charset="UTF-8"'})
        return await call_next(request)
