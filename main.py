
import pymssql
import random
import uuid
import requests
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import Optional
import os
import firebase_admin
from firebase_admin import credentials, messaging
import json



# 🔥 Firebase Setup
firebase_key = json.loads(os.environ["FIREBASE_KEY"])
cred = credentials.Certificate(firebase_key)
firebase_admin.initialize_app(cred)

# =====================================================
# CONFIG
# =====================================================

# --- Brevo Email Config ---
BREVO_API_KEY = os.getenv("KEY")
BREVO_SENDER_EMAIL = "patelkanostudent@gmail.com"
BREVO_SENDER_NAME = "College ERP System"
BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"

# --- Database Config ---
DB_SERVER = "kano2026.mssql.somee.com:1433"   # ✅ fixed
DB_USER = "Dhvanit_SQLLogin_1"
DB_PASSWORD = os.getenv("PASS")
DB_NAME = "kano2026"
# =====================================================

# =====================================================
# FASTAPI APP
# =====================================================
app = FastAPI(title="College ERP Backend")



# =====================================================
# DATABASE CONNECTION
# =====================================================
# Use connection pooling
from queue import Queue

connection_pool = Queue(maxsize=5)

def get_connection():
    if not connection_pool.empty():
        return connection_pool.get()
    return pymssql.connect(
        server=DB_SERVER,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME
    )

def return_connection(conn):
    connection_pool.put(conn)

# =====================================================
# BREVO EMAIL — CORE FUNCTION
# =====================================================
def send_email_brevo(to_email: str, subject: str, body: str) -> bool:
    """
    Send email using Brevo transactional API.
    Returns True on success, False on failure.
    """
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "api-key": BREVO_API_KEY
    }

    payload = {
        "sender": {
            "name": BREVO_SENDER_NAME,
            "email": BREVO_SENDER_EMAIL
        },
        "to": [
            {
                "email": to_email,
                "name": to_email
            }
        ],
        "subject": subject,
        "textContent": body
    }

    try:
        response = requests.post(
            BREVO_API_URL,
            json=payload,
            headers=headers,
            timeout=30
        )

        print(f"Brevo Status Code: {response.status_code}")
        print(f"Brevo Response: {response.text}")

        if response.status_code in (200, 201):
            print(f"Email sent successfully to: {to_email}")
            return True
        else:
            print(f"Brevo FAILED: {response.status_code} - {response.text}")
            return False

    except requests.exceptions.Timeout:
        print("Brevo Error: Request timed out")
        return False

    except requests.exceptions.ConnectionError:
        print("Brevo Error: Cannot connect to Brevo API")
        return False

    except Exception as e:
        print(f"Brevo Error: {e}")
        return False


# =====================================================
# OTP EMAIL
# =====================================================
def generate_otp() -> str:
    return str(random.randint(100000, 999999))


def send_otp_email(email: str, otp: str) -> bool:
    subject = "College Leave Management System — Login OTP"
    body = f"Your OTP is {otp}. Valid for 5 minutes."
    return send_email_brevo(email, subject, body)


# =====================================================
# PARENT NOTIFICATION EMAIL
# =====================================================
def send_parent_email(
    parent_email: str,
    student_name: str,
    from_date: str,
    to_date: str,
    reason: str,
    status: str
) -> bool:
    subject = f"Leave {status} Notification"
    body = (
        f"Dear Parent,\n\n"
        f"Your ward {student_name} applied for leave.\n\n"
        f"From: {from_date}\n"
        f"To: {to_date}\n"
        f"Reason: {reason}\n\n"
        f"Status: {status}\n\n"
        f"Thank you.\n"
        f"College ERP System"
    )
    return send_email_brevo(parent_email, subject, body)


# =====================================================
# PYDANTIC MODELS
# =====================================================
class StudentRegister(BaseModel):
    fullname: str
    roll_no: int
    registration_no: str
    semester: int
    student_email: str
    parent_email: str
    phone_no:str

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
# TOKEN VALIDATION
# =====================================================
def get_user_from_token(authorization: str) -> int:
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Authorization header missing"
        )

    token = authorization.replace("Bearer ", "")

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT UserId FROM LoginSessions "
            "WHERE Token=%s AND IsActive=1",
            (token,)
        )
        row = cursor.fetchone()

        if not row:
            raise HTTPException(
                status_code=401,
                detail="Invalid session"
            )

        return row[0]
    finally:
        conn.close()


# =====================================================
# TEST BREVO EMAIL ENDPOINT
# =====================================================
@app.get("/test/email/{to_email}")
def test_email(to_email: str):
    """
    Test endpoint to check if Brevo email works.
    Usage: GET /test/email/someone@gmail.com
    """
    success = send_email_brevo(
        to_email=to_email,
        subject="Test Email from College ERP",
        body="If you received this, Brevo is working correctly!"
    )

    if success:
        return {
            "status": "success",
            "message": f"Test email sent to {to_email}"
        }
    else:
        raise HTTPException(
            status_code=500,
            detail="Brevo email failed. Check console logs."
        )


# =====================================================
# DASHBOARD
# =====================================================
@app.get("/dashboard")
def dashboard():
    conn = get_connection()
    try:
        cursor = conn.cursor()
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
    nms = 0
    conn = get_connection()
    try:
        cursor = conn.cursor()

        # Check duplicate email
        cursor.execute(
            "SELECT 1 FROM Users WHERE Email=%s",
            (data.student_email,)
        )
        if cursor.fetchone():
            raise HTTPException(
                status_code=400,
                detail="Email already registered"
            )

        # Check duplicate registration
        cursor.execute(
            "SELECT 1 FROM StudentProfile WHERE RegistrationNo=%s",
            (data.registration_no,)
        )
        if cursor.fetchone():
            raise HTTPException(
                status_code=400,
                detail="Student already registered"
            )

        # Insert user
        cursor.execute(
            "INSERT INTO Users (FullName, Email, Role, PhoneNumber) "
            "VALUES (%s, %s, 'STUDENT', %s)",
            (data.fullname, data.student_email, data.phone_no)
        )

        # Get new user ID
        cursor.execute("SELECT SCOPE_IDENTITY()")
        student_id = cursor.fetchone()[0]
        nms = nms + 1

        # Insert student profile
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
                data.parent_email
            )
        )

        # Find available professor
        cursor.execute(
    """
    SELECT p.ProfessorId
    FROM ProfessorProfile p
    LEFT JOIN StudentProfessorMapping sp
        ON p.ProfessorId = sp.ProfessorId
        AND sp.Semester = %s
    GROUP BY p.ProfessorId
    HAVING COUNT(sp.StudentId) < 7
    ORDER BY COUNT(sp.StudentId) ASC
    """,
    (data.semester,)
)
        prof = cursor.fetchone()

        if not prof:
            raise HTTPException(
                status_code=400,
                detail="No professor available"
            )

        # Map student to professor
        cursor.execute(
            """
            INSERT INTO StudentProfessorMapping
            (StudentId, ProfessorId, Semester)
            VALUES (%s, %s, %s)
            """,
            (student_id, prof[0], data.semester)
        )

        conn.commit()

        return {
            "message": "Student registered",
            "professor": prof[0],
            "number_of_student": nms
        }

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# =====================================================
# AUTH — SEND OTP (via Brevo)
# =====================================================
'''@app.post("/auth/send-otp")
def send_otp(data: SendOTP):
    conn = get_connection()
    try:
        cursor = conn.cursor()

        # Check user exists
        cursor.execute(
            "SELECT UserId FROM Users "
            "WHERE Email=%s AND IsActive=1",
            (data.email,)
        )
        user = cursor.fetchone()

        if not user:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        # Generate OTP
        otp = generate_otp()
        expiry = datetime.now() + timedelta(minutes=5)

        # Save OTP to database
        cursor.execute(
            "INSERT INTO EmailOTP (Email, OTPCode, ExpiryTime) "
            "VALUES (%s, %s, %s)",
            (data.email, otp, expiry)
        )
        conn.commit()

        # Send OTP via Brevo
        email_sent = send_otp_email(data.email, otp)

        if email_sent:
            return {"message": "OTP sent successfully via Brevo"}
        else:
            return {
                "message": "OTP saved in database but email failed",
                "otp_for_debug": otp,
                "warning": "Check Brevo API key and sender verification"
            }

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()
'''
@app.post("/auth/send-otp")
def send_otp(data: SendOTP):
    conn = get_connection()
    try:
        cursor = conn.cursor()

        # =========================
        # 🔍 GET USER + PHONE
        # =========================
        cursor.execute(
            "SELECT UserId, PhoneNumber FROM Users WHERE Email=%s AND IsActive=1",
            (data.email,)
        )
        user = cursor.fetchone()

        if not user:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        user_id = user[0]
        phone = user[1]

        # =========================
        # 🔐 GENERATE OTP
        # =========================
        otp = generate_otp()
        expiry = datetime.now() + timedelta(minutes=5)

        # =========================
        # 💾 SAVE OTP
        # =========================
        cursor.execute(
            "INSERT INTO EmailOTP (Email, OTPCode, ExpiryTime) VALUES (%s, %s, %s)",
            (data.email, otp, expiry)
        )
        conn.commit()

        # =========================
        # ✅ EMAIL (MANDATORY)
        # =========================
        email_sent = send_otp_email(data.email, otp)

        if not email_sent:
            raise HTTPException(
                status_code=500,
                detail="Email sending failed"
            )

        # =========================
        # ⚠️ SMS (OPTIONAL)
        # =========================
        sms_status = "no phone"

        print("Fetched Phone:", phone)  # DEBUG

        if phone and phone.strip() != "" and phone != "None":
            try:
                message = f"Wel-come-to-collage-leave-management-system-Your-OTP-is:{otp}-This-OTP-Valid-For-5-Minutes-This-is-own-sms-service-for-education-purpose-only"

                sms_url = (
                    "https://6qc7h5fcwkof.share.zrok.io/"
                    f"?key=12345&phone={phone}&msg={message}"
                )

                print("SMS URL:", sms_url)  # DEBUG

                res = requests.get(sms_url, timeout=5)

                print("SMS Response:", res.status_code, res.text)  # DEBUG

                if res.status_code == 200:
                    sms_status = "sent"
                else:
                    sms_status = "failed"

            except Exception as e:
                print("SMS ERROR:", e)
                sms_status = "failed"
        # =========================
        # 🎯 RESPONSE
        # =========================
        return {
            "message": "OTP sent to Email (SMS optional)",
            "email": "sent",
            "sms": sms_status,
            "phone_used": phone  # debug (optional remove later)
        }

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
    try:
        cursor = conn.cursor()

        # Validate OTP
        cursor.execute(
            """
            SELECT OTPId FROM EmailOTP
            WHERE Email=%s AND OTPCode=%s
              AND IsUsed=0 AND ExpiryTime>=GETDATE()
            """,
            (data.email, data.otp)
        )
        otp_row = cursor.fetchone()

        if not otp_row:
            raise HTTPException(
                status_code=400,
                detail="Invalid OTP"
            )

        # Mark OTP used
        cursor.execute(
            "UPDATE EmailOTP SET IsUsed=1 WHERE OTPId=%s",
            (otp_row[0],)
        )

        # Get user
        cursor.execute(
            "SELECT UserId, Role FROM Users "
            "WHERE Email=%s AND IsActive=1",
            (data.email,)
        )
        user = cursor.fetchone()

        if not user:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        # Create session
        token = str(uuid.uuid4())

        cursor.execute(
            "UPDATE LoginSessions SET IsActive=0 "
            "WHERE UserId=%s",
            (user[0],)
        )

        cursor.execute(
            "INSERT INTO LoginSessions (UserId, Token) "
            "VALUES (%s, %s)",
            (user[0], token)
        )

        conn.commit()

        return {
            "login": "success",
            "token": token,
            "user_id": user[0],
            "role": user[1]
        }

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# =====================================================
# APPLY LEAVE
# =====================================================
@app.post("/leave/apply")
def apply_leave(
    data: LeaveApply,
    authorization: str = Header(None)
):
    
    data.student_id = get_user_from_token(authorization)
    conn = get_connection()
    try:
        cursor = conn.cursor()

        cursor.execute(
            "SELECT ProfessorId FROM StudentProfessorMapping WHERE StudentId=%s",
            (data.student_id,)
        )
        prof = cursor.fetchone()

        cursor.execute("SELECT DeanId FROM DeanProfile")
        dean = cursor.fetchone()

        if not prof or not dean:
            raise HTTPException(status_code=400, detail="Config error")

        # INSERT
        cursor.execute(
            """
            INSERT INTO LeaveApplications
            (StudentId, ProfessorId, DeanId,
             ProfessorStatus, DeanStatus,
             FromDate, ToDate, Reason)
            VALUES (%s,%s,%s,'PENDING','PENDING',%s,%s,%s)
            """,
            (
                data.student_id,
                prof[0],
                dean[0],
                data.from_date,
                data.to_date,
                data.reason
            )
        )

            # Inside @app.post("/leave/apply")
        cursor.execute(
        "SELECT FcmToken FROM Users WHERE UserId=%s",
        (prof[0],)
        )
        prof_token = cursor.fetchone()

        if prof_token and prof_token[0]:
            send_fcm(prof_token[0],"New Leave Request",f"Student {data.student_id} has applied for leave.")
        conn.commit()
        
        return {"message": "Leave applied successfully"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        conn.close()# =====================================================
# STUDENT LEAVE VIEWS
# =====================================================
@app.get("/student/rejected/{student_id}")
def student_rejected(student_id: int):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT LeaveId, FromDate, ToDate, Reason
            FROM LeaveApplications
            WHERE StudentId=%s
              AND FinalStatus LIKE 'REJECTED%%'
            """,
            (student_id,)
        )
        rows = cursor.fetchall()
        return [list(r) for r in rows]
    finally:
        conn.close()


@app.get("/student/approved/{student_id}")
def student_approved(student_id: int):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT LeaveId, FromDate, ToDate, Reason
            FROM LeaveApplications
            WHERE StudentId=%s
              AND FinalStatus='FINAL_APPROVED'
            """,
            (student_id,)
        )
        rows = cursor.fetchall()
        return [list(r) for r in rows]
    finally:
        conn.close()


@app.get("/student/leaves/{student_id}") # ✅ Added {student_id} to match Flutter
def student_leaves(student_id: int):      # ✅ Accepting ID as a parameter
    conn = get_connection()
    try:
        cursor = conn.cursor()
        # Fetching TOP 5 to keep the dashboard clean
        cursor.execute(
            """
            SELECT TOP 5 
                LeaveId, ProfessorStatus, DeanStatus, FinalStatus, FromDate, ToDate, Reason
            FROM LeaveApplications
            WHERE StudentId=%s
            ORDER BY LeaveId DESC
            """,
            (student_id,)
        )
        rows = cursor.fetchall()
        
        results = []
        for r in rows:
            # --- STATUS MINING LOGIC ---
            # This tells the student exactly who needs to take action next
            if r[3] == 'PENDING' and r[1] == 'PENDING':
                mining_status = "Waiting for Professor"
            elif r[1] == 'APPROVED' and r[2] == 'PENDING':
                mining_status = "Waiting for Dean"
            elif r[3] == 'FINAL_APPROVED':
                mining_status = "Approved ✅"
            elif 'REJECTED' in r[3]:
                mining_status = "Rejected ❌"
            else:
                mining_status = r[3] # Fallback to FinalStatus

            results.append({
                "leave_id": r[0],
                "professor_status": r[1],
                "dean_status": r[2],
                "final_status": r[3],
                "display_status": mining_status, # ✅ NEW: Send this to Flutter
                "from_date": str(r[4]),
                "to_date": str(r[5]),
                "reason": r[6]
            })
        return results
    finally:
        conn.close()
# =====================================================
# EMERGENCY LEAVE
# =====================================================

@app.post("/leave/emergency")
def emergency_leave(
    data: EmergencyLeave,
    authorization: str = Header(None)
):
    data.student_id = get_user_from_token(authorization)
    conn = get_connection()
    try:
        cursor = conn.cursor()

        cursor.execute(
            "SELECT ProfessorId FROM StudentProfessorMapping WHERE StudentId=%s",
            (data.student_id,)
        )
        prof = cursor.fetchone()

        cursor.execute("SELECT DeanId FROM DeanProfile")
        dean = cursor.fetchone()

        if not prof or not dean:
            raise HTTPException(status_code=400, detail="Configuration error")

        cursor.execute(
            """
            INSERT INTO LeaveApplications
            (StudentId, ProfessorId, DeanId,
             ProfessorStatus, DeanStatus,
             FromDate, ToDate, Reason)
            VALUES (%s, %s, %s, 'SKIPPED', 'PENDING', %s, %s, %s)
            """,
            (data.student_id, prof[0], dean[0],
             data.from_date, data.to_date, data.reason)
        )
        conn.commit()  # ✅ Moved outside the if block

        # Notify Dean
        cursor.execute("SELECT FcmToken FROM Users WHERE Role='DEAN'")
        dean_token = cursor.fetchone()
        if dean_token and dean_token[0]:
            send_fcm(
                dean_token[0],
                "🚨 EMERGENCY LEAVE",
                f"Student {data.student_id} requested emergency leave."
            )

        return {"message": "Emergency leave applied"}  # ✅ Always returns

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

# =====================================================
# DEAN APIs
# =====================================================
@app.get("/dean/pending")
def dean_pending():
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT l.LeaveId, l.StudentId, u.FullName,
                   s.Semester, l.FromDate, l.ToDate, l.Reason
            FROM LeaveApplications l
            JOIN Users u ON l.StudentId = u.UserId
            JOIN StudentProfile s ON s.StudentId = l.StudentId
            WHERE l.DeanStatus='PENDING'
            """
        )
        rows = cursor.fetchall()
        return [list(r) for r in rows]
    finally:
        conn.close()


@app.get("/dean/approved")
def dean_approved():
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT l.LeaveId, l.StudentId, u.FullName,
                   s.Semester, l.FromDate, l.ToDate, l.Reason
            FROM LeaveApplications l
            JOIN Users u ON l.StudentId = u.UserId
            JOIN StudentProfile s ON s.StudentId = l.StudentId
            WHERE l.DeanStatus='APPROVED'
            """
        )
        rows = cursor.fetchall()
        return [list(r) for r in rows]
    finally:
        conn.close()


@app.get("/dean/emergency")
def dean_emergency():
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT l.LeaveId, l.StudentId, u.FullName,
                   s.Semester, l.FromDate, l.ToDate, l.Reason
            FROM LeaveApplications l
            JOIN Users u ON l.StudentId = u.UserId
            JOIN StudentProfile s ON s.StudentId = l.StudentId
            WHERE l.ProfessorStatus='SKIPPED'
              AND l.DeanStatus='PENDING'
            """
        )
        rows = cursor.fetchall()
        return [list(r) for r in rows]
    finally:
        conn.close()


@app.get("/dean/students")
def dean_students():
    conn = get_connection()
    try:
        cursor = conn.cursor()
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
        return [list(r) for r in rows]
    finally:
        conn.close()


@app.post("/leave/dean-action")
def dean_action(data: Action):

    conn = get_connection()
    try:
        cursor = conn.cursor()

        status = "APPROVED" if data.action == "APPROVED" else "REJECTED"
        final_status = (
            "FINAL_APPROVED" if status == "APPROVED"
            else "REJECTED_BY_DEAN"
        )

        cursor.execute(
            """
            UPDATE LeaveApplications
            SET DeanStatus=%s, FinalStatus=%s
            WHERE LeaveId=%s
            """,
            (status, final_status, data.leave_id)
        )
        conn.commit()
        # Get student + parent info
        cursor.execute(
            """
            SELECT u.FullName, s.ParentEmail,
                   l.FromDate, l.ToDate, l.Reason
            FROM LeaveApplications l
            JOIN Users u ON l.StudentId = u.UserId
            JOIN StudentProfile s ON s.StudentId = l.StudentId
            WHERE l.LeaveId=%s
            """,
            (data.leave_id,)
        )
        row = cursor.fetchone()


        # Send parent email via Brevo
        email_sent = False
        if row:
            try:
                email_sent = send_parent_email(
                    parent_email=row[1],
                    student_name=row[0],
                    from_date=str(row[2]),
                    to_date=str(row[3]),
                    reason=row[4],
                    status=status
                )
            except Exception as mail_err:
                print(f"Parent Email Error: {mail_err}")
 

        # ✅ GET STUDENT TOKEN
        cursor.execute(
            "SELECT u.FcmToken FROM LeaveApplications l "
            "JOIN Users u ON l.StudentId=u.UserId "
            "WHERE l.LeaveId=%s",
            (data.leave_id,)
        )
        student = cursor.fetchone()

        conn.commit()
        # ✅ SEND FCM
        if student and student[0]:
            send_fcm(
                student[0],
                "Leave Status",
                f"Your leave is {status}"
                    )
        # Inside @app.post("/leave/dean-action")
        cursor.execute(
            "SELECT FcmToken FROM Users WHERE UserId = "
            "(SELECT StudentId FROM LeaveApplications WHERE LeaveId = %s)",
            (data.leave_id,)
        )
        student_token = cursor.fetchone()

        if student_token and student_token[0]:
            status_msg = "Approved" if data.action == "APPROVED" else "Rejected"
            send_fcm(student_token[0], "Leave Decision", f"The Dean has {status_msg} your leave request.")
           
        return {
                        "message": f"Dean action done ({status})",
                        "parent_email_sent": email_sent
                    }
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        conn.close()

@app.get("/dean/semester-wise")
def semester_wise():
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT s.Semester,
                   u.FullName AS StudentName,
                   s.RollNo,
                   pUser.FullName AS ProfessorName
            FROM StudentProfessorMapping sp
            JOIN Users u ON sp.StudentId = u.UserId
            JOIN StudentProfile s ON s.StudentId = u.UserId
            JOIN Users pUser ON pUser.UserId = sp.ProfessorId
            ORDER BY s.Semester, s.RollNo
            """
        )
        rows = cursor.fetchall()
        return [list(r) for r in rows]
    finally:
        conn.close()


# =====================================================
# PROFESSOR APIs
# =====================================================
@app.get("/professor/pending/{professor_id}")
def professor_pending(professor_id: int):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT l.LeaveId, l.StudentId, u.FullName,
                   s.Semester, l.FromDate, l.ToDate, l.Reason
            FROM LeaveApplications l
            JOIN Users u ON l.StudentId = u.UserId
            JOIN StudentProfile s ON s.StudentId = l.StudentId
            WHERE l.ProfessorId=%s
              AND l.ProfessorStatus='PENDING'
            """,
            (professor_id,)
        )
        rows = cursor.fetchall()
        return [list(r) for r in rows]
    finally:
        conn.close()


@app.get("/professor/approved/{professor_id}")
def professor_approved(professor_id: int):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT l.LeaveId, u.FullName, s.Semester,
                   l.FromDate, l.ToDate
            FROM LeaveApplications l
            JOIN Users u ON l.StudentId = u.UserId
            JOIN StudentProfile s ON s.StudentId = l.StudentId
            WHERE l.ProfessorId=%s
              AND l.ProfessorStatus='APPROVED'
            """,
            (professor_id,)
        )
        rows = cursor.fetchall()
        return [list(r) for r in rows]
    finally:
        conn.close()


@app.get("/professor/rejected/{professor_id}")
def professor_rejected(professor_id: int):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT l.LeaveId, u.FullName, s.Semester,
                   l.FromDate, l.ToDate
            FROM LeaveApplications l
            JOIN Users u ON l.StudentId = u.UserId
            JOIN StudentProfile s ON s.StudentId = l.StudentId
            WHERE l.ProfessorId=%s
              AND l.ProfessorStatus='REJECTED'
            """,
            (professor_id,)
        )
        rows = cursor.fetchall()
        return [list(r) for r in rows]
    finally:
        conn.close()


@app.get("/professor/students/{professor_id}")
def professor_students(professor_id: int):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT sp.Semester,
                   COUNT(*) AS total_students
            FROM StudentProfessorMapping sp
            WHERE sp.ProfessorId=%s
            GROUP BY sp.Semester
            """,
            (professor_id,)
        )
        rows = cursor.fetchall()
        return [
            {
                "semester": r[0],
                "total_students": r[1]
            }
            for r in rows
        ]
    finally:
        conn.close()


@app.post("/leave/professor-action")
def professor_action(data: Action):
    conn = get_connection()
    try:
        cursor = conn.cursor()

        status = "APPROVED" if data.action == "APPROVED" else "REJECTED"
        final_status = (
            "FORWARDED_TO_DEAN" if status == "APPROVED"
            else "REJECTED_BY_PROFESSOR"
        )

        cursor.execute(
            """
            UPDATE LeaveApplications
            SET ProfessorStatus=%s, FinalStatus=%s
            WHERE LeaveId=%s
            """,
            (status, final_status, data.leave_id)
        )
        conn.commit()

        # ✅ Notify Dean only if approved — but always return a response
        if data.action == "APPROVED":
            cursor.execute("SELECT FcmToken FROM Users WHERE Role='DEAN'")
            dean_token = cursor.fetchone()
            if dean_token and dean_token[0]:
                send_fcm(
                    dean_token[0],
                    "Leave Forwarded",
                    f"Professor approved Leave ID {data.leave_id}. Action required."
                )

        return {"message": f"Professor action done ({status})"}  # ✅ Always returns

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()
# =====================================================
# USER PROFILE
# =====================================================
@app.get("/user/profile")
def get_profile(authorization: str = Header(None)):
    user_id = get_user_from_token(authorization)

    conn = get_connection()
    try:
        cursor = conn.cursor()

        cursor.execute(
            "SELECT FullName, Email, Role "
            "FROM Users WHERE UserId=%s",
            (user_id,)
        )
        user = cursor.fetchone()

        if not user:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        role = user[2]

        profile_data = {
            "user_id": user_id,
            "name": user[0],
            "email": user[1],
            "role": role
        }

        # STUDENT
        if role == "STUDENT":
            cursor.execute(
                """
                SELECT RollNo, RegistrationNo, Semester,
                       StudentEmail, ParentEmail
                FROM StudentProfile
                WHERE StudentId=%s
                """,
                (user_id,)
            )
            data = cursor.fetchone()

            if data:
                profile_data.update({
                    "roll_no": data[0],
                    "registration_no": data[1],
                    "semester": data[2],
                    "student_email": data[3],
                    "parent_email": data[4],
                })

        # PROFESSOR
        elif role == "PROFESSOR":
            cursor.execute(
                """
                SELECT ProfessorCode, Email
                FROM ProfessorProfile
                WHERE ProfessorId=%s
                """,
                (user_id,)
            )
            data = cursor.fetchone()

            if data:
                profile_data.update({
                    "professor_code": data[0],
                    "email": data[1],
                })

        # DEAN
        elif role == "DEAN":
            cursor.execute(
                """
                SELECT DeanCode, Email
                FROM DeanProfile
                WHERE DeanId=%s
                """,
                (user_id,)
            )
            data = cursor.fetchone()

            if data:
                profile_data.update({
                    "dean_code": data[0],
                    "email": data[1],
                })

        return profile_data

    finally:
        conn.close()

#==========================================================
# ===============================
# ADD PROFESSOR (DEAN)
# ==========================================================
# ADD PROFESSOR (DEAN)
# ==========================================================

class ProfessorCreate(BaseModel):
    full_name: str
    email: str


@app.post("/dean/add-professor")
def add_professor(prof: ProfessorCreate):

    conn = get_connection()

    try:
        cursor = conn.cursor()

        # check email already exists
        cursor.execute(
            "SELECT UserId FROM Users WHERE Email=%s",
            (prof.email,)
        )

        if cursor.fetchone():
            raise HTTPException(
                status_code=400,
                detail="Email already exists"
            )

        # insert into Users
        cursor.execute(
            """
            INSERT INTO Users (FullName, Email, Role, IsActive, CreatedAt)
            VALUES (%s,%s,'PROFESSOR',1,GETDATE())
            """,
            (prof.full_name, prof.email)
        )

        # get new professor id
        cursor.execute("SELECT SCOPE_IDENTITY()")
        professor_id = cursor.fetchone()[0]

        # generate professor code
        professor_code = f"PROF{int(professor_id):04d}"

        # insert into ProfessorProfile
        cursor.execute(
            """
            INSERT INTO ProfessorProfile
            (ProfessorId, ProfessorCode, Email)
            VALUES (%s,%s,%s)
            """,
            (
                professor_id,
                professor_code,
                prof.email
            )
        )

        conn.commit()

        return {
            "message": "Professor added successfully",
            "professor_id": professor_id,
            "professor_code": professor_code
        }

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        conn.close()
#==========================================================
#============================fcm tocken==============================
class SaveToken(BaseModel):
    fcm_token: str
@app.post("/save-fcm-token")
def save_fcm_token(data: SaveToken, authorization: str = Header(None)):
    user_id = get_user_from_token(authorization) 
    conn = get_connection()
    try:
        cursor = conn.cursor()
        # 1. Remove this device token from any other user (Switching logic)
                # This runs BEFORE commit, so the token isn't saved yet when you query it back
        cursor.execute(
            "UPDATE Users SET FcmToken = NULL WHERE FcmToken = %s AND UserId != %s",
            (data.fcm_token, user_id)
        )
        cursor.execute(
            "UPDATE Users SET FcmToken = %s WHERE UserId = %s",
            (data.fcm_token, user_id)
        )
        conn.commit()
        return {"status": "success", "message": "Token updated"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()
#=======================================================
def send_fcm(token, title, body):
    try:
        message = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
            token=token,
        )
        response = messaging.send(message)
        print(f"✅ FCM sent successfully: {response}")
    except Exception as e:
        # This is where your 'Permission denied' error is coming from
        print(f"❌ FCM FATAL ERROR: {str(e)}")
# =====================================================
#=============== extar report =========================
#all student 
@app.get("/reports/students")
def all_students_report():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT 
            u.UserId,
            u.FullName,
            sp.Semester,

            COUNT(l.LeaveId) AS total,

            ISNULL(SUM(CASE WHEN l.DeanStatus='APPROVED' THEN 1 END),0) AS approved,
            ISNULL(SUM(CASE WHEN l.DeanStatus='REJECTED' THEN 1 END),0) AS rejected,
            ISNULL(SUM(CASE WHEN l.DeanStatus='PENDING' THEN 1 END),0) AS pending

        FROM StudentProfile sp
        JOIN Users u ON sp.StudentId = u.UserId

        LEFT JOIN LeaveApplications l 
            ON l.StudentId = sp.StudentId

        GROUP BY u.UserId, u.FullName, sp.Semester
        ORDER BY sp.Semester ASC, u.FullName ASC
    """)

    rows = cursor.fetchall()
    conn.close()

    return [
        {
            "student_id": r[0],
            "name": r[1],
            "semester": r[2],
            "total": r[3],
            "approved": r[4],
            "rejected": r[5],
            "pending": r[6]
        }
        for r in rows
    ]
#Student-wise Leave Report
@app.get("/reports/student/{student_id}")
def student_report(student_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT 
            COUNT(*) as total,

            ISNULL(SUM(CASE WHEN DeanStatus='APPROVED' THEN 1 END),0),
            ISNULL(SUM(CASE WHEN DeanStatus='REJECTED' THEN 1 END),0),
            ISNULL(SUM(CASE WHEN DeanStatus='PENDING' THEN 1 END),0)

        FROM LeaveApplications
        WHERE StudentId = %s
    """, (student_id,))

    row = cursor.fetchone()
    conn.close()

    return {
        "student_id": student_id,
        "total": row[0],
        "approved": row[1],
        "rejected": row[2],
        "pending": row[3]
    }
#Monthly Report
@app.get("/reports/monthly")
def monthly_report():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT 
            FORMAT(CreatedAt, 'yyyy-MM') AS month,

            COUNT(*) AS total,

            ISNULL(SUM(CASE WHEN DeanStatus='APPROVED' THEN 1 END),0) AS approved,
            ISNULL(SUM(CASE WHEN DeanStatus='REJECTED' THEN 1 END),0) AS rejected,
            ISNULL(SUM(CASE WHEN DeanStatus='PENDING' THEN 1 END),0) AS pending

        FROM LeaveApplications

        GROUP BY FORMAT(CreatedAt, 'yyyy-MM')
        ORDER BY FORMAT(CreatedAt, 'yyyy-MM')
    """)

    rows = cursor.fetchall()
    conn.close()

    return [
        {
            "month": r[0],
            "total": r[1],
            "approved": r[2],
            "rejected": r[3],
            "pending": r[4]
        }
        for r in rows
    ]
#Semester-wise Report
@app.get("/reports/semester")
def semester_report():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT 
            sp.Semester,

            COUNT(l.LeaveId) AS total,

            ISNULL(SUM(CASE WHEN l.DeanStatus='APPROVED' THEN 1 END),0) AS approved,
            ISNULL(SUM(CASE WHEN l.DeanStatus='REJECTED' THEN 1 END),0) AS rejected,
            ISNULL(SUM(CASE WHEN l.DeanStatus='PENDING' THEN 1 END),0) AS pending

        FROM StudentProfile sp
        LEFT JOIN LeaveApplications l 
            ON l.StudentId = sp.StudentId

        GROUP BY sp.Semester
        ORDER BY sp.Semester ASC
    """)

    rows = cursor.fetchall()
    conn.close()

    return [
        {
            "semester": r[0],
            "total": r[1],
            "approved": r[2],
            "rejected": r[3],
            "pending": r[4]
        }
        for r in rows
    ]
#Emergency Leave Report
@app.get("/reports/emergency")
def emergency_report():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT 
            FORMAT(CreatedAt, 'yyyy-MM') AS month,

            COUNT(*) AS total,

            ISNULL(SUM(CASE WHEN DeanStatus='APPROVED' THEN 1 END),0) AS approved,
            ISNULL(SUM(CASE WHEN DeanStatus='REJECTED' THEN 1 END),0) AS rejected,
            ISNULL(SUM(CASE WHEN DeanStatus='PENDING' THEN 1 END),0) AS pending

        FROM LeaveApplications

        WHERE ProfessorStatus = 'SKIPPED'
        GROUP BY FORMAT(CreatedAt, 'yyyy-MM')
        ORDER BY FORMAT(CreatedAt, 'yyyy-MM')
    """)

    rows = cursor.fetchall()
    conn.close()

    return [
        {
            "month": r[0],
            "total_emergency": r[1],
            "approved": r[2],
            "rejected": r[3],
            "pending": r[4]
        }
        for r in rows
    ]
#Top Leave Students
@app.get("/reports/top-students")
def top_students():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT TOP 5 
            u.FullName,
            sp.Semester,
            COUNT(l.LeaveId) AS total

        FROM LeaveApplications l

        JOIN Users u 
            ON l.StudentId = u.UserId

        JOIN StudentProfile sp 
            ON sp.StudentId = u.UserId

        GROUP BY u.FullName, sp.Semester

        ORDER BY COUNT(l.LeaveId) DESC
    """)

    rows = cursor.fetchall()
    conn.close()

    return [
        {
            "name": r[0],
            "semester": r[1],
            "total": r[2]
        }
        for r in rows
    ]
#Professor Performance
@app.get("/reports/professor-performance")
def professor_performance():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT 
            u.FullName,
            COUNT(l.LeaveId) AS total,
            ISNULL(SUM(CASE WHEN l.ProfessorStatus='PENDING' THEN 1 END),0) AS pending
        FROM ProfessorProfile p
        JOIN Users u ON p.ProfessorId = u.UserId
        LEFT JOIN LeaveApplications l 
            ON l.ProfessorId = p.ProfessorId
        GROUP BY u.FullName
        ORDER BY total DESC
    """)

    rows = cursor.fetchall()
    conn.close()

    return [
        {
            "professor": r[0],
            "total_requests": r[1],
            "pending": r[2]
        }
        for r in rows
    ]
#Chart Data API (Important)
@app.get("/reports/chart")
def chart_data():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT 
            ISNULL(SUM(CASE WHEN FinalStatus='APPROVED' THEN 1 END),0),
            ISNULL(SUM(CASE WHEN FinalStatus='REJECTED' THEN 1 END),0)
        FROM LeaveApplications
    """)

    row = cursor.fetchone()
    conn.close()

    return {
        "approved": row[0],
        "rejected": row[1]
    }
#Suspicious Students
@app.get("/reports/suspicious")
def suspicious_students():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT StudentId, COUNT(*)
        FROM LeaveApplications
        WHERE MONTH(CreatedAt) = MONTH(GETDATE())
          AND YEAR(CreatedAt) = YEAR(GETDATE())
        GROUP BY StudentId
        HAVING COUNT(*) > 5
    """)

    rows = cursor.fetchall()
    conn.close()

    return [{"student_id": r[0], "leaves": r[1]} for r in rows]

#long pending leaves
@app.get("/reports/pending-critical")
def pending_critical():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT 
            StudentId,
            DATEDIFF(DAY, CreatedAt, GETDATE()) as delay
        FROM LeaveApplications
        WHERE DeanStatus='PENDING'
          AND DATEDIFF(DAY, CreatedAt, GETDATE()) > 3
    """)

    rows = cursor.fetchall()
    conn.close()

    return [{"student_id": r[0], "delay_days": r[1]} for r in rows]
#daily report
@app.get("/reports/daily")
def daily_report():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT 
            COUNT(*),
            ISNULL(SUM(CASE WHEN DeanStatus='APPROVED' THEN 1 END),0),
            ISNULL(SUM(CASE WHEN DeanStatus='REJECTED' THEN 1 END),0)
        FROM LeaveApplications
        WHERE CAST(CreatedAt AS DATE) = CAST(GETDATE() AS DATE)
    """)

    row = cursor.fetchone()
    conn.close()

    return {
        "today_total": row[0],
        "approved": row[1],
        "rejected": row[2]
    }
#DAILY semester-wise report
@app.get("/reports/daily-semester")
def daily_semester_report():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT 
            sp.Semester,

            COUNT(l.LeaveId) AS total,

            ISNULL(SUM(CASE WHEN l.DeanStatus='APPROVED' THEN 1 END),0) AS approved,
            ISNULL(SUM(CASE WHEN l.DeanStatus='REJECTED' THEN 1 END),0) AS rejected,
            ISNULL(SUM(CASE WHEN l.DeanStatus='PENDING' THEN 1 END),0) AS pending

        FROM StudentProfile sp

        LEFT JOIN LeaveApplications l 
            ON l.StudentId = sp.StudentId
            AND CAST(l.CreatedAt AS DATE) = CAST(GETDATE() AS DATE)

        GROUP BY sp.Semester
        ORDER BY sp.Semester ASC
    """)

    rows = cursor.fetchall()
    conn.close()

    return [
        {
            "semester": r[0],
            "today_total": r[1],
            "approved": r[2],
            "rejected": r[3],
            "pending": r[4]
        }
        for r in rows
    ]
#inside report
@app.get("/reports/insight")
def insight():
    conn = get_connection()
    cursor = conn.cursor()

    # 🔹 1. Highest Leave Semester (this month)
    cursor.execute("""
        SELECT TOP 1 
            sp.Semester,
            COUNT(*) as total
        FROM LeaveApplications l
        JOIN StudentProfile sp ON l.StudentId = sp.StudentId
        WHERE MONTH(l.CreatedAt) = MONTH(GETDATE())
          AND YEAR(l.CreatedAt) = YEAR(GETDATE())
        GROUP BY sp.Semester
        ORDER BY total DESC
    """)
    sem_row = cursor.fetchone()

    # 🔹 2. High Risk Student (this month)
    cursor.execute("""
        SELECT TOP 1 
            l.StudentId,
            COUNT(*) as total
        FROM LeaveApplications l
        WHERE MONTH(l.CreatedAt) = MONTH(GETDATE())
          AND YEAR(l.CreatedAt) = YEAR(GETDATE())
        GROUP BY l.StudentId
        ORDER BY total DESC
    """)
    stu_row = cursor.fetchone()

    conn.close()

    # 🔹 Safe handling
    semester_msg = "No data"
    student_msg = "No risk detected"

    if sem_row:
        semester_msg = f"Semester {sem_row[0]} has highest leaves ({sem_row[1]}) this month"

    if stu_row and stu_row[1] >= 5:
        student_msg = f"⚠️ Student ID {stu_row[0]} is high-risk with {stu_row[1]} leaves"

    return {
        "message": semester_msg,
        "warning": student_msg
    }
#========================================================
# RUN
# =====================================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=7860)
