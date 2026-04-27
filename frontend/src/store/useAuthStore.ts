import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { AuthUser } from '@/types'

interface AuthState {
  token: string | null
  user: AuthUser | null
  isAuthenticated: boolean
  setAuth: (token: string, user: AuthUser) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      user: null,
      isAuthenticated: false,

      setAuth: (token, user) =>
        set({ token, user, isAuthenticated: true }),

      logout: () =>
        set({ token: null, user: null, isAuthenticated: false }),
    }),
    {
      name: 'al-auth',
      partialize: (s) => ({ token: s.token, user: s.user, isAuthenticated: s.isAuthenticated }),
    },
  ),
)

// 角色辅助
export const isFinance = (user: AuthUser | null) =>
  user?.role === 'BOSS' || user?.role === 'ACCOUNTANT'

export const isBoss = (user: AuthUser | null) =>
  user?.role === 'BOSS'
