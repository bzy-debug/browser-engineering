from typing import List, Tuple
import socket
import ssl
import time
import tkinter

class RedirectLoopError(Exception): pass

class CacheItem:
    content: str
    add_time: float
    max_age: int

    def __init__(self, content: str, max_age: int) -> None:
        self.content = content
        self.max_age = max_age
        self.add_time = time.time()

class Cache:
    cache: dict[str, CacheItem]

    def __init__(self) -> None:
        self.cache = {}

    def add(self, key: str, content: str, max_age: int) -> None:
        self.cache[key] = CacheItem(content, max_age)

    def get(self, key: str) -> str | None:
        if key in self.cache:
            item = self.cache[key]
            if time.time() - item.add_time < item.max_age:
                return item.content
            else:
                del self.cache[key]
        return None

cache = Cache()

class URL:
    scheme: str
    host: str | None
    port: int | None
    path: str
    def __init__(self, url: str) -> None:
        self.scheme, url = url.split("://")
        assert self.scheme in ['http', 'https', 'file']
        if self.scheme == 'http':
            self.port = 80
        elif self.scheme == 'https':
            self.port = 443

        if self.scheme == 'http' or self.scheme == 'https':
            if "/" not in url:
                url = url + "/"
            self.host, url = url.split("/", 1)
            if ":" in self.host:
                self.host, port = self.host.split(":", 1)
                self.port = int(port)
            self.path = "/" + url
        elif self.scheme == 'file':
            self.host = None
            self.port = None
            self.path = url
    def __repr__(self):
        return f"URL(scheme={self.scheme}, host={self.host}, port={self.port}, path={repr(self.path)})"

    def request(self, headers: dict[str, str] | None=None, redirect_count: int=0) -> str:
        global cache
        if redirect_count == 10:
            raise RedirectLoopError()
        cached = cache.get(repr(self))
        if cached is not None:
            return cached
        if self.scheme == 'file':
            with open(self.path, 'r') as f:
                return f.read()
        assert self.host is not None
        assert self.port is not None
        if headers is None:
            headers = {}
        default_headers = {
            "Host": self.host,
            "Connection": "close",
            "User-Agent": "browser"
        }
        sending_headers: dict[str, str] = {}
        for (k, v) in default_headers.items():
            sending_headers[k.casefold()] = v
        for (k, v) in headers.items():
            sending_headers[k.casefold()] = v
        sending_headers_str = "\r\n".join(map(lambda x: "{}: {}".format(*x), sending_headers.items())) + "\r\n"
        s = socket.socket(
            family=socket.AF_INET,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP
        )
        s.connect((self.host, self.port))
        if self.scheme == 'https':
            ctx = ssl.create_default_context()
            s = ctx.wrap_socket(s, server_hostname=self.host)
        request = "GET {} HTTP/1.1\r\n".format(self.path)
        request += sending_headers_str
        request += "\r\n"
        s.send(request.encode("utf8"))
        response = s.makefile('r', encoding='utf8', newline='\r\n')
        statusline = response.readline()
        version, status, explanation = statusline.split(' ', 2)
        response_headers: dict[str, str] = {}
        while True:
            line = response.readline()
            if line == '\r\n': break
            header, value = line.split(':', 1)
            response_headers[header.casefold()] = value.strip()
        assert "transfer-encoding" not in response_headers
        assert "content-encoding" not in response_headers
        status = int(status)
        if status >= 300 and status < 400:
            assert "location" in response_headers
            location = response_headers["location"]
            if location.startswith("/"):
                redirect_url = URL(f"{self.scheme}://{self.host}:{self.port}{location}")
            else:
                redirect_url = URL(location)
            content = redirect_url.request(headers, redirect_count + 1)
        else :
            content = response.read()
        s.close()
        if 'cache-control' in response_headers:
            cache_control = response_headers['cache-control']
            if cache_control.startswith('max-age='):
                max_age = int(cache_control.split('=')[1])
                cache.add(repr(self), content, max_age)
        return content


def lex(body: str) -> str:
    text = ""
    in_tag = False
    for c in body:
        if c == '<':
            in_tag = True
        elif c == '>':
            in_tag = False
        elif not in_tag:
            text += c
    return text

DisplayList = List[Tuple[int, int, str]]

def layout(text: str) -> DisplayList:
    display_list: list[tuple[int, int, str]] = []
    cursor_x, cursor_y = HSTEP, VSTEP
    for c in text:
        display_list.append((cursor_x, cursor_y, c))
        cursor_x += HSTEP
        if cursor_x >= WIDTH - HSTEP:
            cursor_y += VSTEP
            cursor_x = HSTEP
    return display_list

WIDTH, HEIGHT = 800, 600
HSTEP, VSTEP = 13, 18
SCROLL_STEP = 100

def set_parameters(**params):
    global WIDTH, HEIGHT, HSTEP, VSTEP, SCROLL_STEP
    if "WIDTH" in params: WIDTH = params["WIDTH"]
    if "HEIGHT" in params: HEIGHT = params["HEIGHT"]
    if "HSTEP" in params: HSTEP = params["HSTEP"]
    if "VSTEP" in params: VSTEP = params["VSTEP"]
    if "SCROLL_STEP" in params: SCROLL_STEP = params["SCROLL_STEP"]


class Browser:
    window: tkinter.Tk
    canvas: tkinter.Canvas
    display_list: DisplayList
    scroll: int

    def __init__(self):
        self.window = tkinter.Tk()
        self.canvas = tkinter.Canvas(
            self.window,
            width=WIDTH,
            height=HEIGHT
        )
        self.canvas.pack()
        self.scroll = 0
        self.window.bind("<Down>", self.scrolldown)

    def scrolldown(self, e: tkinter.Event):
        self.scroll += SCROLL_STEP
        self.draw()

    def load(self, url: URL):
        body = url.request()
        text = lex(body)
        self.display_list = layout(text)
        self.draw()

    def draw(self):
        self.canvas.delete('all')
        for x, y, c in self.display_list:
            if y > self.scroll + HEIGHT: continue
            if y + VSTEP < self.scroll: continue
            self.canvas.create_text(x, y - self.scroll, text=c)

if __name__ == "__main__":
    import sys
    Browser().load(URL(sys.argv[1]))
    tkinter.mainloop()