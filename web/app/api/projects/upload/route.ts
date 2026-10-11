// Streams video uploads straight through to the Python API.
// (Next.js rewrites buffer request bodies and cap them at 10 MB; videos are often GBs.)
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const API = process.env.FLUXCLIP_API_URL || "http://localhost:8000";

export async function POST(req: Request): Promise<Response> {
  const headers = new Headers();
  for (const h of ["content-type", "content-length"]) {
    const v = req.headers.get(h);
    if (v) headers.set(h, v);
  }
  try {
    const res = await fetch(`${API}/api/projects/upload`, {
      method: "POST",
      headers,
      body: req.body,
      // Required by Node's fetch to stream a request body.
      duplex: "half",
    } as RequestInit & { duplex: "half" });
    return new Response(res.body, {
      status: res.status,
      headers: { "content-type": res.headers.get("content-type") ?? "application/json" },
    });
  } catch (e) {
    return Response.json({ detail: `Upload proxy error: ${(e as Error).message}` }, { status: 502 });
  }
}
