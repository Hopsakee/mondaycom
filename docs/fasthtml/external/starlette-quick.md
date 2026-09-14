# 🌟 Starlette Quick Manual

<!-- originally from bofeng.github.io -->

2020-02-09

Starlette is the ASGI web framework used as the foundation of FastHTML. Listed here are some Starlette features FastHTML developers can use directly, since the `FastHTML` class inherits from the `Starlette` class (but note that FastHTML has its own customised `RouteX` and `RouterX` classes for routing, to handle FT element trees etc).

## Get uploaded file content

```
async def handler(request):
    inp = await request.form()
    uploaded_file = inp["filename"]
    filename = uploaded_file.filename           # abc.png
    content_type = uploaded.content_type    # MIME type, e.g. image/png
    content = await uploaded_file.read()       # image content

```

## Return a customized response (status code and headers)

```
import json
from starlette.responses import Response

async def handler(request):
    data = {
        "name": "Bo"
    }
    return Response(json.dumps(data), media_type="application/json")

```

`Response` takes `status_code`, `headers` and `media_type`, so if we want to change a response's status code, we can do:

```
return Response(content, statu_code=404)

```

And customized headers:

```
headers = {
	"x-extra-key": "value"
}
return Response(content, status_code=200, headers=headers)

```

## Redirect

```
from starlette.responses import RedirectResponse

async handler(request):
    # Customize status_code: 
    #   301: permanent redirect 
    #   302: temporary redirect 
    #   303: see others
    #   307: temporary redirect (default)
    return RedirectResponse(url=url, status_code=303)

```

## Request context

### URL Object: `request.url`

  * Get request full url: `url = str(request.url)`
  * Get scheme: `request.url.scheme` (http, https, ws, wss)
  * Get netloc: `request.url.netloc`, e.g.: example.com:8080
  * Get path: `request.url.path`, e.g.: /search
  * Get query string: `request.url.query`, e.g.: kw=hello
  * Get hostname: `request.url.hostname`, e.g.: example.com
  * Get port: `request.url.port`, e.g.: 8080
  * If using secure scheme: `request.url.is_secure`, True is schme is `https` or `wss`

### Headers: `request.headers`

```
{
    'host': 'example.com:8080', 
    'connection': 'keep-alive', 
    'cache-control': 'max-age=0', 
    'sec-ch-ua': 'Google Chrome 80', 
    'dnt': '1', 
    'upgrade-insecure-requests': '1', 
    'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_3) ...',
    'sec-fetch-dest': 'document', 
    'accept': 'text/html,image/apng,*/*;q=0.8;v=b3;q=0.9', 
    'sec-origin-policy': '0', 
    'sec-fetch-site': 'none', 
    'sec-fetch-mode': 'navigate', 
    'sec-fetch-user': '?1', 
    'accept-encoding': 'gzip, deflate, br', 
    'accept-language': 'en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7,zh-TW;q=0.6', 
    'cookie': 'session=eyJhZG1pbl91c2_KiQ...'
}

```

### Client: `request.client`

  * `request.client.host`: get client sock IP
  * `request.client.port`: get client sock port

### Method: `request.method`

  * `request.method`: GET, POST, etc.

### Get Data

  * `await request.body()`: get raw data from body
  * `await request.json()`: get passed data and parse it as JSON
  * `await request.form()`: get posted data and pass it as dictionary

### Scope: `request.scope`

```
{
    'type': 'http', 
    'http_version': '1.1', 
    'server': ('127.0.0.1', 9092), 
    'client': ('127.0.0.1', 53102), 
    'scheme': 'https', 
    'method': 'GET', 
    'root_path': '', 
    'path': '/', 
    'raw_path': b'/', 
    'query_string': b'kw=hello', 
    'headers': [
        (b'host', b'example.com:8080'), 
        (b'connection', b'keep-alive'), 
        (b'cache-control', b'max-age=0'), 
        ...
    ], 
    'app': <starlette.applications.Starlette object at 0x1081bd650>, 
    'session': {'uid': '57ba03ea7333f72a25f837cf'}, 
    'router': <starlette.routing.Router object at 0x1081bd6d0>, 
    'endpoint': <class 'app.index.Index'>, 
    'path_params': {}
}

```

## Put varaible in request & app scope

```
app.state.dbconn = get_db_conn()
request.state.start_time = time.time()
# use app-scope state variable in a request
request.app.state.dbconn

```

## Utility functions

### Use `State` to wrap a dictionary

```
from starlette.datastructures import State

data = {
    "name": "Bo"
}
print(data["name"])
# now wrap it with State function
wrapped = State(data)
# You can use the dot syntaxt, but can't use `wrapped["name"]` any more.
print(wrapped.name)

```

### login_required wrapper function

NB: This is easier to do in FastHTML using Beforeware.

```
import functools
from starlette.endpoints import HTTPEndpoint
from starlette.responses import Response

def login_required(login_url="/signin"):
    def decorator(handler):
        @functools.wraps(handler)
        async def new_handler(obj, req, *args, **kwargs):
            user = req.session.get("login_user")
            if user is None:
                return seeother(login_url)
            return await handler(obj, req, *args, **kwargs)
        return new_handler
    return decorator

class MyAccount(HTTPEndpiont):
    @login_required()
    async def get(self, request):
        # some logic here
        content = "hello"
        return Response(content)

```

## Exceptions

Handle exception and customize 403, 404, 503, 500 page:

```
from starlette.exceptions import HTTPException

async def exc_handle_403(request, exc):
    return HTMLResponse("My 403 page", status_code=exc.status_code)

async def exc_handle_404(request, exc):
    return HTMLResponse("My 404 page", status_code=exc.status_code)

async def exc_handle_503(request, exc):
    return HTMLResponse("Failed, please try it later", status_code=exc.status_code)

# error is not exception, 500 is server side unexpected error, all other status code will be treated as Exception
async def err_handle_500(request, exc):
    import traceback
    Log.error(traceback.format_exc())
    return HTMLResponse("My 500 page", status_code=500)

# To add handler, we can add either status_code or Exception itself as key
exception_handlers = {
    403: exc_handle_403,
    404: exc_handle_404,
    503: exc_handle_503,
    500: err_handle_500,
    #HTTPException: exc_handle_500,
}

app = Starlette(routes=routes, exception_handlers=exception_handlers)

```

## Background Task

### Put some async task as background task

```
import aiofiles
from starlette.background import BackgroundTask
from starlette.responses import Response

aiofiles_remove = aiofiles.os.wrap(os.remove)

async def del_file(fpath):
    await aiofiles_remove(fpath)

async def handler(request):
    content = ""
    fpath = "/tmp/tmpfile.txt"
    task = BackgroundTask(del_file, fpath=fpath)
    return Response(content, background=task)

```

### Put multiple tasks as background task

```
from starlette.background import BackgroundTasks

async def task1(name):
    pass

async def task2(email):
    pass

async def handler(request):
    tasks = BackgroundTasks()
    tasks.add_task(task1, name="John")
    tasks.add_task(task2, email="info@example.com")
    content = ""
    return Response(content, background=tasks)

```

## Write middleware

There are 2 ways to write middleware:

### Define `__call__` function:

```
class MyMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        # see above scope dictionary as reference
        headers = dict(scope["headers"])
        # do something
        # pass to next middleware
        return await self.app(scope, receive, send)

```

### Use `BaseHTTPMiddleware`

```
from starlette.middleware.base import BaseHTTPMiddleware

class CustomHeaderMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # do something before pass to next middleware
        response = await call_next(request)
        # do something after next middleware returned
        response.headers['X-Author'] = 'John'
        return response

```
