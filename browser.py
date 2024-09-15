import socket
import ssl
import time
import tkinter
import tkinter.font

class RedirectLoopError(Exception): pass

class CacheItem:
    def __init__(self, content, max_age):
        self.content = content
        self.max_age = max_age
        self.add_time = time.time()

class Cache:
    def __init__(self):
        self.cache = {}

    def add(self, key, content, max_age):
        self.cache[key] = CacheItem(content, max_age)

    def get(self, key):
        if key in self.cache:
            item = self.cache[key]
            if time.time() - item.add_time < item.max_age:
                return item.content
            else:
                del self.cache[key]
        return None

cache = Cache()

class URL:
    def __init__(self, url):
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

    def request(self, headers=None, redirect_count=0):
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
    def __init__(self, text, parent):
        self.text = text
        self.children = []
        self.parent = parent
    def __repr__(self) :
        return repr(self.text)

class Element:
    def __init__(self, tag, attributes, parent):
        self.tag = tag
        self.children = []
        self.attributes = attributes
        self.parent = parent
    def __repr__(self):
        attrs = [" " + k + "=\"" + v + "\"" for k, v  in self.attributes.items()]
        attr_str = ""
        for attr in attrs:
            attr_str += attr
        return "<" + self.tag + attr_str + ">"

SELF_CLOSING_TAGS = [
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
]

class HTMLParser:

    HEAD_TAGS = [
        "base", "basefont", "bgsound", "noscript",
        "link", "meta", "title", "style", "script",
    ]

    def __init__(self, body):
        self.body = body
        self.unfinished = []

    def implicit_tags(self, tag):
        while True:
            open_tags = [node.tag for node in self.unfinished]
            if open_tags == [] and tag != "html":
                self.add_tag('html')
            elif open_tags == ["html"] \
                and tag not in ["head", "body", "/html"]:
                if tag in self.HEAD_TAGS:
                    self.add_tag("head")
                else:
                    self.add_tag("body")
            elif open_tags == ['html', 'head'] and \
                    tag not in ['/head'] + self.HEAD_TAGS:
                self.add_tag("/head")
            else:
                break

    def add_text(self, text):
        if text.isspace(): return
        self.implicit_tags(None)
        parent = self.unfinished[-1]
        node = Text(text, parent)
        parent.children.append(node)

    def get_attributes(self, text):
        if text == "script defer src='my-script.js'":
            pass
        splited = text.split(" ", 1)
        tag = splited[0].casefold()
        if len(splited) == 1:
            return tag, {}
        attribute_text = splited[1]
        attributes = {}
        buffer = ""
        key = ""
        value = ""
        in_quote = ""
        def add_attribute():
            nonlocal key, value, buffer
            attributes[key] = value
            key = ""
            value = ""
            buffer = ""
        for c in attribute_text:
            if c == "=":
                if buffer and not key:
                    key = buffer
                    buffer = ""
                else:
                    buffer += c
            elif c in ['"', "'"]:
                if in_quote:
                    if in_quote == c:
                        in_quote = ""
                        if key:
                            value = buffer
                            add_attribute()
                    else:
                        buffer += c
                else:
                    in_quote = c
            elif c.isspace():
                if in_quote:
                    buffer += c
                elif key:
                    value = buffer
                    add_attribute()
                else:
                    key = buffer
                    add_attribute()
            else:
                buffer += c
        if buffer:
            if key:
                value = buffer
            else:
                key = buffer
            add_attribute()
        return tag, attributes

    def add_tag(self, tag):
        tag, attributes = self.get_attributes(tag)
        if tag.startswith("!"): return
        self.implicit_tags(tag)
        if tag.startswith("/"):
            if len(self.unfinished) == 1: return
            node = self.unfinished.pop()
            parent = self.unfinished[-1]
            parent.children.append(node)
        elif tag in SELF_CLOSING_TAGS:
            parent = self.unfinished[-1]
            node = Element(tag, attributes, parent)
            parent.children.append(node)
        else:
            parent = self.unfinished[-1] if self.unfinished else None
            node = Element(tag, attributes, parent)
            self.unfinished.append(node)

    def finish(self):
        if not self.unfinished:
            self.implicit_tags(None)
        while len(self.unfinished) > 1:
            node = self.unfinished.pop()
            parent = self.unfinished[-1]
            parent.children.append(node)
        return self.unfinished.pop()

    def parse(self):
        text = ""
        in_tag = False
        in_comment = False
        in_script = False
        i = 0
        while i < len(self.body):
            c = self.body[i]

            if in_comment:
                if self.body.startswith("-->", i):
                    in_comment = False
                    i += 3
                else:
                    i += 1
                continue

            if self.body.startswith("<!--", i):
                in_comment = True
                if text: self.add_text(text)
                text = ''
                i += 4
                continue

            if c == "<":
                if in_script:
                    text += c
                else:
                    in_tag = True
                    if text: self.add_text(text)
                    text = ""
            elif c == ">":
                if in_script:
                    text += c
                    if text.endswith("</script>"):
                        self.add_text(text[:-len("</script>")])
                        self.add_tag("/script")
                        text = ""
                        in_script = False
                else:
                    in_tag = False
                    self.add_tag(text)
                    if text.startswith("script"):
                        in_script = True
                    elif text == "/script":
                        in_script = False
                    text = ""
            else:
                text += c
            i += 1

        if not in_tag and text:
            self.add_text(text)

        return self.finish()

def print_tree(node, indent = 0):
    print(" " * indent, node)
    for child in node.children:
        print_tree(child, indent + 2)

# "Hello123Abc" -> ["H", "ELLO", "123A", "BC"]
def attr_split(word):
    out = []
    buffer = ''
    is_lower = False
    for c in word:
        if c.islower():
            if is_lower:
                buffer += c
            else:
                if buffer: out.append(buffer)
                buffer = c
                is_lower = True
        else:
            if not is_lower:
                buffer += c
            else :
                if buffer: out.append(buffer)
                buffer = c
                is_lower = False
    if buffer: out.append(buffer)
    return out

class Layout:
    def __init__(self, tree):
        self.display_list = []
        self.line = []
        self.cursor_x = HSTEP
        self.cursor_y = VSTEP
        self.size = 12
        self.weight = 'normal'
        self.style = 'roman'
        self.is_sup = False
        self.is_abbr = False

        self.recurse(tree)

        self.flush()

    def open_tag(self, tag):
        if tag == 'i':
            self.style = "italic"
        elif tag == 'b':
            self.weight = 'bold'
        elif tag == 'small':
            self.size -= 2
        elif tag == 'big':
            self.size += 4
        elif tag == 'br':
            self.flush()
        elif tag == 'sup':
            self.is_sup = True
        elif tag == 'abbr':
            self.is_abbr = True

    def close_tag(self, tag):
        if tag == 'i':
            self.style = 'roman'
        elif tag == 'b':
            self.weight = 'normal'
        elif tag == 'small':
            self.size += 2
        elif tag == 'big':
            self.size -= 4
        elif tag == 'sup':
            self.is_sup = False
        elif tag == 'abbr':
            self.is_abbr = False

    def recurse(self, tree):
        if isinstance(tree, Text):
            for word in tree.text.split():
                self.word(word)
        else:
            self.open_tag(tree.tag)
            for child in tree.children:
                self.recurse(child)
            self.close_tag(tree.tag)

    def word(self, word):
        if self.is_abbr:
            w = 0
            for s in attr_split(word):
                if s.islower():
                    size = self.size / 2
                    weight = 'bold'
                else:
                    size = self.size
                    weight = self.weight
                font = get_font(
                    size=int(size),
                    weight=weight,
                    style=self.style
                )
                w += font.measure(s)
        else:
            size = self.is_sup and self.size / 2 or self.size
            font = get_font(
                size=int(size),
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
                    return
            self.flush()
        if self.is_abbr:
            for s in attr_split(word):
                if s.islower():
                    size = self.size / 2
                    weight = 'bold'
                else:
                    size = self.size
                    weight = self.weight
                font = get_font(
                    size=int(size),
                    weight=weight,
                    style=self.style
                )
                self.line.append((self.cursor_x, s.upper(), font, self.is_sup))
                self.cursor_x += font.measure(s.upper())
                space_font = get_font(size=int(self.size), weight=self.weight, style=self.style)
            self.cursor_x += space_font.measure(' ')
        else:
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

def set_parameters(**params):
    global WIDTH, HEIGHT, HSTEP, VSTEP, SCROLL_STEP
    if "WIDTH" in params: WIDTH = params["WIDTH"]
    if "HEIGHT" in params: HEIGHT = params["HEIGHT"]
    if "HSTEP" in params: HSTEP = params["HSTEP"]
    if "VSTEP" in params: VSTEP = params["VSTEP"]
    if "SCROLL_STEP" in params: SCROLL_STEP = params["SCROLL_STEP"]

GRINNING_FACE: tkinter.PhotoImage

class Browser:
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

    def resize(self, e):
        set_parameters(WIDTH=e.width, HEIGHT=e.height)
        self.display_list = Layout(self.nodes).display_list
        self.draw()

    def scrolldown(self, e):
        if self.scroll + HEIGHT + SCROLL_STEP > self.content_height:
            self.scroll += self.content_height - self.scroll - HEIGHT
        else:
            self.scroll += SCROLL_STEP
        self.draw()

    def load(self, url: URL):
        body = url.request()
        self.nodes = HTMLParser(body).parse()
        self.display_list = Layout(self.nodes).display_list
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