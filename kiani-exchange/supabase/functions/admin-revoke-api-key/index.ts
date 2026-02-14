import { assertAdmin, adminClient, basicRateLimit, writeAuditLog } from "../_shared/admin.ts";

Deno.serve(async (req) => {
  try {
    const ip = req.headers.get("x-forwarded-for") ?? "unknown";
    basicRateLimit(`admin-revoke-api-key:${ip}`, 20);
    const { profile } = await assertAdmin(req);
    const { api_key_id } = await req.json();

    const { data: before } = await adminClient.from("api_keys").select("*").eq("id", api_key_id).single();
    const { data, error } = await adminClient.from("api_keys").update({ revoked_at: new Date().toISOString() }).eq("id", api_key_id).select("*").single();
    if (error) return new Response(JSON.stringify({ error: error.message }), { status: 400 });

    await writeAuditLog({ actorId: profile.id, action: "admin_revoke_api_key", entityType: "api_key", entityId: api_key_id, oldValue: before, newValue: data, ipAddress: ip });
    return Response.json({ data });
  } catch (err) {
    if (err instanceof Response) return err;
    return new Response(JSON.stringify({ error: String(err) }), { status: 500 });
  }
});
