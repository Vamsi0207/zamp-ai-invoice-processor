import { useCallback, useEffect, useState } from 'react'
import { api } from './api'

export function useQuery<T>(path: string, interval = 0) {
  const [data, setData] = useState<T>()
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  const refresh = useCallback(() => setRevision(r => r + 1), [])
  useEffect(() => {
    let active = true
    let pending = false
    const load = async () => {
      if (pending) return
      pending = true
      try { const result = await api<T>(path); if (active) { setData(result); setError('') } }
      catch (e) { if (active) setError(e instanceof Error ? e.message : 'Unable to reach the backend') }
      finally { pending = false }
    }
    setData(undefined)
    void load()
    const timer = interval ? window.setInterval(load, interval) : undefined
    return () => { active = false; if (timer) window.clearInterval(timer) }
  }, [path, interval, revision])
  return { data, error, refresh }
}

export function useRoute() {
  const [route, setRoute] = useState(location.hash.slice(1) || '/')
  useEffect(() => { const change = () => setRoute(location.hash.slice(1) || '/'); window.addEventListener('hashchange', change); return () => window.removeEventListener('hashchange', change) }, [])
  return route
}
