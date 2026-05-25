from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.views.static import serve
from dashboardApp import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path('', include('dashboardApp.urls'))
    
]

urlpatterns += [
    re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
]