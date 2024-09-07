from typing import List, Literal, Tuple, Union
import socket
import ssl
import time
import tkinter
import tkinter.font

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

class Text:
    text: str
    def __init__(self, text: str):
        self.text = text
    def __repr__(self) -> str:
        return f"Text({repr(self.text)})"

class Tag:
    tag: str
    def __init__(self, tag: str):
        self.tag = tag
    def __repr__(self) -> str:
        return f"Tag({repr(self.tag)})"

Token = Union[Text, Tag]

def lex(body: str) -> List[Token]:
    out = []
    buffer = ''
    in_tag = False
    for c in body:
        if c == '<':
            in_tag = True
            if buffer: out.append(Text(buffer))
            buffer = ''
        elif c == '>':
            in_tag = False
            out.append(Tag(buffer))
            buffer = ''
        else:
            buffer += c
    if not in_tag and buffer:
        out.append(Text(buffer))
    return out

DisplayList = List[Tuple[float, float, str, tkinter.font.Font]]
Line = List[Tuple[float, str, tkinter.font.Font, bool]]

class Layout:
    display_list: DisplayList
    line: Line
    size: float
    is_sup: bool
    cursor_x: float
    cursor_y: float
    weight: Literal["normal", "bold"]
    style: Literal['roman', 'italic']

    def __init__(self, tokens: List[Token]):
        self.display_list = []
        self.line = []
        self.cursor_x = HSTEP
        self.cursor_y = VSTEP
        self.size = 12
        self.weight = 'normal'
        self.style = 'roman'
        self.is_sup = False

        for tok in tokens:
            self.token(tok)

        self.flush()

    def token(self, token: Token):
        if isinstance(token, Text):
            self.word(token)
        elif token.tag == 'i':
            self.style = "italic"
        elif token.tag == '/i':
            self.style = 'roman'
        elif token.tag == 'b':
            self.weight = 'bold'
        elif token.tag == '/b':
            self.weight = 'normal'
        elif token.tag == 'small':
            self.size -= 2
        elif token.tag == '/small':
            self.size += 2
        elif token.tag == 'big':
            self.size += 4
        elif token.tag == '/big':
            self.size -= 4
        elif token.tag == 'br':
            self.flush()
        elif token.tag == '/p':
            self.flush()
            self.cursor_y += VSTEP
        elif token.tag == 'h1 class="title"':
            self.flush()
        elif token.tag == '/h1':
            self.flush(center=True)
        elif token.tag == 'sup':
            self.is_sup = True
            self.size /= 2
        elif token.tag == '/sup':
            self.is_sup = False
            self.size *= 2


    def word(self, text: Text):
        for word in text.text.split():
            font = get_font(
                size=int(self.size),
                weight=self.weight,
                style=self.style
            )
            w = font.measure(word)
            if self.cursor_x + w >= WIDTH - HSTEP:
                if word.find("\N{soft hyphen}") != -1:
                    parts = word.split("\N{soft hyphen}")
                    split_index = -1
                    for i in range(1, len(parts) + 1):
                        w = font.measure(f'{"".join(parts[0:i])}-')
                        if self.cursor_x + w >= WIDTH - HSTEP:
                            split_index = i - 1
                            break
                    if split_index != -1:
                        self.line.append((self.cursor_x, "".join(parts[0:split_index]) + "-", font, self.is_sup))
                        self.flush()
                        self.word(Text("\N{soft hyphen}".join(parts[split_index:])))
                        continue
                self.flush()
            self.line.append((self.cursor_x, word, font, self.is_sup))
            self.cursor_x += w + font.measure(' ')

    def flush(self, center=False):
        if not self.line: return
        if center:
            last_x, last_word, last_font, _ = self.line[-1]
            first_x, _, _, _ = self.line[0]
            total_width = last_x + last_font.measure(last_word) - first_x
            h_offset = (WIDTH - 2 * HSTEP - total_width) / 2
        else:
            h_offset = 0
        metrics = [font.metrics() for _, _, font, _ in self.line]
        max_ascent = max([metric['ascent'] for metric in metrics])
        baseline = self.cursor_y + 1.25 * max_ascent
        top = baseline - max_ascent
        for x, word, font, is_sup in self.line:
            if is_sup:
                y = top
            else:
                y = baseline - font.metrics('ascent')
            self.display_list.append((x + h_offset, y, word, font))
        max_descent = max([metric['descent'] for metric in metrics])
        self.cursor_y = baseline + 1.25 * max_descent
        self.cursor_x = HSTEP
        self.line = []


WIDTH, HEIGHT = 800, 600
HSTEP, VSTEP = 13, 18
SCROLL_STEP = 100
FONTS = {}

def get_font(size, weight, style) -> tkinter.font.Font:
    key = (size, weight, style)
    if key not in FONTS:
        font = tkinter.font.Font(size=size, weight=weight, slant=style)
        label = tkinter.Label(font=font)
        FONTS[key] = (font, label)
    return FONTS[key][0]

def set_parameters(**params: int):
    global WIDTH, HEIGHT, HSTEP, VSTEP, SCROLL_STEP
    if "WIDTH" in params: WIDTH = params["WIDTH"]
    if "HEIGHT" in params: HEIGHT = params["HEIGHT"]
    if "HSTEP" in params: HSTEP = params["HSTEP"]
    if "VSTEP" in params: VSTEP = params["VSTEP"]
    if "SCROLL_STEP" in params: SCROLL_STEP = params["SCROLL_STEP"]

GRINNING_FACE: tkinter.PhotoImage

class Browser:
    window: tkinter.Tk
    canvas: tkinter.Canvas
    tokens: List[Token]
    display_list: DisplayList
    scroll: float


    def __init__(self):
        global GRINNING_FACE
        self.window = tkinter.Tk()
        self.canvas = tkinter.Canvas(
            self.window,
            width=WIDTH,
            height=HEIGHT
        )
        self.canvas.pack(expand=True, fill='both')
        self.scroll = 0
        self.window.bind("<Down>", self.scrolldown)
        self.window.bind("<Configure>", self.resize)
        GRINNING_FACE = tkinter.PhotoImage(file='openmoji/1F600.png')

    def resize(self, e: tkinter.Event):
        set_parameters(WIDTH=e.width, HEIGHT=e.height)
        self.display_list = Layout(self.tokens).display_list
        self.draw()

    def scrolldown(self, e: tkinter.Event):
        if self.scroll + HEIGHT + SCROLL_STEP > self.content_height:
            self.scroll += self.content_height - self.scroll - HEIGHT
        else:
            self.scroll += SCROLL_STEP
        self.draw()

    def load(self, url: URL):
        body = url.request()
        self.tokens = lex(body)
        self.display_list = Layout(self.tokens).display_list
        self.draw()

    @property
    def content_height(self) -> float:
        _, y, _, _ = self.display_list[-1]
        return y + VSTEP

    def draw(self):
        self.canvas.delete('all')
        for x, y, c, font in self.display_list:
            if y > self.scroll + HEIGHT: continue
            if y + VSTEP < self.scroll: continue
            if c == '\N{GRINNING FACE}':
                self.canvas.create_image(x, y - self.scroll, image=GRINNING_FACE)
            else:
                self.canvas.create_text(x, y - self.scroll, text=c, anchor='nw', font=font)

        if self.content_height <= HEIGHT: return
        scrollbar_start = self.scroll / self.content_height * HEIGHT
        scrollbar_end = (self.scroll + HEIGHT) / self.content_height * HEIGHT
        self.canvas.create_rectangle(WIDTH - 8, scrollbar_start, WIDTH, scrollbar_end, width=0, fill='blue')

if __name__ == "__main__":
    import sys
    Browser().load(URL(sys.argv[1]))
    tkinter.mainloop()