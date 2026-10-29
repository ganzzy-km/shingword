"""Local development TLS termination only. Waitress remains the HTTP app server."""
import http.client,ssl,sys
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit
from auth_setup import approved_store,ROOT
LIMIT=50*1024*1024
HOP={'connection','keep-alive','proxy-authenticate','proxy-authorization','te','trailer','transfer-encoding','upgrade'}

def hop_names(headers):
 return HOP|{name.strip().lower() for value in headers.get_all('Connection',[]) for name in value.split(',')}

class LocalTLSProxy(BaseHTTPRequestHandler):
 protocol_version='HTTP/1.1';upstream_port=5000;public_host='localhost:8770'
 def log_message(self,*args):pass  # Never log OAuth queries, cookies or payloads.
 def setup(self):super().setup();self.connection.settimeout(15)
 def reject(self,status):
  self.close_connection=True;self.send_response(status);self.send_header('Content-Length','0');self.send_header('Connection','close');self.end_headers()
 def forward(self):
  if self.headers.get_all('Host',[])!=[self.public_host]:return self.reject(400)
  try:
   raw_target=self.requestline.split()[1]
   if raw_target.startswith('//'):raise ValueError()
   parsed=urlsplit(self.path)
   if parsed.scheme or parsed.netloc or not self.path.startswith('/') or self.path.startswith('//') or '#' in self.path:raise ValueError()
   lengths=self.headers.get_all('Content-Length',[])
   if self.headers.get('Transfer-Encoding') or len(lengths)>1:raise ValueError()
   n=int(lengths[0]) if lengths else 0
   if n<0 or n>LIMIT:return self.reject(413)
   if self.command not in {'GET','HEAD','POST','PATCH','PUT','DELETE','OPTIONS'}:return self.reject(405)
   body=self.rfile.read(n) if n else None
   if n and len(body)!=n:raise ValueError()
  except (ValueError,OSError):return self.reject(400)
  denied=hop_names(self.headers)|{'host','forwarded','content-length','expect'}
  headers={k:v for k,v in self.headers.items() if k.lower() not in denied and not k.lower().startswith('x-forwarded-')}
  headers.update(Host=self.public_host,**{'X-Forwarded-Proto':'https'})
  connection=http.client.HTTPConnection('127.0.0.1',self.upstream_port,timeout=180)
  try:
   connection.request(self.command,self.path,body=body,headers=headers);r=connection.getresponse()
   payload=r.read(LIMIT+1)
   if len(payload)>LIMIT:return self.reject(502)
   self.send_response(r.status)
   for k,v in r.getheaders():
    if k.lower() not in hop_names(r.headers)|{'content-length','server','date'}:self.send_header(k,v)
   self.send_header('Content-Length',str(len(payload)));self.end_headers()
   if self.command!='HEAD':self.wfile.write(payload)
  except (OSError,http.client.HTTPException):self.close_connection=True;self.reject(502)
  finally:connection.close()
 do_GET=do_HEAD=do_POST=do_PATCH=do_PUT=do_DELETE=do_OPTIONS=do_CONNECT=forward
 def handle_expect_100(self):self.reject(417);return False

def create_proxy(directory,store,*,port=8770,handler=LocalTLSProxy):
 context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.minimum_version=ssl.TLSVersion.TLSv1_2
 context.load_cert_chain(str(directory/'localhost.cert.pem'),str(directory/'localhost.key.pem'),password=store.get('GEULBIT_LOCAL_TLS_KEY_PASSWORD'))
 server=ThreadingHTTPServer(('127.0.0.1',port),handler);server.daemon_threads=True;server.socket=context.wrap_socket(server.socket,server_side=True);return server

def main():
 store=approved_store();server=create_proxy(ROOT/'operational/tls',store)
 print('LOCAL_TLS_PROXY https://localhost:8770 -> Waitress 127.0.0.1:5000; loopback only; no request logging',flush=True)
 try:server.serve_forever()
 finally:server.server_close()
if __name__=='__main__':main()
