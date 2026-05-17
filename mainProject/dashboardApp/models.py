from django.db import models
from django.contrib.auth.models import User
import uuid

class Profile(models.Model):
    STATUS_CHOICES = [
        ("Pending", "Pending"),
        ("Approved", "Approved"),
        ("Rejected", "Rejected"),
    ]
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    pf_picture = models.ImageField(null=True, blank=True, upload_to="images/", default="images/default.jpg",)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Pending")

    def __str__(self):
        return self.user.username

class Event(models.Model):
    title = models.CharField(max_length=150)
    venue = models.CharField(max_length=255)
    event_date = models.DateField()

    date = models.DateField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.title


class QRSession(models.Model):
    MODE_CHOICES = [
        ("check_in", "Check In"),
        ("check_out", "Check Out"),
    ]

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="qr_sessions")
    code = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    mode = models.CharField(max_length=20, choices=MODE_CHOICES)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.event.title} - {self.mode}"


class AttendanceEntry(models.Model):
    CAMPUS_CHOICES = [
        ("COE", "COE"),
        ("CBT", "CBT"),
        ("CAS", "CAS"),
        ("CCIS", "CCIS"),
        ("CTE", "CTE"),
    ]

    SEX_CHOICES = [
        ("M", "Male"),
        ("F", "Female"),
    ]

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="entries")
    name = models.CharField(max_length=150)
    campus = models.CharField(max_length=10, choices=CAMPUS_CHOICES)
    sex = models.CharField(max_length=1, choices=SEX_CHOICES)
    signature_image = models.ImageField(upload_to="attendance_signatures/")
    check_in = models.DateTimeField(null=True, blank=True)
    check_out = models.DateTimeField(null=True, blank=True)
    check_in_image = models.ImageField(upload_to="attendance/check_in/", null=True, blank=True)
    check_out_image = models.ImageField(upload_to="attendance/check_out/", null=True, blank=True)

    submitted_at = models.DateTimeField(auto_now_add=True)

    @property
    def status(self):
        if self.check_in and self.check_out:
            return "Present"
        elif self.check_in:
            return "Checked In"
        return "Not Yet Scanned"

    def __str__(self):
        return self.name
    
    