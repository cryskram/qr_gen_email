import os
import csv
import uuid
from pathlib import Path
from dotenv import load_dotenv
import qrcode
from supabase import create_client
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.base import MIMEBase
from email import encoders

load_dotenv(override=True)

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_ANON_KEY = os.environ["SUPABASE_ANON_KEY"]
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER = os.environ["SMTP_USER"]
SMTP_PASS = os.environ["SMTP_PASS"]
EMAIL_FROM = os.environ.get("EMAIL_FROM", SMTP_USER)
BASE_SCAN_URL = os.environ.get(
    "BASE_SCAN_URL",
    "https://osweek.bmsceieeecs.in/repogenesis/scan",  # this was the frontend link of the hackathon website
)

DATA_CSV = "dummy.csv"
OUT_DIR = Path("qrcodes")
OUT_DIR.mkdir(exist_ok=True)

supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


def generate_uid():
    return "OSW_RG" + uuid.uuid4().hex[:10].upper()


def qr_for_uid(uid):
    return f"{BASE_SCAN_URL}?id={uid}"


def create_qr_image(payload, out_path: Path):
    qr = qrcode.QRCode(
        version=2,
        error_correction=qrcode.constants.ERROR_CORRECT_Q,
        box_size=10,
        border=2,
    )

    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="darkgreen", back_color="white")
    img.save(out_path)


def participant_exists(email):
    res = (
        supabase.table("participants")
        .select("id")
        .eq("email", email)
        .limit(1)
        .execute()
    )
    return res.data and len(res.data) > 0


def upsert_participant(uid, name, email, phone, team):
    payload = {"id": uid, "name": name, "email": email, "phone": phone, "team": team}

    supabase.table("participants").insert(payload).execute()


def send_email_with_qr(to_email, to_name, uid, png_path: Path):
    subject = f"[RepoGenesis] Your QR Code - {uid}"
    body_html = f"""
    <p>Hi {to_name},</p>
    <p><a href="{qr_for_uid(uid)}">{qr_for_uid(uid)}</a></p>
    <p>Please show this QR code at the registration desk, entry points, and food counters.</p>
    """

    msg = MIMEMultipart()
    msg["From"] = EMAIL_FROM
    msg["To"] = to_email
    msg["Subject"] = subject

    msg.attach(MIMEText(body_html, "html"))

    with open(png_path, "rb") as f:
        img = MIMEImage(f.read())
        img.add_header("Content-ID", "<qrcode>")
        img.add_header("Content-Disposition", "inline", filename=png_path.name)
        msg.attach(img)

    with open(png_path, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{png_path.name}"')
    msg.attach(part)

    smtp = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)
    smtp.ehlo()
    if SMTP_PORT == 587:
        smtp.starttls()
    smtp.login(SMTP_USER, SMTP_PASS)
    smtp.sendmail(EMAIL_FROM, [to_email], msg.as_string())
    smtp.quit()


def main():
    if not Path(DATA_CSV).exists():
        print("CSV not found")
        return

    with open(DATA_CSV, newline="", encoding="utf-8") as csvf:
        reader = csv.DictReader(csvf)
        for row in reader:
            name = row.get("name") or "Participant"
            email = row.get("email")
            phone = row.get("phone", "")
            team = row.get("team", "")

            if not email:
                print(f"Skipping row with no email: {row}")
                continue

            if participant_exists(email):
                print(
                    f"Participant with email {email} already exists in DB - skipping."
                )
                continue

            uid = generate_uid()
            payload = qr_for_uid(uid)
            out_path = OUT_DIR / f"{uid}.png"
            create_qr_image(payload, out_path)
            print(f"Generated QR for {email} -> {out_path}")

            try:
                upsert_participant(uid, name, email, phone, team)
                print(f"Inserted participant {uid} into Supabase.")
            except Exception as e:
                print(f"Error inserting to supabase for {email}: {e}")

            try:
                send_email_with_qr(email, name, uid, out_path)
                print(f"Emailed QR to {email}")
            except Exception as e:
                print(f"Failed to send email to {email}: {e}")


if __name__ == "__main__":
    main()
