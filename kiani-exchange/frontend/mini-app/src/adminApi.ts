const API_BASE = import.meta.env.VITE_API_BASE_URL || import.meta.env.VITE_API_URL || '/api'

const TOKEN_KEY = 'kiani_admin_token'
const ROLE_KEY = 'kiani_admin_role'
const USER_KEY = 'kiani_admin_user'

type LoginResponse = {
  token: string
  token_type: string
  expires_in: number
  role: string
  username: string
}

export const getAdminToken = (): string => sessionStorage.getItem(TOKEN_KEY) || ''
export const getAdminRole = (): string => sessionStorage.getItem(ROLE_KEY) || ''
export const getAdminUsername = (): string => sessionStorage.getItem(USER_KEY) || ''

export const clearAdminSession = () => {
  sessionStorage.removeItem(TOKEN_KEY)
  sessionStorage.removeItem(ROLE_KEY)
  sessionStorage.removeItem(USER_KEY)
}

export const adminLogin = async (username: string, password: string): Promise<LoginResponse> => {
  const response = await fetch(`${API_BASE}/admin/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok || !data?.token) {
    throw new Error(data?.detail || `admin_login_http_${response.status}`)
  }
  sessionStorage.setItem(TOKEN_KEY, String(data.token))
  sessionStorage.setItem(ROLE_KEY, String(data.role || ''))
  sessionStorage.setItem(USER_KEY, String(data.username || username))
  return data as LoginResponse
}

export const adminFetch = async (path: string, init: RequestInit = {}): Promise<Response> => {
  const token = getAdminToken()
  if (!token) {
    throw new Error('admin_not_authenticated')
  }

  const headers = new Headers(init.headers || {})
  headers.set('Authorization', `Bearer ${token}`)

  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
  })

  if (response.status === 401) {
    clearAdminSession()
    window.dispatchEvent(new Event('kiani-admin-auth-expired'))
  }

  return response
}

export const adminJson = async <T>(path: string, init: RequestInit = {}): Promise<T> => {
  const response = await adminFetch(path, init)
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(data?.detail || `admin_http_${response.status}`)
  }
  return data as T
}
