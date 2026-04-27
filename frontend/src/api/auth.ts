import type { LoginResponse, AuthUser } from '@/types'

export async function login(username: string, password: string): Promise<LoginResponse> {
  const body = new URLSearchParams({ username, password })
  const res = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: body.toString(),
  })
  if (!res.ok) {
    const d = await res.json().catch(() => ({}))
    throw new Error((d as { detail?: string }).detail ?? '登录失败')
  }
  return res.json()
}

export async function getUsers(): Promise<AuthUser[]> {
  const { api } = await import('./client')
  return api.get('/api/auth/users')
}

export async function createUser(data: { display_name: string; role: string; username: string; password: string }) {
  const { api } = await import('./client')
  return api.post('/api/auth/users', data)
}

export async function updateUserPassword(userId: number, password: string) {
  const { api } = await import('./client')
  return api.put(`/api/auth/users/${userId}/password`, { password })
}
