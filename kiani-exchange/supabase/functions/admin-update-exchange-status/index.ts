import { assertAdmin, adminClient, basicRateLimit, writeAuditLog } from "../_shared/admin.ts";

Deno.serve(async (req) => {
  try {
    const ip = req.headers.get("x-forwarded-for") ?? "unknown";
    basicRateLimit(`admin-update-exchange-status:${ip}`, 30);
    const { profile } = await assertAdmin(req);

    const { exchange_id, status, admin_note, bot_webhook } = await req.json();
    const { data: before } = await adminClient.from("exchange_requests").select("*").eq("id", exchange_id).single();

    const { data, error } = await adminClient
      .from("exchange_requests")
      .update({ status, admin_note, updated_at: new Date().toISOString() })
      .eq("id", exchange_id)
      .select("*")
      .single();

    if (error) return new Response(JSON.stringify({ error: error.message }), { status: 400 });

    await writeAuditLog({ actorId: profile.id, action: "admin_update_exchange_status", entityType: "exchange_request", entityId: exchange_id, oldValue: before, newValue: data, ipAddress: ip });

    if (bot_webhook) {
      await fetch(bot_webhook, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ event: "exchange_status_changed", exchange: data }),
      });
    }

    return Response.json({ data });
  } catch (err) {
    if (err instanceof Response) return err;
    return new Response(JSON.stringify({ error: String(err) }), { status: 500 });
  }
});
