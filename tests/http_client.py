"""Minimal ASGI HTTP client for integration checks without a running server."""

import asyncio
from urllib.parse import urlsplit


async def request(app, path, *, method="GET", body=b"", headers=()):
    address = urlsplit(path)
    incoming = asyncio.Queue()
    incoming.put_nowait({"type": "http.request", "body": body, "more_body": False})
    messages = []

    async def receive():
        return await incoming.get()

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": address.path,
        "raw_path": address.path.encode(),
        "query_string": address.query.encode(),
        "root_path": "",
        "headers": [(b"host", b"testserver"), *headers],
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 12345),
    }
    await asyncio.wait_for(app(scope, receive, send), timeout=10)
    start = next(message for message in messages if message["type"] == "http.response.start")
    content = b"".join(
        message.get("body", b"") for message in messages if message["type"] == "http.response.body"
    )
    return start["status"], dict(start["headers"]), content


def multipart(fields, files=()):
    boundary = "scene-scribe-test-boundary"
    chunks = []
    for name, value in fields.items():
        chunks += [
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        ]
    for field, name, content in files:
        chunks += [
            f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{name}"\r\nContent-Type: video/mp4\r\n\r\n'.encode(),
            content,
            b"\r\n",
        ]
    chunks += [f"--{boundary}--\r\n".encode()]
    return b"".join(chunks), [(b"content-type", f"multipart/form-data; boundary={boundary}".encode())]
