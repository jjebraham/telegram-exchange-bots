import { assertAdmin, adminClient, basicRateLimit } from "../_shared/admin.ts";

Deno.serve(async (req) => {
  try {
    const ip = req.headers.get("x-forwarded-for") ?? "unknown";
    basicRateLimit(`admin-list-exchanges:${ip}`);
    await assertAdmin(req);

    const { searchParams } = new URL(req.url);
    const status = searchParams.get("status");
    const risk = searchParams.get("risk");
    const from = searchParams.get("from");
    const to = searchParams.get("to");

    let q = adminClient.from("exchange_requests").select("*").order("created_at", { ascending: false });
    if (status) q = q.eq("status", status);
    if (risk) q = q.eq("risk_level", risk);
    if (from) q = q.gte("created_at", from);
    if (to) q = q.lte("created_at", to);

    const { data, error } = await q;
    if (error) return new Response(JSON.stringify({ error: error.message }), { status: 400 });
    return Response.json({ data });
  } catch (err) {
    if (err instanceof Response) return err;
    return new Response(JSON.stringify({ error: String(err) }), { status: 500 });
  }
});
