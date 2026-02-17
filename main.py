import pymssql
import random
import uuid
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timedelta, date

# =====================================================
# CONFIG
# =====================================================
DB_SERVER = "kano2026.mssql.somee.com"
DB_USER = "Dhvanit_SQLLogin_1"
DB_PASSWORD = "34l95acp9v"
DB_NAME = "kano2026"

# 🔥 PUT YOUR BREVO API KEY HERE
BREVO_API_KEY = "xsmtpsib-f97e32120e8bb5fa6595718d2a33cd17053f4c9fac4ae626ef0f547f2ad3cd8a-NTTjnQiuYhhKt3Wv"

# =====================================================
# FASTAPI INIT
# =====================================================
app = FastAPI()

# =====================================================
# CORS
# =====================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =====================================================
# ROOT
# =====================================================
@app.get("/")
def home():
    return {"message": "API Running"}

# =====================================================
# DB CONNECTION
# =====================================================
def get_connection():
    return pymssql.connect(
        server=DB_SERVER,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        timeout=30
    )

# =====================================================
# UTILS
# =====================================================
def generate_otp():
    return str(random.randint(100000, 999999))

def send_otp_email(email, otp):
    try:
        url = "https://api.brevo.com/v3/smtp/email"

        payload = {
            "sender": {
                "name": "College ERP",
                "email": "patelkanostudent@gmail.com"
            },
            "to": [{"email": email}],
            "subject": "OTP Verification",
            "htmlContent": f"<h2>Your OTP is {otp}</h2><p>Valid for 5 minutes</p>"
        }

        headers = {
            "accept": "application/json",
            "api-key": BREVO_API_KEY,
            "content-type": "application/json"
        }

        res = requests.post(url, json=payload, headers=headers)

        print("EMAIL STATUS:", res.status_code)
        print("EMAIL RESPONSE:", res.text)

    except Exception as e:
        print("EMAIL ERROR:", e)

# =====================================================
# MODELS
# =====================================================
class SendOTP(BaseModel):
    email: str

class OTPVerify(BaseModel):
    email: str
    otp: str

# =====================================================
# SEND OTP
# =====================================================
@app.post("/auth/send-otp")
def send_otp(data: SendOTP):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT UserId FROM Users WHERE Email=%s", (data.email,))
        user = cursor.fetchone()

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        otp = generate_otp()
        expiry = datetime.now() + timedelta(minutes=5)

        cursor.execute("""
            INSERT INTO EmailOTP (Email, OTPCode, ExpiryTime)
            VALUES (%s, %s, %s)
        """, (data.email, otp, expiry))

        conn.commit()

    finally:
        conn.close()

    # 🔥 Send email (no crash)
    try:
        send_otp_email(data.email, otp)
    except Exception as e:
        print("Email failed:", e)

    # 🔥 Also return OTP for testing
    return {
        "message": "OTP sent",
        "otp": otp
    }

# =====================================================
# VERIFY OTP
# =====================================================
@app.post("/auth/verify-otp")
def verify_otp(data: OTPVerify):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT OTPId FROM EmailOTP
            WHERE Email=%s AND OTPCode=%s AND IsUsed=0 AND ExpiryTime>=GETDATE()
        """, (data.email, data.otp))

        otp_row = cursor.fetchone()

        if not otp_row:
            raise HTTPException(status_code=400, detail="Invalid OTP")

        cursor.execute("UPDATE EmailOTP SET IsUsed=1 WHERE OTPId=%s", (otp_row[0],))

        cursor.execute("SELECT UserId, Role FROM Users WHERE Email=%s", (data.email,))
        user = cursor.fetchone()

        token = str(uuid.uuid4())

        cursor.execute("UPDATE LoginSessions SET IsActive=0 WHERE UserId=%s", (user[0],))
        cursor.execute("INSERT INTO LoginSessions (UserId, Token) VALUES (%s, %s)", (user[0], token))

        conn.commit()

        return {
            "login": "success",
            "token": token,
            "user_id": user[0],
            "role": user[1]
        }

    finally:
        conn.close()
