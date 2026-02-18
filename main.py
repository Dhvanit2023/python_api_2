import pymssql
import random
import uuid
import requests
import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime, timedelta
from fastapi.middleware.cors import CORSMiddleware

# =====================================================
# ENV VARIABLES (SET IN RENDER)
# =====================================================
DB_PASSWORD = os.getenv("DB_PASSWORD")
BREVO_API_KEY = os.getenv("BREVO_API_KEY")

# =====================================================
# DB CONFIG
# =====================================================
DB_SERVER = "kano2026.mssql.somee.com"
DB_USER = "Dhvanit_SQLLogin_1"
DB_NAME = "kano2026"

EMAIL_FROM = "patelkanostudent@gmail.com"

# =====================================================
# FASTAPI
# =====================================================
app = FastAPI(title="College ERP Backend")

# =====================================================
# CORS (ANDROID SUPPORT)
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
    return {"message": "API Running 🚀"}

# =====================================================
# DB CONNECTION
# =====================================================
def get_connection():
    try:
        return pymssql.connect(
            server=DB_SERVER,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            timeout=30
        )
    except Exception as e:
        print("DB ERROR:", e)
        raise HTTPException(status_code=500, detail="Database connection failed")

# =====================================================
# UTILS
# =====================================================
def generate_otp():
    return str(random.randint(100000, 999999))

def validate_fields(data_dict):
    for key, value in data_dict.items():
        if value is None or str(value).strip() == "":
            raise HTTPException(status_code=400, detail=f"{key} is required")

# =====================================================
# BREVO EMAIL
# =====================================================
def send_otp_email(email, otp):
    try:
        url = "https://api.brevo.com/v3/smtp/email"

        payload = {
            "sender": {"name": "College ERP", "email": EMAIL_FROM},
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

    except Exception as e:
        print("Email Error:", e)

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
    validate_fields(data.dict())

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT 1 FROM Users WHERE Email=%s", (data.student_email,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="Email already registered")

        cursor.execute("SELECT 1 FROM StudentProfile WHERE RegistrationNo=%s", (data.registration_no,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="Student already registered")

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
            raise HTTPException(status_code=400, detail="No professor available")

        cursor.execute("""
            INSERT INTO StudentProfessorMapping (StudentId, ProfessorId, Semester)
            VALUES (%s, %s, %s)
        """, (student_id, prof[0], data.semester))

        conn.commit()

        return {"message": "Student registered successfully", "assigned_professor": prof[0]}

    finally:
        conn.close()

# =====================================================
# SEND OTP (ANTI SPAM)
# =====================================================
@app.post("/auth/send-otp")
def send_otp(data: SendOTP):
    if not data.email:
        raise HTTPException(status_code=400, detail="Email required")

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT UserId FROM Users WHERE Email=%s AND IsActive=1", (data.email,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="User not found")

        # check existing OTP
        cursor.execute("""
            SELECT OTPCode FROM EmailOTP
            WHERE Email=%s AND IsUsed=0 AND ExpiryTime >= GETDATE()
        """, (data.email,))

        if cursor.fetchone():
            return {"message": "OTP already sent"}

        otp = generate_otp()
        expiry = datetime.now() + timedelta(minutes=5)

        cursor.execute("""
            INSERT INTO EmailOTP (Email, OTPCode, ExpiryTime)
            VALUES (%s, %s, %s)
        """, (data.email, otp, expiry))

        conn.commit()

    finally:
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

    try:
        cursor.execute("""
            SELECT OTPId FROM EmailOTP
            WHERE Email=%s AND OTPCode=%s AND IsUsed=0 AND ExpiryTime>=GETDATE()
        """, (data.email, data.otp))

        otp_row = cursor.fetchone()

        if not otp_row:
            raise HTTPException(status_code=400, detail="Invalid or expired OTP")

        cursor.execute("UPDATE EmailOTP SET IsUsed=1 WHERE OTPId=%s", (otp_row[0],))

        cursor.execute("SELECT UserId, Role FROM Users WHERE Email=%s AND IsActive=1", (data.email,))
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

# =====================================================
# APPLY LEAVE
# =====================================================
@app.post("/leave/apply")
def apply_leave(data: LeaveApply):
    validate_fields(data.dict())

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT ProfessorId FROM StudentProfessorMapping WHERE StudentId=%s", (data.student_id,))
        prof = cursor.fetchone()

        cursor.execute("SELECT TOP 1 DeanId FROM DeanProfile")
        dean = cursor.fetchone()

        if not prof or not dean:
            raise HTTPException(status_code=400, detail="Configuration error")

        cursor.execute("""
            INSERT INTO LeaveApplications
            (StudentId, ProfessorId, DeanId, FromDate, ToDate, Reason)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            data.student_id,
            prof[0],
            dean[0],
            data.from_date,
            data.to_date,
            data.reason
        ))

        conn.commit()

        return {"message": "Leave applied"}

    finally:
        conn.close()

# =====================================================
# EMERGENCY LEAVE
# =====================================================
@app.post("/leave/emergency")
def emergency_leave(data: EmergencyLeave):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT ProfessorId FROM StudentProfessorMapping WHERE StudentId=%s", (data.student_id,))
        prof = cursor.fetchone()

        cursor.execute("SELECT TOP 1 DeanId FROM DeanProfile")
        dean = cursor.fetchone()

        if not prof or not dean:
            raise HTTPException(status_code=400, detail="Configuration error")

        cursor.execute("""
            INSERT INTO LeaveApplications
            (StudentId, ProfessorId, DeanId, ProfessorStatus, FromDate, ToDate, Reason)
            VALUES (%s, %s, %s, 'SKIPPED', %s, %s, %s)
        """, (
            data.student_id,
            prof[0],
            dean[0],
            data.from_date,
            data.to_date,
            data.reason
        ))

        conn.commit()

        return {"message": "Emergency leave sent"}

    finally:
        conn.close()

# =====================================================
# STUDENT DASHBOARD
# =====================================================
@app.get("/student/leaves/{student_id}")
def student_leaves(student_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    rows = cursor.execute("""
        SELECT LeaveId, ProfessorStatus, DeanStatus, FinalStatus
        FROM LeaveApplications WHERE StudentId=%s
    """, (student_id,)).fetchall()

    conn.close()

    return [
        {
            "leave_id": r[0],
            "professor_status": r[1],
            "dean_status": r[2],
            "final_status": r[3]
        } for r in rows
    ]

# =====================================================
# PROFESSOR
# =====================================================
@app.get("/professor/pending/{professor_id}")
def professor_pending(professor_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    rows = cursor.execute("""
        SELECT LeaveId, StudentId, FromDate, ToDate, Reason
        FROM LeaveApplications
        WHERE ProfessorId=%s AND ProfessorStatus='PENDING'
    """, (professor_id,)).fetchall()

    conn.close()

    return rows

@app.post("/leave/professor-action")
def professor_action(data: Action):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        status = "APPROVED" if data.action == "APPROVED" else "REJECTED"
        final = "FORWARDED_TO_DEAN" if status == "APPROVED" else "REJECTED_BY_PROFESSOR"

        cursor.execute("""
            UPDATE LeaveApplications
            SET ProfessorStatus=%s, FinalStatus=%s
            WHERE LeaveId=%s
        """, (status, final, data.leave_id))

        conn.commit()

        return {"message": "Professor action done"}

    finally:
        conn.close()

# =====================================================
# DEAN
# =====================================================
@app.get("/dean/pending")
def dean_pending():
    conn = get_connection()
    cursor = conn.cursor()

    rows = cursor.execute("""
        SELECT LeaveId, StudentId, FromDate, ToDate, Reason
        FROM LeaveApplications
        WHERE DeanStatus='PENDING'
    """).fetchall()

    conn.close()

    return rows

@app.post("/leave/dean-action")
def dean_action(data: Action):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        status = "APPROVED" if data.action == "APPROVED" else "REJECTED"
        final = "FINAL_APPROVED" if status == "APPROVED" else "REJECTED_BY_DEAN"

        cursor.execute("""
            UPDATE LeaveApplications
            SET DeanStatus=%s, FinalStatus=%s
            WHERE LeaveId=%s
        """, (status, final, data.leave_id))

        conn.commit()

        return {"message": "Dean action done"}

    finally:
        conn.close()
