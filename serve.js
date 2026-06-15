// Minimal static server for the built app (bun serve.js).
const ROOT = 'public';
const PORT = Number(process.env.PORT || 8011);

const server = Bun.serve({
  port: PORT,
  async fetch(req) {
    const url = new URL(req.url);
    let path = decodeURIComponent(url.pathname);
    if (path === '/') path = '/index.html';
    // resolve symlinked data/ too
    const file = Bun.file(ROOT + path);
    if (await file.exists()) return new Response(file);
    return new Response('Not found', { status: 404 });
  },
});

console.log(`STL Cool Roofs → http://localhost:${server.port}`);
