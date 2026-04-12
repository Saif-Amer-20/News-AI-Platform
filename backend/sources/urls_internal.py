from django.urls import path

from .views_internal import ProcessRawItemView

urlpatterns = [
    path("process-raw-item/", ProcessRawItemView.as_view(), name="process-raw-item"),
]
