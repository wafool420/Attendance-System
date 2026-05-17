from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash
from django.contrib import messages

from .forms import RegisterUserForm
from .models import Profile
import qrcode
from io import BytesIO
import base64

from django.utils import timezone
from django.shortcuts import get_object_or_404

from .models import Event, QRSession, AttendanceEntry
from .forms import AttendanceEntryForm

from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Font


def login_user(request):
    if request.method == "POST":
        username = request.POST["username"]
        password = request.POST["password"]

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            return redirect("home")
        else:
            messages.success(request, "Incorrect user or password.")
            return redirect("login")

    return render(request, "authentication/login.html", {})


def register_user(request):
    if request.method == "POST":
        form = RegisterUserForm(request.POST)

        if form.is_valid():
            user = form.save()

            Profile.objects.create(user=user, status="Pending")

            username = form.cleaned_data["username"]
            password = form.cleaned_data["password1"]
            user = authenticate(username=username, password=password)

            if user is not None:
                login(request, user)
                return redirect("home")
    else:
        form = RegisterUserForm()

    return render(request, "authentication/register.html", {
        "form": form,
    })


@login_required
def home(request):
    if request.user.profile.status != "Approved":
        return render(request, "app/pending_approval.html")

    event = Event.objects.filter(is_active=True).last()
    qr_image = None
    latest_qr = None

    if event:
        latest_qr = QRSession.objects.filter(event=event, is_active=True).last()

        if latest_qr:
            scan_url = request.build_absolute_uri(f"/attendance-form/{latest_qr.code}/")

            qr = qrcode.make(scan_url)
            buffer = BytesIO()
            qr.save(buffer, format="PNG")
            qr_image = base64.b64encode(buffer.getvalue()).decode()

    entries = AttendanceEntry.objects.filter(event=event) if event else AttendanceEntry.objects.none()

    present_count = entries.filter(check_in__isnull=False, check_out__isnull=False).count()
    not_yet_scanned = entries.filter(check_in__isnull=True).count()
    absent_count = entries.filter(check_in__isnull=False, check_out__isnull=True).count()

    return render(request, "app/home.html", {
        "event": event,
        "latest_qr": latest_qr,
        "qr_image": qr_image,
        "entries": entries,
        "present_count": present_count,
        "absent_count": absent_count,
        "not_yet_scanned": not_yet_scanned,
    })


def logout_user(request):
    logout(request)
    return redirect("login")


@login_required
def delete_account(request):
    if request.method == "POST":
        user = request.user
        logout(request)
        user.delete()
        messages.success(request, "Your account has been deleted successfully.")
        return redirect("login")

    return render(request, "authentication/delete_account.html")


@login_required
def change_password(request):
    if request.method == "POST":
        form = PasswordChangeForm(request.user, request.POST)

        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            messages.success(request, "Your password has been changed successfully.")
            return redirect("home")
    else:
        form = PasswordChangeForm(request.user)

    return render(request, "authentication/change_password.html", {
        "form": form,
    })

from django.utils import timezone

@login_required
def create_event(request):
    if request.method != "POST":
        return redirect("home")

    title = request.POST.get("title")
    venue = request.POST.get("venue")
    event_date = request.POST.get("event_date")

    if not title or not venue or not event_date:
        return redirect("home")

    today = timezone.localdate()
    is_today = event_date == str(today)

    # Extra backend safety in case JS validation is bypassed
    if event_date < str(today):
        return redirect("home")

    if is_today:
        Event.objects.filter(is_active=True).update(
            is_active=False,
            closed_at=timezone.now()
        )

    Event.objects.create(
        title=title,
        venue=venue,
        event_date=event_date,
        is_active=is_today
    )

    if is_today:
        return redirect("home")

    return redirect("attendance_log")

@login_required
def open_event_now(request, event_id):
    event = get_object_or_404(Event, id=event_id)

    if request.method == "POST":
        Event.objects.filter(is_active=True).update(
            is_active=False,
            closed_at=timezone.now()
        )

        event.is_active = True
        event.closed_at = None
        event.save()

        messages.success(request, "Event opened successfully.")

    return redirect("home")


@login_required
def generate_qr(request, mode):
    if request.user.profile.status != "Approved":
        return redirect("home")

    event = Event.objects.filter(is_active=True).last()

    if not event:
        messages.error(request, "Please create an event first.")
        return redirect("home")

    QRSession.objects.filter(event=event, is_active=True).update(is_active=False)

    QRSession.objects.create(
        event=event,
        mode=mode,
        is_active=True
    )

    return redirect("home")

def attendance_form(request, code):
    qr_session = get_object_or_404(QRSession, code=code)

    if not qr_session.is_active:
        return render(request, "app/invalid_qr.html")

    if request.method == "POST":
        form = AttendanceEntryForm(request.POST, request.FILES)

        if form.is_valid():
            name = form.cleaned_data["name"]
            campus = form.cleaned_data["campus"]
            sex = form.cleaned_data["sex"]

            entry = AttendanceEntry.objects.filter(
                event=qr_session.event,
                name__iexact=name,
                campus=campus,
                sex=sex,
            ).first()

            if qr_session.mode == "check_in":
                if entry and entry.check_in:
                    return render(request, "app/attendance_result.html", {
                        "message": "You are already checked in."
                    })

                if not entry:
                    entry = form.save(commit=False)
                    entry.event = qr_session.event

                entry.check_in = timezone.now()
                entry.check_in_image = request.FILES.get("signature_image")
                entry.save()

                return render(request, "app/attendance_result.html", {
                    "message": "Check-in successful."
                })

            if qr_session.mode == "check_out":
                if not entry or not entry.check_in:
                    return render(request, "app/attendance_result.html", {
                        "message": "No check-in record found. Please check in first."
                    })

                if entry.check_out:
                    return render(request, "app/attendance_result.html", {
                        "message": "You are already checked out."
                    })

                entry.check_out = timezone.now()
                entry.check_out_image = request.FILES.get("signature_image")
                entry.save()

                return render(request, "app/attendance_result.html", {
                    "message": "Check-out successful."
                })

    else:
        form = AttendanceEntryForm()

    return render(request, "app/attendance_form.html", {
        "form": form,
        "event": qr_session.event,
        "mode": qr_session.mode,
    })

@login_required
def delete_event(request, event_id):
    event = get_object_or_404(Event, id=event_id)
    event.delete()
    messages.success(request, "Event deleted successfully.")
    return redirect("attendance_log")

@login_required
def delete_entry(request, entry_id):
    entry = get_object_or_404(AttendanceEntry, id=entry_id)
    entry.delete()
    return redirect('home')

@login_required
def close_event(request, event_id):
    event = get_object_or_404(Event, id=event_id)

    if request.method == "POST":
        event.is_active = False
        event.closed_at = timezone.now()
        event.save()

        QRSession.objects.filter(event=event, is_active=True).update(is_active=False)

        messages.success(request, "Event closed and moved to attendance log.")

    return redirect("home")

@login_required
def attendance_log(request):
    events = Event.objects.filter(is_active=False).order_by("-event_date", "-created_at")

    return render(request, "app/attendance_log.html", {
        "events": events,
    })

@login_required
def reopen_event(request, event_id):
    event = get_object_or_404(Event, id=event_id)

    if request.method == "POST":
        Event.objects.filter(is_active=True).update(is_active=False)

        event.is_active = True
        event.closed_at = None
        event.save()

        messages.success(request, "Event reopened successfully.")

    return redirect("home")

@login_required
def incoming_requests(request):
    if request.user.profile.status != "Approved":
        return redirect("home")

    selected_status = request.GET.get("status", "All")

    all_profiles = Profile.objects.all()

    if selected_status == "Approved":
        profiles = all_profiles.filter(status="Approved")
    elif selected_status == "Rejected":
        profiles = all_profiles.filter(status="Rejected")
    else:
        profiles = all_profiles.filter(status="Pending")

    return render(request, "app/incoming_requests.html", {
        "profiles": profiles,
        "selected_status": selected_status,
        "total_requests": all_profiles.filter(status="Pending").count(),
        "pending_count": all_profiles.filter(status="Pending").count(),
        "approved_count": all_profiles.filter(status="Approved").count(),
        "rejected_count": all_profiles.filter(status="Rejected").count(),
    })


@login_required
def approve_user(request, profile_id):
    if request.user.profile.status != "Approved":
        return redirect("home")

    profile = Profile.objects.get(id=profile_id)
    profile.status = "Approved"
    profile.save()

    return redirect("incoming_requests")


@login_required
def reject_user(request, profile_id):
    if request.user.profile.status != "Approved":
        return redirect("home")

    profile = Profile.objects.get(id=profile_id)
    profile.status = "Rejected"
    profile.save()

    return redirect("incoming_requests")


@login_required
def delete_rejected_user(request, profile_id):
    if request.user.profile.status != "Approved":
        return redirect("home")

    profile = Profile.objects.get(id=profile_id)
    user = profile.user
    user.delete()

    return redirect("incoming_requests")

@login_required
def remove_approved_user(request, profile_id):
    if request.user.profile.status != "Approved":
        return redirect("home")

    profile = Profile.objects.get(id=profile_id)
    profile.status = "Pending"
    profile.save()

    return redirect("incoming_requests")

@login_required
def export_attendance_excel(request, event_id):
    event = get_object_or_404(Event, id=event_id)

    wb = Workbook()
    ws = wb.active
    ws.title = "Attendance"
    
    
    ws.append([event.title])
    ws.append([])
    ws.append(["Event Date", event.event_date.strftime("%B %d, %Y")])
    ws.append(["Started", event.created_at.strftime("%B %d, %Y %I:%M %p")])
    ws.append(["Closed At", event.closed_at.strftime("%B %d, %Y %I:%M %p") if event.closed_at else "Still Active"])
    ws.append([])

    headers = ["Name", "Campus", "Sex", "Check In", "Check Out", "Status"]
    ws.append(headers)

    for cell in ws[4]:
        cell.font = Font(bold=True)

    for entry in event.entries.all():
        status = "Present" if entry.check_in and entry.check_out else "Absent"

        ws.append([
            entry.name.title(),
            entry.campus,
            entry.get_sex_display(),
            entry.check_in.strftime("%I:%M %p") if entry.check_in else "—",
            entry.check_out.strftime("%I:%M %p") if entry.check_out else "—",
            status,
        ])

    for col in ws.columns:
        max_length = 0
        column = col[0].column_letter

        for cell in col:
            if cell.value:
                max_length = max(max_length, len(str(cell.value)))

        ws.column_dimensions[column].width = max_length + 3

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="{event.title}_attendance.xlsx"'

    wb.save(response)
    return response

@login_required
def edit_event(request, event_id):
    event = get_object_or_404(Event, id=event_id)

    if request.method == "POST":
        title = request.POST.get("title")
        venue = request.POST.get("venue")
        event_date = request.POST.get("event_date")

        if title and venue and event_date:
            event.title = title
            event.venue = venue
            event.event_date = event_date
            event.save()

        if event.is_active:
            return redirect("home")

        return redirect("attendance_log")

    return redirect("home")
