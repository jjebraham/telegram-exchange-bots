import { createClient } from '@supabase/supabase-js'

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY

export const supabase = createClient(supabaseUrl, supabaseAnonKey)

export async function callAdminFunction(path: string, body: Record<string, unknown>) {
  const { data: sessionData } = await supabase.auth.getSession()
  const token = sessionData.session?.access_token

  const response = await fetch(`${supabaseUrl}/functions/v1/${path}`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
  })

  return response.json()
}
