from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from core import views
from core.auth_views import SessionView, AuthView

router=DefaultRouter()
for prefix,view in [('students',views.StudentViewSet),('plans',views.PlanViewSet),('questions',views.QuestionViewSet),
    ('papers',views.PaperViewSet),('batches',views.BatchViewSet),('files',views.FileViewSet),('pages',views.PageViewSet),
    ('submissions',views.SubmissionViewSet),('attempts',views.AttemptViewSet),('mistakes',views.MistakeViewSet),('audit',views.AuditViewSet)]:
    router.register(prefix,view,basename=prefix)
urlpatterns=[path('admin/',admin.site.urls),path('api/session/',SessionView.as_view()),
    path('api/auth/<str:action>/',AuthView.as_view()),path('api/dashboard/',views.dashboard),path('api/',include(router.urls))]
