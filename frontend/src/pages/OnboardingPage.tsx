import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Shield, Eye, EyeOff } from 'lucide-react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Routes } from '@/lib/constants'
import { getErrorMessage } from '@/lib/errors'
import { useOnboardingCreateMutation } from '@/hooks/useOnboardingQueries'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { CenteredCard } from '@/components/ui/centered-card'
import { FormField } from '@/components/ui/form-field'
import { IconButton } from '@/components/ui/icon-button'

const onboardingSchema = z.object({
  email: z.string().email('Invalid email address'),
  password: z.string().min(8, 'Password must be at least 8 characters'),
})

type OnboardingForm = z.infer<typeof onboardingSchema>

export function OnboardingPage() {
  const navigate = useNavigate()
  const createOnboarding = useOnboardingCreateMutation()
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<OnboardingForm>({
    resolver: zodResolver(onboardingSchema),
  })

  const onSubmit = async (data: OnboardingForm) => {
    setError(null)
    setIsSubmitting(true)
    try {
      await createOnboarding.mutateAsync({
        email: data.email,
        password: data.password,
      })
      navigate(Routes.LOGIN)
    } catch (err) {
      setError(getErrorMessage(err) || 'Onboarding failed')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <CenteredCard
      title="Set Up Your Alarm"
      description="Create the first admin to get started."
      icon={<Shield className="h-6 w-6" />}
    >
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
        <FormField label="Admin email" htmlFor="email" required error={errors.email?.message}>
          <Input
            id="email"
            type="email"
            placeholder="admin@example.com"
            {...register('email')}
            disabled={isSubmitting}
          />
        </FormField>

        <FormField label="Admin password" htmlFor="password" required error={errors.password?.message}>
          <div className="relative">
            <Input
              id="password"
              type={showPassword ? 'text' : 'password'}
              placeholder="Create a strong password"
              {...register('password')}
              disabled={isSubmitting}
            />
            <IconButton
              type="button"
              className="absolute right-0 top-0 h-full px-3"
              onClick={() => setShowPassword(!showPassword)}
              aria-label={showPassword ? 'Hide password' : 'Show password'}
            >
              {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </IconButton>
          </div>
        </FormField>

        {error && (
          <Alert variant="error" layout="inline">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <Button type="submit" className="w-full" disabled={isSubmitting}>
          {isSubmitting ? 'Setting up...' : 'Create Admin'}
        </Button>
      </form>
    </CenteredCard>
  )
}

export default OnboardingPage
