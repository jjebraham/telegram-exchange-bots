import { assertAdmin, adminClient, basicRateLimit, writeAuditLog } from "../_shared/admin.ts";

async function sha256(input: string) {
  const data = new TextEncoder().encode(input);
  const hashBuffer = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(hashBuffer)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

Deno.serve(async (req) => {
  try {
    const ip = req.headers.get("x-forwarded-for") ?? "unknown";
    basicRateLimit(`admin-create-api-key:${ip}`, 10);
    const { profile } = await assertAdmin(req);
    const { name } = await req.json();

    const plaintext = `kea_${crypto.randomUUID().replaceAll("-", "")}`;
    const hashed_key = await sha256(plaintext);

    const { data, error } = await adminClient.from("api_keys").insert({ name, hashed_key, created_by: profile.id }).select("id,name,created_at").single();
    if (error) return new Response(JSON.stringify({ error: error.message }), { status: 400 });

    await writeAuditLog({ actorId: profile.id, action: "admin_create_api_key", entityType: "api_key", entityId: data.id, newValue: data, ipAddress: ip });
    return Response.json({ api_key: plaintext, meta: data });
  } catch (err) {
    if (err instanceof Response) return err;
    return new Response(JSON.stringify({ error: String(err) }), { status: 500 });
  }
});
