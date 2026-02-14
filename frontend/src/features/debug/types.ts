export interface LogEntry {
  timestamp: string
  level: string
  levelNo: number
  logger: string
  message: string
  excText: string | null
  filename: string
  lineno: number
  funcName: string
  /** Pre-formatted ANSI string for direct xterm.js rendering */
  formatted: string
}

/** Numeric log level thresholds matching Python's logging module */
export const LOG_LEVELS = {
  DEBUG: 10,
  INFO: 20,
  WARNING: 30,
  ERROR: 40,
  CRITICAL: 50,
} as const

export type LogLevelName = keyof typeof LOG_LEVELS
