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
        return "URL(scheme={}, host={}, port={}, path={!r})".format(
            self.scheme, self.host, self.port, self.path)

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

    def resolve(self, url):
        if "://" in url: return URL(url)
        if not url.startswith('/'):
            dir, _ = self.path.rsplit('/', 1)
            while url.startswith('../'):
                _, url = url.split('/', 1)
                if "/" in dir:
                    dir, _ = dir.rsplit('/', 1)
            url = dir + "/" + url
        if url.startswith("//"):
            return URL(f"{self.scheme}:{url}")
        else:
            return URL(f"{self.scheme}://{self.host}:{str(self.port)}{url}")


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

def print_tree(node, indent = 0):
    print(" " * indent, node)
    for child in node.children:
        print_tree(child, indent + 2)

class TagSelector:
    def __init__(self, tag):
        self.tag = tag
        self.priority = 1

    def __repr__(self):
        return "TagSelector(tag={}, priority={})".format(
            self.tag, self.priority)

    def matches(self, node):
        return isinstance(node, Element) and self.tag == node.tag

class DescendantSelector:
    def __init__(self, ancestor, descendant):
        self.ancestor = ancestor
        self.descendant = descendant
        self.priority = self.ancestor.priority + self.descendant.priority

    def __repr__(self):
        return ("DescendantSelector(ancestor={}, descendant={}, priority={})") \
            .format(self.ancestor, self.descendant, self.priority)

    def matches(self, node):
        if not self.descendant.matches(node): return False
        while node.parent:
            if self.ancestor.matches(node.parent): return True
            node = node.parent
        return False

def cascade_priority(rule):
    selector, body = rule
    return selector.priority

class CSSParser:
    def __init__(self, s):
        self.s = s
        self.i = 0

    def whitespace(self):
        while self.i < len(self.s) and self.s[self.i].isspace():
            self.i += 1

    def word(self):
        start = self.i
        while self.i < len(self.s):
            if self.s[self.i].isalnum() or self.s[self.i] in "#-.%":
                self.i += 1
            else:
                break
        if not (self.i > start):
            raise Exception("word: Parsing error")
        return self.s[start:self.i]

    def literal(self, literal):
        if not (self.i < len(self.s) and self.s[self.i] == literal):
            raise Exception("literal: Parsing error")
        self.i += 1

    def pair(self):
        prop = self.word()
        self.whitespace()
        self.literal(':')
        self.whitespace()
        val = self.word()
        return prop.casefold(), val

    def ignore_until(self, chars):
        while self.i < len(self.s):
            if self.s[self.i] in chars:
                return self.s[self.i]
            else:
                self.i += 1
        return None

    def selector(self):
        out = TagSelector(self.word().casefold())
        self.whitespace()
        while self.i < len(self.s) and self.s[self.i] != '{':
            tag = self.word()
            descendent = TagSelector(tag.casefold())
            out = DescendantSelector(out, descendent)
            self.whitespace()
        return out

    def body(self):
        pairs = {}
        while self.i < len(self.s):
            try:
                prop, val = self.pair()
                pairs[prop.casefold()] = val
                self.whitespace()
                self.literal(';')
                self.whitespace()
            except Exception:
                why = self.ignore_until([';', '}'])
                if why == ';':
                    self.literal(';')
                    self.whitespace()
                else:
                    break
        return pairs

    def parse(self):
        rules = []
        while self.i < len(self.s):
            try:
                self.whitespace()
                selector = self.selector()
                self.literal('{')
                self.whitespace()
                body = self.body()
                self.literal('}')
                rules.append((selector, body))
            except Exception:
                why = self.ignore_until(['}'])
                if why == '}':
                    self.literal('}')
                    self.whitespace()
                else:
                    break
        return rules

INHERITED_PROPERTIES = {
    "font-size": "16px",
    "font-style": "normal",
    "font-weight": "normal",
    "color": "black",
}

def style(node, rules):
    node.style = {}
    for property, default_value in INHERITED_PROPERTIES.items():
        if node.parent:
            node.style[property] = node.parent.style[property]
        else:
            node.style[property] = default_value
    for selector, body in rules:
        if not selector.matches(node): continue
        for property, value in body.items():
            node.style[property] = value
    if isinstance(node, Element) and "style" in node.attributes:
        pairs = CSSParser(node.attributes["style"]).body()
        for property, value in pairs.items():
            node.style[property] = value

    if node.style['font-size'].endswith('%'):
        if node.parent:
            parent_font_size = node.parent.style["font-size"]
        else:
            parent_font_size = INHERITED_PROPERTIES['font-size']
        node_pct = float(node.style['font-size'][:-1]) / 100
        parent_px = float(parent_font_size[:-2])
        node.style['font-size'] = f"{node_pct * parent_px}px"

    for child in node.children:
        style(child, rules)

class HTMLParser:

    SELF_CLOSING_TAGS = [
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    ]

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
        elif tag in self.SELF_CLOSING_TAGS:
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

FONTS = {}

def get_font(size, weight, style) -> tkinter.font.Font:
    key = (size, weight, style)
    if key not in FONTS:
        font = tkinter.font.Font(size=size, weight=weight, slant=style)
        label = tkinter.Label(font=font)
        FONTS[key] = (font, label)
    return FONTS[key][0]

WIDTH, HEIGHT = 800, 600
HSTEP, VSTEP = 13, 18
BLOCK_ELEMENTS = [
    "html", "body", "article", "section", "nav", "aside",
    "h1", "h2", "h3", "h4", "h5", "h6", "hgroup", "header",
    "footer", "address", "p", "hr", "pre", "blockquote",
    "ol", "ul", "menu", "li", "dl", "dt", "dd", "figure",
    "figcaption", "main", "div", "table", "form", "fieldset",
    "legend", "details", "summary"
]

class DocumentLayout:

    def __repr__(self):
        return "DocumentLayout()"

    def __init__(self, node):
        self.node = node
        self.parent = None
        self.children = []
        self.x = None
        self.y = None
        self.width = None
        self.height = None

    def layout(self):
        child = BlockLayout(self.node, self, None)
        self.children.append(child)
        self.width = WIDTH - 2 * HSTEP
        self.x = HSTEP
        self.y = VSTEP
        child.layout()
        self.height = child.height

    def paint(self):
        return []

class BlockLayout:
    def __init__(self, node, parent, previous):
        self.node = node
        self.parent = parent
        self.previous = previous
        self.children = []
        self.x = None
        self.y = None
        self.width = None
        self.height = None
        self.display_list = []

    def paint(self):
        cmds = []
        bgcolor = self.node.style.get('background-color', 'transparent')
        if bgcolor != 'transparent':
            x2, y2 = self.x + self.width, self.y + self.height
            rect = DrawRect(self.x, self.y, x2, y2, bgcolor)
            cmds.append(rect)
        if self.layout_mode() == "inline":
            for x, y, word, font, color in self.display_list:
                cmds.append(DrawText(x, y, word, font, color))
        return cmds

    def layout_intermediate(self):
        previous = None
        for child in self.node.children:
            next = BlockLayout(child, self, previous)
            self.children.append(next)
            previous = next

    def layout_mode(self):
        if isinstance(self.node, Text):
            return "inline"
        elif any([isinstance(child, Element) and \
                  child.tag in BLOCK_ELEMENTS
                  for child in self.node.children]):
            return "block"
        elif self.node.children:
            return "inline"
        else:
            return "block"

    def layout(self):
        self.x = self.parent.x
        self.width = self.parent.width
        if self.previous:
            self.y = self.previous.y + self.previous.height
        else:
            self.y = self.parent.y
        mode = self.layout_mode()
        if mode == "block":
            self.layout_intermediate()
        else:
            self.display_list = []
            self.cursor_x = 0
            self.cursor_y = 0
            self.line = []
            self.recurse(self.node)
            self.flush()

        for child in self.children:
            child.layout()

        if mode == "block":
            self.height = sum([child.height for child in self.children])
        else:
            self.height = self.cursor_y

    def recurse(self, node):
        if isinstance(node, Text):
            for word in node.text.split():
                self.word(node, word)
        else:
            if node.tag == "br":
                self.flush()
            for child in node.children:
                self.recurse(child)

    def word(self, node, word):
        color = node.style['color']
        weight = node.style['font-weight']
        style = node.style['font-style']
        if style == 'normal': style = "roman"
        size = int(float(node.style['font-size'][:-2]) * .75)
        font = get_font(size, weight, style)
        w = font.measure(word)
        if self.cursor_x + w > self.width:
            self.flush()
        self.line.append((self.cursor_x, word, font, color))
        self.cursor_x += w + font.measure(' ')

    def flush(self):
        if not self.line: return
        metrics = [font.metrics() for _, _, font, color in self.line]
        max_ascent = max([metric['ascent'] for metric in metrics])
        baseline = self.cursor_y + 1.25 * max_ascent
        for rel_x, word, font, color in self.line:
            x = self.x + rel_x
            y = self.y + baseline - font.metrics('ascent')
            self.display_list.append((x, y, word, font, color))
        max_descent = max([metric['descent'] for metric in metrics])
        self.cursor_y = baseline + 1.25 * max_descent
        self.cursor_x = 0
        self.line = []

    def __repr__(self):
        return "BlockLayout(x={}, y={}, width={}, height={}, node={})".format(
            self.x, self.y, self.width, self.height, repr(self.node))

def paint_tree(layout_object, display_list):
    display_list.extend(layout_object.paint())

    for child in layout_object.children:
        paint_tree(child, display_list)

def tree_to_list(tree, list):
    list.append(tree)
    for child in tree.children:
        tree_to_list(child, list)
    return list

SCROLL_STEP = 100

class DrawText:

    def __repr__(self):
        return "DrawText(top={} left={} bottom={} text={} font={} color={})" \
            .format(self.top, self.left, self.bottom, self.text, self.font, self.color)

    def __init__(self, x1, y1, text, font, color):
        self.top = y1
        self.left = x1
        self.text = text
        self.font = font
        self.bottom = y1 + font.metrics('linespace')
        self.color = color

    def execute(self, scroll, canvas):
        canvas.create_text(
            self.left,
            self.top - scroll,
            text=self.text,
            font=self.font,
            fill=self.color,
            anchor='nw'
        )

class DrawRect:

    def __repr__(self):
        return "DrawRect(top={} left={} bottom={} right={} color={})".format(
            self.top, self.left, self.bottom, self.right, self.color)

    def __init__(self, x1, y1, x2, y2, color):
        self.top = y1
        self.left = x1
        self.bottom = y2
        self.right = x2
        self.color = color

    def execute(self, scroll, canvas):
        canvas.create_rectangle(
            self.left,
            self.top - scroll,
            self.right,
            self.bottom - scroll,
            width=0,
            fill=self.color
        )

def set_parameters(**params):
    global WIDTH, HEIGHT, HSTEP, VSTEP, SCROLL_STEP
    if "WIDTH" in params: WIDTH = params["WIDTH"]
    if "HEIGHT" in params: HEIGHT = params["HEIGHT"]
    if "HSTEP" in params: HSTEP = params["HSTEP"]
    if "VSTEP" in params: VSTEP = params["VSTEP"]
    if "SCROLL_STEP" in params: SCROLL_STEP = params["SCROLL_STEP"]

GRINNING_FACE: tkinter.PhotoImage

DEFAULT_STYLE_SHEET = CSSParser(open('browser.css').read()).parse()

class Browser:
    def __init__(self):
        global GRINNING_FACE
        self.window = tkinter.Tk()
        self.canvas = tkinter.Canvas(
            self.window,
            width=WIDTH,
            height=HEIGHT,
            bg="white"
        )
        self.canvas.pack(expand=True, fill='both')
        self.scroll = 0
        self.window.bind("<Down>", self.scrolldown)
        self.window.bind("<Configure>", self.resize)
        GRINNING_FACE = tkinter.PhotoImage(file='openmoji/1F600.png')

    def _render(self):
        self.document = DocumentLayout(self.nodes)
        self.document.layout()
        self.display_list = []
        paint_tree(self.document, self.display_list)
        self.draw()

    def resize(self, e):
        set_parameters(WIDTH=e.width, HEIGHT=e.height)
        self._render()

    def scrolldown(self, e):
        max_y = max(self.document.height + 2*VSTEP - HEIGHT, 0)
        self.scroll = min(self.scroll + SCROLL_STEP, max_y)
        self.draw()

    def load(self, url: URL):
        body = url.request()
        self.nodes = HTMLParser(body).parse()
        rules = DEFAULT_STYLE_SHEET.copy()
        links = [node.attributes["href"]
             for node in tree_to_list(self.nodes, [])
             if isinstance(node, Element)
             and node.tag == "link"
             and node.attributes.get("rel") == "stylesheet"
             and "href" in node.attributes]
        for link in links:
            style_url = url.resolve(link)
            try:
                body = style_url.request()
            except:
                continue
            rules.extend(CSSParser(body).parse())
        style(self.nodes, sorted(rules, key=cascade_priority))
        self._render()

    def draw(self):
        self.canvas.delete('all')
        for cmd in self.display_list:
            if cmd.top > self.scroll + HEIGHT: continue
            if cmd.bottom < self.scroll: continue
            cmd.execute(self.scroll, self.canvas)

if __name__ == "__main__":
    import sys
    Browser().load(URL(sys.argv[1]))
    tkinter.mainloop()