"""Loopback-only experimental UI; all assets and requests stay local."""
import hashlib
import json
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from experiment_data import ROOT, load_library, save
from report import records


def serve(reader, port=8770):
    library = load_library()
    token = secrets.token_urlsafe(32)
    jobs = {}
    lock = threading.Lock()
    worker = ThreadPoolExecutor(max_workers=1)
    hosts = {f'127.0.0.1:{port}',f'localhost:{port}'}

    def query_job(job_id, brief):
        from query import find
        try:
            result = find(reader,library,brief)
            with lock: jobs[job_id]={'status':'done','key':result['key']}
        except Exception as exc:
            with lock: jobs[job_id]={'status':'failed','error':str(exc)}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, content, kind='application/json',status=200,download=False):
            body = json.dumps(content,ensure_ascii=False).encode() if kind=='application/json' else content
            self.send_response(status)
            self.send_header('Content-Type',kind+'; charset=utf-8')
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
            if download:self.send_header('Content-Disposition','attachment; filename="checked-sources.json"')
            self.end_headers();self.wfile.write(body)

        def valid_host(self):
            if self.headers.get('Host') not in hosts:
                self.send({'error':'Loopback requests only'},status=403);return False
            return True

        def do_GET(self):
            if not self.valid_host():return
            url=urlsplit(self.path)
            if url.path=='/':
                html=(ROOT/'review.html').read_text().replace('__LOCAL_TOKEN__',token)
                self.send(html.encode(),'text/html');return
            if url.path=='/api/threads':
                items=records()
                feedback=ROOT/'feedback.json'
                self.send({'threads':items,'captions':len(library.rows),
                           'feedback':json.loads(feedback.read_text()) if feedback.exists() else {},
                           'model':reader.llm.model});return
            if url.path=='/api/job':
                with lock: job=jobs.get(parse_qs(url.query).get('id',[''])[0],{'status':'unknown'})
                self.send(job);return
            if url.path=='/api/catalogue':
                key=parse_qs(url.query).get('key',[''])[0]
                record=next((r for r in records() if r['key']==key),None)
                if record and record.get('handoff',{}).get('candidates'):
                    self.send(record['handoff'],download=True);return
                self.send({'error':'No individually checked source catalogue'},status=404);return
            if url.path=='/api/connections':
                p=ROOT/'data/connections.json'
                self.send(json.loads(p.read_text()) if p.exists() else []);return
            self.send({'error':'Not found'},status=404)

        def do_POST(self):
            if not self.valid_host():return
            origin=self.headers.get('Origin')
            if self.headers.get('X-Prototype-Token')!=token or origin and urlsplit(origin).netloc not in hosts:
                self.send({'error':'Open the local review page to make this request'},status=403);return
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=1_000_000:
                self.send({'error':'Request exceeds 1 MB; nothing was truncated or submitted'},status=413);return
            try:
                data=json.loads(self.rfile.read(length))
                if self.path=='/api/find':
                    brief=data['brief']
                    if not isinstance(brief,str) or not brief.strip():raise ValueError('Write a request first')
                    job_id=secrets.token_hex(12)
                    with lock:jobs[job_id]={'status':'running'}
                    worker.submit(query_job,job_id,brief)
                    self.send({'job_id':job_id},status=202);return
                if self.path=='/api/feedback':
                    key=data['key']; verdict=data['verdict'];note=data.get('note','')
                    if key not in {r['key'] for r in records()} or verdict not in {'useful','wrong','needs_work'}:
                        raise ValueError('Choose an existing thread and review verdict')
                    if not isinstance(note,str):raise ValueError('Invalid note')
                    path=ROOT/'feedback.json'
                    with lock:
                        feedback=json.loads(path.read_text()) if path.exists() else {}
                        feedback[key]={'verdict':verdict,'note':note}
                        save(path,feedback)
                    self.send({'saved':True});return
                self.send({'error':'Not found'},status=404)
            except (ValueError,KeyError,TypeError) as exc:
                self.send({'error':str(exc)},status=400)

    print(f'Caption prototype: http://127.0.0.1:{port}/',flush=True)
    ThreadingHTTPServer(('127.0.0.1',port),Handler).serve_forever()
