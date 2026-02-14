import { assertAdmin, adminClient, basicRateLimit, writeAuditLog } from "../_shared/admin.ts";

Deno.serve(async (req) => {
  try {
    const ip = req.headers.get("x-forwarded-for") ?? "unknown";
    basicRateLimit(`admin-update-user:${ip}`, 30);
    const { profile } = await assertAdmin(req);
    const body = await req.json();

    const { user_id, ...updates } = body;
    if (!user_id) return new Response(JSON.stringify({ error: "user_id_required" }), { status: 400 });

    const { data: before } = await adminClient.from("profiles").select("*").eq("id", user_id).single();
    const { data, error } = await adminClient.from("profiles").update(updates).eq("id", user_id).select("*").single();
    if (error) return new Response(JSON.stringify({ error: error.message }), { status: 400 });

    await writeAuditLog({ actorId: profile.id, action: "admin_update_user", entityType: "profile", entityId: user_id, oldValue: before, newValue: data, ipAddress: ip });
    return Response.json({ data });
  } catch (err) {
    if (err instanceof Response) return err;
    return new Response(JSON.stringify({ error: String(err) }), { status: 500 });
  }
});
