import { readAssetBytes } from "@/lib/docs";

export async function GET(_req: Request, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  const rel = path.join("/");
  const asset = await readAssetBytes(rel);
  if (!asset) return new Response("not found", { status: 404 });
  return new Response(new Uint8Array(asset.bytes), {
    headers: {
      "content-type": asset.mime,
      "cache-control": "public, max-age=3600",
    },
  });
}
