import { useEffect } from 'react'
import { useLayoutStore } from '@/stores/layoutStore'

export function LayoutBootstrap() {
  const setIsMobile = useLayoutStore((s) => s.setIsMobile)

  useEffect(() => {
    const checkMobile = () => {
      setIsMobile(window.innerWidth < 1024)
    }
    checkMobile()
    window.addEventListener('resize', checkMobile)
    return () => window.removeEventListener('resize', checkMobile)
  }, [setIsMobile])

  return null
}
