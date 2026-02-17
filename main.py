import pyodbc
import smtplib
import random
import uuid
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime, timedelta
from email.message import EmailMessage
import firebase_admin
from firebase_admin import credentials, messaging

#cred = credentials.Certificate("firebase_key.json")
#firebase_admin.initialize_app(cred)
# =====================================================
# CONFIG
# =====================================================
DB_CONN_STR = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=kano2026.mssql.somee.com;"
    "DATABASE=kano2026;"
    "UID=Dhvanit_SQLLogin_1;"
    "PWD=34l95acp9v;"
    "Encrypt=yes;"
    "TrustServerCertificate=yes;"
)

EMAIL_FROM = "patelkanostudent@gmail.com"
EMAIL_APP_PASSWORD = "xrvx welj nagp bsbz"

# =====================================================
# UTILS
# =====================================================
def get_connection():
    return pyodbc.connect(DB_CONN_STR)

def generate_otp():
    return str(random.randint(100000, 999999))

def send_otp_email(email, otp):
    msg = EmailMessage()
    msg["Subject"] = "College ERP Login OTP"
    msg["From"] = EMAIL_FROM
    msg["To"] = email
    msg.set_content(f"Your OTP is {otp}. Valid for 5 minutes.")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_FROM, EMAIL_APP_PASSWORD)
        server.send_message(msg)

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
    action: str   # APPROVED / REJECTED

# =====================================================
# STUDENT REGISTER + AUTO PROFESSOR ASSIGN
# =====================================================
@app.post("/student/register")
def student_register(data: StudentRegister):
    conn = get_connection()
    cursor = conn.cursor()

    # Email already exists
    if cursor.execute(
        "SELECT 1 FROM Users WHERE Email=?", data.student_email
    ).fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="Email already registered")

    # Registration number exists
    if cursor.execute(
        "SELECT 1 FROM StudentProfile WHERE RegistrationNo=?",
        data.registration_no
    ).fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="Student already registered")

    # Insert user
    cursor.execute("""
        INSERT INTO Users (FullName, Email, Role)
        VALUES (?, ?, 'STUDENT')
    """, data.fullname, data.student_email)

    student_id = cursor.execute("SELECT @@IDENTITY").fetchone()[0]

    # Insert student profile
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

    # Auto assign professor (max 7 students per semester)
    prof = cursor.execute("""
        SELECT p.ProfessorId
        FROM ProfessorProfile p
        LEFT JOIN StudentProfessorMapping sp
            ON sp.ProfessorId = p.ProfessorId
            AND sp.Semester = ?
        GROUP BY p.ProfessorId
        HAVING COUNT(sp.StudentId) < 7
        ORDER BY COUNT(sp.StudentId)
    """, data.semester).fetchone()

    if not prof:
        conn.close()
        raise HTTPException(status_code=400, detail="No professor available")

    cursor.execute("""
        INSERT INTO StudentProfessorMapping
        (StudentId, ProfessorId, Semester)
        VALUES (?, ?, ?)
    """, student_id, prof[0], data.semester)

    conn.commit()
    conn.close()

    return {
        "message": "Student registered successfully",
        "assigned_professor": prof[0]
    }

# =====================================================
# OTP LOGIN
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
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")

    cursor.execute("UPDATE EmailOTP SET IsUsed=1 WHERE OTPId=?", otp_row[0])

    user = cursor.execute("""
        SELECT UserId, Role FROM Users WHERE Email=? AND IsActive=1
    """, data.email).fetchone()

    token = str(uuid.uuid4())

    cursor.execute("UPDATE LoginSessions SET IsActive=0 WHERE UserId=?", user[0])
    cursor.execute(
        "INSERT INTO LoginSessions (UserId, Token) VALUES (?, ?)",
        user[0], token
    )

    conn.commit()
    conn.close()

    return {
        "login": "success",
        "token": token,
        "user_id": user[0],
        "role": user[1]
    }

# =====================================================
# APPLY NORMAL LEAVE
# =====================================================
@app.post("/leave/apply")
def apply_leave(data: LeaveApply):
    conn = get_connection()
    cursor = conn.cursor()

    prof = cursor.execute("""
        SELECT ProfessorId FROM StudentProfessorMapping
        WHERE StudentId=?
    """, data.student_id).fetchone()

    if not prof:
        conn.close()
        raise HTTPException(status_code=400, detail="Professor not assigned")

    dean = cursor.execute("SELECT DeanId FROM DeanProfile").fetchone()
    if not dean:
        conn.close()
        raise HTTPException(status_code=500, detail="Dean not configured")

    cursor.execute("""
        INSERT INTO LeaveApplications
        (StudentId, ProfessorId, DeanId, FromDate, ToDate, Reason)
        VALUES (?, ?, ?, ?, ?, ?)
    """,
    data.student_id,
    prof[0],
    dean[0],
    data.from_date,
    data.to_date,
    data.reason)

    conn.commit()
    conn.close()
    return {"message": "Leave applied"}

# =====================================================
# EMERGENCY LEAVE (SKIP PROFESSOR)
# =====================================================
@app.post("/leave/emergency")
def emergency_leave(data: EmergencyLeave):
    conn = get_connection()
    cursor = conn.cursor()

    prof = cursor.execute("""
        SELECT ProfessorId FROM StudentProfessorMapping
        WHERE StudentId=?
    """, data.student_id).fetchone()

    dean = cursor.execute("SELECT DeanId FROM DeanProfile").fetchone()

    if not prof or not dean:
        conn.close()
        raise HTTPException(status_code=400, detail="Configuration error")

    cursor.execute("""
        INSERT INTO LeaveApplications
        (StudentId, ProfessorId, DeanId, ProfessorStatus,
         FromDate, ToDate, Reason)
        VALUES (?, ?, ?, 'SKIPPED', ?, ?, ?)
    """,
    data.student_id,
    prof[0],
    dean[0],
    data.from_date,
    data.to_date,
    data.reason)

    conn.commit()
    conn.close()
    return {"message": "Emergency leave sent to Dean"}

# =====================================================
# STUDENT DASHBOARD
# =====================================================
@app.get("/student/leaves/{student_id}")
def student_leaves(student_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    rows = cursor.execute("""
        SELECT LeaveId, ProfessorStatus, DeanStatus, FinalStatus
        FROM LeaveApplications WHERE StudentId=?
    """, student_id).fetchall()
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
# PROFESSOR DASHBOARD
# =====================================================
@app.get("/professor/pending/{professor_id}")
def professor_pending(professor_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    rows = cursor.execute("""
        SELECT LeaveId, StudentId, FromDate, ToDate, Reason
        FROM LeaveApplications
        WHERE ProfessorId=? AND ProfessorStatus='PENDING'
    """, professor_id).fetchall()
    conn.close()
    return rows

@app.post("/leave/professor-action")
def professor_action(data: Action):
    conn = get_connection()
    cursor = conn.cursor()

    status = "APPROVED" if data.action == "APPROVED" else "REJECTED"
    final = "FORWARDED_TO_DEAN" if status == "APPROVED" else "REJECTED_BY_PROFESSOR"

    cursor.execute("""
        UPDATE LeaveApplications
        SET ProfessorStatus=?, FinalStatus=?
        WHERE LeaveId=?
    """, status, final, data.leave_id)

    conn.commit()
    conn.close()
    return {"message": "Professor action completed"}

# =====================================================
# DEAN DASHBOARD
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

    status = "APPROVED" if data.action == "APPROVED" else "REJECTED"
    final = "FINAL_APPROVED" if status == "APPROVED" else "REJECTED_BY_DEAN"

    cursor.execute("""
        UPDATE LeaveApplications
        SET DeanStatus=?, FinalStatus=?
        WHERE LeaveId=?
    """, status, final, data.leave_id)

    conn.commit()
    conn.close()
    return {"message": "Dean action completed"}

# =====================================================
# RUN
# =====================================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
