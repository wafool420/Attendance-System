from django.contrib import admin
from django.urls import path
from . import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('login_user', views.login_user, name="login"),
    path('logout_user', views.logout_user, name="logout"),
    path('register_user', views.register_user, name="register"),
    path('', views.home, name="home"),
    path("delete-account/", views.delete_account, name="delete_account"),
    path("change-password/", views.change_password, name="change_password"),
    path("incoming-requests/", views.incoming_requests, name="incoming_requests"),
    path("approve-user/<int:profile_id>/", views.approve_user, name="approve_user"),
    path("reject-user/<int:profile_id>/", views.reject_user, name="reject_user"),
    path("delete-rejected-user/<int:profile_id>/", views.delete_rejected_user, name="delete_rejected_user"),
    path("remove-approved-user/<int:profile_id>/", views.remove_approved_user, name="remove_approved_user"),
    path("create-event/", views.create_event, name="create_event"),
    path("generate-qr/<int:event_id>/<str:mode>/", views.generate_qr, name="generate_qr"),
    path("attendance-form/<uuid:code>/", views.attendance_form, name="attendance_form"),
    path('delete-entry/<int:entry_id>/', views.delete_entry, name='delete_entry'),
    path("delete-event/<int:event_id>/", views.delete_event, name="delete_event"),
    path("close-event/<int:event_id>/", views.close_event, name="close_event"),
    path("attendance-log/", views.attendance_log, name="attendance_log"),
    path("reopen-event/<int:event_id>/", views.reopen_event, name="reopen_event"),
    path("export-attendance/<int:event_id>/", views.export_attendance_excel, name="export_attendance_excel"),
    path("open-event-now/<int:event_id>/", views.open_event_now, name="open_event_now"),
    path("edit-event/<int:event_id>/", views.edit_event, name="edit_event"),
    path("event/<int:event_id>/", views.event_detail, name="event_detail"),
    path("update-captcha/<int:event_id>/", views.update_captcha, name="update_captcha"),
    path("export-attendance-pdf/<int:event_id>/", views.export_attendance_pdf, name="export_attendance_pdf"),
]
