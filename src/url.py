import socket

class URL:
    scheme: str
    host: str
    path: str
    def __init__(self, url: str) -> None:
        self.scheme, url = url.split("://")
        assert self.scheme in ['http']
        if "/" not in url:
            url = "/" + url
        self.host, url = url.split("/", 1)
        self.path = "/" + url

    def request(self):
        s = socket.socket(
            family=socket.AF_INET,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP
        )
        s.connect((self.host, 80))
        request = "GET {} HTTP/1.0\r\n".format(self.path)
        request += "Host: {}\r\n".format(self.host)
        request += "\r\n"
        s.send(request.encode("utf8"))