import pymssql
import smtplib
import random
import uuid
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime, timedelta, date
from email.message import EmailMessage

# =====================================================
# CONFIG (DIRECT VALUES)
# =====================================================
DB_SERVER = "kano2026.mssql.somee.com"
DB_USER = "Dhvanit_SQLLogin_1"
DB_PASSWORD = "34l95acp9v"
DB_NAME = "kano2026"

EMAIL_FROM = "patelkanostudent@gmail.com"
EMAIL_PASS = "xrvx welj nagp bsbz"

# =====================================================
# DB CONNECTION
# =====================================================
def get_connection():
    try:
        conn = pymssql.connect(
            server=DB_SERVER,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            timeout=30
        )
        return conn
    except Exception as e:
        print("DB ERROR:", e)
        raise HTTPException(status_code=500, detail="Database connection failed")

# =====================================================
# UTILS
# =====================================================
def generate_otp():
    return str(random.randint(100000, 999999))

def send_otp_email(email, otp):
    try:
        msg = EmailMessage()
        msg["Subject"] = "College ERP Login OTP"
        msg["From"] = EMAIL_FROM
        msg["To"] = email
        msg.set_content(f"Your OTP is {otp}. Valid for 5 minutes.")

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_FROM, EMAIL_PASS)
            server.send_message(msg)

        print("OTP sent")

    except Exception as e:
        print("Email Error:", e)
        raise HTTPException(status_code=500, detail="Email failed")

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
    from_date: date
    to_date: date
    reason: str

class EmergencyLeave(BaseModel):
    student_id: int
    from_date: date
    to_date: date
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

    cursor.execute("SELECT 1 FROM Users WHERE Email=%s", (data.student_email,))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="Email exists")

    cursor.execute("SELECT 1 FROM StudentProfile WHERE RegistrationNo=%s", (data.registration_no,))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="Student exists")

    cursor.execute("""
        INSERT INTO Users (FullName, Email, Role)
        VALUES (%s, %s, 'STUDENT')
    """, (data.fullname, data.student_email))

    conn.commit()

    cursor.execute("SELECT SCOPE_IDENTITY()")
    student_id = cursor.fetchone()[0]

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
        conn.close()
        raise HTTPException(status_code=400, detail="No professor")

    cursor.execute("""
        INSERT INTO StudentProfessorMapping (StudentId, ProfessorId, Semester)
        VALUES (%s, %s, %s)
    """, (student_id, prof[0], data.semester))

    conn.commit()
    conn.close()

    return {"message": "Registered", "professor": prof[0]}

# =====================================================
# SEND OTP
# =====================================================
@app.post("/auth/send-otp")
def send_otp(data: SendOTP):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT UserId FROM Users WHERE Email=%s", (data.email,))
    user = cursor.fetchone()

    if not user:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found")

    otp = generate_otp()
    expiry = datetime.now() + timedelta(minutes=5)

    cursor.execute("""
        INSERT INTO EmailOTP (Email, OTPCode, ExpiryTime)
        VALUES (%s, %s, %s)
    """, (data.email, otp, expiry))

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

    cursor.execute("""
        SELECT OTPId FROM EmailOTP
        WHERE Email=%s AND OTPCode=%s AND IsUsed=0 AND ExpiryTime>=GETDATE()
    """, (data.email, data.otp))

    otp_row = cursor.fetchone()

    if not otp_row:
        conn.close()
        raise HTTPException(status_code=400, detail="Invalid OTP")

    cursor.execute("UPDATE EmailOTP SET IsUsed=1 WHERE OTPId=%s", (otp_row[0],))

    cursor.execute("SELECT UserId, Role FROM Users WHERE Email=%s", (data.email,))
    user = cursor.fetchone()

    token = str(uuid.uuid4())

    cursor.execute("UPDATE LoginSessions SET IsActive=0 WHERE UserId=%s", (user[0],))
    cursor.execute("INSERT INTO LoginSessions (UserId, Token) VALUES (%s, %s)", (user[0], token))

    conn.commit()
    conn.close()

    return {"token": token, "user_id": user[0], "role": user[1]}

# =====================================================
# APPLY LEAVE
# =====================================================
@app.post("/leave/apply")
def apply_leave(data: LeaveApply):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT ProfessorId FROM StudentProfessorMapping WHERE StudentId=%s", (data.student_id,))
    prof = cursor.fetchone()

    cursor.execute("SELECT TOP 1 DeanId FROM DeanProfile")
    dean = cursor.fetchone()

    if not prof or not dean:
        conn.close()
        raise HTTPException(status_code=400, detail="Config error")

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
    conn.close()

    return {"message": "Leave applied"}

# =====================================================
# PROFESSOR ACTION
# =====================================================
@app.post("/leave/professor-action")
def professor_action(data: Action):
    conn = get_connection()
    cursor = conn.cursor()

    status = "APPROVED" if data.action == "APPROVED" else "REJECTED"
    final = "FORWARDED_TO_DEAN" if status == "APPROVED" else "REJECTED_BY_PROFESSOR"

    cursor.execute("""
        UPDATE LeaveApplications
        SET ProfessorStatus=%s, FinalStatus=%s
        WHERE LeaveId=%s
    """, (status, final, data.leave_id))

    conn.commit()
    conn.close()

    return {"message": "Updated"}

# =====================================================
# DEAN ACTION
# =====================================================
@app.post("/leave/dean-action")
def dean_action(data: Action):
    conn = get_connection()
    cursor = conn.cursor()

    status = "APPROVED" if data.action == "APPROVED" else "REJECTED"
    final = "FINAL_APPROVED" if status == "APPROVED" else "REJECTED_BY_DEAN"

    cursor.execute("""
        UPDATE LeaveApplications
        SET DeanStatus=%s, FinalStatus=%s
        WHERE LeaveId=%s
    """, (status, final, data.leave_id))

    conn.commit()
    conn.close()

    return {"message": "Done"}
