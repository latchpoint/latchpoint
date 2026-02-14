import { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ONE_MINUTE_MS, Routes as AppRoutes } from '@/lib/constants'
import { AppShell, ProtectedRoute, SetupGate } from '@/components/layout'
import { AppErrorBoundary } from '@/components/providers/AppErrorBoundary'
import { ThemeProvider } from '@/components/providers/ThemeProvider'
import { LayoutBootstrap } from '@/components/providers/LayoutBootstrap'
import { ModalProvider } from '@/components/modals'
import { Spinner } from '@/components/ui/spinner'
import { useOnboardingStatusQuery } from '@/hooks/useOnboardingQueries'
import { useCurrentUserQuery } from '@/hooks/useAuthQueries'
import { useGlobalQueryErrorHandler } from '@/hooks/useQueryErrorHandler'

const LoginPage = lazy(() => import('@/pages/LoginPage'))
const OnboardingPage = lazy(() => import('@/pages/OnboardingPage'))
const SetupWizardPage = lazy(() => import('@/pages/SetupWizardPage'))
const SetupMqttPage = lazy(() => import('@/pages/SetupMqttPage'))
const SetupZwavejsPage = lazy(() => import('@/pages/SetupZwavejsPage'))
const ImportSensorsPage = lazy(() => import('@/pages/ImportSensorsPage'))
const DashboardPage = lazy(() => import('@/pages/DashboardPage'))
const RulesPage = lazy(() => import('@/pages/RulesPage'))
const RulesTestPage = lazy(() => import('@/pages/RulesTestPage'))
const CodesPage = lazy(() => import('@/pages/CodesPage'))
const DoorCodesPage = lazy(() => import('@/pages/DoorCodesPage'))
const EventsPage = lazy(() => import('@/pages/EventsPage'))
const ControlPanelsPage = lazy(() => import('@/pages/ControlPanelsPage'))
const SchedulerPage = lazy(() => import('@/pages/SchedulerPage'))
const DebugLayout = lazy(() => import('@/pages/debug/DebugLayout'))
const DebugIndexRedirect = lazy(() => import('@/pages/debug/DebugIndexRedirect'))
const DebugEntitiesTab = lazy(() => import('@/pages/debug/DebugEntitiesTab'))
const DebugLogsTab = lazy(() => import('@/pages/debug/DebugLogsTab'))
const SettingsLayout = lazy(() => import('@/pages/settings/SettingsLayout'))
const SettingsIndexRedirect = lazy(() => import('@/pages/settings/SettingsIndexRedirect'))
const SettingsAlarmTab = lazy(() => import('@/pages/settings/SettingsAlarmTab'))
const SettingsHomeAssistantTab = lazy(() => import('@/pages/settings/SettingsHomeAssistantTab'))
const SettingsMqttTab = lazy(() => import('@/pages/settings/SettingsMqttTab'))
const SettingsFrigateTab = lazy(() => import('@/pages/settings/SettingsFrigateTab'))
const SettingsZwavejsTab = lazy(() => import('@/pages/settings/SettingsZwavejsTab'))
const SettingsNotificationsTab = lazy(() => import('@/pages/settings/SettingsNotificationsTab'))
const NotFoundPage = lazy(() => import('@/pages/NotFoundPage'))

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: ONE_MINUTE_MS,
      refetchOnWindowFocus: false,
      refetchOnReconnect: true,
    },
    mutations: {
      retry: 0,
    },
  },
})

function AppContent() {
  useGlobalQueryErrorHandler()
  const onboardingStatusQuery = useOnboardingStatusQuery()
  const onboardingRequired = onboardingStatusQuery.data?.onboardingRequired ?? null
  const onboardingLoading = onboardingStatusQuery.isLoading
  useCurrentUserQuery()

  if (onboardingLoading || onboardingRequired === null) {
    return <Spinner fullscreen size="lg" />
  }

  return (
    <>
      <Suspense fallback={<Spinner fullscreen size="lg" />}>
        <Routes>
          {/* Public routes */}
          <Route
            path={AppRoutes.ONBOARDING}
            element={
              onboardingRequired ? (
                <OnboardingPage />
              ) : (
                <Navigate to={AppRoutes.LOGIN} replace />
              )
            }
          />
          <Route
            path={AppRoutes.LOGIN}
            element={
              onboardingRequired ? (
                <Navigate to={AppRoutes.ONBOARDING} replace />
              ) : (
                <LoginPage />
              )
            }
          />

          {/* Protected routes with layout */}
          <Route
            element={
              onboardingRequired ? (
                <Navigate to={AppRoutes.ONBOARDING} replace />
              ) : (
                <ProtectedRoute>
                  <SetupGate>
                    <AppShell />
                  </SetupGate>
                </ProtectedRoute>
              )
            }
          >
            <Route path={AppRoutes.SETUP} element={<SetupWizardPage />} />
            <Route path={AppRoutes.SETUP_MQTT} element={<SetupMqttPage />} />
            <Route path={AppRoutes.SETUP_ZWAVEJS} element={<SetupZwavejsPage />} />
            <Route path={AppRoutes.SETUP_IMPORT_SENSORS} element={<ImportSensorsPage />} />
            <Route path={AppRoutes.HOME} element={<DashboardPage />} />
            <Route path={AppRoutes.RULES} element={<RulesPage />} />
            <Route path={AppRoutes.RULES_TEST} element={<RulesTestPage />} />
            <Route path={AppRoutes.CODES} element={<CodesPage />} />
            <Route path={AppRoutes.DOOR_CODES} element={<DoorCodesPage />} />
            <Route path={AppRoutes.EVENTS} element={<EventsPage />} />
            <Route path={AppRoutes.CONTROL_PANELS} element={<ControlPanelsPage />} />
            <Route path={AppRoutes.SCHEDULER} element={<SchedulerPage />} />
            <Route path={AppRoutes.DEBUG} element={<DebugLayout />}>
              <Route index element={<DebugIndexRedirect />} />
              <Route path="entities" element={<DebugEntitiesTab />} />
              <Route path="logs" element={<DebugLogsTab />} />
            </Route>
            <Route path={AppRoutes.SETTINGS} element={<SettingsLayout />}>
              <Route index element={<SettingsIndexRedirect />} />
              <Route path="alarm" element={<SettingsAlarmTab />} />
              <Route path="notifications" element={<SettingsNotificationsTab />} />
              <Route path="home-assistant" element={<SettingsHomeAssistantTab />} />
              <Route path="mqtt" element={<SettingsMqttTab />} />
              <Route path="frigate" element={<SettingsFrigateTab />} />
              <Route path="zigbee2mqtt" element={<Navigate to={`${AppRoutes.SETTINGS}/mqtt`} replace />} />
              <Route path="zwavejs" element={<SettingsZwavejsTab />} />
            </Route>
          </Route>

          {/* Redirects and 404 */}
          <Route path={AppRoutes.DASHBOARD} element={<Navigate to={AppRoutes.HOME} replace />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </Suspense>
    </>
  )
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <ThemeProvider>
          <AppErrorBoundary>
            <LayoutBootstrap />
            <AppContent />
            <ModalProvider />
          </AppErrorBoundary>
        </ThemeProvider>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

export default App
