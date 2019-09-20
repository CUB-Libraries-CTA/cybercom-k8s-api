from django.urls import include, path, re_path
from rest_framework import routers
#from tutorial import views
from django.contrib import admin
from .views import APIRoot, UserProfile, samlLogout
from django.utils.translation import ugettext_lazy as _
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from rest_framework.urlpatterns import format_suffix_patterns
from .jwt_payload import MyTokenObtainPairView

# JWT Authentication
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
    TokenVerifyView,
)

from api import config


admin.site.site_header = _(config.APPLICATION_TITLE)
admin.site.site_title = _(config.APPLICATION_TITLE)

# Wire up our API using automatic URL routing.
# Additionally, we include login URLs for the browsable API.
urlpatterns = [
    # Root API
    path("api/", APIRoot.as_view()),
    path("api/api-saml/", include('django_saml2_pro_auth.urls')),
    #Authentication and Admin
    path('api/api-auth/',
         include('rest_framework.urls', namespace='rest_framework')),
    path('api/api-auth/logout/',samlLogout.as_view(),name='user-logout'),
    re_path(r'^api/token/$', MyTokenObtainPairView.as_view(),
            name='token_obtain_pair'),
    re_path(r'^api/token/refresh/$',
            TokenRefreshView.as_view(), name='token_refresh'),
    re_path(r'^api/token/verify/$',
            TokenVerifyView.as_view(), name='token_verify'),
    path('api/admin/', admin.site.urls),
    # Cybercommons Django Apps
    path('api/queue/', include('cybercom_queue.urls')),
    path('api/data_store/', include('data_store.urls')),
    path('api/catalog/', include('catalog.urls')),
    path('api/user/', UserProfile.as_view(), name='user-list'),
    path('api/counter/', include('counter.urls'), name='counter-list'),
    path('api/s3/', include('s3.urls'), name='s3-list')

]

urlpatterns += staticfiles_urlpatterns()
urlpatterns = format_suffix_patterns(
    urlpatterns, allowed=['json', 'jsonp', 'xml', 'yaml'])
