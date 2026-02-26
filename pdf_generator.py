"""
PDF Certificate Generator — v2 with QR Code verification
Uses ReportLab + qrcode + Pillow
"""
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, Image as RLImage,
)
from reportlab.lib.colors import HexColor

import qrcode
from PIL import Image as PILImage

from config import COLLEGE_NAME, COLLEGE_ADDRESS, PRINCIPAL_NAME, APP_BASE_URL

NAVY   = HexColor("#1a237e")
GOLD   = HexColor("#b8860b")
LTGRAY = HexColor("#f5f5f5")
MDGRAY = HexColor("#9e9e9e")
BLACK  = HexColor("#212121")


def _make_qr_image(cert_number: str) -> BytesIO:
    """Generate a QR code pointing to the public verification URL."""
    url = f"{APP_BASE_URL}/verify/{cert_number}"
    qr  = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M,
                         box_size=6, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img: PILImage.Image = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def generate_certificate_pdf(student: dict, certificate: dict) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            rightMargin=2*cm, leftMargin=2*cm,
                            topMargin=1.5*cm, bottomMargin=1.5*cm)

    styles = getSampleStyleSheet()

    title_style   = ParagraphStyle("CertTitle",   parent=styles["Title"],
                                   fontSize=24, textColor=NAVY, spaceAfter=4,
                                   alignment=TA_CENTER, fontName="Helvetica-Bold")
    college_style = ParagraphStyle("CollegeName", fontSize=16, textColor=NAVY,
                                   alignment=TA_CENTER, fontName="Helvetica-Bold", spaceAfter=2)
    address_style = ParagraphStyle("CollegeAddr", fontSize=9,  textColor=MDGRAY,
                                   alignment=TA_CENTER, fontName="Helvetica", spaceAfter=6)
    cert_no_style = ParagraphStyle("CertNo",      fontSize=9,  textColor=BLACK,
                                   alignment=TA_LEFT, fontName="Helvetica")
    body_style    = ParagraphStyle("CertBody",    fontSize=11, textColor=BLACK,
                                   alignment=TA_JUSTIFY, fontName="Helvetica",
                                   leading=18, spaceAfter=6)
    label_style   = ParagraphStyle("FieldLabel",  fontSize=10, textColor=MDGRAY,
                                   fontName="Helvetica-Bold")
    value_style   = ParagraphStyle("FieldValue",  fontSize=10, textColor=BLACK,
                                   fontName="Helvetica")
    sig_style     = ParagraphStyle("SigLabel",    fontSize=10, textColor=BLACK,
                                   alignment=TA_CENTER, fontName="Helvetica-Bold")
    small_center  = ParagraphStyle("SmallCenter", fontSize=7,  textColor=MDGRAY,
                                   alignment=TA_CENTER, fontName="Helvetica")

    def fmt_date(d):
        from datetime import date as _date, datetime
        if not d:
            return "—"
        if isinstance(d, (_date, datetime)):
            return d.strftime("%d %B %Y")
        return str(d)

    story = []

    # ── College header ──────────────────────────────────────────────────────
    import os
    base_dir = os.path.dirname(__file__)
    header_path = os.path.join(base_dir, "static", "img", "header.jpeg")
    
    if os.path.exists(header_path):
        header_img = RLImage(header_path, width=17*cm, height=2.8*cm, kind='proportional')
        story.append(header_table := Table([[header_img]], colWidths=[17*cm]))
        header_table.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER"), ("BOTTOMPADDING", (0,0), (-1,-1), 0)]))
    else:
        logo_path = os.path.join(base_dir, "static", "img", "logo.png")
        if os.path.exists(logo_path):
            logo = RLImage(logo_path, width=2.5*cm, height=2.5*cm)
            header_table = Table([[
                logo,
                [Paragraph(COLLEGE_NAME.upper(), college_style), Paragraph(COLLEGE_ADDRESS, address_style)]
            ]], colWidths=[3*cm, 13*cm])
            header_table.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (1, 0), (1, 0), "CENTER"),
            ]))
            story.append(header_table)
        else:
            story.append(Paragraph(COLLEGE_NAME.upper(), college_style))
            story.append(Paragraph(COLLEGE_ADDRESS, address_style))

    story.append(HRFlowable(width="100%", thickness=2, color=NAVY, spaceAfter=4))
    story.append(HRFlowable(width="100%", thickness=0.5, color=GOLD, spaceAfter=8))

    # Cert number + date
    cert_meta = Table([[
        Paragraph(f"Certificate No: <b>{certificate['certificate_number']}</b>", cert_no_style),
        Paragraph(f"Date: <b>{fmt_date(certificate['issue_date'])}</b>", cert_no_style),
    ]], colWidths=["60%", "40%"])
    cert_meta.setStyle(TableStyle([
        ("ALIGN",  (1, 0), (1, 0), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(cert_meta)
    story.append(Spacer(1, 8))

    # ── Title ───────────────────────────────────────────────────────────────
    story.append(Paragraph("LEAVING CERTIFICATE", title_style))
    story.append(HRFlowable(width="50%", thickness=1, color=GOLD, spaceBefore=2, spaceAfter=8))

    story.append(Paragraph(
        "This is to certify that the following student was enrolled in this institution "
        "and has left the college on the date mentioned below:", body_style,
    ))
    story.append(Spacer(1, 6))

    # ── Student info table ──────────────────────────────────────────────────
    info_rows = [
        ("Full Name",          student.get("name", "")),
        ("Father's Name",      student.get("father_name", "")),
        ("Mother's Name",      student.get("mother_name") or "—"),
        ("Date of Birth",      fmt_date(student.get("dob"))),
        ("Gender",             student.get("gender") or "—"),
        ("Email Address",      student.get("email") or "—"),
        ("Mobile Number",      student.get("phone") or "—"),
        ("Course",             student.get("course", "")),
        ("Department",         student.get("department", "")),
        ("Year of Admission",  str(student.get("admission_year", ""))),
        ("Passing Year",       str(student.get("passing_year", "")) if student.get("passing_year") else "—"),
        ("Year of Leaving",    str(student.get("leaving_year", ""))),
        ("Date of Leaving",    fmt_date(student.get("leaving_date"))),
        ("Reason for Leaving", student.get("reason_for_leaving") or "—"),
        ("Conduct",            student.get("conduct", "Good")),
        ("Academic Status",    student.get("academic_status", "Regular")),
    ]
    if student.get("gap_year_applicable"):
        info_rows.append(("Gap Years", str(student.get("gap_years", ""))))
    table_data = [[Paragraph(lb, label_style), Paragraph(f"  :  {vl}", value_style)]
                  for lb, vl in info_rows]
    info_table = Table(table_data, colWidths=["38%", "62%"])
    info_table.setStyle(TableStyle([
        ("ROWBACKGROUNDS", (0,0), (-1,-1), [LTGRAY, colors.white]),
        ("TOPPADDING",    (0,0), (-1,-1), 2.5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 2.5),
        ("LEFTPADDING",   (0,0), (-1,-1), 8),
        ("RIGHTPADDING",  (0,0), (-1,-1), 8),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("BOX",           (0,0), (-1,-1), 0.5, MDGRAY),
        ("LINEBELOW",     (0,0), (-1,-2), 0.3, MDGRAY),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 10))

    story.append(Paragraph(
        "We wish him/her all the best in future endeavours. This certificate is issued "
        "on request of the student for the purpose he/she may specify.", body_style,
    ))
    story.append(Spacer(1, 16))

    # ── QR Code + Signatures ────────────────────────────────────────────────
    qr_buf    = _make_qr_image(certificate["certificate_number"])
    qr_image  = RLImage(qr_buf, width=2.2*cm, height=2.2*cm)
    verify_url = f"{APP_BASE_URL}/verify/{certificate['certificate_number']}"

    qr_block = Table(
        [[
            qr_image,
            Paragraph(
                f"<b>Verify Online</b><br/>"
                f"<font size='7' color='grey'>{verify_url}</font>",
                ParagraphStyle("QRLabel", fontSize=8, textColor=BLACK,
                               fontName="Helvetica", leading=11),
            ),
        ]],
        colWidths=[2.5*cm, 8*cm],
    )
    qr_block.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("LEFTPADDING", (0,0), (-1,-1), 0),
    ]))

    sign_path = os.path.join(base_dir, "static", "img", "principal_sign.png")
    if os.path.exists(sign_path):
        sign_img = RLImage(sign_path, width=3*cm, height=1.5*cm)
        principal_cell = [sign_img, Paragraph(f"Principal<br/><font size='9' color='grey'>{PRINCIPAL_NAME}</font>", sig_style)]
    else:
        principal_cell = Paragraph(f"Principal<br/><font size='9' color='grey'>{PRINCIPAL_NAME}</font>", sig_style)

    seal_path = os.path.join(base_dir, "static", "img", "seal.png")
    if os.path.exists(seal_path):
        seal_img = RLImage(seal_path, width=2.5*cm, height=2.5*cm, kind='proportional')
        center_cell = seal_img
    else:
        center_cell = Paragraph("Class Teacher / HOD", sig_style)

    sig_table = Table([[
        qr_block,
        center_cell,
        principal_cell,
    ]], colWidths=["35%", "32%", "33%"])
    
    t_style = [
        ("TOPPADDING",  (0,0), (-1,-1), 20),
        ("ALIGN",       (1,0), (2,0),   "CENTER"),
        ("LINEABOVE",   (2,0), (2,0),   0.7, BLACK),
        ("VALIGN",      (0,0), (0,0),   "BOTTOM"),
    ]
    if os.path.exists(seal_path):
        t_style.append(("VALIGN", (1,0), (1,0), "MIDDLE"))
        t_style.append(("TOPPADDING", (1,0), (1,0), 6))
    else:
        t_style.append(("LINEABOVE", (1,0), (1,0), 0.7, BLACK))
        t_style.append(("VALIGN", (1,0), (1,0), "BOTTOM"))
        
    sig_table.setStyle(TableStyle(t_style))
    story.append(sig_table)

    # ── Footer ──────────────────────────────────────────────────────────────
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=0.5, color=MDGRAY))
    story.append(Paragraph(
        f"Generated by: {certificate.get('generated_by','Admin')} &nbsp;|&nbsp; {COLLEGE_NAME} &nbsp;|&nbsp; developed by PB Dev Company",
        small_center,
    ))

    doc.build(story)
    return buf.getvalue()
