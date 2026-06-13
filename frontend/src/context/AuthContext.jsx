import { createContext, useContext, useState, useCallback } from 'react'

const TOKEN_KEY = 'dataguard_token'
const USER_KEY  = 'dataguard_user'
const BASE      = 'http://localhost:8000'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY) || null)
  const [user,  setUser]  = useState(() => {
    try { return JSON.parse(localStorage.getItem(USER_KEY)) } catch { return null }
  })

  const login = useCallback(async (username, password) => {
    const res = await fetch(`${BASE}/auth/login`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ username, password }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || 'Login failed')
    }
    const data = await res.json()
    localStorage.setItem(TOKEN_KEY, data.access_token)
    localStorage.setItem(USER_KEY,  JSON.stringify({ username: data.username, full_name: data.full_name }))
    setToken(data.access_token)
    setUser({ username: data.username, full_name: data.full_name })
    return data
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
    setToken(null)
    setUser(null)
  }, [])

  const register = useCallback(async (username, password, email, full_name) => {
    const res = await fetch(`${BASE}/auth/register`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ username, password, email, full_name }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || 'Registration failed')
    }
    return res.json()
  }, [])

  return (
    <AuthContext.Provider value={{ token, user, isAuthenticated: !!token, login, logout, register }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
