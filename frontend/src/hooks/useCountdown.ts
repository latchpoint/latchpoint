import { useState, useEffect, useCallback, useRef } from 'react'

interface CountdownOptions {
  initialSeconds: number
  onComplete?: () => void
  onTick?: (remainingSeconds: number) => void
  autoStart?: boolean
}

interface CountdownState {
  remainingSeconds: number
  isRunning: boolean
  isComplete: boolean
  progress: number // 0 to 1
}

export function useCountdown({
  initialSeconds,
  onComplete,
  onTick,
  autoStart = false,
}: CountdownOptions): CountdownState & {
  start: () => void
  pause: () => void
  reset: () => void
  setSeconds: (seconds: number) => void
} {
  const [remainingSeconds, setRemainingSeconds] = useState(initialSeconds)
  const [isRunning, setIsRunning] = useState(autoStart)
  const [totalSeconds, setTotalSeconds] = useState(initialSeconds)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const onCompleteRef = useRef(onComplete)
  const onTickRef = useRef(onTick)

  // Update refs when callbacks change
  useEffect(() => {
    onCompleteRef.current = onComplete
    onTickRef.current = onTick
  }, [onComplete, onTick])

  // Clear interval on unmount
  useEffect(() => {
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
      }
    }
  }, [])

  // Main countdown effect
  useEffect(() => {
    if (!isRunning) {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
      return
    }

    intervalRef.current = setInterval(() => {
      setRemainingSeconds((prev) => {
        const next = prev - 1
        if (next <= 0) {
          setIsRunning(false)
          onCompleteRef.current?.()
          return 0
        }
        onTickRef.current?.(next)
        return next
      })
    }, 1000)

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
    }
  }, [isRunning])

  const start = useCallback(() => {
    if (remainingSeconds > 0) {
      setIsRunning(true)
    }
  }, [remainingSeconds])

  const pause = useCallback(() => {
    setIsRunning(false)
  }, [])

  const reset = useCallback(() => {
    setIsRunning(false)
    setRemainingSeconds(totalSeconds)
  }, [totalSeconds])

  const setSeconds = useCallback((seconds: number) => {
    setTotalSeconds(seconds)
    setRemainingSeconds(seconds)
    setIsRunning(false)
  }, [])

  const isComplete = remainingSeconds <= 0
  const progress = totalSeconds > 0 ? (totalSeconds - remainingSeconds) / totalSeconds : 0

  return {
    remainingSeconds,
    isRunning,
    isComplete,
    progress,
    start,
    pause,
    reset,
    setSeconds,
  }
}

// Convenience hook for alarm-specific countdowns
export function useAlarmCountdown() {
  const [type, setType] = useState<'entry' | 'exit' | 'trigger' | null>(null)
  const [totalSeconds, setTotalSeconds] = useState(0)

  const countdown = useCountdown({
    initialSeconds: 0,
    autoStart: false,
  })

  const startEntryDelay = useCallback(
    (seconds: number) => {
      setType('entry')
      setTotalSeconds(seconds)
      countdown.setSeconds(seconds)
      countdown.start()
    },
    [countdown]
  )

  const startExitDelay = useCallback(
    (seconds: number) => {
      setType('exit')
      setTotalSeconds(seconds)
      countdown.setSeconds(seconds)
      countdown.start()
    },
    [countdown]
  )

  const startTriggerTimer = useCallback(
    (seconds: number) => {
      setType('trigger')
      setTotalSeconds(seconds)
      countdown.setSeconds(seconds)
      countdown.start()
    },
    [countdown]
  )

  const stop = useCallback(() => {
    setType(null)
    countdown.pause()
    countdown.reset()
  }, [countdown])

  return {
    ...countdown,
    type,
    totalSeconds,
    startEntryDelay,
    startExitDelay,
    startTriggerTimer,
    stop,
  }
}

export default useCountdown
