from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("integrations", views.IntegrationInstanceViewSet, basename="integration")
router.register("sync-quarantine", views.SyncQuarantineViewSet, basename="sync-quarantine")

urlpatterns = router.urls
