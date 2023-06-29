import subprocess
import socket
import ssl
import sys

def transform(body: str) -> str:
  # transfomr '<' to '&lt;' '>' to '&gt;'
  return body.replace('<', '&lt;').replace('>', '&gt;')

def request(url: str) -> tuple[dict[str, str], str]:
  # url = 'https://example.org/index.html'
  # url = 'file:///path/to/file'
  # url = 'data:text/html,Hello world!'

  s = socket.socket(
    family= socket.AF_INET,
    type=socket.SOCK_STREAM,
    proto=socket.IPPROTO_TCP
  )

  scheme, url = url.split(':', 1)

  assert scheme in ['http', 'https', 'file', 'data'], "Unknown scheme {}".format(scheme)

  if scheme == 'file':
    assert url.startswith('//'), "scheme file should start with //"
    url = url[len('//'):]
    with open(url, encoding='utf-8') as f:
      data = f.read()
    return {}, f"<html><body>{transform(data)}</body></html>"

  elif scheme == 'data':
    content_type, content = url.split(',', 1)
    return {}, f"<html><body>{transform(content)}</body></html>"

  assert url.startswith('//'), "http or https should start with //"
  url = url[len('//'):]

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

  print('wait for response')

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

def entities_process(html: str) -> str:
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

  return buffer

def show(html: str):
  in_body = False
  in_angle = False
  tag = ''
  buffer = ''

  for c in html:
    if c == '<':
      in_angle = True
      tag = ''
      continue
    elif c == '>':
      in_angle = False
      in_body = tag == 'body'
      continue
    elif in_angle:
      tag += c
      continue
    if in_body and not in_angle:
      buffer += c

  print(entities_process(buffer))

def load(url: str):
  headers, body = request(url)
  show(body)

if __name__ == '__main__':
  if len(sys.argv) == 1:
    load('file://browser.py')
    exit(0)
  load(sys.argv[1])
