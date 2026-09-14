# index.md

---

# Starlette Introduction

Starlette is a lightweight [ASGI][asgi] framework/toolkit,
which is ideal for building async web services in Python.

It is production-ready, and gives you the following:

* A lightweight, low-complexity HTTP web framework.
* WebSocket support.
* In-process background tasks.
* Startup and shutdown events.
* Test client built on `httpx`.
* CORS, GZip, Static Files, Streaming responses.
* Session and Cookie support.
* 100% test coverage.
* 100% type annotated codebase.
* Few hard dependencies.
* Compatible with `asyncio` and `trio` backends.
* Great overall performance [against independent benchmarks][techempower].

## Requirements

Python 3.8+

## Installation

```shell
$ pip3 install starlette
```

You'll also want to install an ASGI server, such as [uvicorn](http://www.uvicorn.org/), [daphne](https://github.com/django/daphne/), or [hypercorn](https://pgjones.gitlab.io/hypercorn/).

```shell
$ pip3 install uvicorn
```

## Example

**example.py**:

```python
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route


async def homepage(request):
    return JSONResponse({'hello': 'world'})


app = Starlette(debug=True, routes=[
    Route('/', homepage),
])
```

Then run the application...

```shell
$ uvicorn example:app
```

For a more complete example, [see here](https://github.com/encode/starlette-example).

## Dependencies

Starlette only requires `anyio`, and the following dependencies are optional:

* [`httpx`][httpx] - Required if you want to use the `TestClient`.
* [`jinja2`][jinja2] - Required if you want to use `Jinja2Templates`.
* [`python-multipart`][python-multipart] - Required if you want to support form parsing, with `request.form()`.
* [`itsdangerous`][itsdangerous] - Required for `SessionMiddleware` support.
* [`pyyaml`][pyyaml] - Required for `SchemaGenerator` support.

You can install all of these with `pip3 install starlette[full]`.

## Framework or Toolkit

Starlette is designed to be used either as a complete framework, or as
an ASGI toolkit. You can use any of its components independently.

```python
from starlette.responses import PlainTextResponse


async def app(scope, receive, send):
    assert scope['type'] == 'http'
    response = PlainTextResponse('Hello, world!')
    await response(scope, receive, send)
```

Run the `app` application in `example.py`:

```shell
$ uvicorn example:app
INFO: Started server process [11509]
INFO: Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

Run uvicorn with `--reload` to enable auto-reloading on code changes.

## Modularity

The modularity that Starlette is designed on promotes building re-usable
components that can be shared between any ASGI framework. This should enable
an ecosystem of shared middleware and mountable applications.

The clean API separation also means it's easier to understand each component
in isolation.

---

# applications.md

Starlette includes an application class `Starlette` that nicely ties together all of
its other functionality.

```python
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route, Mount, WebSocketRoute
from starlette.staticfiles import StaticFiles


def homepage(request):
    return PlainTextResponse('Hello, world!')

def user_me(request):
    username = "John Doe"
    return PlainTextResponse('Hello, %s!' % username)

def user(request):
    username = request.path_params['username']
    return PlainTextResponse('Hello, %s!' % username)

async def websocket_endpoint(websocket):
    await websocket.accept()
    await websocket.send_text('Hello, websocket!')
    await websocket.close()

def startup():
    print('Ready to go')


routes = [
    Route('/', homepage),
    Route('/user/me', user_me),
    Route('/user/{username}', user),
    WebSocketRoute('/ws', websocket_endpoint),
    Mount('/static', StaticFiles(directory="static")),
]

app = Starlette(debug=True, routes=routes, on_startup=[startup])
```

### Instantiating the application

::: starlette.applications.Starlette
    :docstring:

### Storing state on the app instance

You can store arbitrary extra state on the application instance, using the
generic `app.state` attribute.

For example:

```python
app.state.ADMIN_EMAIL = 'admin@example.org'
```

### Accessing the app instance

Where a `request` is available (i.e. endpoints and middleware), the app is available on `request.app`.


# requests.md


Starlette includes a `Request` class that gives you a nicer interface onto
the incoming request, rather than accessing the ASGI scope and receive channel directly.

### Request

Signature: `Request(scope, receive=None)`

```python
from starlette.requests import Request
from starlette.responses import Response


async def app(scope, receive, send):
    assert scope['type'] == 'http'
    request = Request(scope, receive)
    content = '%s %s' % (request.method, request.url.path)
    response = Response(content, media_type='text/plain')
    await response(scope, receive, send)
```

Requests present a mapping interface, so you can use them in the same
way as a `scope`.

For instance: `request['path']` will return the ASGI path.

If you don't need to access the request body you can instantiate a request
without providing an argument to `receive`.

#### Method

The request method is accessed as `request.method`.

#### URL

The request URL is accessed as `request.url`.

The property is a string-like object that exposes all the
components that can be parsed out of the URL.

For example: `request.url.path`, `request.url.port`, `request.url.scheme`.

#### Headers

Headers are exposed as an immutable, case-insensitive, multi-dict.

For example: `request.headers['content-type']`

#### Query Parameters

Query parameters are exposed as an immutable multi-dict.

For example: `request.query_params['search']`

#### Path Parameters

Router path parameters are exposed as a dictionary interface.

For example: `request.path_params['username']`

#### Client Address

The client's remote address is exposed as a named two-tuple `request.client` (or `None`).

The hostname or IP address: `request.client.host`

The port number from which the client is connecting: `request.client.port`

#### Cookies

Cookies are exposed as a regular dictionary interface.

For example: `request.cookies.get('mycookie')`

Cookies are ignored in case of an invalid cookie. (RFC2109)

#### Body

There are a few different interfaces for returning the body of the request:

The request body as bytes: `await request.body()`

The request body, parsed as form data or multipart: `async with request.form() as form:`

The request body, parsed as JSON: `await request.json()`

You can also access the request body as a stream, using the `async for` syntax:

```python
from starlette.requests import Request
from starlette.responses import Response

    
async def app(scope, receive, send):
    assert scope['type'] == 'http'
    request = Request(scope, receive)
    body = b''
    async for chunk in request.stream():
        body += chunk
    response = Response(body, media_type='text/plain')
    await response(scope, receive, send)
```

If you access `.stream()` then the byte chunks are provided without storing
the entire body to memory. Any subsequent calls to `.body()`, `.form()`, or `.json()`
will raise an error.

In some cases such as long-polling, or streaming responses you might need to
determine if the client has dropped the connection. You can determine this
state with `disconnected = await request.is_disconnected()`.

#### Request Files

Request files are normally sent as multipart form data (`multipart/form-data`).

Signature: `request.form(max_files=1000, max_fields=1000)`

You can configure the number of maximum fields or files with the parameters `max_files` and `max_fields`:

```python
async with request.form(max_files=1000, max_fields=1000):
    ...
```

!!! info
    These limits are for security reasons, allowing an unlimited number of fields or files could lead to a denial of service attack by consuming a lot of CPU and memory parsing too many empty fields.

When you call `async with request.form() as form` you receive a `starlette.datastructures.FormData` which is an immutable
multidict, containing both file uploads and text input. File upload items are represented as instances of `starlette.datastructures.UploadFile`.

`UploadFile` has the following attributes:

* `filename`: An `str` with the original file name that was uploaded or `None` if its not available (e.g. `myimage.jpg`).
* `content_type`: An `str` with the content type (MIME type / media type) or `None` if it's not available (e.g. `image/jpeg`).
* `file`: A <a href="https://docs.python.org/3/library/tempfile.html#tempfile.SpooledTemporaryFile" target="_blank">`SpooledTemporaryFile`</a> (a <a href="https://docs.python.org/3/glossary.html#term-file-like-object" target="_blank">file-like</a> object). This is the actual Python file that you can pass directly to other functions or libraries that expect a "file-like" object.
* `headers`: A `Headers` object. Often this will only be the `Content-Type` header, but if additional headers were included in the multipart field they will be included here. Note that these headers have no relationship with the headers in `Request.headers`.
* `size`: An `int` with uploaded file's size in bytes. This value is calculated from request's contents, making it better choice to find uploaded file's size than `Content-Length` header. `None` if not set.

`UploadFile` has the following `async` methods. They all call the corresponding file methods underneath (using the internal `SpooledTemporaryFile`).

* `async write(data)`: Writes `data` (`bytes`) to the file.
* `async read(size)`: Reads `size` (`int`) bytes of the file.
* `async seek(offset)`: Goes to the byte position `offset` (`int`) in the file.
    * E.g., `await myfile.seek(0)` would go to the start of the file.
* `async close()`: Closes the file.

As all these methods are `async` methods, you need to "await" them.

For example, you can get the file name and the contents with:

```python
async with request.form() as form:
    filename = form["upload_file"].filename
    contents = await form["upload_file"].read()
```

!!! info
    As settled in [RFC-7578: 4.2](https://www.ietf.org/rfc/rfc7578.txt), form-data content part that contains file 
    assumed to have `name` and `filename` fields in `Content-Disposition` header: `Content-Disposition: form-data;
    name="user"; filename="somefile"`. Though `filename` field is optional according to RFC-7578, it helps 
    Starlette to differentiate which data should be treated as file. If `filename` field was supplied, `UploadFile` 
    object will be created to access underlying file, otherwise form-data part will be parsed and available as a raw 
    string.

#### Application

The originating Starlette application can be accessed via `request.app`.

#### Other state

If you want to store additional information on the request you can do so
using `request.state`.

For example:

`request.state.time_started = time.time()`


# responses.md


Starlette includes a few response classes that handle sending back the
appropriate ASGI messages on the `send` channel.

### Response

Signature: `Response(content, status_code=200, headers=None, media_type=None)`

* `content` - A string or bytestring.
* `status_code` - An integer HTTP status code.
* `headers` - A dictionary of strings.
* `media_type` - A string giving the media type. eg. "text/html"

Starlette will automatically include a Content-Length header. It will also
include a Content-Type header, based on the media_type and appending a charset
for text types, unless a charset has already been specified in the `media_type`.

Once you've instantiated a response, you can send it by calling it as an
ASGI application instance.

```python
from starlette.responses import Response


async def app(scope, receive, send):
    assert scope['type'] == 'http'
    response = Response('Hello, world!', media_type='text/plain')
    await response(scope, receive, send)
```
#### Set Cookie

Starlette provides a `set_cookie` method to allow you to set cookies on the response object.

Signature: `Response.set_cookie(key, value, max_age=None, expires=None, path="/", domain=None, secure=False, httponly=False, samesite="lax")`

* `key` - A string that will be the cookie's key.
* `value` - A string that will be the cookie's value.
* `max_age` - An integer that defines the lifetime of the cookie in seconds. A negative integer or a value of `0` will discard the cookie immediately. `Optional`
* `expires` - Either an integer that defines the number of seconds until the cookie expires, or a datetime. `Optional`
* `path` - A string that specifies the subset of routes to which the cookie will apply. `Optional`
* `domain` - A string that specifies the domain for which the cookie is valid. `Optional`
* `secure` - A bool indicating that the cookie will only be sent to the server if request is made using SSL and the HTTPS protocol. `Optional`
* `httponly` - A bool indicating that the cookie cannot be accessed via JavaScript through `Document.cookie` property, the `XMLHttpRequest` or `Request` APIs. `Optional`
* `samesite` - A string that specifies the samesite strategy for the cookie. Valid values are `'lax'`, `'strict'` and `'none'`. Defaults to `'lax'`. `Optional`

#### Delete Cookie

Conversely, Starlette also provides a `delete_cookie` method to manually expire a set cookie.

Signature: `Response.delete_cookie(key, path='/', domain=None)`


### HTMLResponse

Takes some text or bytes and returns an HTML response.

```python
from starlette.responses import HTMLResponse


async def app(scope, receive, send):
    assert scope['type'] == 'http'
    response = HTMLResponse('<html><body><h1>Hello, world!</h1></body></html>')
    await response(scope, receive, send)
```

### PlainTextResponse

Takes some text or bytes and returns a plain text response.

```python
from starlette.responses import PlainTextResponse


async def app(scope, receive, send):
    assert scope['type'] == 'http'
    response = PlainTextResponse('Hello, world!')
    await response(scope, receive, send)
```

### JSONResponse

Takes some data and returns an `application/json` encoded response.

```python
from starlette.responses import JSONResponse


async def app(scope, receive, send):
    assert scope['type'] == 'http'
    response = JSONResponse({'hello': 'world'})
    await response(scope, receive, send)
```

#### Custom JSON serialization

If you need fine-grained control over JSON serialization, you can subclass
`JSONResponse` and override the `render` method.

For example, if you wanted to use a third-party JSON library such as
[orjson](https://pypi.org/project/orjson/):

```python
from typing import Any

import orjson
from starlette.responses import JSONResponse


class OrjsonResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return orjson.dumps(content)
```

In general you *probably* want to stick with `JSONResponse` by default unless
you are micro-optimising a particular endpoint or need to serialize non-standard
object types.

### RedirectResponse

Returns an HTTP redirect. Uses a 307 status code by default.

```python
from starlette.responses import PlainTextResponse, RedirectResponse


async def app(scope, receive, send):
    assert scope['type'] == 'http'
    if scope['path'] != '/':
        response = RedirectResponse(url='/')
    else:
        response = PlainTextResponse('Hello, world!')
    await response(scope, receive, send)
```

### StreamingResponse

Takes an async generator or a normal generator/iterator and streams the response body.

```python
from starlette.responses import StreamingResponse
import asyncio


async def slow_numbers(minimum, maximum):
    yield '<html><body><ul>'
    for number in range(minimum, maximum + 1):
        yield '<li>%d</li>' % number
        await asyncio.sleep(0.5)
    yield '</ul></body></html>'


async def app(scope, receive, send):
    assert scope['type'] == 'http'
    generator = slow_numbers(1, 10)
    response = StreamingResponse(generator, media_type='text/html')
    await response(scope, receive, send)
```

Have in mind that <a href="https://docs.python.org/3/glossary.html#term-file-like-object" target="_blank">file-like</a> objects (like those created by `open()`) are normal iterators. So, you can return them directly in a `StreamingResponse`.

### FileResponse

Asynchronously streams a file as the response.

Takes a different set of arguments to instantiate than the other response types:

* `path` - The filepath to the file to stream.
* `headers` - Any custom headers to include, as a dictionary.
* `media_type` - A string giving the media type. If unset, the filename or path will be used to infer a media type.
* `filename` - If set, this will be included in the response `Content-Disposition`.
* `content_disposition_type` - will be included in the response `Content-Disposition`. Can be set to "attachment" (default) or "inline".

File responses will include appropriate `Content-Length`, `Last-Modified` and `ETag` headers.

```python
from starlette.responses import FileResponse


async def app(scope, receive, send):
    assert scope['type'] == 'http'
    response = FileResponse('statics/favicon.ico')
    await response(scope, receive, send)
```

## Third party responses

#### [EventSourceResponse](https://github.com/sysid/sse-starlette)

A response class that implements [Server-Sent Events](https://html.spec.whatwg.org/multipage/server-sent-events.html). It enables event streaming from the server to the client without the complexity of websockets.

#### [baize.asgi.FileResponse](https://baize.aber.sh/asgi#fileresponse)

As a smooth replacement for Starlette [`FileResponse`](https://www.starlette.io/responses/#fileresponse), it will automatically handle [Head method](https://developer.mozilla.org/en-US/docs/Web/HTTP/Methods/HEAD) and [Range requests](https://developer.mozilla.org/en-US/docs/Web/HTTP/Range_requests).


# websockets.md


Starlette includes a `WebSocket` class that fulfils a similar role
to the HTTP request, but that allows sending and receiving data on a websocket.

### WebSocket

Signature: `WebSocket(scope, receive=None, send=None)`

```python
from starlette.websockets import WebSocket


async def app(scope, receive, send):
    websocket = WebSocket(scope=scope, receive=receive, send=send)
    await websocket.accept()
    await websocket.send_text('Hello, world!')
    await websocket.close()
```

WebSockets present a mapping interface, so you can use them in the same
way as a `scope`.

For instance: `websocket['path']` will return the ASGI path.

#### URL

The websocket URL is accessed as `websocket.url`.

The property is actually a subclass of `str`, and also exposes all the
components that can be parsed out of the URL.

For example: `websocket.url.path`, `websocket.url.port`, `websocket.url.scheme`.

#### Headers

Headers are exposed as an immutable, case-insensitive, multi-dict.

For example: `websocket.headers['sec-websocket-version']`

#### Query Parameters

Query parameters are exposed as an immutable multi-dict.

For example: `websocket.query_params['search']`

#### Path Parameters

Router path parameters are exposed as a dictionary interface.

For example: `websocket.path_params['username']`

### Accepting the connection

* `await websocket.accept(subprotocol=None, headers=None)`

### Sending data

* `await websocket.send_text(data)`
* `await websocket.send_bytes(data)`
* `await websocket.send_json(data)`

JSON messages default to being sent over text data frames, from version 0.10.0 onwards.
Use `websocket.send_json(data, mode="binary")` to send JSON over binary data frames.

### Receiving data

* `await websocket.receive_text()`
* `await websocket.receive_bytes()`
* `await websocket.receive_json()`

May raise `starlette.websockets.WebSocketDisconnect()`.

JSON messages default to being received over text data frames, from version 0.10.0 onwards.
Use `websocket.receive_json(data, mode="binary")` to receive JSON over binary data frames.

### Iterating data

* `websocket.iter_text()`
* `websocket.iter_bytes()`
* `websocket.iter_json()`

Similar to `receive_text`, `receive_bytes`, and `receive_json` but returns an
async iterator.

```python hl_lines="7-8"
from starlette.websockets import WebSocket


async def app(scope, receive, send):
    websocket = WebSocket(scope=scope, receive=receive, send=send)
    await websocket.accept()
    async for message in websocket.iter_text():
        await websocket.send_text(f"Message text was: {message}")
    await websocket.close()
```

When `starlette.websockets.WebSocketDisconnect` is raised, the iterator will exit.

### Closing the connection

* `await websocket.close(code=1000, reason=None)`

### Sending and receiving messages

If you need to send or receive raw ASGI messages then you should use
`websocket.send()` and `websocket.receive()` rather than using the raw `send` and
`receive` callables. This will ensure that the websocket's state is kept
correctly updated.

* `await websocket.send(message)`
* `await websocket.receive()`

### Send Denial Response

If you call `websocket.close()` before calling `websocket.accept()` then
the server will automatically send a HTTP 403 error to the client.

If you want to send a different error response, you can use the
`websocket.send_denial_response()` method. This will send the response
and then close the connection.

* `await websocket.send_denial_response(response)`

This requires the ASGI server to support the WebSocket Denial Response
extension. If it is not supported a `RuntimeError` will be raised.


# routing.md

## HTTP Routing

Starlette has a simple but capable request routing system. A routing table
is defined as a list of routes, and passed when instantiating the application.

```python
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route


async def homepage(request):
    return PlainTextResponse("Homepage")

async def about(request):
    return PlainTextResponse("About")


routes = [
    Route("/", endpoint=homepage),
    Route("/about", endpoint=about),
]

app = Starlette(routes=routes)
```

The `endpoint` argument can be one of:

* A regular function or async function, which accepts a single `request`
argument and which should return a response.
* A class that implements the ASGI interface, such as Starlette's [HTTPEndpoint](endpoints.md#httpendpoint).

## Path Parameters

Paths can use URI templating style to capture path components.

```python
Route('/users/{username}', user)
```
By default this will capture characters up to the end of the path or the next `/`.

You can use convertors to modify what is captured. The available convertors are:

* `str` returns a string, and is the default.
* `int` returns a Python integer.
* `float` returns a Python float.
* `uuid` return a Python `uuid.UUID` instance.
* `path` returns the rest of the path, including any additional `/` characters.

Convertors are used by prefixing them with a colon, like so:

```python
Route('/users/{user_id:int}', user)
Route('/floating-point/{number:float}', floating_point)
Route('/uploaded/{rest_of_path:path}', uploaded)
```

If you need a different converter that is not defined, you can create your own.
See below an example on how to create a `datetime` convertor, and how to register it:

```python
from datetime import datetime

from starlette.convertors import Convertor, register_url_convertor


class DateTimeConvertor(Convertor):
    regex = "[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(.[0-9]+)?"

    def convert(self, value: str) -> datetime:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")

    def to_string(self, value: datetime) -> str:
        return value.strftime("%Y-%m-%dT%H:%M:%S")

register_url_convertor("datetime", DateTimeConvertor())
```

After registering it, you'll be able to use it as:

```python
Route('/history/{date:datetime}', history)
```

Path parameters are made available in the request, as the `request.path_params`
dictionary.

```python
async def user(request):
    user_id = request.path_params['user_id']
    ...
```

## Handling HTTP methods

Routes can also specify which HTTP methods are handled by an endpoint:

```python
Route('/users/{user_id:int}', user, methods=["GET", "POST"])
```

By default function endpoints will only accept `GET` requests, unless specified.

## Submounting routes

In large applications you might find that you want to break out parts of the
routing table, based on a common path prefix.

```python
routes = [
    Route('/', homepage),
    Mount('/users', routes=[
        Route('/', users, methods=['GET', 'POST']),
        Route('/{username}', user),
    ])
]
```

This style allows you to define different subsets of the routing table in
different parts of your project.

```python
from myproject import users, auth

routes = [
    Route('/', homepage),
    Mount('/users', routes=users.routes),
    Mount('/auth', routes=auth.routes),
]
```

You can also use mounting to include sub-applications within your Starlette
application. For example...

```python
# This is a standalone static files server:
app = StaticFiles(directory="static")

# This is a static files server mounted within a Starlette application,
# underneath the "/static" path.
routes = [
    ...
    Mount("/static", app=StaticFiles(directory="static"), name="static")
]

app = Starlette(routes=routes)
```

## Reverse URL lookups

You'll often want to be able to generate the URL for a particular route,
such as in cases where you need to return a redirect response.

* Signature: `url_for(name, **path_params) -> URL`

```python
routes = [
    Route("/", homepage, name="homepage")
]

# We can use the following to return a URL...
url = request.url_for("homepage")
```

URL lookups can include path parameters...

```python
routes = [
    Route("/users/{username}", user, name="user_detail")
]

# We can use the following to return a URL...
url = request.url_for("user_detail", username=...)
```

If a `Mount` includes a `name`, then submounts should use a `{prefix}:{name}`
style for reverse URL lookups.

```python
routes = [
    Mount("/users", name="users", routes=[
        Route("/", user, name="user_list"),
        Route("/{username}", user, name="user_detail")
    ])
]

# We can use the following to return URLs...
url = request.url_for("users:user_list")
url = request.url_for("users:user_detail", username=...)
```

Mounted applications may include a `path=...` parameter.

```python
routes = [
    ...
    Mount("/static", app=StaticFiles(directory="static"), name="static")
]

# We can use the following to return URLs...
url = request.url_for("static", path="/css/base.css")
```

For cases where there is no `request` instance, you can make reverse lookups
against the application, although these will only return the URL path.

```python
url = app.url_path_for("user_detail", username=...)
```

## Host-based routing

If you want to use different routes for the same path based on the `Host` header.

Note that port is removed from the `Host` header when matching.
For example, `Host (host='example.org:3600', ...)` will be processed
even if the `Host` header contains or does not contain a port other than `3600`
(`example.org:5600`, `example.org`).
Therefore, you can specify the port if you need it for use in `url_for`.

There are several ways to connect host-based routes to your application

```python
site = Router()  # Use eg. `@site.route()` to configure this.
api = Router()  # Use eg. `@api.route()` to configure this.
news = Router()  # Use eg. `@news.route()` to configure this.

routes = [
    Host('api.example.org', api, name="site_api")
]

app = Starlette(routes=routes)

app.host('www.example.org', site, name="main_site")

news_host = Host('news.example.org', news)
app.router.routes.append(news_host)
```

URL lookups can include host parameters just like path parameters

```python
routes = [
    Host("{subdomain}.example.org", name="sub", app=Router(routes=[
        Mount("/users", name="users", routes=[
            Route("/", user, name="user_list"),
            Route("/{username}", user, name="user_detail")
        ])
    ]))
]
...
url = request.url_for("sub:users:user_detail", username=..., subdomain=...)
url = request.url_for("sub:users:user_list", subdomain=...)
```

## Route priority

Incoming paths are matched against each `Route` in order.

In cases where more that one route could match an incoming path, you should
take care to ensure that more specific routes are listed before general cases.

For example:

```python
# Don't do this: `/users/me` will never match incoming requests.
routes = [
    Route('/users/{username}', user),
    Route('/users/me', current_user),
]

# Do this: `/users/me` is tested first.
routes = [
    Route('/users/me', current_user),
    Route('/users/{username}', user),
]
```

## Working with Router instances

If you're working at a low-level you might want to use a plain `Router`
instance, rather that creating a `Starlette` application. This gives you
a lightweight ASGI application that just provides the application routing,
without wrapping it up in any middleware.

```python
app = Router(routes=[
    Route('/', homepage),
    Mount('/users', routes=[
        Route('/', users, methods=['GET', 'POST']),
        Route('/{username}', user),
    ])
])
```

## WebSocket Routing

When working with WebSocket endpoints, you should use `WebSocketRoute`
instead of the usual `Route`.

Path parameters, and reverse URL lookups for `WebSocketRoute` work the the same
as HTTP `Route`, which can be found in the HTTP [Route](#http-routing) section above.

The `endpoint` argument can be one of:

* An async function, which accepts a single `websocket` argument.
* A class that implements the ASGI interface, such as Starlette's [WebSocketEndpoint](endpoints.md#websocketendpoint).


# endpoints.md


Starlette includes the classes `HTTPEndpoint` and `WebSocketEndpoint` that provide a class-based view pattern for
handling HTTP method dispatching and WebSocket sessions.

### HTTPEndpoint

The `HTTPEndpoint` class can be used as an ASGI application:

```python
from starlette.responses import PlainTextResponse
from starlette.endpoints import HTTPEndpoint


class App(HTTPEndpoint):
    async def get(self, request):
        return PlainTextResponse(f"Hello, world!")
```

If you're using a Starlette application instance to handle routing, you can
dispatch to an `HTTPEndpoint` class. Make sure to dispatch to the class itself,
rather than to an instance of the class:

```python
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.endpoints import HTTPEndpoint
from starlette.routing import Route


class Homepage(HTTPEndpoint):
    async def get(self, request):
        return PlainTextResponse(f"Hello, world!")


class User(HTTPEndpoint):
    async def get(self, request):
        username = request.path_params['username']
        return PlainTextResponse(f"Hello, {username}")

routes = [
    Route("/", Homepage),
    Route("/{username}", User)
]

app = Starlette(routes=routes)
```

HTTP endpoint classes will respond with "405 Method not allowed" responses for any
request methods which do not map to a corresponding handler.

### WebSocketEndpoint

The `WebSocketEndpoint` class is an ASGI application that presents a wrapper around
the functionality of a `WebSocket` instance.

The ASGI connection scope is accessible on the endpoint instance via `.scope` and
has an attribute `encoding` which may optionally be set, in order to validate the expected websocket data in the `on_receive` method.

The encoding types are:

* `'json'`
* `'bytes'`
* `'text'`

There are three overridable methods for handling specific ASGI websocket message types:

* `async def on_connect(websocket, **kwargs)`
* `async def on_receive(websocket, data)`
* `async def on_disconnect(websocket, close_code)`

The `WebSocketEndpoint` can also be used with the `Starlette` application class.


# middleware.md


Starlette includes several middleware classes for adding behavior that is applied across
your entire application. These are all implemented as standard ASGI
middleware classes, and can be applied either to Starlette or to any other ASGI application.

## Using middleware

The Starlette application class allows you to include the ASGI middleware
in a way that ensures that it remains wrapped by the exception handler.

```python
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

routes = ...

# Ensure that all requests include an 'example.com' or
# '*.example.com' host header, and strictly enforce https-only access.
middleware = [
    Middleware(
        TrustedHostMiddleware,
        allowed_hosts=['example.com', '*.example.com'],
    ),
    Middleware(HTTPSRedirectMiddleware)
]

app = Starlette(routes=routes, middleware=middleware)
```

Every Starlette application automatically includes two pieces of middleware by default:

* `ServerErrorMiddleware` - Ensures that application exceptions may return a custom 500 page, or display an application traceback in DEBUG mode. This is *always* the outermost middleware layer.
* `ExceptionMiddleware` - Adds exception handlers, so that particular types of expected exception cases can be associated with handler functions. For example raising `HTTPException(status_code=404)` within an endpoint will end up rendering a custom 404 page.

Middleware is evaluated from top-to-bottom, so the flow of execution in our example
application would look like this:

* Middleware
    * `ServerErrorMiddleware`
    * `TrustedHostMiddleware`
    * `HTTPSRedirectMiddleware`
    * `ExceptionMiddleware`
* Routing
* Endpoint

The following middleware implementations are available in the Starlette package:

- CORSMiddleware
- SessionMiddleware
- HTTPSRedirectMiddleware
- TrustedHostMiddleware
- GZipMiddleware
- BaseHTTPMiddleware

# lifespan.md


Starlette applications can register a lifespan handler for dealing with
code that needs to run before the application starts up, or when the application
is shutting down.

```python
import contextlib

from starlette.applications import Starlette


@contextlib.asynccontextmanager
async def lifespan(app):
    async with some_async_resource():
        print("Run at startup!")
        yield
        print("Run on shutdown!")


routes = [
    ...
]

app = Starlette(routes=routes, lifespan=lifespan)
```

Starlette will not start serving any incoming requests until the lifespan has been run.

The lifespan teardown will run once all connections have been closed, and
any in-process background tasks have completed.

Consider using [`anyio.create_task_group()`](https://anyio.readthedocs.io/en/stable/tasks.html)
for managing asynchronous tasks.

## Lifespan State

The lifespan has the concept of `state`, which is a dictionary that
can be used to share the objects between the lifespan, and the requests.

```python
import contextlib
from typing import AsyncIterator, TypedDict

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route


class State(TypedDict):
    http_client: httpx.AsyncClient


@contextlib.asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[State]:
    async with httpx.AsyncClient() as client:
        yield {"http_client": client}


async def homepage(request: Request) -> PlainTextResponse:
    client = request.state.http_client
    response = await client.get("https://www.example.com")
    return PlainTextResponse(response.text)


app = Starlette(
    lifespan=lifespan,
    routes=[Route("/", homepage)]
)
```

The `state` received on the requests is a **shallow** copy of the state received on the
lifespan handler.

## Running lifespan in tests

You should use `TestClient` as a context manager, to ensure that the lifespan is called.

```python
from example import app
from starlette.testclient import TestClient


def test_homepage():
    with TestClient(app) as client:
        # Application's lifespan is called on entering the block.
        response = client.get("/")
        assert response.status_code == 200

    # And the lifespan's teardown is run when exiting the block.
```


# background.md


Starlette includes a `BackgroundTask` class for in-process background tasks.

A background task should be attached to a response, and will run only once
the response has been sent.

### Background Task

Used to add a single background task to a response.

Signature: `BackgroundTask(func, *args, **kwargs)`

```python
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.background import BackgroundTask


...

async def signup(request):
    data = await request.json()
    username = data['username']
    email = data['email']
    task = BackgroundTask(send_welcome_email, to_address=email)
    message = {'status': 'Signup successful'}
    return JSONResponse(message, background=task)

async def send_welcome_email(to_address):
    ...


routes = [
    ...
    Route('/user/signup', endpoint=signup, methods=['POST'])
]

app = Starlette(routes=routes)
```

### BackgroundTasks

Used to add multiple background tasks to a response.

Signature: `BackgroundTasks(tasks=[])`

!!! important
    The tasks are executed in order. In case one of the tasks raises
    an exception, the following tasks will not get the opportunity to be executed.


# server-push.md


Starlette includes support for HTTP/2 and HTTP/3 server push, making it
possible to push resources to the client to speed up page load times.

### `Request.send_push_promise`

Used to initiate a server push for a resource. If server push is not available
this method does nothing.

Signature: `send_push_promise(path)`

* `path` - A string denoting the path of the resource.

```python
from starlette.applications import Starlette
from starlette.responses import HTMLResponse
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles


async def homepage(request):
    """
    Homepage which uses server push to deliver the stylesheet.
    """
    await request.send_push_promise("/static/style.css")
    return HTMLResponse(
        '<html><head><link rel="stylesheet" href="/static/style.css"/></head></html>'
    )

routes = [
    Route("/", endpoint=homepage),
    Mount("/static", StaticFiles(directory="static"), name="static")
]

app = Starlette(routes=routes)
```


# exceptions.md


Starlette allows you to install custom exception handlers to deal with
how you return responses when errors or handled exceptions occur.

```python
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import HTMLResponse


HTML_404_PAGE = ...
HTML_500_PAGE = ...


async def not_found(request: Request, exc: HTTPException):
    return HTMLResponse(content=HTML_404_PAGE, status_code=exc.status_code)

async def server_error(request: Request, exc: HTTPException):
    return HTMLResponse(content=HTML_500_PAGE, status_code=exc.status_code)


exception_handlers = {
    404: not_found,
    500: server_error
}

app = Starlette(routes=routes, exception_handlers=exception_handlers)
```

If `debug` is enabled and an error occurs, then instead of using the installed
500 handler, Starlette will respond with a traceback response.

```python
app = Starlette(debug=True, routes=routes, exception_handlers=exception_handlers)
```

As well as registering handlers for specific status codes, you can also
register handlers for classes of exceptions.

In particular you might want to override how the built-in `HTTPException` class
is handled. For example, to use JSON style responses:

```python
async def http_exception(request: Request, exc: HTTPException):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

exception_handlers = {
    HTTPException: http_exception
}
```

The `HTTPException` is also equipped with the `headers` argument. Which allows the propagation
of the headers to the response class:

```python
async def http_exception(request: Request, exc: HTTPException):
    return JSONResponse(
        {"detail": exc.detail},
        status_code=exc.status_code,
        headers=exc.headers
    )
```

You might also want to override how `WebSocketException` is handled:

```python
async def websocket_exception(websocket: WebSocket, exc: WebSocketException):
    await websocket.close(code=1008)

exception_handlers = {
    WebSocketException: websocket_exception
}
```

## Errors and handled exceptions

It is important to differentiate between handled exceptions and errors.

Handled exceptions do not represent error cases. They are coerced into appropriate
HTTP responses, which are then sent through the standard middleware stack. By default
the `HTTPException` class is used to manage any handled exceptions.

Errors are any other exception that occurs within the application. These cases
should bubble through the entire middleware stack as exceptions. Any error
logging middleware should ensure that it re-raises the exception all the
way up to the server.

In practical terms, the error handled used is `exception_handler[500]` or `exception_handler[Exception]`.
Both keys `500` and `Exception` can be used. See below:

```python
async def handle_error(request: Request, exc: HTTPException):
    # Perform some logic
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

exception_handlers = {
    Exception: handle_error  # or "500: handle_error"
}
```

It's important to notice that in case a [`BackgroundTask`](https://www.starlette.io/background/) raises an exception,
it will be handled by the `handle_error` function, but at that point, the response was already sent. In other words,
the response created by `handle_error` will be discarded. In case the error happens before the response was sent, then
it will use the response object - in the above example, the returned `JSONResponse`.

In order to deal with this behaviour correctly, the middleware stack of a
`Starlette` application is configured like this:

* `ServerErrorMiddleware` - Returns 500 responses when server errors occur.
* Installed middleware
* `ExceptionMiddleware` - Deals with handled exceptions, and returns responses.
* Router
* Endpoints

## HTTPException

The `HTTPException` class provides a base class that you can use for any
handled exceptions. The `ExceptionMiddleware` implementation defaults to
returning plain-text HTTP responses for any `HTTPException`.

* `HTTPException(status_code, detail=None, headers=None)`

You should only raise `HTTPException` inside routing or endpoints. Middleware
classes should instead just return appropriate responses directly.

## WebSocketException

You can use the `WebSocketException` class to raise errors inside of WebSocket endpoints.

* `WebSocketException(code=1008, reason=None)`

You can set any code valid as defined [in the specification](https://tools.ietf.org/html/rfc6455#section-7.4.1).


# testclient.md


The test client allows you to make requests against your ASGI application,
using the `httpx` library.

```python
from starlette.responses import HTMLResponse
from starlette.testclient import TestClient


async def app(scope, receive, send):
    assert scope['type'] == 'http'
    response = HTMLResponse('<html><body>Hello, world!</body></html>')
    await response(scope, receive, send)


def test_app():
    client = TestClient(app)
    response = client.get('/')
    assert response.status_code == 200
```

The test client exposes the same interface as any other `httpx` session.
In particular, note that the calls to make a request are just standard
function calls, not awaitables.

You can use any of `httpx` standard API, such as authentication, session
cookies handling, or file uploads.

For example, to set headers on the TestClient you can do:

```python
client = TestClient(app)

# Set headers on the client for future requests
client.headers = {"Authorization": "..."}
response = client.get("/")

# Set headers for each request separately
response = client.get("/", headers={"Authorization": "..."})
```

And for example to send files with the TestClient:

```python
client = TestClient(app)

# Send a single file
with open("example.txt", "rb") as f:
    response = client.post("/form", files={"file": f})

# Send multiple files
with open("example.txt", "rb") as f1:
    with open("example.png", "rb") as f2:
        files = {"file1": f1, "file2": ("filename", f2, "image/png")}
        response = client.post("/form", files=files)
```

### Testing WebSocket sessions

You can also test websocket sessions with the test client.

The `httpx` library will be used to build the initial handshake, meaning you
can use the same authentication options and other headers between both http and
websocket testing.

```python
from starlette.testclient import TestClient
from starlette.websockets import WebSocket


async def app(scope, receive, send):
    assert scope['type'] == 'websocket'
    websocket = WebSocket(scope, receive=receive, send=send)
    await websocket.accept()
    await websocket.send_text('Hello, world!')
    await websocket.close()


def test_app():
    client = TestClient(app)
    with client.websocket_connect('/') as websocket:
        data = websocket.receive_text()
        assert data == 'Hello, world!'
```

#### Sending data

* `.send_text(data)` - Send the given text to the application.
* `.send_bytes(data)` - Send the given bytes to the application.
* `.send_json(data, mode="text")` - Send the given data to the application. Use `mode="binary"` to send JSON over binary data frames.

#### Receiving data

* `.receive_text()` - Wait for incoming text sent by the application and return it.
* `.receive_bytes()` - Wait for incoming bytestring sent by the application and return it.
* `.receive_json(mode="text")` - Wait for incoming json data sent by the application and return it. Use `mode="binary"` to receive JSON over binary data frames.

May raise `starlette.websockets.WebSocketDisconnect`.

#### Closing the connection

* `.close(code=1000)` - Perform a client-side close of the websocket connection.

### Asynchronous tests

Sometimes you will want to do async things outside of your application.
For example, you might want to check the state of your database after calling your app using your existing async database client / infrastructure.

For these situations, using `TestClient` is difficult because it creates it's own event loop and async resources (like a database connection) often cannot be shared across event loops.
The simplest way to work around this is to just make your entire test async and use an async client, like [httpx.AsyncClient].

Here is an example of such a test:

```python
from httpx import AsyncClient
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.requests import Request
from starlette.responses import PlainTextResponse


def hello(request: Request) -> PlainTextResponse:
    return PlainTextResponse("Hello World!")


app = Starlette(routes=[Route("/", hello)])


# if you're using pytest, you'll need to to add an async marker like:
# @pytest.mark.anyio  # using https://github.com/agronholm/anyio
# or install and configure pytest-asyncio (https://github.com/pytest-dev/pytest-asyncio)
async def test_app() -> None:
    # note: you _must_ set `base_url` for relative urls like "/" to work
    async with AsyncClient(app=app, base_url="http://testserver") as client:
        r = await client.get("/")
        assert r.status_code == 200
        assert r.text == "Hello World!"
```
