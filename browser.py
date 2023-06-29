import subprocess
import socket
import ssl
import sys

def file_handler(url):
  path = url[len('file://'):]
  subprocess.run(args=['open', path])

def data_handler(url):
  content_type, content = url[len('data:'):].split(',', 1)
  print(f'<html><body>{content}</body></html>')

def request(url):
  # url = 'https://example.org/index.html'

  s = socket.socket(
    family= socket.AF_INET,
    type=socket.SOCK_STREAM,
    proto=socket.IPPROTO_TCP
  )

  scheme, url = url.split('://', 1)

  assert scheme in ['http', 'https'], "Unknown scheme {}".format(scheme)

  host, path = url.split('/', 1)
  port = 80 if scheme == 'http' else 443
  if ':' in host:
    host, port = host.split(':', 1)
    port = int(port)
  path = '/' + path

  if scheme == 'https':
    ctx = ssl.create_default_context()
    s = ctx.wrap_socket(s, server_hostname=host)

  s.connect((host, port))
  s.send((f'GET {path} HTTP/1.1\r\n' +
          f'Host: {host}\r\n' +
          'Connection: close\r\n' +
          'User-Agent: Mozilla/5.0\r\n\r\n').encode('utf8'))

  response = s.makefile('r', encoding='utf8', newline='\r\n')

  statusline = response.readline()
  version, status, explanation = statusline.split(" ", 2)
  assert status == "200", "{}: {}".format(status, explanation)

  headers = {}
  while True:
    line = response.readline()
    if line == "\r\n": break
    header, value = line.split(":", 1)
    headers[header.lower()] = value.strip()

  assert "transfer-encoding" not in headers
  assert "content-encoding" not in headers

  body = response.read()
  s.close()
  return headers, body

def entities_process(html):
  # &lt; and &gt;
  buffer = ""

  for c in html:
    if c == ';':
      if buffer[-3:] == "&lt":
        buffer = buffer[:-3] + "<"
        continue
      elif buffer[-3:] == "&gt":
        buffer = buffer[:-3] + ">"
        continue

    buffer += c

def show(html):
  in_body = False
  in_angle = False
  tag = ''

  for c in html:
    if c == '<':
      in_angle = True
      tag = ''
    elif c == '>':
      in_angle = False
    elif in_angle:
      tag += c
    elif not in_angle and tag == 'body':
      in_body = True
    elif not in_angle and tag == '/body':
      in_body = False
    elif in_body:
      print(c, end='')

def load(url):
  headers, body = request(url)
  show(body)

if __name__ == '__main__':
  url = sys.argv[1]
  load(url)
