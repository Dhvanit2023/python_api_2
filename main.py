import pymssql
import requests
import random
import uuid
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from datetime import datetime, timedelta


# =====================================================
# CONFIG
# =====================================================
# --- Database ---
DB_SERVER   = "kano2026.mssql.somee.com"
DB_USER     = "Dhvanit_SQLLogin_1"
DB_PASSWORD = "34l95acp9v"
DB_NAME     = "kano2026"

# --- Brevo (formerly Sendinblue) ---
BREVO_API_KEY = "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"          # <-- paste your key
BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"
EMAIL_FROM_ADDRESS = "patelkanostudent@gmail.com"   # must be verified in Brevo
EMAIL_FROM_NAME    = "College ERP System"


# =====================================================
# FASTAPI INSTANCE
# =====================================================
app = FastAPI(title="College ERP Backend")


# =====================================================
# DATABASE HELPER
# =====================================================
def get_connection():
    """Return a new pymssql connection."""
    return pymssql.connect(
        server=DB_SERVER,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME
    )


# =====================================================
# BREVO EMAIL HELPER
# =====================================================
def send_brevo_email(to_email: str, subject: str, body: str):
    """
    Send an email via Brevo transactional API.
    Raises an exception on failure.
    """
    headers = {
        "accept": "application/json",
        "api-key": BREVO_API_KEY,
        "content-type": "application/json",
    }
    payload = {
        "sender": {
            "name": EMAIL_FROM_NAME,
            "email": EMAIL_FROM_ADDRESS,
        },
        "to": [
            {"email": to_email}
        ],
        "subject": subject,
        "textContent": body,
    }

    resp = requests.post(BREVO_API_URL, json=payload, headers=headers)

    if resp.status_code not in (200, 201):
        raise Exception(
            f"Brevo email failed [{resp.status_code}]: {resp.text}"
        )

    return resp.json()


def send_otp_email(email: str, otp: str):
    """Send OTP to user via Brevo."""
    subject = "College Leave Management System — Login OTP"
    body = f"Your OTP is {otp}. Valid for 5 minutes."
    send_brevo_email(email, subject, body)


def send_parent_email(
    parent_email: str,
    student_name: str,
    from_date: str,
    to_date: str,
    reason: str,
    status: str,
):
    """Notify parent about leave status via Brevo."""
    subject = f"Leave {status} Notification"
    body = (
        f"Dear Parent,\n\n"
        f"Your ward {student_name} applied for leave.\n\n"
        f"From   : {from_date}\n"
        f"To     : {to_date}\n"
        f"Reason : {reason}\n\n"
        f"Status : {status}\n\n"
        f"Thank you,\n"
        f"College ERP System"
    )
    send_brevo_email(parent_email, subject, body)


# =====================================================
# OTP GENERATOR
# =====================================================
def generate_otp() -> str:
    return str(random.randint(100000, 999999))


# =====================================================
# REQUEST / RESPONSE MODELS
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
# DASHBOARD
# =====================================================
@app.get("/dashboard")
def dashboard():
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT COUNT(*) FROM Users "
            "WHERE Role='STUDENT' AND IsActive=1"
        )
        count = cursor.fetchone()[0]
        return {"total_students": count}
    finally:
        conn.close()


# =====================================================
# STUDENT REGISTER
# =====================================================
@app.post("/student/register")
def student_register(data: StudentRegister):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        # ---- check duplicate email ----
        cursor.execute(
            "SELECT 1 FROM Users WHERE Email=%s",
            (data.student_email,),
        )
        if cursor.fetchone():
            raise HTTPException(
                status_code=400,
                detail="Email already registered",
            )

        # ---- check duplicate registration no ----
        cursor.execute(
            "SELECT 1 FROM StudentProfile WHERE RegistrationNo=%s",
            (data.registration_no,),
        )
        if cursor.fetchone():
            raise HTTPException(
                status_code=400,
                detail="Student already registered",
            )

        # ---- insert user ----
        cursor.execute(
            "INSERT INTO Users (FullName, Email, Role) "
            "VALUES (%s, %s, 'STUDENT')",
            (data.fullname, data.student_email),
        )

        # ---- get new user id ----
        cursor.execute("SELECT SCOPE_IDENTITY()")
        student_id = int(cursor.fetchone()[0])

        # ---- insert student profile ----
        cursor.execute(
            """
            INSERT INTO StudentProfile
                (StudentId, RollNo, RegistrationNo,
                 Semester, StudentEmail, ParentEmail)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                student_id,
                data.roll_no,
                data.registration_no,
                data.semester,
                data.student_email,
                data.parent_email,
            ),
        )

        # ---- auto-assign professor (< 7 students) ----
        cursor.execute(
            """
            SELECT p.ProfessorId
            FROM ProfessorProfile p
            LEFT JOIN StudentProfessorMapping sp
                ON sp.ProfessorId = p.ProfessorId
                AND sp.Semester = %s
            GROUP BY p.ProfessorId
            HAVING COUNT(sp.StudentId) < 7
            ORDER BY COUNT(sp.StudentId)
            """,
            (data.semester,),
        )
        prof = cursor.fetchone()

        if not prof:
            conn.rollback()
            raise HTTPException(
                status_code=400,
                detail="No professor available for this semester",
            )

        cursor.execute(
            """
            INSERT INTO StudentProfessorMapping
                (StudentId, ProfessorId, Semester)
            VALUES (%s, %s, %s)
            """,
            (student_id, prof[0], data.semester),
        )

        conn.commit()

        return {
            "message": "Student registered successfully",
            "student_id": student_id,
            "assigned_professor_id": prof[0],
        }

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# =====================================================
# AUTH — SEND OTP
# =====================================================
@app.post("/auth/send-otp")
def send_otp(data: SendOTP):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT UserId FROM Users "
            "WHERE Email=%s AND IsActive=1",
            (data.email,),
        )
        user = cursor.fetchone()

        if not user:
            raise HTTPException(
                status_code=404, detail="User not found"
            )

        otp = generate_otp()
        expiry = datetime.now() + timedelta(minutes=5)

        cursor.execute(
            "INSERT INTO EmailOTP (Email, OTPCode, ExpiryTime) "
            "VALUES (%s, %s, %s)",
            (data.email, otp, expiry),
        )
        conn.commit()

        # send via brevo
        send_otp_email(data.email, otp)

        return {"message": "OTP sent"}

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# =====================================================
# AUTH — VERIFY OTP
# =====================================================
@app.post("/auth/verify-otp")
def verify_otp(data: OTPVerify):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT OTPId FROM EmailOTP
            WHERE Email=%s AND OTPCode=%s
              AND IsUsed=0 AND ExpiryTime >= GETDATE()
            """,
            (data.email, data.otp),
        )
        otp_row = cursor.fetchone()

        if not otp_row:
            raise HTTPException(
                status_code=400, detail="Invalid or expired OTP"
            )

        # mark used
        cursor.execute(
            "UPDATE EmailOTP SET IsUsed=1 WHERE OTPId=%s",
            (otp_row[0],),
        )

        # get user
        cursor.execute(
            "SELECT UserId, Role FROM Users "
            "WHERE Email=%s AND IsActive=1",
            (data.email,),
        )
        user = cursor.fetchone()

        if not user:
            raise HTTPException(
                status_code=404, detail="User not found"
            )

        token = str(uuid.uuid4())

        # invalidate old sessions
        cursor.execute(
            "UPDATE LoginSessions SET IsActive=0 WHERE UserId=%s",
            (user[0],),
        )

        # create new session
        cursor.execute(
            "INSERT INTO LoginSessions (UserId, Token) VALUES (%s, %s)",
            (user[0], token),
        )

        conn.commit()

        return {
            "login": "success",
            "token": token,
            "user_id": user[0],
            "role": user[1],
        }

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# =====================================================
# TOKEN VALIDATOR (shared helper)
# =====================================================
def get_user_from_token(authorization: str) -> int:
    """Extract and validate Bearer token, return UserId."""
    if not authorization:
        raise HTTPException(
            status_code=401, detail="Authorization header missing"
        )

    token = authorization.replace("Bearer ", "")

    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT UserId FROM LoginSessions "
            "WHERE Token=%s AND IsActive=1",
            (token,),
        )
        row = cursor.fetchone()

        if not row:
            raise HTTPException(
                status_code=401, detail="Invalid or expired session"
            )

        return row[0]
    finally:
        conn.close()


# =====================================================
# USER PROFILE (token-based)
# =====================================================
@app.get("/user/profile")
def get_profile(authorization: str = Header(None)):
    user_id = get_user_from_token(authorization)

    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT FullName, Email, Role FROM Users WHERE UserId=%s",
            (user_id,),
        )
        user = cursor.fetchone()

        if not user:
            raise HTTPException(
                status_code=404, detail="User not found"
            )

        role = user[2]
        profile = {
            "user_id": user_id,
            "name": user[0],
            "email": user[1],
            "role": role,
        }

        # ---------- STUDENT ----------
        if role == "STUDENT":
            cursor.execute(
                """
                SELECT RollNo, RegistrationNo, Semester,
                       StudentEmail, ParentEmail
                FROM StudentProfile WHERE StudentId=%s
                """,
                (user_id,),
            )
            d = cursor.fetchone()
            if d:
                profile.update({
                    "roll_no": d[0],
                    "registration_no": d[1],
                    "semester": d[2],
                    "student_email": d[3],
                    "parent_email": d[4],
                })

        # ---------- PROFESSOR ----------
        elif role == "PROFESSOR":
            cursor.execute(
                "SELECT ProfessorCode, Email "
                "FROM ProfessorProfile WHERE ProfessorId=%s",
                (user_id,),
            )
            d = cursor.fetchone()
            if d:
                profile.update({
                    "professor_code": d[0],
                    "professor_email": d[1],
                })

        # ---------- DEAN ----------
        elif role == "DEAN":
            cursor.execute(
                "SELECT DeanCode, Email "
                "FROM DeanProfile WHERE DeanId=%s",
                (user_id,),
            )
            d = cursor.fetchone()
            if d:
                profile.update({
                    "dean_code": d[0],
                    "dean_email": d[1],
                })

        return profile

    finally:
        conn.close()


# =====================================================
# LEAVE — APPLY (normal)
# =====================================================
@app.post("/leave/apply")
def apply_leave(data: LeaveApply):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT ProfessorId FROM StudentProfessorMapping "
            "WHERE StudentId=%s",
            (data.student_id,),
        )
        prof = cursor.fetchone()

        cursor.execute("SELECT DeanId FROM DeanProfile")
        dean = cursor.fetchone()

        if not prof or not dean:
            raise HTTPException(
                status_code=400,
                detail="Professor or Dean not configured",
            )

        cursor.execute(
            """
            INSERT INTO LeaveApplications
                (StudentId, ProfessorId, DeanId,
                 ProfessorStatus, DeanStatus,
                 FromDate, ToDate, Reason)
            VALUES (%s, %s, %s, 'PENDING', 'PENDING', %s, %s, %s)
            """,
            (
                data.student_id, prof[0], dean[0],
                data.from_date, data.to_date, data.reason,
            ),
        )

        conn.commit()
        return {"message": "Leave applied successfully"}

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# =====================================================
# LEAVE — EMERGENCY (skip professor)
# =====================================================
@app.post("/leave/emergency")
def emergency_leave(data: EmergencyLeave):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT ProfessorId FROM StudentProfessorMapping "
            "WHERE StudentId=%s",
            (data.student_id,),
        )
        prof = cursor.fetchone()

        cursor.execute("SELECT DeanId FROM DeanProfile")
        dean = cursor.fetchone()

        if not prof or not dean:
            raise HTTPException(
                status_code=400,
                detail="Professor or Dean not configured",
            )

        cursor.execute(
            """
            INSERT INTO LeaveApplications
                (StudentId, ProfessorId, DeanId,
                 ProfessorStatus, DeanStatus,
                 FromDate, ToDate, Reason)
            VALUES (%s, %s, %s, 'SKIPPED', 'PENDING', %s, %s, %s)
            """,
            (
                data.student_id, prof[0], dean[0],
                data.from_date, data.to_date, data.reason,
            ),
        )

        conn.commit()
        return {"message": "Emergency leave sent to Dean directly"}

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# =====================================================
# STUDENT — VIEW LEAVES
# =====================================================
@app.get("/student/leaves/{student_id}")
def student_leaves(student_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT LeaveId, ProfessorStatus, DeanStatus, FinalStatus
            FROM LeaveApplications WHERE StudentId=%s
            """,
            (student_id,),
        )
        rows = cursor.fetchall()
        return [
            {
                "leave_id": r[0],
                "professor_status": r[1],
                "dean_status": r[2],
                "final_status": r[3],
            }
            for r in rows
        ]
    finally:
        conn.close()


@app.get("/student/approved/{student_id}")
def student_approved(student_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT LeaveId, FromDate, ToDate, Reason
            FROM LeaveApplications
            WHERE StudentId=%s AND FinalStatus='FINAL_APPROVED'
            """,
            (student_id,),
        )
        rows = cursor.fetchall()
        return [
            {
                "leave_id": r[0],
                "from_date": str(r[1]),
                "to_date": str(r[2]),
                "reason": r[3],
            }
            for r in rows
        ]
    finally:
        conn.close()


@app.get("/student/rejected/{student_id}")
def student_rejected(student_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT LeaveId, FromDate, ToDate, Reason
            FROM LeaveApplications
            WHERE StudentId=%s AND FinalStatus LIKE 'REJECTED%%'
            """,
            (student_id,),
        )
        rows = cursor.fetchall()
        return [
            {
                "leave_id": r[0],
                "from_date": str(r[1]),
                "to_date": str(r[2]),
                "reason": r[3],
            }
            for r in rows
        ]
    finally:
        conn.close()


# =====================================================
# PROFESSOR — PENDING / APPROVED / REJECTED
# =====================================================
@app.get("/professor/pending/{professor_id}")
def professor_pending(professor_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT l.LeaveId, l.StudentId, u.FullName, s.Semester,
                   l.FromDate, l.ToDate, l.Reason
            FROM LeaveApplications l
            JOIN Users u ON l.StudentId = u.UserId
            JOIN StudentProfile s ON s.StudentId = l.StudentId
            WHERE l.ProfessorId=%s AND l.ProfessorStatus='PENDING'
            """,
            (professor_id,),
        )
        rows = cursor.fetchall()
        return [
            {
                "leave_id": r[0],
                "student_id": r[1],
                "student_name": r[2],
                "semester": r[3],
                "from_date": str(r[4]),
                "to_date": str(r[5]),
                "reason": r[6],
            }
            for r in rows
        ]
    finally:
        conn.close()


@app.get("/professor/approved/{professor_id}")
def professor_approved(professor_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT l.LeaveId, u.FullName, s.Semester,
                   l.FromDate, l.ToDate
            FROM LeaveApplications l
            JOIN Users u ON l.StudentId = u.UserId
            JOIN StudentProfile s ON s.StudentId = l.StudentId
            WHERE l.ProfessorId=%s AND l.ProfessorStatus='APPROVED'
            """,
            (professor_id,),
        )
        rows = cursor.fetchall()
        return [
            {
                "leave_id": r[0],
                "student_name": r[1],
                "semester": r[2],
                "from_date": str(r[3]),
                "to_date": str(r[4]),
            }
            for r in rows
        ]
    finally:
        conn.close()


@app.get("/professor/rejected/{professor_id}")
def professor_rejected(professor_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT l.LeaveId, u.FullName, s.Semester,
                   l.FromDate, l.ToDate
            FROM LeaveApplications l
            JOIN Users u ON l.StudentId = u.UserId
            JOIN StudentProfile s ON s.StudentId = l.StudentId
            WHERE l.ProfessorId=%s AND l.ProfessorStatus='REJECTED'
            """,
            (professor_id,),
        )
        rows = cursor.fetchall()
        return [
            {
                "leave_id": r[0],
                "student_name": r[1],
                "semester": r[2],
                "from_date": str(r[3]),
                "to_date": str(r[4]),
            }
            for r in rows
        ]
    finally:
        conn.close()


@app.get("/professor/students/{professor_id}")
def professor_students(professor_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT sp.Semester, COUNT(*) AS total_students
            FROM StudentProfessorMapping sp
            WHERE sp.ProfessorId=%s
            GROUP BY sp.Semester
            """,
            (professor_id,),
        )
        rows = cursor.fetchall()
        return [
            {"semester": r[0], "total_students": r[1]}
            for r in rows
        ]
    finally:
        conn.close()


# =====================================================
# PROFESSOR — ACTION (approve / reject)
# =====================================================
@app.post("/leave/professor-action")
def professor_action(data: Action):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        status = "APPROVED" if data.action == "APPROVED" else "REJECTED"
        final = (
            "FORWARDED_TO_DEAN"
            if status == "APPROVED"
            else "REJECTED_BY_PROFESSOR"
        )

        cursor.execute(
            """
            UPDATE LeaveApplications
            SET ProfessorStatus=%s, FinalStatus=%s
            WHERE LeaveId=%s
            """,
            (status, final, data.leave_id),
        )

        conn.commit()
        return {
            "message": f"Professor {status.lower()} the leave",
            "final_status": final,
        }

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# =====================================================
# DEAN — PENDING / APPROVED / EMERGENCY / STUDENTS
# =====================================================
@app.get("/dean/pending")
def dean_pending():
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT l.LeaveId, l.StudentId, u.FullName, s.Semester,
                   l.FromDate, l.ToDate, l.Reason
            FROM LeaveApplications l
            JOIN Users u ON l.StudentId = u.UserId
            JOIN StudentProfile s ON s.StudentId = l.StudentId
            WHERE l.DeanStatus='PENDING'
            """
        )
        rows = cursor.fetchall()
        return [
            {
                "leave_id": r[0],
                "student_id": r[1],
                "student_name": r[2],
                "semester": r[3],
                "from_date": str(r[4]),
                "to_date": str(r[5]),
                "reason": r[6],
            }
            for r in rows
        ]
    finally:
        conn.close()


@app.get("/dean/approved")
def dean_approved():
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT l.LeaveId, l.StudentId, u.FullName, s.Semester,
                   l.FromDate, l.ToDate, l.Reason
            FROM LeaveApplications l
            JOIN Users u ON l.StudentId = u.UserId
            JOIN StudentProfile s ON s.StudentId = l.StudentId
            WHERE l.DeanStatus='APPROVED'
            """
        )
        rows = cursor.fetchall()
        return [
            {
                "leave_id": r[0],
                "student_id": r[1],
                "student_name": r[2],
                "semester": r[3],
                "from_date": str(r[4]),
                "to_date": str(r[5]),
                "reason": r[6],
            }
            for r in rows
        ]
    finally:
        conn.close()


@app.get("/dean/emergency")
def dean_emergency():
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT l.LeaveId, l.StudentId, u.FullName, s.Semester,
                   l.FromDate, l.ToDate, l.Reason
            FROM LeaveApplications l
            JOIN Users u ON l.StudentId = u.UserId
            JOIN StudentProfile s ON s.StudentId = l.StudentId
            WHERE l.ProfessorStatus='SKIPPED'
              AND l.DeanStatus='PENDING'
            """
        )
        rows = cursor.fetchall()
        return [
            {
                "leave_id": r[0],
                "student_id": r[1],
                "student_name": r[2],
                "semester": r[3],
                "from_date": str(r[4]),
                "to_date": str(r[5]),
                "reason": r[6],
            }
            for r in rows
        ]
    finally:
        conn.close()


@app.get("/dean/students")
def dean_students():
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT u.UserId, u.FullName, s.RollNo,
                   s.RegistrationNo, s.Semester,
                   s.StudentEmail, s.ParentEmail
            FROM Users u
            JOIN StudentProfile s ON u.UserId = s.StudentId
            WHERE u.Role='STUDENT' AND u.IsActive=1
            """
        )
        rows = cursor.fetchall()
        return [
            {
                "user_id": r[0],
                "name": r[1],
                "roll_no": r[2],
                "registration_no": r[3],
                "semester": r[4],
                "student_email": r[5],
                "parent_email": r[6],
            }
            for r in rows
        ]
    finally:
        conn.close()


@app.get("/dean/semester-wise")
def semester_wise():
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT s.Semester,
                   u.FullName     AS StudentName,
                   s.RollNo,
                   pUser.FullName AS ProfessorName
            FROM StudentProfessorMapping sp
            JOIN Users u            ON sp.StudentId   = u.UserId
            JOIN StudentProfile s   ON s.StudentId    = u.UserId
            JOIN Users pUser        ON pUser.UserId   = sp.ProfessorId
            ORDER BY s.Semester, s.RollNo
            """
        )
        rows = cursor.fetchall()
        return [
            {
                "semester": r[0],
                "student_name": r[1],
                "roll_no": r[2],
                "professor_name": r[3],
            }
            for r in rows
        ]
    finally:
        conn.close()


# =====================================================
# DEAN — ACTION (approve / reject + parent email)
# =====================================================
@app.post("/leave/dean-action")
def dean_action(data: Action):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        status = "APPROVED" if data.action == "APPROVED" else "REJECTED"
        final = (
            "FINAL_APPROVED"
            if status == "APPROVED"
            else "REJECTED_BY_DEAN"
        )

        # update leave record
        cursor.execute(
            """
            UPDATE LeaveApplications
            SET DeanStatus=%s, FinalStatus=%s
            WHERE LeaveId=%s
            """,
            (status, final, data.leave_id),
        )

        # fetch student + parent info for email
        cursor.execute(
            """
            SELECT u.FullName, s.ParentEmail,
                   l.FromDate, l.ToDate, l.Reason
            FROM LeaveApplications l
            JOIN Users u          ON l.StudentId = u.UserId
            JOIN StudentProfile s ON s.StudentId = l.StudentId
            WHERE l.LeaveId=%s
            """,
            (data.leave_id,),
        )
        row = cursor.fetchone()

        conn.commit()

        # send parent notification via brevo
        if row:
            try:
                send_parent_email(
                    parent_email=row[1],
                    student_name=row[0],
                    from_date=str(row[2]),
                    to_date=str(row[3]),
                    reason=row[4],
                    status=status,
                )
                email_sent = True
            except Exception as mail_err:
                print(f"Brevo email error: {mail_err}")
                email_sent = False
        else:
            email_sent = False

        return {
            "message": f"Dean {status.lower()} the leave",
            "final_status": final,
            "parent_email_sent": email_sent,
        }

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# =====================================================
# RUN
# =====================================================
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
