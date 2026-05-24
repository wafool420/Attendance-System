from django.contrib import admin
from .models import Profile, AttendanceEntry, Event

# Register your models here.
admin.site.register(Profile)
admin.site.register(AttendanceEntry)
admin.site.register(Event)