import pymssql
import smtplib
import random
import uuid
from fastapi import FastAPI, HTTPException,Header
from pydantic import BaseModel
from datetime import datetime, timedelta
from email.message import EmailMessage

from datetime import datetime
# =====================================================
# CONFIG
# =====================================================


EMAIL_FROM = "patelkanostudent@gmail.com"
EMAIL_APP_PASSWORD = "xrvx welj nagp bsbz"

# =====================================================
# FASTAPI
# =====================================================
app = FastAPI(title="College ERP Backend")

# =====================================================
# UTILS
# =====================================================
def get_connection():
    return pymssql.connect(
        server="kano2026.mssql.somee.com",
        user="Dhvanit_SQLLogin_1",
        password="34l95acp9v",
        database="kano2026"
    )

def generate_otp():
    return str(random.randint(100000, 999999))

def send_otp_email(email, otp):
    msg = EmailMessage()
    msg["Subject"] = "College Leave Management System Login OTP"
    msg["From"] = EMAIL_FROM
    msg["To"] = email
    msg.set_content(f"Your OTP is {otp}. Valid for 5 minutes.")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_FROM, EMAIL_APP_PASSWORD)
        server.send_message(msg)

# =====================================================
# MODELS
# =====================================================
class StudentRegister(BaseModel):
    nms:int
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
#=====================================================
@app.get("/dashboard")
def dashboard():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM Users WHERE Role='STUDENT' AND IsActive=1")
    count = cursor.fetchone()[0]

    return {
        #"server_time": str(datetime.now()),
        "total_students": count
    }
# =====================================================
# STUDENT REGISTER
# =====================================================
@app.post("/student/register")
def student_register(data: StudentRegister):
    nms=0
    conn = get_connection()
    cursor = conn.cursor()

    if cursor.execute("SELECT 1 FROM Users WHERE Email=?", data.student_email).fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="Email already registered")

    if cursor.execute("SELECT 1 FROM StudentProfile WHERE RegistrationNo=?", data.registration_no).fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="Student already registered")

    cursor.execute("INSERT INTO Users (FullName, Email, Role) VALUES (?, ?, 'STUDENT')",
                   
                   data.fullname, data.student_email)
    

    student_id = cursor.execute("SELECT @@IDENTITY").fetchone()[0]
    nms=nms+1
    cursor.execute("""
        INSERT INTO StudentProfile
        (StudentId, RollNo, RegistrationNo, Semester, StudentEmail, ParentEmail)
        VALUES (?, ?, ?, ?, ?, ?)
    """, student_id, data.roll_no, data.registration_no,
         data.semester, data.student_email, data.parent_email)

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
        INSERT INTO StudentProfessorMapping
        (StudentId, ProfessorId, Semester)
        VALUES (?, ?, ?)
    """, student_id, prof[0], data.semester)

    conn.commit()
    conn.close()

    return {"message": "Student registered", "professor": prof[0],'number of student':nms}

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

    cursor.execute("INSERT INTO EmailOTP (Email, OTPCode, ExpiryTime) VALUES (?, ?, ?)",
                   data.email, otp, expiry)

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
        raise HTTPException(status_code=400, detail="Invalid OTP")

    cursor.execute("UPDATE EmailOTP SET IsUsed=1 WHERE OTPId=?", otp_row[0])

    user = cursor.execute(
        "SELECT UserId, Role FROM Users WHERE Email=? AND IsActive=1",
        data.email
    ).fetchone()

    token = str(uuid.uuid4())

    cursor.execute("UPDATE LoginSessions SET IsActive=0 WHERE UserId=?", user[0])
    cursor.execute("INSERT INTO LoginSessions (UserId, Token) VALUES (?, ?)",
                   user[0], token)

    conn.commit()
    conn.close()

    return {
        "login": "success",
        "token": token,
        "user_id": user[0],
        "role": user[1]
    }

# =====================================================
# APPLY LEAVE
# =====================================================
@app.post("/leave/apply")
def apply_leave(data: LeaveApply):
    conn = get_connection()
    cursor = conn.cursor()

    prof = cursor.execute("SELECT ProfessorId FROM StudentProfessorMapping WHERE StudentId=?",
                          data.student_id).fetchone()

    dean = cursor.execute("SELECT DeanId FROM DeanProfile").fetchone()

    if not prof or not dean:
        conn.close()
        raise HTTPException(status_code=400, detail="Configuration error")

    cursor.execute("""
        INSERT INTO LeaveApplications
        (StudentId, ProfessorId, DeanId, ProfessorStatus, DeanStatus,
         FromDate, ToDate, Reason)
        VALUES (?, ?, ?, 'PENDING', 'PENDING', ?, ?, ?)
    """, data.student_id, prof[0], dean[0],
         data.from_date, data.to_date, data.reason)

    conn.commit()
    conn.close()

    return {"message": "Leave applied"}

@app.get("/student/rejected/{student_id}")
def student_rejected(student_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    rows = cursor.execute("""
        SELECT LeaveId, FromDate, ToDate, Reason
        FROM LeaveApplications
        WHERE StudentId=? AND FinalStatus LIKE 'REJECTED%'
    """, student_id).fetchall()

    conn.close()

    return [list(r) for r in rows]

@app.get("/student/approved/{student_id}")
def student_approved(student_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    rows = cursor.execute("""
        SELECT LeaveId, FromDate, ToDate, Reason
        FROM LeaveApplications
        WHERE StudentId=? AND FinalStatus='FINAL_APPROVED'
    """, student_id).fetchall()

    conn.close()

    return [list(r) for r in rows]

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
# EMERGENCY LEAVE
# =====================================================
@app.post("/leave/emergency")
def emergency_leave(data: EmergencyLeave):
    conn = get_connection()
    cursor = conn.cursor()

    prof = cursor.execute("SELECT ProfessorId FROM StudentProfessorMapping WHERE StudentId=?",
                          data.student_id).fetchone()

    dean = cursor.execute("SELECT DeanId FROM DeanProfile").fetchone()

    if not prof or not dean:
        conn.close()
        raise HTTPException(status_code=400, detail="Configuration error")

    cursor.execute("""
        INSERT INTO LeaveApplications
        (StudentId, ProfessorId, DeanId, ProfessorStatus, DeanStatus,
         FromDate, ToDate, Reason)
        VALUES (?, ?, ?, 'SKIPPED', 'PENDING', ?, ?, ?)
    """, data.student_id, prof[0], dean[0],
         data.from_date, data.to_date, data.reason)

    conn.commit()
    conn.close()

    return {"message": "Emergency leave sent"}

# =====================================================
# DEAN APIs
# =====================================================
@app.get("/dean/pending")
def dean_pending():
    conn = get_connection()
    cursor = conn.cursor()

    rows = cursor.execute("""
        SELECT l.LeaveId, l.StudentId, u.FullName, s.Semester,
               l.FromDate, l.ToDate, l.Reason
        FROM LeaveApplications l
        JOIN Users u ON l.StudentId = u.UserId
        JOIN StudentProfile s ON s.StudentId = l.StudentId
        WHERE l.DeanStatus='PENDING'
    """).fetchall()

    conn.close()

    return [list(r) for r in rows]

@app.get("/dean/approved")
def dean_approved():
    conn = get_connection()
    cursor = conn.cursor()

    rows = cursor.execute("""
        SELECT l.LeaveId, l.StudentId, u.FullName, s.Semester,
               l.FromDate, l.ToDate, l.Reason
        FROM LeaveApplications l
        JOIN Users u ON l.StudentId = u.UserId
        JOIN StudentProfile s ON s.StudentId = l.StudentId
        WHERE l.DeanStatus='APPROVED'
    """).fetchall()

    conn.close()

    return [list(r) for r in rows]

@app.get("/dean/emergency")
def dean_emergency():
    conn = get_connection()
    cursor = conn.cursor()

    rows = cursor.execute("""
        SELECT l.LeaveId, l.StudentId, u.FullName, s.Semester,
               l.FromDate, l.ToDate, l.Reason
        FROM LeaveApplications l
        JOIN Users u ON l.StudentId = u.UserId
        JOIN StudentProfile s ON s.StudentId = l.StudentId
        WHERE l.ProfessorStatus='SKIPPED' AND l.DeanStatus='PENDING'
    """).fetchall()

    conn.close()

    return [list(r) for r in rows]

@app.get("/dean/students")
def dean_students():
    conn = get_connection()
    cursor = conn.cursor()

    rows = cursor.execute("""
        SELECT u.UserId, u.FullName, s.RollNo, s.RegistrationNo,
               s.Semester, s.StudentEmail, s.ParentEmail
        FROM Users u
        JOIN StudentProfile s ON u.UserId = s.StudentId
        WHERE u.Role='STUDENT' AND u.IsActive=1
    """).fetchall()

    conn.close()

    return [list(r) for r in rows]

@app.post("/leave/dean-action")
def dean_action(data: Action):
    conn = get_connection()
    cursor = conn.cursor()

    # ===========================
    # STATUS SET
    # ===========================
    status = "APPROVED" if data.action == "APPROVED" else "REJECTED"
    final_status = "FINAL_APPROVED" if status == "APPROVED" else "REJECTED_BY_DEAN"

    # ===========================
    # UPDATE LEAVE
    # ===========================
    cursor.execute("""
        UPDATE LeaveApplications
        SET DeanStatus=?, FinalStatus=?
        WHERE LeaveId=?
    """, status, final_status, data.leave_id)

    # ===========================
    # GET STUDENT + PARENT DATA
    # ===========================
    row = cursor.execute("""
        SELECT u.FullName, s.ParentEmail, l.FromDate, l.ToDate, l.Reason
        FROM LeaveApplications l
        JOIN Users u ON l.StudentId = u.UserId
        JOIN StudentProfile s ON s.StudentId = l.StudentId
        WHERE l.LeaveId=?
    """, data.leave_id).fetchone()

    conn.commit()
    conn.close()

    # ===========================
    # SEND EMAIL
    # ===========================
    try:
        if row:
            student_name = row[0]
            parent_email = row[1]
            from_date = row[2]
            to_date = row[3]
            reason = row[4]

            msg = EmailMessage()
            msg["Subject"] = f"Leave {status} Notification"
            msg["From"] = EMAIL_FROM
            msg["To"] = parent_email

            msg.set_content(f"""
Dear Parent,

Your ward {student_name} applied for leave.

From: {from_date}
To: {to_date}
Reason: {reason}

Status: {status}

Thank you,
College ERP System
""")

            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(EMAIL_FROM, EMAIL_APP_PASSWORD)
                server.send_message(msg)

            print("Email sent to:", parent_email)

    except Exception as e:
        print("Email Error:", e)

    return {"message": f"Dean action done & parent notified ({status})"}

@app.get("/dean/semester-wise")
def semester_wise():
    conn = get_connection()
    cursor = conn.cursor()

    rows = cursor.execute("""
        SELECT 
            s.Semester,
            u.FullName AS StudentName,
            s.RollNo,
            pUser.FullName AS ProfessorName
        FROM StudentProfessorMapping sp
        JOIN Users u ON sp.StudentId = u.UserId
        JOIN StudentProfile s ON s.StudentId = u.UserId
        JOIN Users pUser ON pUser.UserId = sp.ProfessorId
        ORDER BY s.Semester, s.RollNo
    """).fetchall()

    conn.close()

    return [list(r) for r in rows]

def send_parent_email(parent_email, student_name, from_date, to_date, reason, status):
    msg = EmailMessage()
    msg["Subject"] = f"Leave {status} Notification"
    msg["From"] = EMAIL_FROM
    msg["To"] = parent_email

    msg.set_content(f"""
Dear Parent,

Your ward {student_name} applied leave.

From: {from_date}
To: {to_date}
Reason: {reason}

Status: {status}

Thank you.
College ERP System
""")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_FROM, EMAIL_APP_PASSWORD)
        server.send_message(msg)




@app.get("/professor/pending/{professor_id}")
def professor_pending(professor_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    rows = cursor.execute("""
        SELECT l.LeaveId, l.StudentId, u.FullName, s.Semester,
               l.FromDate, l.ToDate, l.Reason
        FROM LeaveApplications l
        JOIN Users u ON l.StudentId = u.UserId
        JOIN StudentProfile s ON s.StudentId = l.StudentId
        WHERE l.ProfessorId=? AND l.ProfessorStatus='PENDING'
    """, professor_id).fetchall()

    conn.close()

    return [list(r) for r in rows]

@app.get("/professor/approved/{professor_id}")
def professor_approved(professor_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    rows = cursor.execute("""
        SELECT l.LeaveId, u.FullName, s.Semester,
               l.FromDate, l.ToDate
        FROM LeaveApplications l
        JOIN Users u ON l.StudentId = u.UserId
        JOIN StudentProfile s ON s.StudentId = l.StudentId
        WHERE l.ProfessorId=? AND l.ProfessorStatus='APPROVED'
    """, professor_id).fetchall()

    conn.close()

    return [list(r) for r in rows]

@app.get("/professor/rejected/{professor_id}")
def professor_rejected(professor_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    rows = cursor.execute("""
        SELECT l.LeaveId, u.FullName, s.Semester,
               l.FromDate, l.ToDate
        FROM LeaveApplications l
        JOIN Users u ON l.StudentId = u.UserId
        JOIN StudentProfile s ON s.StudentId = l.StudentId
        WHERE l.ProfessorId=? AND l.ProfessorStatus='REJECTED'
    """, professor_id).fetchall()

    conn.close()

    return [list(r) for r in rows]

@app.get("/professor/students/{professor_id}")
def professor_students(professor_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    rows = cursor.execute("""
        SELECT sp.Semester, COUNT(*) as total_students
        FROM StudentProfessorMapping sp
        WHERE sp.ProfessorId=?
        GROUP BY sp.Semester
    """, professor_id).fetchall()

    conn.close()

    return [
        {"semester": r[0], "total_students": r[1]} for r in rows
    ]

@app.post("/leave/professor-action")
def professor_action(data: Action):
    conn = get_connection()
    cursor = conn.cursor()

    status = "APPROVED" if data.action == "APPROVED" else "REJECTED"

    cursor.execute("""
        UPDATE LeaveApplications
        SET ProfessorStatus=?, FinalStatus=?
        WHERE LeaveId=?
    """,
    status,
    "FORWARDED_TO_DEAN" if status == "APPROVED" else "REJECTED_BY_PROFESSOR",
    data.leave_id)

    conn.commit()
    conn.close()

    return {"message": "Done"}

#=========================extra start=====================================





def get_user_from_token(authorization: str):
    token = authorization.replace("Bearer ", "")

    conn = get_connection()
    cursor = conn.cursor()

    row = cursor.execute("""
        SELECT UserId FROM LoginSessions
        WHERE Token=? AND IsActive=1
    """, token).fetchone()

    if not row:
        conn.close()
        raise HTTPException(status_code=401, detail="Invalid session")

    return row[0]

@app.get("/user/profile")
def get_profile(authorization: str = Header(None)):

    user_id = get_user_from_token(authorization)

    conn = get_connection()
    cursor = conn.cursor()

    # Get basic user info
    user = cursor.execute("""
        SELECT FullName, Email, Role
        FROM Users WHERE UserId=?
    """, user_id).fetchone()

    if not user:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found")

    role = user[2]

    profile_data = {
        "user_id": user_id,
        "name": user[0],
        "email": user[1],
        "role": role
    }

    # ========================
    # STUDENT PROFILE
    # ========================
    if role == "STUDENT":
        data = cursor.execute("""
            SELECT RollNo, RegistrationNo, Semester,
                   StudentEmail, ParentEmail
            FROM StudentProfile WHERE StudentId=?
        """, user_id).fetchone()

        if data:
            profile_data.update({
                "roll_no": data[0],
                "registration_no": data[1],
                "semester": data[2],
                "student_email": data[3],
                "parent_email": data[4],
            })

    # ========================
    # PROFESSOR PROFILE
    # ========================
    elif role == "PROFESSOR":
        data = cursor.execute("""
            SELECT ProfessorCode, Email
            FROM ProfessorProfile WHERE ProfessorId=?
        """, user_id).fetchone()

        if data:
            profile_data.update({
                "professor_code": data[0],
                "email": data[1],
            })

    # ========================
    # DEAN PROFILE
    # ========================
    elif role == "DEAN":
        data = cursor.execute("""
            SELECT DeanCode, Email
            FROM DeanProfile WHERE DeanId=?
        """, user_id).fetchone()

        if data:
            profile_data.update({
                "dean_code": data[0],
                "email": data[1],
            })

    conn.close()

    return profile_data

#=======================extra finished====================================
# =====================================================
# RUN
# =====================================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
