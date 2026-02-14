import { assertAdmin, adminClient, basicRateLimit, writeAuditLog } from "../_shared/admin.ts";

Deno.serve(async (req) => {
  try {
    const ip = req.headers.get("x-forwarded-for") ?? "unknown";
    basicRateLimit(`admin-ban-user:${ip}`, 20);
    const { profile } = await assertAdmin(req);
    const { user_id, is_banned = true } = await req.json();

    const { data: before } = await adminClient.from("profiles").select("id,is_banned").eq("id", user_id).single();
    const { data, error } = await adminClient.from("profiles").update({ is_banned }).eq("id", user_id).select("id,is_banned").single();
    if (error) return new Response(JSON.stringify({ error: error.message }), { status: 400 });

    await writeAuditLog({ actorId: profile.id, action: "admin_ban_user", entityType: "profile", entityId: user_id, oldValue: before, newValue: data, ipAddress: ip });
    return Response.json({ data });
  } catch (err) {
    if (err instanceof Response) return err;
    return new Response(JSON.stringify({ error: String(err) }), { status: 500 });
  }
});
