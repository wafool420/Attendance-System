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

from datetime import date, time
from django.db.models import Q

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER

import os
from django.conf import settings
from reportlab.platypus import Image
from reportlab.platypus import Image, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.enums import TA_LEFT, TA_CENTER


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

def auto_open_due_events():
    now = timezone.localtime()
    today = now.date()
    current_time = now.time()

    Event.objects.filter(
        is_active=False,
        closed_at__isnull=True,
        event_date=today
    ).filter(
        Q(start_time__isnull=True) | Q(start_time__lte=current_time)
    ).update(
        is_active=True
    )


@login_required
def home(request):
    if request.user.profile.status != "Approved":
        return render(request, "app/pending_approval.html")

    auto_open_due_events()

    events = Event.objects.filter(is_active=True).order_by(
        "event_date",
        "start_time",
        "created_at"
    )

    return render(request, "app/home.html", {
        "events": events,
        "today": timezone.localdate(),
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
    start_time = request.POST.get("start_time") or None

    if not title or not venue or not event_date or not start_time:
        messages.error(request, "Please complete all fields, including start time.")
        return redirect("home")

    today = timezone.localdate()
    now = timezone.localtime()

    if event_date < str(today):
        messages.error(request, "You cannot create an event in the past.")
        return redirect("home")

    event_time = time.fromisoformat(start_time)

    current_hour = now.hour
    current_minute = now.minute

    selected_hour = event_time.hour
    selected_minute = event_time.minute

    selected_is_past = (selected_hour, selected_minute) < (current_hour, current_minute)
    selected_is_now = (selected_hour, selected_minute) == (current_hour, current_minute)

    if event_date == str(today) and selected_is_past:
        messages.error(request, "Invalid start time. You cannot create an event with a past time.")
        return redirect("home")

    should_open_now = event_date == str(today) and selected_is_now

    Event.objects.create(
        title=title,
        venue=venue,
        event_date=event_date,
        start_time=start_time,
        is_active=should_open_now,
    )

    if should_open_now:
        messages.success(request, "Event created and opened successfully.")
        return redirect("home")

    messages.success(request, "Event scheduled successfully.")
    return redirect("attendance_log")

@login_required
def open_event_now(request, event_id):
    event = get_object_or_404(Event, id=event_id)

    if request.method == "POST":
        now = timezone.localtime()

        event.is_active = True
        event.closed_at = None
        event.event_date = now.date()
        event.start_time = now.time().replace(second=0, microsecond=0)
        event.save()

        messages.success(request, "Event opened successfully. Start time has been updated.")

    return redirect("home")


@login_required
def generate_qr(request, event_id, mode):
    if request.user.profile.status != "Approved":
        return redirect("home")

    event = get_object_or_404(Event, id=event_id, is_active=True)

    if mode not in ["check_in", "check_out"]:
        messages.error(request, "Invalid QR mode.")
        return redirect("home")

    QRSession.objects.filter(event=event, is_active=True).update(is_active=False)

    QRSession.objects.create(
        event=event,
        mode=mode,
        is_active=True
    )

    return redirect("event_detail", event_id=event.id)

def attendance_form(request, code):
    qr_session = get_object_or_404(QRSession, code=code)

    if not qr_session.is_active:
        return render(request, "app/invalid_qr.html")

    if request.method == "POST":
        form = AttendanceEntryForm(request.POST, request.FILES)

        if form.is_valid():
            if qr_session.event.captcha_enabled:
                answer_1 = request.POST.get("captcha_answer_1")
                answer_2 = request.POST.get("captcha_answer_2")
                answer_3 = request.POST.get("captcha_answer_3")

                if (
                    answer_1 != qr_session.event.captcha_q1_answer or
                    answer_2 != qr_session.event.captcha_q2_answer or
                    answer_3 != qr_session.event.captcha_q3_answer
                ):
                    messages.error(request, "Captcha quiz failed. Please answer the event questions correctly.")
                    return render(request, "app/attendance_form.html", {
                        "form": form,
                        "event": qr_session.event,
                        "mode": qr_session.mode,
                    })

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
    auto_open_due_events()

    today = timezone.localdate()

    pending_events = Event.objects.filter(
        is_active=False,
        closed_at__isnull=True
    ).order_by("event_date", "start_time", "created_at")

    closed_events = Event.objects.filter(
        is_active=False,
        closed_at__isnull=False
    ).order_by("-closed_at", "-event_date", "-start_time")

    return render(request, "app/attendance_log.html", {
        "pending_events": pending_events,
        "closed_events": closed_events,
        "today": today,
    })

@login_required
def reopen_event(request, event_id):
    event = get_object_or_404(Event, id=event_id)

    if request.method == "POST":
        now = timezone.localtime()

        event.is_active = True
        event.closed_at = None
        event.event_date = now.date()
        event.start_time = now.time().replace(second=0, microsecond=0)
        event.save()

        messages.success(request, "Event reopened successfully. Start time has been updated.")

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
        start_time = request.POST.get("start_time") or None

        if not title or not venue or not event_date or not start_time:
            messages.error(request, "Please complete all fields.")
            return redirect("event_detail", event_id=event.id)

        today = timezone.localdate()
        now = timezone.localtime()

        if event_date < str(today):
            messages.error(request, "You cannot set an event date in the past.")
            return redirect("event_detail", event_id=event.id)

        event_time = time.fromisoformat(start_time)

        selected_is_past = (event_time.hour, event_time.minute) < (now.hour, now.minute)

        if event_date == str(today) and selected_is_past:
            messages.error(request, "Invalid start time. You cannot set the event time in the past.")
            return redirect("event_detail", event_id=event.id)

        event.title = title
        event.venue = venue
        event.event_date = event_date
        event.start_time = start_time
        event.save()

        if event.is_active:
            return redirect("event_detail", event_id=event.id)

        return redirect("attendance_log")

    return redirect("home")

def auto_open_today_event():
    today = timezone.localdate()

    today_event = Event.objects.filter(
        event_date=today,
        is_active=False,
        closed_at__isnull=True
    ).last()

    active_event = Event.objects.filter(is_active=True).last()

    if today_event and not active_event:
        today_event.is_active = True
        today_event.save()

    return Event.objects.filter(is_active=True).last()


@login_required
def event_detail(request, event_id):
    if request.user.profile.status != "Approved":
        return redirect("home")

    event = get_object_or_404(Event, id=event_id)

    latest_qr = QRSession.objects.filter(event=event, is_active=True).last()
    qr_image = None

    if latest_qr:
        scan_url = request.build_absolute_uri(f"/attendance-form/{latest_qr.code}/")

        qr = qrcode.make(scan_url)
        buffer = BytesIO()
        qr.save(buffer, format="PNG")
        qr_image = base64.b64encode(buffer.getvalue()).decode()

    entries = AttendanceEntry.objects.filter(event=event)

    return render(request, "app/event_detail.html", {
        "event": event,
        "latest_qr": latest_qr,
        "qr_image": qr_image,
        "entries": entries,
        "present_count": entries.filter(check_in__isnull=False, check_out__isnull=False).count(),
        "absent_count": entries.filter(check_in__isnull=False, check_out__isnull=True).count(),
        "not_yet_scanned": entries.filter(check_in__isnull=True).count(),
    })

@login_required
def update_captcha(request, event_id):
    if request.user.profile.status != "Approved":
        return redirect("home")

    event = get_object_or_404(Event, id=event_id)

    if request.method == "POST":
        captcha_action = request.POST.get("captcha_action")

        if captcha_action == "disable":
            event.captcha_enabled = False
            event.save()
            messages.success(request, "Captcha quiz disabled.")
            return redirect("event_detail", event_id=event.id)

        q1 = request.POST.get("captcha_q1", "").strip()
        q1_a = request.POST.get("captcha_q1_a", "").strip()
        q1_b = request.POST.get("captcha_q1_b", "").strip()
        q1_c = request.POST.get("captcha_q1_c", "").strip()
        q1_answer = request.POST.get("captcha_q1_answer", "").strip().upper()

        q2 = request.POST.get("captcha_q2", "").strip()
        q2_a = request.POST.get("captcha_q2_a", "").strip()
        q2_b = request.POST.get("captcha_q2_b", "").strip()
        q2_c = request.POST.get("captcha_q2_c", "").strip()
        q2_answer = request.POST.get("captcha_q2_answer", "").strip().upper()

        q3 = request.POST.get("captcha_q3", "").strip()
        q3_a = request.POST.get("captcha_q3_a", "").strip()
        q3_b = request.POST.get("captcha_q3_b", "").strip()
        q3_c = request.POST.get("captcha_q3_c", "").strip()
        q3_answer = request.POST.get("captcha_q3_answer", "").strip().upper()

        required_fields = [
            q1, q1_a, q1_b, q1_c, q1_answer,
            q2, q2_a, q2_b, q2_c, q2_answer,
            q3, q3_a, q3_b, q3_c, q3_answer,
        ]

        if not all(required_fields):
            messages.error(
                request,
                "Please complete all captcha questions, choices, and correct answers."
            )
            return redirect("event_detail", event_id=event.id)

        event.captcha_enabled = True

        event.captcha_q1 = q1
        event.captcha_q1_a = q1_a
        event.captcha_q1_b = q1_b
        event.captcha_q1_c = q1_c
        event.captcha_q1_answer = q1_answer

        event.captcha_q2 = q2
        event.captcha_q2_a = q2_a
        event.captcha_q2_b = q2_b
        event.captcha_q2_c = q2_c
        event.captcha_q2_answer = q2_answer

        event.captcha_q3 = q3
        event.captcha_q3_a = q3_a
        event.captcha_q3_b = q3_b
        event.captcha_q3_c = q3_c
        event.captcha_q3_answer = q3_answer

        event.save()

        messages.success(request, "Captcha quiz saved and enabled.")

    return redirect("event_detail", event_id=event.id)

@login_required
def export_attendance_pdf(request, event_id):
    event = get_object_or_404(Event, id=event_id)

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{event.title}_attendance.pdf"'

    doc = SimpleDocTemplate(
        response,
        pagesize=letter,
        rightMargin=45,
        leftMargin=45,
        topMargin=40,
        bottomMargin=40,
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "TitleStyle",
        parent=styles["Heading1"],
        alignment=TA_CENTER,
        fontSize=16,
        leading=20,
        spaceAfter=18,
    )

    normal_bold = ParagraphStyle(
        "NormalBold",
        parent=styles["Normal"],
        fontSize=11,
        leading=14,
        spaceAfter=8,
    )

    story = []

    logo_path = os.path.join(
    settings.BASE_DIR,
    "static",
    "app",
    "images",
    "snsu_logo.jpg"
)

    header_style = ParagraphStyle(
    "HeaderStyle",
    parent=styles["Normal"],
    fontSize=11,
    leading=13,
    alignment=TA_LEFT,
)

    header_text = Paragraph(
        """
        Republic of the Philippines<br/>
        <b>SURIGAO DEL NORTE STATE UNIVERSITY</b><br/>
        Narciso Street, Surigao City
        """,
        header_style
    )

    if os.path.exists(logo_path):
        logo = Image(logo_path, width=0.78 * inch, height=0.78 * inch)
    else:
        logo = ""

    header_table = Table(
        [[logo, header_text, ""]],
        colWidths=[0.9 * inch, 4.1 * inch, 1.5 * inch],
    )

    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (0, 0), "CENTER"),
        ("ALIGN", (1, 0), (1, 0), "LEFT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    story.append(header_table)
    story.append(Spacer(1, 6))

    line_table = Table(
    [[""]],
    colWidths=[6.55 * inch],
    rowHeights=[9],
    )

    line_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),

        ("LINEABOVE", (0, 0), (-1, -1), 2, colors.green),
        ("LINEBELOW", (0, 0), (-1, -1), 2, colors.green),
    ]))

    story.append(line_table)

    thin_line = Table([[""]], colWidths=[6.25 * inch], rowHeights=[3])
    thin_line.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 1.5, colors.green),
    ]))

    story.append(thin_line)
    story.append(Spacer(1, 18))

    story.append(Paragraph("ATTENDANCE SHEET", title_style))
    story.append(Spacer(1, 10))

    story.append(Paragraph(f"<b>Title of Activity:</b> {event.title}", normal_bold))
    story.append(Paragraph(
        f"<b>Date and Time:</b> {event.event_date.strftime('%B %d, %Y')}",
        normal_bold
    ))
    story.append(Paragraph(f"<b>Venue:</b> {event.venue}", normal_bold))
    story.append(Spacer(1, 12))

    # Table header
    data = [
        ["NO.", "NAME", "CAMPUS", "M", "F", "STATUS"]
    ]

    entries = event.entries.all().order_by("name")

    for index, entry in enumerate(entries, start=1):
        status = "PRESENT" if entry.check_in and entry.check_out else "CHECKED IN"

        male_mark = "✓" if entry.sex == "M" else ""
        female_mark = "✓" if entry.sex == "F" else ""

        data.append([
            str(index),
            entry.name.upper(),
            entry.campus,
            male_mark,
            female_mark,
            status,
        ])

    # Add empty rows if fewer than 5, like your template
    while len(data) < 6:
        data.append([str(len(data)) + ".", "", "", "", "", ""])

    table = Table(
        data,
        colWidths=[
            0.6 * inch,
            2.0 * inch,
            1.1 * inch,
            0.45 * inch,
            0.45 * inch,
            1.6 * inch,
        ],
    )

    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 1, colors.black),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),

        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 12),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 8),

        ("FONTNAME", (0, 1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 1), (-1, -1), 10),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white]),

        ("TEXTCOLOR", (3, 1), (4, -1), colors.green),
    ]))

    story.append(table)

    doc.build(story)

    return response