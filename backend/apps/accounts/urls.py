from django.urls import path

from . import views

urlpatterns = [
    path("config/", views.AuthConfigView.as_view(), name="auth-config"),
    path("login/", views.LocalLoginView.as_view(), name="auth-login"),
    path("logout/", views.LogoutView.as_view(), name="auth-logout"),
    path("me/", views.MeView.as_view(), name="auth-me"),
    path("oidc/login/", views.OIDCLoginView.as_view(), name="oidc-login"),
    path("oidc/callback/", views.OIDCCallbackView.as_view(), name="oidc-callback"),
]
