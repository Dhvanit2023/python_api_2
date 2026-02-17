import pymssql
import random
import uuid
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timedelta

# =====================================================
# CONFIG
# =====================================================
DB_SERVER = "kano2026.mssql.somee.com"
DB_USER = "Dhvanit_SQLLogin_1"
DB_PASSWORD = "34l95acp9v"
DB_NAME = "kano2026"

# 🔥 PUT YOUR BREVO API KEY HERE
BREVO_API_KEY = "xsmtpsib-f97e32120e8bb5fa6595718d2a33cd17053f4c9fac4ae626ef0f547f2ad3cd8a-13A9Z4SHMzWiaIfF"

# =====================================================
# FASTAPI
# =====================================================
app = FastAPI(title="College ERP Backend")

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

@app.get("/")
def home():
    return {"message": "API running"}

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
            "subject": "College ERP OTP",
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
class StudentRegister(BaseModel):
    fullname: str
    roll_no: int
    registration_no: str
    semester: int
    student_email: str
    parent_email: str

class SendOTP(BaseModel):
    email: str

class OTPVerify(BaseModel):
    email: str
    otp: str

class LeaveApply(BaseModel):
    student_id: int
    from_date: str
    to_date: str
    reason: str

class EmergencyLeave(BaseModel):
    student_id: int
    from_date: str
    to_date: str
    reason: str

class Action(BaseModel):
    leave_id: int
    action: str

# =====================================================
# STUDENT REGISTER
# =====================================================
@app.post("/student/register")
def student_register(data: StudentRegister):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT 1 FROM Users WHERE Email=%s", (data.student_email,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="Email exists")

        cursor.execute("SELECT 1 FROM StudentProfile WHERE RegistrationNo=%s", (data.registration_no,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="Student exists")

        cursor.execute("""
            INSERT INTO Users (FullName, Email, Role)
            VALUES (%s, %s, 'STUDENT')
        """, (data.fullname, data.student_email))

        conn.commit()

        cursor.execute("SELECT SCOPE_IDENTITY()")
        student_id = int(cursor.fetchone()[0])

        cursor.execute("""
            INSERT INTO StudentProfile
            (StudentId, RollNo, RegistrationNo, Semester, StudentEmail, ParentEmail)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            student_id,
            data.roll_no,
            data.registration_no,
            data.semester,
            data.student_email,
            data.parent_email
        ))

        cursor.execute("""
            SELECT TOP 1 p.ProfessorId
            FROM ProfessorProfile p
            LEFT JOIN StudentProfessorMapping sp
            ON sp.ProfessorId = p.ProfessorId AND sp.Semester=%s
            GROUP BY p.ProfessorId
            HAVING COUNT(sp.StudentId) < 7
            ORDER BY COUNT(sp.StudentId)
        """, (data.semester,))

        prof = cursor.fetchone()

        if not prof:
            raise HTTPException(status_code=400, detail="No professor")

        cursor.execute("""
            INSERT INTO StudentProfessorMapping (StudentId, ProfessorId, Semester)
            VALUES (%s, %s, %s)
        """, (student_id, prof[0], data.semester))

        conn.commit()

        return {"message": "Student registered", "professor_id": prof[0]}

    finally:
        conn.close()

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

    # Send email safely
    try:
        send_otp_email(data.email, otp)
    except:
        print("Email failed")

    return {"message": "OTP sent", "otp": otp}

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
