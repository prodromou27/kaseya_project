from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("integrations", views.IntegrationInstanceViewSet, basename="integration")

urlpatterns = router.urls
