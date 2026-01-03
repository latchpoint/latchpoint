from __future__ import annotations

from django.urls import path

from . import views

urlpatterns = [
    path("onboarding/", views.OnboardingView.as_view(), name="onboarding"),
    path("onboarding/setup-status/", views.SetupStatusView.as_view(), name="onboarding-setup-status"),
    path("auth/csrf/", views.CsrfView.as_view(), name="auth-csrf"),
    path("auth/login/", views.LoginView.as_view(), name="auth-login"),
    path("auth/logout/", views.LogoutView.as_view(), name="auth-logout"),
    path("auth/token/refresh/", views.RefreshTokenView.as_view(), name="auth-token-refresh"),
    path("users/", views.UsersView.as_view(), name="users"),
    path("users/me/", views.CurrentUserView.as_view(), name="users-me"),
    path("codes/", views.CodesView.as_view(), name="codes"),
    path("codes/<int:code_id>/", views.CodeDetailView.as_view(), name="code-detail"),
]
