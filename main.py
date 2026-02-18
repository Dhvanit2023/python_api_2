import pyodbc
import random
import uuid
import requests
import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime, timedelta
import firebase_admin
from firebase_admin import credentials, messaging

# =====================================================
# CONFIG (ONLY 2 ENV VARIABLES)
# =====================================================
DB_PASSWORD = os.getenv("DB_PASSWORD")   # 🔥 from Render
BREVO_API_KEY = os.getenv("BREVO_API_KEY")  # 🔥 from Render

DB_CONN_STR = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=kano2026.mssql.somee.com;"
    "DATABASE=kano2026;"
    "UID=Dhvanit_SQLLogin_1;"
    f"PWD={DB_PASSWORD};"
    "Encrypt=yes;"
    "TrustServerCertificate=yes;"
)

EMAIL_FROM = "patelkanostudent@gmail.com"

# =====================================================
# UTILS
# =====================================================
def get_connection():
    return pyodbc.connect(DB_CONN_STR)

def generate_otp():
    return str(random.randint(100000, 999999))

# =====================================================
# BREVO EMAIL FUNCTION
# =====================================================
def send_otp_email(email, otp):
    try:
        url = "https://api.brevo.com/v3/smtp/email"

        payload = {
            "sender": {
                "name": "College ERP",
                "email": EMAIL_FROM
            },
            "to": [{"email": email}],
            "subject": "College ERP Login OTP",
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

        if res.status_code != 201:
            raise Exception("Email sending failed")

    except Exception as e:
        print("Email Error:", e)

# =====================================================
# FASTAPI
# =====================================================
app = FastAPI(title="College ERP Backend")

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

    if cursor.execute("SELECT 1 FROM Users WHERE Email=?", data.student_email).fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="Email already registered")

    if cursor.execute("SELECT 1 FROM StudentProfile WHERE RegistrationNo=?", data.registration_no).fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="Student already registered")

    cursor.execute("""
        INSERT INTO Users (FullName, Email, Role)
        VALUES (?, ?, 'STUDENT')
    """, data.fullname, data.student_email)

    student_id = cursor.execute("SELECT @@IDENTITY").fetchone()[0]

    cursor.execute("""
        INSERT INTO StudentProfile
        (StudentId, RollNo, RegistrationNo, Semester, StudentEmail, ParentEmail)
        VALUES (?, ?, ?, ?, ?, ?)
    """,
    student_id,
    data.roll_no,
    data.registration_no,
    data.semester,
    data.student_email,
    data.parent_email)

    prof = cursor.execute("""
        SELECT p.ProfessorId
        FROM ProfessorProfile p
        LEFT JOIN StudentProfessorMapping sp
        ON sp.ProfessorId = p.ProfessorId AND sp.Semester = ?
        GROUP BY p.ProfessorId
        HAVING COUNT(sp.StudentId) < 7
        ORDER BY COUNT(sp.StudentId)
    """, data.semester).fetchone()

    if not prof:
        conn.close()
        raise HTTPException(status_code=400, detail="No professor available")

    cursor.execute("""
        INSERT INTO StudentProfessorMapping (StudentId, ProfessorId, Semester)
        VALUES (?, ?, ?)
    """, student_id, prof[0], data.semester)

    conn.commit()
    conn.close()

    return {"message": "Student registered", "assigned_professor": prof[0]}

# =====================================================
# SEND OTP
# =====================================================
@app.post("/auth/send-otp")
def send_otp(data: SendOTP):
    conn = get_connection()
    cursor = conn.cursor()

    user = cursor.execute(
        "SELECT UserId FROM Users WHERE Email=? AND IsActive=1",
        data.email
    ).fetchone()

    if not user:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found")

    otp = generate_otp()
    expiry = datetime.now() + timedelta(minutes=5)

    cursor.execute("""
        INSERT INTO EmailOTP (Email, OTPCode, ExpiryTime)
        VALUES (?, ?, ?)
    """, data.email, otp, expiry)

    conn.commit()
    conn.close()

    send_otp_email(data.email, otp)

    return {"message": "OTP sent"}

# =====================================================
# VERIFY OTP
# =====================================================
@app.post("/auth/verify-otp")
def verify_otp(data: OTPVerify):
    conn = get_connection()
    cursor = conn.cursor()

    otp_row = cursor.execute("""
        SELECT OTPId FROM EmailOTP
        WHERE Email=? AND OTPCode=? AND IsUsed=0 AND ExpiryTime>=GETDATE()
    """, data.email, data.otp).fetchone()

    if not otp_row:
        conn.close()
        raise HTTPException(status_code=400, detail="Invalid OTP")

    cursor.execute("UPDATE EmailOTP SET IsUsed=1 WHERE OTPId=?", otp_row[0])

    user = cursor.execute("""
        SELECT UserId, Role FROM Users WHERE Email=? AND IsActive=1
    """, data.email).fetchone()

    token = str(uuid.uuid4())

    cursor.execute("UPDATE LoginSessions SET IsActive=0 WHERE UserId=?", user[0])
    cursor.execute("INSERT INTO LoginSessions (UserId, Token) VALUES (?, ?)", user[0], token)

    conn.commit()
    conn.close()

    return {"login": "success", "token": token, "user_id": user[0], "role": user[1]}
