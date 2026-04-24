import { useEffect, useRef, useState } from 'react'
import { isRecord } from '@/lib/typeGuards'
import { getErrorMessage } from '@/types/errors'

export type SettingsErrorCategory =
  | 'validation'
  | 'auth'
  | 'network'
  | 'server'
  | 'unknown'

export interface CategorizedError {
  category: SettingsErrorCategory
  message: string
}

export type SettingsActionVerb = 'Save' | 'Refresh'

export function categorizeSettingsError(
  err: unknown,
  verbPrefix: SettingsActionVerb
): CategorizedError {
  if (isRecord(err) && err.code === '400' && isRecord(err.details)) {
    const firstKey = Object.keys(err.details)[0]
    const raw = err.details[firstKey]
    const firstMsg = Array.isArray(raw) && typeof raw[0] === 'string' ? raw[0] : 'invalid'
    return {
      category: 'validation',
      message: `${verbPrefix} failed: ${firstKey} — ${firstMsg}`,
    }
  }
  if (isRecord(err) && (err.code === '401' || err.code === '403')) {
    return {
      category: 'auth',
      message: `${verbPrefix} failed: you don't have permission to change these settings.`,
    }
  }
  if (err instanceof TypeError) {
    return {
      category: 'network',
      message: `${verbPrefix} failed: could not reach the server. Check your connection and try again.`,
    }
  }
  if (isRecord(err) && typeof err.code === 'string') {
    const status = Number.parseInt(err.code, 10)
    if (Number.isFinite(status) && status >= 500) {
      let message = `${verbPrefix} failed: the server returned an error. Check logs.`
      const details = err.details
      if (isRecord(details)) {
        const detailRaw = details.detail
        if (Array.isArray(detailRaw) && typeof detailRaw[0] === 'string') {
          message += ` ${detailRaw[0]}`
        }
      }
      return { category: 'server', message }
    }
  }
  return {
    category: 'unknown',
    message: `${verbPrefix} failed: ${getErrorMessage(err)}`,
  }
}

export type NoticeVariant = 'info' | 'success'

export interface UseSettingsActionFeedbackResult {
  error: string | null
  notice: string | null
  noticeVariant: NoticeVariant
  setError: (msg: string | null) => void
  setNotice: (msg: string | null) => void
  clear: () => void
  runSave: <T>(fn: () => Promise<T>, successMessage: string) => Promise<T | undefined>
  runRefresh: <T>(fn: () => Promise<T>, successMessage: string) => Promise<T | undefined>
}

export interface UseSettingsActionFeedbackOptions {
  saveDismissMs?: number
  refreshDismissMs?: number
}

export function useSettingsActionFeedback(
  options?: UseSettingsActionFeedbackOptions
): UseSettingsActionFeedbackResult {
  const saveDismissMs = options?.saveDismissMs ?? 5000
  const refreshDismissMs = options?.refreshDismissMs ?? 3000

  const [error, setErrorState] = useState<string | null>(null)
  const [notice, setNoticeState] = useState<string | null>(null)
  const [noticeVariant, setNoticeVariant] = useState<NoticeVariant>('info')
  const dismissTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const cancelDismiss = () => {
    if (dismissTimerRef.current !== null) {
      clearTimeout(dismissTimerRef.current)
      dismissTimerRef.current = null
    }
  }

  useEffect(() => {
    return () => cancelDismiss()
  }, [])

  const scheduleDismiss = (ms: number) => {
    cancelDismiss()
    dismissTimerRef.current = setTimeout(() => {
      setNoticeState(null)
      setNoticeVariant('info')
      dismissTimerRef.current = null
    }, ms)
  }

  /**
   * Resets error and notice to null, noticeVariant to 'info', and cancels any
   * pending auto-dismiss timer. Safe to call when no state is set.
   */
  const clear = () => {
    cancelDismiss()
    setErrorState(null)
    setNoticeState(null)
    setNoticeVariant('info')
  }

  /**
   * Write an error without triggering categorization or auto-dismiss.
   * Entry point for non-Save/Refresh actions (sync, reset, publishDiscovery)
   * that need to surface a message through the same banner slot. Clears any
   * prior notice.
   */
  const setError = (msg: string | null) => {
    cancelDismiss()
    setErrorState(msg)
    setNoticeState(null)
  }

  /**
   * Write an info-variant notice without scheduling auto-dismiss.
   * Entry point for non-Save/Refresh actions. Clears any prior error.
   */
  const setNotice = (msg: string | null) => {
    cancelDismiss()
    setNoticeState(msg)
    setNoticeVariant('info')
    setErrorState(null)
  }

  async function runAction<T>(
    fn: () => Promise<T>,
    successMessage: string,
    verb: SettingsActionVerb,
    dismissMs: number
  ): Promise<T | undefined> {
    try {
      const result = await fn()
      cancelDismiss()
      setErrorState(null)
      setNoticeState(successMessage)
      setNoticeVariant('success')
      scheduleDismiss(dismissMs)
      return result
    } catch (err) {
      const { message } = categorizeSettingsError(err, verb)
      cancelDismiss()
      setErrorState(message)
      setNoticeState(null)
      return undefined
    }
  }

  async function runSave<T>(fn: () => Promise<T>, successMessage: string): Promise<T | undefined> {
    return runAction(fn, successMessage, 'Save', saveDismissMs)
  }

  async function runRefresh<T>(fn: () => Promise<T>, successMessage: string): Promise<T | undefined> {
    return runAction(fn, successMessage, 'Refresh', refreshDismissMs)
  }

  return { error, notice, noticeVariant, setError, setNotice, clear, runSave, runRefresh }
}
