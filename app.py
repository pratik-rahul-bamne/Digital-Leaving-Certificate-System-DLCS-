"""
College Leaving Certificate System — Flask Application (v2 Smart Edition)
New features: QR code on PDF, Student portal, LC request workflow, Email notifications
"""
import os
from datetime import datetime, date
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

import config
import db as database
from pdf_generator import generate_certificate_pdf

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "fallback_secret_key")

# TEMPORARY DEBUG FLAG FOR RAILWAY
app.config["DEBUG"] = True

# Admin Creds (fallback to environ if desired)
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024  # 2 MB limit
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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


# Initialize the database immediately so it works with Gunicorn
init_app()

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

@app.route("/test")
def test():
    return "App Working ✅"


@app.route("/login", methods=["GET", "POST"])
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
            session["admin_id"]       = user["id"]
            session["admin_username"] = user["username"]
            session["role"]           = "admin"
            flash(f"Welcome back, {user['username']}!", "success")
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("student_login"))

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        role = request.form.get("role", "student")
        username = request.form.get("username", "").strip()
        
        new_pwd = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
        hashed = generate_password_hash(new_pwd)
        
        if role == "student":
            user = database.query("SELECT id, email FROM student_users WHERE username = %s", (username,), fetchone=True)
            if user:
                database.query("UPDATE student_users SET password_hash = %s WHERE id = %s", (hashed, user["id"]), commit=True)
                if user.get("email"):
                    send_email(
                        to=user["email"],
                        subject="DLCS - Password Reset",
                        body_html=f"<p>Hello,</p><p>Your student portal password has been reset. Your new temporary password is: <strong>{new_pwd}</strong></p><p>Please log in.</p>"
                    )
                    flash("Password reset! Check your email for the new password.", "success")
                else:
                    flash(f"Password reset! Your temporary password is: {new_pwd} (No email on file)", "success")
                return redirect(url_for('student_login'))
            else:
                flash("Student username not found.", "danger")
        elif role == "admin":
            user = database.query("SELECT id FROM admin_users WHERE username = %s", (username,), fetchone=True)
            if user:
                database.query("UPDATE admin_users SET password_hash = %s WHERE id = %s", (hashed, user["id"]), commit=True)
                flash(f"Admin password reset! Your temporary password is: {new_pwd}", "success")
                return redirect(url_for('login'))
            else:
                flash("Admin username not found.", "danger")
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
    search   = request.args.get("q", "").strip()
    page     = int(request.args.get("page", 1))
    per_page = 15
    offset   = (page - 1) * per_page
    like     = f"%{search.lower()}%"

    if search:
        students = database.query(
            """SELECT * FROM students WHERE is_deleted = %s AND
               (LOWER(name) LIKE %s OR LOWER(course) LIKE %s OR LOWER(department) LIKE %s)
               ORDER BY student_id DESC LIMIT %s OFFSET %s""",
            (False, like, like, like, per_page, offset), fetchall=True,
        )
        total = database.query(
            """SELECT COUNT(*) AS cnt FROM students WHERE is_deleted = %s AND
               (LOWER(name) LIKE %s OR LOWER(course) LIKE %s OR LOWER(department) LIKE %s)""",
            (False, like, like, like), fetchone=True,
        )
    else:
        students = database.query(
            "SELECT * FROM students WHERE is_deleted = %s ORDER BY student_id DESC LIMIT %s OFFSET %s",
            (False, per_page, offset), fetchall=True,
        )
        total = database.query(
            "SELECT COUNT(*) AS cnt FROM students WHERE is_deleted = %s", (False,), fetchone=True,
        )

    total_count = total["cnt"] if total else 0
    total_pages = max(1, (total_count + per_page - 1) // per_page)
    return render_template("students/list.html", students=students or [], search=search,
                           page=page, total_pages=total_pages, total_count=total_count)


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
            if file and file.filename != '' and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                unique_filename = f"{uuid.uuid4().hex}_{filename}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
                gap_cert_path = f"uploads/{unique_filename}"
                
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
            flash(f"Error adding student: {e}", "danger")
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
            if file and file.filename != '' and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                unique_filename = f"{uuid.uuid4().hex}_{filename}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
                gap_cert_path = f"uploads/{unique_filename}"
                
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
            flash(f"Error updating: {e}", "danger")
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
        return render_template("verify.html", valid=False, cert_number=cert_number)
    student = database.query(
        "SELECT * FROM students WHERE student_id = %s", (cert["student_id"],), fetchone=True
    )
    return render_template("verify.html", valid=True, cert=cert, student=student)


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
        flash(f"Request approved — Certificate {cert_number} generated!", "success")
    return redirect(url_for("requests_list"))


@app.route("/requests/<int:request_id>/reject", methods=["POST"])
@login_required
def requests_reject(request_id):
    note = request.form.get("admin_note", "").strip()
    database.query(
        "UPDATE lc_requests SET status='rejected', admin_note=%s WHERE request_id=%s",
        (note or "Rejected by admin.", request_id),
        commit=True,
    )
    flash("Request rejected.", "info")
    return redirect(url_for("requests_list"))


# ═══════════════════════════════════════════════════════════════════════════════
#  STUDENT PORTAL
# ═══════════════════════════════════════════════════════════════════════════════
@app.route("/student/login", methods=["GET", "POST"])
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
    return render_template("student/dashboard.html", student=student, requests=requests or [])


@app.route("/student/request-lc", methods=["POST"])
@student_login_required
def student_request_lc():
    student_id = session["student_id"]
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
            if file and file.filename != '' and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                unique_filename = f"{uuid.uuid4().hex}_{filename}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
                gap_cert_path = f"uploads/{unique_filename}"

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
            flash(f"Registration failed: {e}", "danger")

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
    flash("Registration rejected.", "info")
    return redirect(url_for("registrations_list"))


# ═══════════════════════════════════════════════════════════════════════════════
#  ERROR HANDLERS
# ═══════════════════════════════════════════════════════════════════════════════
@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


@app.errorhandler(403)
def forbidden(e):
    return render_template("404.html"), 403


# ═══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(debug=True, host="0.0.0.0", port=port)
