import { assertAdmin, adminClient, basicRateLimit } from "../_shared/admin.ts";

Deno.serve(async (req) => {
  try {
    const ip = req.headers.get("x-forwarded-for") ?? "unknown";
    basicRateLimit(`admin-get-users:${ip}`);
    await assertAdmin(req);

    const { searchParams } = new URL(req.url);
    const page = Number(searchParams.get("page") ?? "1");
    const pageSize = Math.min(100, Number(searchParams.get("pageSize") ?? "20"));
    const role = searchParams.get("role");
    const query = searchParams.get("query");

    let q = adminClient.from("profiles").select("*", { count: "exact" }).range((page - 1) * pageSize, page * pageSize - 1);
    if (role) q = q.eq("role", role);
    if (query) q = q.or(`phone.ilike.%${query}%,email.ilike.%${query}%,full_name.ilike.%${query}%`);

    const { data, count, error } = await q;
    if (error) return new Response(JSON.stringify({ error: error.message }), { status: 400 });

    return Response.json({ data, count, page, pageSize });
  } catch (err) {
    if (err instanceof Response) return err;
    return new Response(JSON.stringify({ error: String(err) }), { status: 500 });
  }
});
