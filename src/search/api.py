"""A-owned JSON/multipart adapter over the shared FastAPI app; C files stay intact."""
from __future__ import annotations

import base64
import json
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.exceptions import HTTPException
from pydantic import ValidationError
from src.common.schemas import SearchRequest


class SearchTransport:
    def __init__(self, app, max_body_bytes=8*1024*1024):
        self.app = app; self.max_body_bytes = max_body_bytes

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['path'] != '/api/search' or scope['method'] != 'POST':
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            body.extend(message.get('body', b''))
            if len(body) > self.max_body_bytes:
                return await JSONResponse({'detail': 'search request body too large'}, 413)(scope, receive, send)
            if not message.get('more_body', False):
                break
        async def original_body():
            return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
        content_type = dict(scope.get('headers', [])).get(b'content-type', b'').decode()
        try:
            if content_type.startswith('multipart/form-data'):
                request = Request(scope, original_body)
                async with request.form() as form:
                    if set(form)-{'query_text', 'query_image', 'top_k'}:
                        raise ValueError('unknown multipart field')
                    payload = {}
                    for key in ('query_text', 'top_k'):
                        if key in form:
                            value = form[key]
                            if not isinstance(value, str):
                                raise ValueError('text/top_k form field must be text')
                            payload[key] = int(value) if key == 'top_k' else value
                    if 'query_image' in form:
                        image = form['query_image']
                        payload['query_image'] = base64.b64encode(await image.read()).decode() if hasattr(image, 'read') else image
            elif content_type.startswith('application/json'):
                payload = json.loads(body)
            else:
                raise ValueError('use application/json or multipart/form-data')
            if not isinstance(payload, dict):
                raise ValueError('search input must be an object')
            if 'top_k' in payload and (isinstance(payload['top_k'], bool) or not isinstance(payload['top_k'], int)):
                raise ValueError('top_k must be an integer')
            SearchRequest.model_validate(payload)
        except (ValueError, TypeError, ValidationError, HTTPException) as error:
            return await JSONResponse({'detail': str(error)}, 422)(scope, receive, send)
        forwarded = json.dumps(payload).encode(); new_scope = dict(scope)
        new_scope['headers'] = [(k, v) for k, v in scope.get('headers', []) if k not in (b'content-type', b'content-length')]
        new_scope['headers'] += [(b'content-type', b'application/json'), (b'content-length', str(len(forwarded)).encode())]
        async def translated_body():
            return {'type': 'http.request', 'body': forwarded, 'more_body': False}
        return await self.app(new_scope, translated_body, send)


def create_app(cfg=None, search_service=None):
    from src.serving.main import create_app as shared_app
    return SearchTransport(shared_app(cfg=cfg, search_service=search_service))


app = create_app()
