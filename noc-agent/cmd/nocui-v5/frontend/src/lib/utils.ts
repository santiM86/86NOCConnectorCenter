import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

/** Utility usata da tutti i componenti shadcn-style. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** Formattazione durata in formato human (ns → "2h 14m"). */
export function formatDuration(ns: number): string {
  if (!ns || ns < 0) return '—'
  const s = Math.floor(ns / 1_000_000_000)
  const days = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  if (days > 0) return `${days}g ${h}h`
  if (h > 0) return `${h}h ${m}m`
  if (m > 0) return `${m}m ${sec}s`
  return `${sec}s`
}

/** RTT da ns a stringa ms con 1 decimale, oppure "—". */
export function formatRtt(ns?: number): string {
  if (!ns) return '—'
  const ms = ns / 1_000_000
  if (ms < 1) return `${ms.toFixed(2)}ms`
  if (ms < 10) return `${ms.toFixed(1)}ms`
  return `${Math.round(ms)}ms`
}

/** Formatta byte in human (KB, MB, GB). */
export function formatBytes(b: number): string {
  if (!b) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let n = b
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024
    i++
  }
  return `${n.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}

/** Differenza umana tra una data ISO e ora (es. "3 min fa"). */
export function timeAgo(iso?: string): string {
  if (!iso) return '—'
  const t = new Date(iso).getTime()
  if (isNaN(t)) return '—'
  const diff = Math.floor((Date.now() - t) / 1000)
  if (diff < 5) return 'adesso'
  if (diff < 60) return `${diff}s fa`
  if (diff < 3600) return `${Math.floor(diff / 60)}m fa`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h fa`
  return `${Math.floor(diff / 86400)}g fa`
}
