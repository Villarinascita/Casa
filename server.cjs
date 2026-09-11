const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const allowed = new Set(['index.html','app.js','styles.css','manifest.webmanifest','sw.js','icon.svg']);
http.createServer((req,res)=>{
 const file = new URL(req.url,'http://localhost').pathname.slice(1) || 'index.html';
 if(!allowed.has(file)){res.writeHead(404);return res.end('Not found');}
 const types={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.webmanifest':'application/manifest+json','.svg':'image/svg+xml'};
 res.setHeader('Content-Type',types[path.extname(file)]||'text/plain');
 res.setHeader('X-Content-Type-Options','nosniff');
 fs.createReadStream(path.join(__dirname,file)).pipe(res);
}).listen(4173,'127.0.0.1',()=>console.log('Insieme: http://localhost:4173'));
