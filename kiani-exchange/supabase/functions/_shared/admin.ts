import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

export const adminClient = createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY);

export async function assertAdmin(req: Request) {
  const authHeader = req.headers.get("Authorization") ?? "";
  const jwt = authHeader.replace("Bearer ", "").trim();
  if (!jwt) throw new Response(JSON.stringify({ error: "missing_auth" }), { status: 401 });

  const {
    data: { user },
    error,
  } = await adminClient.auth.getUser(jwt);
  if (error || !user) throw new Response(JSON.stringify({ error: "invalid_jwt" }), { status: 401 });

  const { data: profile } = await adminClient
    .from("profiles")
    .select("id,role,is_active,is_banned")
    .eq("id", user.id)
    .single();

  if (!profile) throw new Response(JSON.stringify({ error: "profile_missing" }), { status: 403 });
  if (profile.is_banned || !profile.is_active) throw new Response(JSON.stringify({ error: "inactive_or_banned" }), { status: 403 });
  if (!["admin", "superadmin"].includes(profile.role)) throw new Response(JSON.stringify({ error: "forbidden" }), { status: 403 });

  return { user, profile };
}

const rl = new Map<string, { count: number; resetAt: number }>();
export function basicRateLimit(identity: string, limit = 60, windowMs = 60_000) {
  const now = Date.now();
  const state = rl.get(identity);
  if (!state || state.resetAt < now) {
    rl.set(identity, { count: 1, resetAt: now + windowMs });
    return;
  }
  state.count += 1;
  if (state.count > limit) {
    throw new Response(JSON.stringify({ error: "rate_limit" }), { status: 429 });
  }
}

export async function writeAuditLog(params: {
  actorId: string;
  action: string;
  entityType?: string;
  entityId?: string;
  oldValue?: unknown;
  newValue?: unknown;
  ipAddress?: string;
}) {
  await adminClient.from("audit_logs").insert({
    actor_id: params.actorId,
    action: params.action,
    entity_type: params.entityType,
    entity_id: params.entityId,
    old_value: params.oldValue,
    new_value: params.newValue,
    ip_address: params.ipAddress,
  });
}
