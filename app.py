"""
College Leaving Certificate System — Flask Application (v2 Smart Edition)
New features: QR code on PDF, Student portal, LC request workflow, Email notifications
"""
import os
from datetime import datetime, date, timedelta
from functools import wraps
from io import BytesIO
import uuid
from werkzeug.utils import secure_filename

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, send_file, abort, jsonify
)
import string
import random
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

import config
import db as database
from pdf_generator import generate_certificate_pdf

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

# ── Security config ───────────────────────────────────────────────────────────
app.config["DEBUG"] = os.getenv("FLASK_DEBUG", "false").lower() == "true"
app.config["WTF_CSRF_ENABLED"] = True
app.config["WTF_CSRF_TIME_LIMIT"] = 3600        # CSRF token valid for 1 hour
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=60)
app.config["SESSION_COOKIE_HTTPONLY"] = True     # Prevent JS access to cookie
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"   # CSRF extra layer
app.config["SESSION_COOKIE_SECURE"] = not app.config["DEBUG"]  # Fix #5: HTTPS-only cookie in prod

# ── CSRF & Rate-Limiter setup ─────────────────────────────────────────────────
csrf = CSRFProtect(app)
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    # Fix #14: use Redis in production for persistence across restarts.
    # Set RATELIMIT_STORAGE_URI=redis://localhost:6379 in .env to upgrade.
    storage_uri=os.getenv("RATELIMIT_STORAGE_URI", "memory://"),
)

# Admin Creds (fallback to environ if desired)
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

# Vercel serverless has a read-only filesystem everywhere except /tmp.
# Use /tmp/uploads when running on Vercel, static/uploads locally.
if os.environ.get("VERCEL"):
    app.config['UPLOAD_FOLDER'] = '/tmp/uploads'
else:
    app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024  # 2 MB limit
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}
# Fix #7: map extension → expected Pillow format for magic-bytes verification
_EXT_TO_FORMAT = {'png': 'PNG', 'jpg': 'JPEG', 'jpeg': 'JPEG', 'pdf': None}

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def allowed_file(filename, file_stream=None):
    """Validate extension AND magic bytes (Fix #7). Pass file_stream for content check."""
    if not filename or '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return False
    if file_stream is not None and ext in ('png', 'jpg', 'jpeg'):
        try:
            from PIL import Image as _PILCheck
            _PILCheck.open(file_stream).verify()
            file_stream.seek(0)   # reset stream after verify
        except Exception:
            return False
    return True

# ── Mail setup ────────────────────────────────────────────────────────────────
app.config.update(
    MAIL_SERVER         = config.MAIL_SERVER,
    MAIL_PORT           = config.MAIL_PORT,
    MAIL_USE_TLS        = config.MAIL_USE_TLS,
    MAIL_USERNAME       = config.MAIL_USERNAME,
    MAIL_PASSWORD       = config.MAIL_PASSWORD,
    MAIL_DEFAULT_SENDER = config.MAIL_DEFAULT_SENDER,
)
mail = Mail(app)


# ── Helpers ────────────────────────────────────────────────────────────────────
def send_email(to, subject, body_html):
    """Send email only when MAIL_ENABLED=true in .env."""
    if not config.MAIL_ENABLED or not to:
        return
    try:
        msg = Message(subject, recipients=[to], html=body_html)
        mail.send(msg)
    except Exception as e:
        app.logger.warning(f"Email send failed: {e}")


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "admin_id" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def student_login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "student_user_id" not in session:
            flash("Please log in to your student account.", "warning")
            return redirect(url_for("student_login"))
        return f(*args, **kwargs)
    return decorated


# ── DB + Admin seed ────────────────────────────────────────────────────────────
_DEFAULT_CREDS = ("admin", "admin123")

def init_app():
    database.init_db()
    existing = database.query(
        "SELECT id FROM admin_users WHERE username = %s",
        (config.ADMIN_USERNAME,), fetchone=True,
    )
    if not existing:
        database.query(
            "INSERT INTO admin_users (username, password_hash) VALUES (%s, %s)",
            (config.ADMIN_USERNAME, generate_password_hash(config.ADMIN_PASSWORD)),
            commit=True,
        )
    # Fix #4: warn loudly when default credentials are still in use
    if config.ADMIN_USERNAME == _DEFAULT_CREDS[0] and config.ADMIN_PASSWORD == _DEFAULT_CREDS[1]:
        app.logger.warning(
            "⚠️  SECURITY WARNING: Default admin credentials (admin/admin123) are active. "
            "Set ADMIN_USERNAME and ADMIN_PASSWORD in your .env file immediately."
        )


# Initialize the database immediately so it works with Gunicorn
init_app()


# ── Fix #13: Content-Security-Policy header ───────────────────────────────────
@app.after_request
def set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com https://cdn.jsdelivr.net; "
        "img-src 'self' data:; "
        "connect-src 'self';"
    )
    return response

# ═══════════════════════════════════════════════════════════════════════════════
#  ADMIN AUTH
# ═══════════════════════════════════════════════════════════════════════════════
@app.route("/")
def index():
    # Default landing: student login
    if "student_user_id" in session:
        return redirect(url_for("student_dashboard"))
    if "admin_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("student_login"))

# Fix #12: removed unauthenticated /test debug route


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def login():
    if "admin_id" in session:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = database.query(
            "SELECT * FROM admin_users WHERE username = %s",
            (username,), fetchone=True,
        )
        if user and check_password_hash(user["password_hash"], password):
            session.permanent = True
            session["admin_id"]       = user["id"]
            session["admin_username"] = user["username"]
            session["role"]           = "admin"
            flash(f"Welcome back, {user['username']}!", "success")
            database.log_action("admin_login", admin_id=user["id"], ip=request.remote_addr)
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("student_login"))

# Fix #2: rate-limit forgot-password to prevent abuse
@app.route("/forgot-password", methods=["GET", "POST"])
@limiter.limit("3 per minute", methods=["POST"])
def forgot_password():
    if request.method == "POST":
        import secrets as _secrets
        role     = request.form.get("role", "student")
        username = request.form.get("username", "").strip()

        # Fix #9: use cryptographically secure PRNG
        new_pwd = _secrets.token_urlsafe(10)          # ~13 characters
        hashed  = generate_password_hash(new_pwd)

        # Fix #8: always show the SAME generic message — prevents username enumeration
        _GENERIC_MSG = ("If that username exists, a password reset has been sent or displayed. "
                        "Check your email or contact the admin office.")

        if role == "student":
            user = database.query(
                "SELECT id, email FROM student_users WHERE username = %s",
                (username,), fetchone=True
            )
            if user:
                database.query(
                    "UPDATE student_users SET password_hash = %s WHERE id = %s",
                    (hashed, user["id"]), commit=True
                )
                if user.get("email"):
                    send_email(
                        to=user["email"],
                        subject="DLCS - Password Reset",
                        body_html=(
                            f"<p>Hello,</p>"
                            f"<p>Your student portal password has been reset."
                            f" Your new temporary password is: <strong>{new_pwd}</strong></p>"
                            f"<p>Please log in and change it immediately.</p>"
                        )
                    )
                else:
                    # No email on file — log server-side only (Fix #3 analogue for students)
                    app.logger.info(
                        f"Password reset for student '{username}': {new_pwd} (no email)"
                    )
        elif role == "admin":
            user = database.query(
                "SELECT id, email FROM admin_users WHERE username = %s",
                (username,), fetchone=True
            )
            if user:
                database.query(
                    "UPDATE admin_users SET password_hash = %s WHERE id = %s",
                    (hashed, user["id"]), commit=True
                )
                admin_email = user.get("email")
                if admin_email:
                    # Fix #3: email the temp password instead of showing it in a flash
                    send_email(
                        to=admin_email,
                        subject="DLCS - Admin Password Reset",
                        body_html=(
                            f"<p>Your admin password has been reset.</p>"
                            f"<p>New temporary password: <strong>{new_pwd}</strong></p>"
                            f"<p>Log in and change it immediately.</p>"
                        )
                    )
                else:
                    # Fix #3: log server-side only — never expose in flash
                    app.logger.warning(
                        f"[ADMIN RESET] '{username}' new password: {new_pwd} — no email on file!"
                    )

        # Always redirect with the same message (Fix #8)
        flash(_GENERIC_MSG, "info")
        return redirect(url_for('student_login'))
    return render_template("forgot_password.html")


# ═══════════════════════════════════════════════════════════════════════════════
#  ADMIN DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════
@app.route("/dashboard")
@login_required
def dashboard():
    total_students = database.query(
        "SELECT COUNT(*) AS cnt FROM students WHERE is_deleted = %s", (False,), fetchone=True
    )
    total_certs = database.query(
        "SELECT COUNT(*) AS cnt FROM certificates", (), fetchone=True
    )
    pending_requests = database.query(
        "SELECT COUNT(*) AS cnt FROM lc_requests WHERE status = %s", ("pending",), fetchone=True
    )
    recent_certs = database.query(
        """SELECT c.certificate_number, c.issue_date, s.name, s.course, s.department
           FROM certificates c JOIN students s ON c.student_id = s.student_id
           ORDER BY c.created_at DESC LIMIT 5""",
        fetchall=True,
    )
    return render_template(
        "dashboard.html",
        total_students   = total_students["cnt"]    if total_students    else 0,
        total_certs      = total_certs["cnt"]       if total_certs       else 0,
        pending_requests = pending_requests["cnt"]  if pending_requests  else 0,
        recent_certs     = recent_certs or [],
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  STUDENTS (ADMIN)
# ═══════════════════════════════════════════════════════════════════════════════
@app.route("/students")
@login_required
def students_list():
    search      = request.args.get("q", "").strip()
    f_dept      = request.args.get("dept", "").strip()
    f_adm_year  = request.args.get("adm_year", "").strip()
    f_leave_year= request.args.get("leave_year", "").strip()
    f_conduct   = request.args.get("conduct", "").strip()
    f_has_cert  = request.args.get("has_cert", "").strip()   # "yes" | "no" | ""
    page        = int(request.args.get("page", 1))
    per_page    = 15
    offset      = (page - 1) * per_page
    like        = f"%{search.lower()}%"

    where_clauses = ["is_deleted = %s"]
    params        = [False]

    if search:
        where_clauses.append("(LOWER(name) LIKE %s OR LOWER(course) LIKE %s OR LOWER(department) LIKE %s)")
        params += [like, like, like]
    if f_dept:
        where_clauses.append("LOWER(department) = %s")
        params.append(f_dept.lower())
    if f_adm_year:
        where_clauses.append("admission_year = %s")
        params.append(int(f_adm_year))
    if f_leave_year:
        where_clauses.append("leaving_year = %s")
        params.append(int(f_leave_year))
    if f_conduct:
        where_clauses.append("LOWER(conduct) = %s")
        params.append(f_conduct.lower())

    where_sql = " AND ".join(where_clauses)

    if f_has_cert == "yes":
        base_sql = f"SELECT s.* FROM students s WHERE {where_sql} AND EXISTS (SELECT 1 FROM certificates c WHERE c.student_id = s.student_id)"
        count_sql = f"SELECT COUNT(*) AS cnt FROM students s WHERE {where_sql} AND EXISTS (SELECT 1 FROM certificates c WHERE c.student_id = s.student_id)"
    elif f_has_cert == "no":
        base_sql = f"SELECT s.* FROM students s WHERE {where_sql} AND NOT EXISTS (SELECT 1 FROM certificates c WHERE c.student_id = s.student_id)"
        count_sql = f"SELECT COUNT(*) AS cnt FROM students s WHERE {where_sql} AND NOT EXISTS (SELECT 1 FROM certificates c WHERE c.student_id = s.student_id)"
    else:
        base_sql  = f"SELECT * FROM students WHERE {where_sql}"
        count_sql = f"SELECT COUNT(*) AS cnt FROM students WHERE {where_sql}"

    students = database.query(
        base_sql + " ORDER BY student_id DESC LIMIT %s OFFSET %s",
        params + [per_page, offset], fetchall=True,
    )
    total = database.query(count_sql, params, fetchone=True)

    # Distinct values for filter dropdowns
    depts       = database.query("SELECT DISTINCT department FROM students WHERE is_deleted=0 OR is_deleted=false ORDER BY department", fetchall=True) or []
    adm_years   = database.query("SELECT DISTINCT admission_year FROM students WHERE is_deleted=0 OR is_deleted=false ORDER BY admission_year DESC", fetchall=True) or []
    leave_years = database.query("SELECT DISTINCT leaving_year FROM students WHERE is_deleted=0 OR is_deleted=false ORDER BY leaving_year DESC", fetchall=True) or []

    total_count = total["cnt"] if total else 0
    total_pages = max(1, (total_count + per_page - 1) // per_page)
    active_filters = any([f_dept, f_adm_year, f_leave_year, f_conduct, f_has_cert])
    return render_template("students/list.html", students=students or [], search=search,
                           page=page, total_pages=total_pages, total_count=total_count,
                           f_dept=f_dept, f_adm_year=f_adm_year, f_leave_year=f_leave_year,
                           f_conduct=f_conduct, f_has_cert=f_has_cert,
                           depts=depts, adm_years=adm_years, leave_years=leave_years,
                           active_filters=active_filters)


# ── Bulk Certificate Generation ──────────────────────────────────────────────
@app.route("/certificates/bulk-generate", methods=["POST"])
@login_required
def certificates_bulk_generate():
    """Generate certificates for selected students and return as a ZIP archive."""
    import zipfile
    student_ids = request.form.getlist("student_ids")
    if not student_ids:
        flash("No students selected.", "warning")
        return redirect(url_for("students_list"))

    zip_buffer = BytesIO()
    generated = 0
    skipped   = 0
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for sid in student_ids:
            try:
                sid = int(sid)
                cert_id, cert_number = _do_generate(sid, session.get("admin_username", "admin"))
                if not cert_id:
                    skipped += 1
                    continue
                student = database.query(
                    "SELECT * FROM students WHERE student_id = %s", (sid,), fetchone=True
                )
                cert = database.query(
                    "SELECT * FROM certificates WHERE certificate_id = %s", (cert_id,), fetchone=True
                )
                pdf_bytes = generate_certificate_pdf(student, cert)
                safe_name = student["name"].replace(" ", "_")
                zf.writestr(f"LC_{safe_name}_{cert_number}.pdf", pdf_bytes)
                database.log_action("cert_generated", admin_id=session.get("admin_id"),
                                     student_id=sid, certificate_id=cert_id, ip=request.remote_addr)
                generated += 1
            except Exception as e:
                app.logger.warning(f"Bulk generate failed for student {sid}: {e}")
                skipped += 1

    zip_buffer.seek(0)
    flash(f"Bulk generation complete: {generated} certificates generated, {skipped} skipped.", "success" if generated else "warning")
    from datetime import datetime as _dt
    filename = f"DLCS_Bulk_Certificates_{_dt.today().strftime('%Y%m%d')}.zip"
    return send_file(zip_buffer, mimetype="application/zip",
                     as_attachment=True, download_name=filename)



@app.route("/students/add", methods=["GET", "POST"])
@login_required
def students_add():
    if request.method == "POST":
        f = request.form
        
        dob_date = f.get("dob_date", "")
        dob_month = f.get("dob_month", "")
        dob_year = f.get("dob_year", "")
        dob = f"{dob_year}-{dob_month}-{dob_date}" if dob_year and dob_month and dob_date else f.get("dob", "")
        
        dept = f.get("department", "").strip()
        if dept == "Other":
            dept = f.get("other_department", "Other").strip()
            
        gap_applicable = True if f.get("gap_year_applicable") else False
        gap_years = int(f.get("gap_years", 0)) if gap_applicable and f.get("gap_years") else 0
        
        gap_cert_path = None
        if gap_applicable and 'gap_certificate' in request.files:
            file = request.files['gap_certificate']
            # Fix #7: Pass file.stream to verify magic bytes for image uploads
            if file and file.filename != '' and allowed_file(file.filename, file.stream):
                filename = secure_filename(file.filename)
                unique_filename = f"{uuid.uuid4().hex}_{filename}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
                gap_cert_path = f"uploads/{unique_filename}"
            elif file and file.filename != '':
                flash("Invalid file type or corrupted image.", "danger")
                return render_template("students/add.html")
                
        try:
            database.query(
                """INSERT INTO students
                   (name,father_name,mother_name,dob,gender,address,
                    course,department,admission_year,admission_type,passing_year,leaving_year,
                    leaving_date,reason_for_leaving,conduct,academic_status,
                    gap_year_applicable,gap_years,gap_certificate_path,email,phone)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    f["name"].strip(), f["father_name"].strip(),
                    f.get("mother_name","").strip() or None,
                    dob, f.get("gender",""),
                    f.get("address","").strip() or None,
                    f["course"].strip(), dept,
                    int(f["admission_year"]), f.get("admission_type", "First Year"),
                    int(f["passing_year"]) if f.get("passing_year") else None,
                    int(f["leaving_year"]),
                    f.get("leaving_date") or None,
                    f.get("reason_for_leaving","").strip() or None,
                    f.get("conduct","Good"),
                    f.get("academic_status","Regular"),
                    gap_applicable, gap_years, gap_cert_path,
                    f.get("email","").strip() or None,
                    f.get("phone","").strip() or None,
                ),
                commit=True,
            )
            flash("Student added successfully!", "success")
            return redirect(url_for("students_list"))
        except Exception as e:
            # Fix #15: Don't leak raw DB exception (like schema names) to UI
            app.logger.error(f"Error adding student: {e}")
            flash("Error adding student. Please check your inputs or try again.", "danger")
    return render_template("students/add.html")


@app.route("/students/<int:student_id>")
@login_required
def students_view(student_id):
    student = database.query(
        "SELECT * FROM students WHERE student_id = %s AND is_deleted = %s",
        (student_id, False), fetchone=True,
    )
    if not student:
        abort(404)
    certs = database.query(
        "SELECT * FROM certificates WHERE student_id = %s ORDER BY created_at DESC",
        (student_id,), fetchall=True,
    )
    has_portal = database.query(
        "SELECT id FROM student_users WHERE student_id = %s", (student_id,), fetchone=True
    )
    return render_template("students/view.html", student=student,
                           certs=certs or [], has_portal=bool(has_portal))


@app.route("/students/<int:student_id>/edit", methods=["GET", "POST"])
@login_required
def students_edit(student_id):
    student = database.query(
        "SELECT * FROM students WHERE student_id = %s AND is_deleted = %s",
        (student_id, False), fetchone=True,
    )
    if not student:
        abort(404)
    if request.method == "POST":
        f = request.form
        
        dob_date = f.get("dob_date", "")
        dob_month = f.get("dob_month", "")
        dob_year = f.get("dob_year", "")
        dob = f"{dob_year}-{dob_month}-{dob_date}" if dob_year and dob_month and dob_date else f.get("dob", "")
        
        dept = f.get("department", "").strip()
        if dept == "Other":
            dept = f.get("other_department", "Other").strip()
            
        gap_applicable = True if f.get("gap_year_applicable") else False
        gap_years = int(f.get("gap_years", 0)) if gap_applicable and f.get("gap_years") else 0
        
        gap_cert_path = student.get("gap_certificate_path")
        if gap_applicable and 'gap_certificate' in request.files:
            file = request.files['gap_certificate']
            # Fix #7: Magic bytes verification
            if file and file.filename != '' and allowed_file(file.filename, file.stream):
                filename = secure_filename(file.filename)
                unique_filename = f"{uuid.uuid4().hex}_{filename}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
                gap_cert_path = f"uploads/{unique_filename}"
            elif file and file.filename != '':
                flash("Invalid file type or corrupted image.", "danger")
                return render_template("students/edit.html", student=student)
                
        try:
            database.query(
                """UPDATE students SET name=%s,father_name=%s,mother_name=%s,dob=%s,gender=%s,
                   address=%s,course=%s,department=%s,admission_year=%s,admission_type=%s,passing_year=%s,
                   leaving_year=%s,leaving_date=%s,reason_for_leaving=%s,conduct=%s,academic_status=%s,
                   gap_year_applicable=%s,gap_years=%s,gap_certificate_path=%s,email=%s,phone=%s WHERE student_id=%s""",
                (
                    f["name"].strip(), f["father_name"].strip(),
                    f.get("mother_name","").strip() or None,
                    dob, f.get("gender",""),
                    f.get("address","").strip() or None,
                    f["course"].strip(), dept,
                    int(f["admission_year"]), f.get("admission_type", "First Year"),
                    int(f["passing_year"]) if f.get("passing_year") else None,
                    int(f["leaving_year"]),
                    f.get("leaving_date") or None,
                    f.get("reason_for_leaving","").strip() or None,
                    f.get("conduct","Good"),
                    f.get("academic_status","Regular"),
                    gap_applicable, gap_years, gap_cert_path,
                    f.get("email","").strip() or None,
                    f.get("phone","").strip() or None,
                    student_id,
                ),
                commit=True,
            )
            flash("Student updated successfully!", "success")
            return redirect(url_for("students_view", student_id=student_id))
        except Exception as e:
            # Fix #15: Prevent schema leak
            app.logger.error(f"Error updating student {student_id}: {e}")
            flash("Error updating student. Please check your inputs or try again.", "danger")
    return render_template("students/edit.html", student=student)


@app.route("/students/<int:student_id>/delete", methods=["POST"])
@login_required
def students_delete(student_id):
    database.query(
        "UPDATE students SET is_deleted = %s WHERE student_id = %s",
        (True, student_id), commit=True,
    )
    flash("Student record removed.", "info")
    return redirect(url_for("students_list"))


@app.route("/students/<int:student_id>/create-portal", methods=["POST"])
@login_required
def create_student_portal(student_id):
    """Create a student portal account so they can log in and request LCs."""
    student = database.query(
        "SELECT * FROM students WHERE student_id = %s AND is_deleted = %s",
        (student_id, False), fetchone=True,
    )
    if not student:
        abort(404)
    existing = database.query(
        "SELECT id FROM student_users WHERE student_id = %s", (student_id,), fetchone=True
    )
    if existing:
        flash("Portal account already exists for this student.", "warning")
        return redirect(url_for("students_view", student_id=student_id))

    username = f"stu{student_id:04d}"
    # Default password = student's DOB without dashes (e.g. 20020615)
    raw_dob = str(student.get("dob", "")).replace("-", "")
    password = raw_dob if raw_dob else "student123"
    hashed   = generate_password_hash(password)

    database.query(
        "INSERT INTO student_users (student_id, username, password_hash, email) VALUES (%s,%s,%s,%s)",
        (student_id, username, hashed, student.get("email")),
        commit=True,
    )
    flash(
        f"Portal account created! Username: {username}  |  Password: {password}",
        "success"
    )
    return redirect(url_for("students_view", student_id=student_id))


# ═══════════════════════════════════════════════════════════════════════════════
#  CERTIFICATES (ADMIN)
# ═══════════════════════════════════════════════════════════════════════════════
def _do_generate(student_id, generated_by, request_id=None):
    """Core certificate generation logic — shared by admin and request approval."""
    student = database.query(
        "SELECT * FROM students WHERE student_id = %s AND is_deleted = %s",
        (student_id, False), fetchone=True,
    )
    if not student:
        return None, None

    conn, db_type = database.get_connection()
    try:
        cert_number = database.next_cert_number(conn, db_type)
        today       = date.today().isoformat()
        cur = conn.cursor()
        if db_type == "postgres":
            cur.execute(
                """INSERT INTO certificates (student_id, certificate_number, issue_date, generated_by)
                   VALUES (%s,%s,%s,%s) RETURNING certificate_id""",
                (student_id, cert_number, today, generated_by),
            )
            cert_id = cur.fetchone()[0]
        else:
            cur.execute(
                """INSERT INTO certificates (student_id, certificate_number, issue_date, generated_by)
                   VALUES (?,?,?,?)""",
                (student_id, cert_number, today, generated_by),
            )
            cert_id = cur.lastrowid

        # If tied to a request, mark it approved
        if request_id:
            if db_type == "postgres":
                cur.execute(
                    "UPDATE lc_requests SET status='approved', certificate_id=%s WHERE request_id=%s",
                    (cert_id, request_id),
                )
            else:
                cur.execute(
                    "UPDATE lc_requests SET status='approved', certificate_id=? WHERE request_id=?",
                    (cert_id, request_id),
                )

        conn.commit()
    finally:
        conn.close()

    # Email notification
    student_email = student.get("email")
    send_email(
        to       = student_email,
        subject  = f"Your Leaving Certificate is Ready — {cert_number}",
        body_html= f"""
        <h2>Leaving Certificate Generated</h2>
        <p>Dear <strong>{student['name']}</strong>,</p>
        <p>Your Leaving Certificate has been generated successfully.</p>
        <p><strong>Certificate Number:</strong> {cert_number}</p>
        <p>You can verify your certificate at:<br>
           <a href="{config.APP_BASE_URL}/verify/{cert_number}">
           {config.APP_BASE_URL}/verify/{cert_number}</a></p>
        <p>Regards,<br>{config.COLLEGE_NAME}</p>
        """,
    )
    return cert_id, cert_number


@app.route("/certificates/generate/<int:student_id>", methods=["POST"])
@login_required
def certificates_generate(student_id):
    cert_id, cert_number = _do_generate(
        student_id, session.get("admin_username", "admin")
    )
    if not cert_id:
        abort(404)
    database.log_action("cert_generated", admin_id=session.get("admin_id"),
                        student_id=student_id, certificate_id=cert_id, ip=request.remote_addr)
    flash(f"Certificate {cert_number} generated successfully!", "success")
    return redirect(url_for("certificates_download", cert_id=cert_id))


@app.route("/certificates/download/<int:cert_id>")
@login_required
def certificates_download(cert_id):
    cert    = database.query("SELECT * FROM certificates WHERE certificate_id = %s", (cert_id,), fetchone=True)
    if not cert:
        abort(404)
    student = database.query("SELECT * FROM students WHERE student_id = %s", (cert["student_id"],), fetchone=True)
    if not student:
        abort(404)
    pdf_bytes = generate_certificate_pdf(student, cert)
    filename  = f"LC_{student['name'].replace(' ','_')}_{cert['certificate_number']}.pdf"
    return send_file(BytesIO(pdf_bytes), mimetype="application/pdf",
                     as_attachment=False, download_name=filename)


@app.route("/certificates/download/<int:cert_id>/save")
@login_required
def certificates_save(cert_id):
    cert    = database.query("SELECT * FROM certificates WHERE certificate_id = %s", (cert_id,), fetchone=True)
    if not cert:
        abort(404)
    student = database.query("SELECT * FROM students WHERE student_id = %s", (cert["student_id"],), fetchone=True)
    if not student:
        abort(404)
    pdf_bytes = generate_certificate_pdf(student, cert)
    filename  = f"LC_{student['name'].replace(' ','_')}_{cert['certificate_number']}.pdf"
    return send_file(BytesIO(pdf_bytes), mimetype="application/pdf",
                     as_attachment=True, download_name=filename)


@app.route("/certificates")
@login_required
def certificates_list():
    certs = database.query(
        """SELECT c.*, s.name AS student_name, s.course, s.department
           FROM certificates c JOIN students s ON c.student_id = s.student_id
           ORDER BY c.created_at DESC""",
        fetchall=True,
    )
    return render_template("certificates/list.html", certs=certs or [])


# ── Public QR Verification ────────────────────────────────────────────────────
@app.route("/verify/<cert_number>")
def verify_certificate(cert_number):
    cert = database.query(
        "SELECT * FROM certificates WHERE certificate_number = %s", (cert_number,), fetchone=True
    )
    if not cert:
        return render_template("verify.html", valid=False, cert_number=cert_number,
                               now=__import__('datetime').date.today().strftime("%d %B %Y"))
    student = database.query(
        "SELECT * FROM students WHERE student_id = %s", (cert["student_id"],), fetchone=True
    )
    return render_template("verify.html", valid=True, cert=cert, student=student,
                           now=__import__('datetime').date.today().strftime("%d %B %Y"))


# ═══════════════════════════════════════════════════════════════════════════════
#  LC REQUESTS (ADMIN view)
# ═══════════════════════════════════════════════════════════════════════════════
@app.route("/requests")
@login_required
def requests_list():
    reqs = database.query(
        """SELECT r.*, s.name AS student_name, s.course, s.department
           FROM lc_requests r JOIN students s ON r.student_id = s.student_id
           ORDER BY r.created_at DESC""",
        fetchall=True,
    )
    return render_template("requests/list.html", reqs=reqs or [])


@app.route("/requests/<int:request_id>/approve", methods=["POST"])
@login_required
def requests_approve(request_id):
    req = database.query(
        "SELECT * FROM lc_requests WHERE request_id = %s", (request_id,), fetchone=True
    )
    if not req or req["status"] != "pending":
        flash("Request not found or already processed.", "warning")
        return redirect(url_for("requests_list"))

    cert_id, cert_number = _do_generate(
        req["student_id"], session.get("admin_username", "admin"), request_id=request_id
    )
    if cert_id:
        database.log_action("request_approved", admin_id=session.get("admin_id"),
                            student_id=req["student_id"], certificate_id=cert_id, ip=request.remote_addr)
        flash(f"Request approved — Certificate {cert_number} generated!", "success")
    return redirect(url_for("requests_list"))


@app.route("/requests/<int:request_id>/reject", methods=["POST"])
@login_required
def requests_reject(request_id):
    note = request.form.get("admin_note", "").strip()
    final_note = note or "Rejected by admin."
    database.query(
        "UPDATE lc_requests SET status='rejected', admin_note=%s WHERE request_id=%s",
        (final_note, request_id),
        commit=True,
    )
    database.log_action("request_rejected", admin_id=session.get("admin_id"),
                        ip=request.remote_addr)
    # Email the student about the rejection
    req = database.query(
        """SELECT r.*, s.email AS student_email, s.name AS student_name
           FROM lc_requests r JOIN students s ON r.student_id = s.student_id
           WHERE r.request_id = %s""",
        (request_id,), fetchone=True,
    )
    if req and req.get("student_email"):
        send_email(
            to=req["student_email"],
            subject="Your LC Request Has Been Rejected",
            body_html=f"""
            <h2>LC Request Update</h2>
            <p>Dear <strong>{req['student_name']}</strong>,</p>
            <p>Unfortunately, your Leaving Certificate request has been <strong>rejected</strong> by the administration.</p>
            <p><strong>Reason:</strong> {final_note}</p>
            <p>If you believe this is an error, please visit the college admin office or re-submit your request with the required corrections.</p>
            <p>Regards,<br>{config.COLLEGE_NAME}</p>
            """,
        )
    flash("Request rejected.", "info")
    return redirect(url_for("requests_list"))


# ═══════════════════════════════════════════════════════════════════════════════
#  STUDENT PORTAL
# ═══════════════════════════════════════════════════════════════════════════════
@app.route("/student/login", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def student_login():
    if "student_user_id" in session:
        return redirect(url_for("student_dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = database.query(
            "SELECT * FROM student_users WHERE username = %s", (username,), fetchone=True
        )
        if user and check_password_hash(user["password_hash"], password):
            session.permanent = True
            session["student_user_id"] = user["id"]
            session["student_id"]      = user["student_id"]
            session["role"]            = "student"
            flash("Welcome to your LC Portal!", "success")
            return redirect(url_for("student_dashboard"))
        flash("Invalid username or password.", "danger")
    return render_template("student/login.html")


@app.route("/student/dashboard")
@student_login_required
def student_dashboard():
    student_id = session["student_id"]
    student    = database.query(
        "SELECT * FROM students WHERE student_id = %s", (student_id,), fetchone=True
    )
    requests   = database.query(
        """SELECT r.*, c.certificate_number FROM lc_requests r
           LEFT JOIN certificates c ON r.certificate_id = c.certificate_id
           WHERE r.student_id = %s ORDER BY r.created_at DESC""",
        (student_id,), fetchall=True,
    )
    certs = database.query(
        "SELECT * FROM certificates WHERE student_id = %s ORDER BY created_at DESC",
        (student_id,), fetchall=True,
    )
    return render_template("student/dashboard.html", student=student,
                           requests=requests or [], certs=certs or [])


@app.route("/student/request-lc", methods=["POST"])
@student_login_required
def student_request_lc():
    student_id = session["student_id"]
    # Fix #10: verify student record is active (not soft-deleted)
    active_student = database.query(
        "SELECT student_id FROM students WHERE student_id = %s AND is_deleted = %s",
        (student_id, False), fetchone=True,
    )
    if not active_student:
        session.clear()
        flash("Your account is no longer active. Please contact the admin office.", "danger")
        return redirect(url_for("student_login"))

    # Block if a pending request already exists
    existing = database.query(
        "SELECT request_id FROM lc_requests WHERE student_id=%s AND status='pending'",
        (student_id,), fetchone=True,
    )
    if existing:
        flash("You already have a pending LC request. Please wait for admin approval.", "warning")
        return redirect(url_for("student_dashboard"))

    reason = request.form.get("reason", "").strip()
    database.query(
        "INSERT INTO lc_requests (student_id, reason) VALUES (%s, %s)",
        (student_id, reason or "Student request"), commit=True,
    )
    flash("LC request submitted! You will be notified once it's approved.", "success")
    return redirect(url_for("student_dashboard"))


@app.route("/student/download/<int:cert_id>")
@student_login_required
def student_download_cert(cert_id):
    cert = database.query(
        "SELECT * FROM certificates WHERE certificate_id = %s", (cert_id,), fetchone=True
    )
    if not cert or cert["student_id"] != session["student_id"]:
        abort(403)
    student   = database.query(
        "SELECT * FROM students WHERE student_id = %s", (cert["student_id"],), fetchone=True
    )
    pdf_bytes = generate_certificate_pdf(student, cert)
    filename  = f"LC_{student['name'].replace(' ','_')}_{cert['certificate_number']}.pdf"
    return send_file(BytesIO(pdf_bytes), mimetype="application/pdf",
                     as_attachment=True, download_name=filename)


@app.route("/student/logout")
def student_logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("student_login"))


@app.route("/student/register", methods=["GET", "POST"])
def student_register():
    if "student_user_id" in session:
        return redirect(url_for("student_dashboard"))
    if request.method == "POST":
        f = request.form
        username = f.get("username", "").strip().lower()
        password = f.get("password", "")
        confirm  = f.get("confirm_password", "")

        # Validations
        if not username or not password:
            flash("Username and password are required.", "danger")
            return render_template("student/register.html")
        if password != confirm:
            flash("Passwords do not match.", "danger")
            return render_template("student/register.html")
        if len(password) < 6:
            flash("Password must be at least 6 characters.", "danger")
            return render_template("student/register.html")

        # Check username unique across both student_users and pending registrations
        existing_user = database.query(
            "SELECT id FROM student_users WHERE username = %s", (username,), fetchone=True
        )
        existing_reg = database.query(
            "SELECT reg_id FROM student_registrations WHERE username = %s", (username,), fetchone=True
        )
        if existing_user or existing_reg:
            flash("Username already taken. Please choose another.", "danger")
            return render_template("student/register.html")

        dob_date = f.get("dob_date", "")
        dob_month = f.get("dob_month", "")
        dob_year = f.get("dob_year", "")
        dob = f"{dob_year}-{dob_month}-{dob_date}" if dob_year and dob_month and dob_date else f.get("dob", "")
        
        dept = f.get("department", "").strip()
        if dept == "Other":
            dept = f.get("other_department", "Other").strip()
            
        gap_applicable = True if f.get("gap_year_applicable") else False
        gap_years = int(f.get("gap_years", 0)) if gap_applicable and f.get("gap_years") else 0
        
        gap_cert_path = None
        if gap_applicable and 'gap_certificate' in request.files:
            file = request.files['gap_certificate']
            # Fix #7: pass stream for Pillow magic-byte checks
            if file and file.filename != '' and allowed_file(file.filename, file.stream):
                filename = secure_filename(file.filename)
                unique_filename = f"{uuid.uuid4().hex}_{filename}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
                gap_cert_path = f"uploads/{unique_filename}"
            elif file and file.filename != '':
                flash("Invalid gap certificate file. Please upload a valid image or PDF.", "danger")
                return render_template("student/register.html")

        try:
            database.query(
                """INSERT INTO student_registrations
                   (name, father_name, mother_name, dob, gender, address,
                    course, department, admission_year, admission_type, passing_year, leaving_year,
                    leaving_date, reason_for_leaving, conduct, academic_status,
                    gap_year_applicable, gap_years, gap_certificate_path,
                    email, phone, username, password_hash)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    f["name"].strip(), f["father_name"].strip(),
                    f.get("mother_name", "").strip() or None,
                    dob, f.get("gender", ""),
                    f.get("address", "").strip() or None,
                    f["course"].strip(), dept,
                    int(f["admission_year"]), f.get("admission_type", "First Year"),
                    int(f["passing_year"]) if f.get("passing_year") else None,
                    int(f["leaving_year"]),
                    f.get("leaving_date") or None,
                    f.get("reason_for_leaving", "").strip() or None,
                    f.get("conduct", "Good"),
                    f.get("academic_status", "Regular"),
                    gap_applicable, gap_years, gap_cert_path,
                    f.get("email", "").strip() or None,
                    f.get("phone", "").strip() or None,
                    username,
                    generate_password_hash(password),
                ),
                commit=True,
            )
            flash("Registration submitted! The college admin will review and activate your account. Please check back later.", "success")
            return redirect(url_for("student_login"))
        except Exception as e:
            # Fix #15: Prevent DB error/schema text leaking to the user
            app.logger.error(f"Registration failed for {username}: {e}")
            flash("Registration failed due to a server error. Please try again later.", "danger")

    return render_template("student/register.html")


# ── Admin: Registration approvals ──────────────────────────────────────────────
@app.route("/registrations")
@login_required
def registrations_list():
    regs = database.query(
        "SELECT * FROM student_registrations ORDER BY created_at DESC",
        fetchall=True,
    )
    return render_template("registrations/list.html", regs=regs or [])

@app.route("/registrations/<int:reg_id>")
@login_required
def registrations_view(reg_id):
    reg = database.query("SELECT * FROM student_registrations WHERE reg_id = %s", (reg_id,), fetchone=True)
    if not reg:
        abort(404)
    return render_template("registrations/view.html", reg=reg)

@app.route("/registrations/<int:reg_id>/approve", methods=["POST"])
@login_required
def registrations_approve(reg_id):
    reg = database.query(
        "SELECT * FROM student_registrations WHERE reg_id = %s", (reg_id,), fetchone=True
    )
    if not reg or reg["status"] != "pending":
        flash("Registration not found or already processed.", "warning")
        return redirect(url_for("registrations_list"))

    try:
        # 1. Create student record
        database.query(
            """INSERT INTO students
               (name, father_name, mother_name, dob, gender, address,
                course, department, admission_year, admission_type, passing_year, leaving_year,
                leaving_date, reason_for_leaving, conduct, academic_status, 
                gap_year_applicable, gap_years, gap_certificate_path, email, phone)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                reg["name"], reg["father_name"], reg.get("mother_name"),
                reg["dob"], reg.get("gender"), reg.get("address"),
                reg["course"], reg["department"],
                reg["admission_year"], reg.get("admission_type", "First Year"), reg.get("passing_year"), reg["leaving_year"],
                reg.get("leaving_date"), reg.get("reason_for_leaving"),
                reg.get("conduct", "Good"), reg.get("academic_status", "Regular"),
                reg.get("gap_year_applicable", False), reg.get("gap_years", 0), reg.get("gap_certificate_path"),
                reg.get("email"), reg.get("phone"),
            ),
            commit=True,
        )
        # 2. Get new student_id
        new_student = database.query(
            "SELECT student_id FROM students WHERE name=%s ORDER BY student_id DESC LIMIT 1",
            (reg["name"],), fetchone=True,
        )
        student_id = new_student["student_id"]

        # 3. Create portal account
        database.query(
            "INSERT INTO student_users (student_id, username, password_hash, email) VALUES (%s,%s,%s,%s)",
            (student_id, reg["username"], reg["password_hash"], reg.get("email")),
            commit=True,
        )
        # 4. Mark registration approved
        database.query(
            "UPDATE student_registrations SET status='approved' WHERE reg_id=%s",
            (reg_id,), commit=True,
        )
        flash(f"Registration approved! Student '{reg['name']}' can now log in as '{reg['username']}'.", "success")
        database.log_action("registration_approved", admin_id=session.get("admin_id"),
                            student_id=student_id, ip=request.remote_addr)
    except Exception as e:
        flash(f"Approval failed: {e}", "danger")

    return redirect(url_for("registrations_list"))


@app.route("/registrations/<int:reg_id>/reject", methods=["POST"])
@login_required
def registrations_reject(reg_id):
    note = request.form.get("admin_note", "").strip()
    database.query(
        "UPDATE student_registrations SET status='rejected', admin_note=%s WHERE reg_id=%s",
        (note or "Registration rejected by admin.", reg_id),
        commit=True,
    )
    database.log_action("registration_rejected", admin_id=session.get("admin_id"),
                        ip=request.remote_addr)
    flash("Registration rejected.", "info")
    return redirect(url_for("registrations_list"))


# ═══════════════════════════════════════════════════════════════════════════════
#  ANALYTICS
# ═══════════════════════════════════════════════════════════════════════════════
@app.route("/admin/analytics")
@login_required
def admin_analytics():
    from datetime import datetime as _dt
    import calendar

    # Total certs
    total_certs_row = database.query("SELECT COUNT(*) AS cnt FROM certificates", fetchone=True)
    total_certs = total_certs_row["cnt"] if total_certs_row else 0

    # This month
    today = _dt.today()
    month_prefix = today.strftime("%Y-%m")
    this_month_row = database.query(
        "SELECT COUNT(*) AS cnt FROM certificates WHERE created_at LIKE %s",
        (f"{month_prefix}%",), fetchone=True
    )
    this_month_certs = this_month_row["cnt"] if this_month_row else 0

    # Request status counts
    status_rows = database.query(
        "SELECT status, COUNT(*) AS cnt FROM lc_requests GROUP BY status", fetchall=True
    ) or []
    status_map = {r["status"]: r["cnt"] for r in status_rows}
    approved_reqs = status_map.get("approved", 0)
    pending_reqs  = status_map.get("pending", 0)
    rejected_reqs = status_map.get("rejected", 0)

    # Monthly cert counts for past 6 months
    monthly_labels = []
    monthly_data   = []
    for i in range(5, -1, -1):
        mo = today.month - i
        yr = today.year
        while mo <= 0:
            mo += 12
            yr -= 1
        label = f"{calendar.month_abbr[mo]} {yr}"
        prefix = f"{yr}-{mo:02d}"
        row = database.query(
            "SELECT COUNT(*) AS cnt FROM certificates WHERE created_at LIKE %s",
            (f"{prefix}%",), fetchone=True
        )
        monthly_labels.append(label)
        monthly_data.append(row["cnt"] if row else 0)

    # Certs by department
    dept_cert_rows = database.query(
        """SELECT s.department, COUNT(*) AS cnt FROM certificates c
           JOIN students s ON c.student_id = s.student_id
           GROUP BY s.department ORDER BY cnt DESC LIMIT 10""",
        fetchall=True
    ) or []
    dept_cert_labels = [r["department"] for r in dept_cert_rows]
    dept_cert_data   = [r["cnt"] for r in dept_cert_rows]

    # Students by department
    dept_students = database.query(
        """SELECT department, COUNT(*) AS cnt FROM students
           WHERE is_deleted=0 OR is_deleted=false
           GROUP BY department ORDER BY cnt DESC LIMIT 8""",
        fetchall=True
    ) or []

    return render_template("analytics.html",
        total_certs=total_certs, this_month_certs=this_month_certs,
        approved_reqs=approved_reqs, pending_reqs=pending_reqs, rejected_reqs=rejected_reqs,
        monthly_labels=monthly_labels, monthly_data=monthly_data,
        dept_cert_labels=dept_cert_labels, dept_cert_data=dept_cert_data,
        dept_students=dept_students,
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  AUDIT LOG
# ═══════════════════════════════════════════════════════════════════════════════
# Fix #1: allowlist of column names used in WHERE clause — no user string ever
# reaches the SQL query structure itself; only safe parameterised values are used.
_AUDIT_LOG_ALLOWED_ACTIONS = {
    "admin_login", "cert_generated", "request_approved", "request_rejected",
    "registration_approved", "registration_rejected",
}

@app.route("/admin/audit-log")
@login_required
def admin_audit_log():
    f_action    = request.args.get("action", "").strip()
    f_date_from = request.args.get("date_from", "").strip()
    f_date_to   = request.args.get("date_to", "").strip()
    page        = int(request.args.get("page", 1))
    per_page    = 25
    offset      = (page - 1) * per_page

    # Fix #1: Build query with FIXED SQL template — user values only in params
    conds  = []
    params = []
    if f_action and f_action in _AUDIT_LOG_ALLOWED_ACTIONS:
        conds.append("action = %s")
        params.append(f_action)
    elif f_action:                # unknown action — silently ignore (not in allowlist)
        f_action = ""
    if f_date_from:
        conds.append("created_at >= %s")
        params.append(f_date_from)
    if f_date_to:
        conds.append("created_at <= %s")
        params.append(f_date_to + " 23:59:59")

    # Safe: WHERE clause is built from a fixed list of literal strings, never user input
    where_sql = ("WHERE " + " AND ".join(conds)) if conds else ""
    logs = database.query(
        f"SELECT * FROM audit_logs {where_sql} ORDER BY created_at DESC LIMIT %s OFFSET %s",
        params + [per_page, offset], fetchall=True,
    ) or []
    total_row = database.query(
        f"SELECT COUNT(*) AS cnt FROM audit_logs {where_sql}", params, fetchone=True
    )
    total_count = total_row["cnt"] if total_row else 0
    total_pages = max(1, (total_count + per_page - 1) // per_page)

    action_types = database.query(
        "SELECT DISTINCT action FROM audit_logs ORDER BY action", fetchall=True
    ) or []

    return render_template("audit_log.html", logs=logs, page=page,
                           total_pages=total_pages, total_count=total_count,
                           f_action=f_action, f_date_from=f_date_from, f_date_to=f_date_to,
                           action_types=action_types)


# ═══════════════════════════════════════════════════════════════════════════════
#  ERROR HANDLERS
# ═══════════════════════════════════════════════════════════════════════════════
@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404



@app.errorhandler(403)
def forbidden(e):
    return render_template("404.html"), 403


# ════════════════════════════════════════════════════════════════════════════════
#  RATE-LIMIT ERROR HANDLER
# ════════════════════════════════════════════════════════════════════════════════
@app.errorhandler(429)
def ratelimit_handler(e):
    flash("Too many attempts. Please wait a minute and try again.", "danger")
    # Fix #11: remove open-redirect via request.referrer — always redirect to known safe URL
    return redirect(url_for("student_login")), 302


# ═══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(debug=app.config["DEBUG"], host="0.0.0.0", port=port)
