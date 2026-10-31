import axios, { AxiosError } from 'axios'

const TOKEN_KEY = 'cx_token'

export const tokenStore = {
  get(): string | null {
    try { return localStorage.getItem(TOKEN_KEY) } catch { return null }
  },
  set(t: string) {
    try { localStorage.setItem(TOKEN_KEY, t) } catch { /* storage unavailable */ }
  },
  clear() {
    try { localStorage.removeItem(TOKEN_KEY) } catch { /* storage unavailable */ }
  },
}

export const api = axios.create({ baseURL: import.meta.env.VITE_API_BASE ?? '/api', timeout: 120000 })

api.interceptors.request.use((cfg) => {
  const t = tokenStore.get()
  if (t) cfg.headers.Authorization = `Bearer ${t}`
  return cfg
})

let onUnauthorized: (() => void) | null = null
export const setUnauthorizedHandler = (fn: () => void) => { onUnauthorized = fn }

api.interceptors.response.use(
  (r) => r,
  (err: AxiosError) => {
    if (err.response?.status === 401 && !err.config?.url?.includes('/auth/login')) onUnauthorized?.()
    return Promise.reject(err)
  },
)

export function errorMessage(e: unknown): string {
  if (axios.isAxiosError(e)) {
    const d = e.response?.data as any
    if (typeof d?.detail === 'string') return d.detail
    if (Array.isArray(d?.detail)) return d.detail.map((x: any) => x.msg).join('; ')
    if (e.code === 'ECONNABORTED') return 'The request timed out'
    if (!e.response) return 'Cannot reach the API. Is the backend running?'
    return `Request failed (${e.response.status})`
  }
  return e instanceof Error ? e.message : 'Unexpected error'
}

export const get = async <T = any>(url: string, params?: Record<string, any>) => (await api.get<T>(url, { params })).data
export const post = async <T = any>(url: string, body?: any, params?: Record<string, any>) => (await api.post<T>(url, body ?? {}, { params })).data
