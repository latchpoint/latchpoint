import { useId, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

type TooltipProps = {
  content: string
  children: React.ReactNode
  side?: 'top' | 'bottom' | 'left' | 'right'
}

type TooltipPosition = { left: number; top: number }

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max)
}

function flippedSide(side: NonNullable<TooltipProps['side']>): NonNullable<TooltipProps['side']> {
  switch (side) {
    case 'top':
      return 'bottom'
    case 'bottom':
      return 'top'
    case 'left':
      return 'right'
    case 'right':
      return 'left'
  }
}

export function Tooltip({ content, children, side = 'top' }: TooltipProps) {
  const tooltipId = useId()
  const [open, setOpen] = useState(false)
  const [position, setPosition] = useState<TooltipPosition>({ left: 0, top: 0 })
  const [positioned, setPositioned] = useState(false)
  const triggerRef = useRef<HTMLSpanElement | null>(null)
  const tooltipRef = useRef<HTMLSpanElement | null>(null)

  useLayoutEffect(() => {
    if (!open) return
    if (typeof window === 'undefined') return

    let raf = 0
    const offsetPx = 8
    const viewportPaddingPx = 8

    const update = () => {
      const triggerEl = triggerRef.current
      const tooltipEl = tooltipRef.current
      if (!triggerEl || !tooltipEl) return

      const triggerRect = triggerEl.getBoundingClientRect()
      const tooltipRect = tooltipEl.getBoundingClientRect()

      const vw = window.innerWidth
      const vh = window.innerHeight

      const compute = (placement: NonNullable<TooltipProps['side']>): TooltipPosition => {
        switch (placement) {
          case 'bottom':
            return {
              left: triggerRect.left + triggerRect.width / 2 - tooltipRect.width / 2,
              top: triggerRect.bottom + offsetPx,
            }
          case 'left':
            return {
              left: triggerRect.left - tooltipRect.width - offsetPx,
              top: triggerRect.top + triggerRect.height / 2 - tooltipRect.height / 2,
            }
          case 'right':
            return {
              left: triggerRect.right + offsetPx,
              top: triggerRect.top + triggerRect.height / 2 - tooltipRect.height / 2,
            }
          case 'top':
          default:
            return {
              left: triggerRect.left + triggerRect.width / 2 - tooltipRect.width / 2,
              top: triggerRect.top - tooltipRect.height - offsetPx,
            }
        }
      }

      const isOutOfBounds = (pos: TooltipPosition) => {
        return (
          pos.left < viewportPaddingPx ||
          pos.top < viewportPaddingPx ||
          pos.left + tooltipRect.width > vw - viewportPaddingPx ||
          pos.top + tooltipRect.height > vh - viewportPaddingPx
        )
      }

      let placement: NonNullable<TooltipProps['side']> = side
      let next = compute(placement)
      if (isOutOfBounds(next)) {
        const flipped = compute(flippedSide(placement))
        if (!isOutOfBounds(flipped)) placement = flippedSide(placement)
        next = compute(placement)
      }

      setPosition({
        left: clamp(next.left, viewportPaddingPx, vw - tooltipRect.width - viewportPaddingPx),
        top: clamp(next.top, viewportPaddingPx, vh - tooltipRect.height - viewportPaddingPx),
      })
      setPositioned(true)
    }

    const scheduleUpdate = () => {
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(update)
    }

    update()
    window.addEventListener('scroll', scheduleUpdate, true)
    window.addEventListener('resize', scheduleUpdate)

    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('scroll', scheduleUpdate, true)
      window.removeEventListener('resize', scheduleUpdate)
    }
  }, [open, side])

  const openTooltip = () => {
    setPositioned(false)
    setOpen(true)
  }

  return (
    <span className="inline-flex">
      <span
        ref={triggerRef}
        aria-describedby={open ? tooltipId : undefined}
        onMouseEnter={openTooltip}
        onMouseLeave={() => setOpen(false)}
        onFocus={openTooltip}
        onBlur={() => setOpen(false)}
      >
        {children}
      </span>

      {open &&
        typeof document !== 'undefined' &&
        createPortal(
          <span
            ref={tooltipRef}
            id={tooltipId}
            role="tooltip"
            style={{
              left: position.left,
              top: position.top,
              maxWidth: '250px',
              opacity: positioned ? 1 : 0,
            }}
            className="pointer-events-none fixed z-50 w-max whitespace-normal break-words rounded-md border bg-popover px-2 py-1 text-xs text-popover-foreground shadow-md"
          >
            {content}
          </span>,
          document.body
        )}
    </span>
  )
}

export default Tooltip
