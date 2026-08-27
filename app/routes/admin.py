from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, Response
from flask_login import login_required, current_user
from app.models import User, Student, Teacher, Class, Subject, Exam, Attendance, Fee, Announcement, Book, BookIssue, TimeTable, Department, Event, Homework, IDCard, Mark, Permission, RolePermission
from app import db
from app.school import get_school_details
from app.uploads import save_student_photo
from datetime import date, datetime, timedelta
import io
import csv

admin = Blueprint('admin', __name__, url_prefix='/admin')

FEE_STATUSES = ('Pending', 'Paid', 'Overdue')

PERMISSION_DEFINITIONS = [
    ('view_students', 'View Students'),
    ('edit_students', 'Add/Edit Students'),
    ('delete_students', 'Delete Students'),
    ('view_teachers', 'View Teachers'),
    ('edit_teachers', 'Add/Edit Teachers'),
    ('view_attendance', 'View Attendance'),
    ('mark_attendance', 'Mark Attendance'),
    ('view_marks', 'View Marks'),
    ('enter_marks', 'Enter Marks'),
    ('view_fees', 'View Fees'),
    ('manage_fees', 'Manage Fees'),
    ('view_library', 'View Library'),
    ('manage_library', 'Manage Library'),
    ('view_analytics', 'View Analytics'),
    ('manage_settings', 'Manage Settings'),
]

DEFAULT_ROLE_PERMISSIONS = {
    'admin': [permission[0] for permission in PERMISSION_DEFINITIONS],
    'teacher': ['view_students', 'view_attendance', 'mark_attendance', 'view_marks', 'enter_marks'],
    'student': ['view_attendance', 'view_marks', 'view_fees'],
}

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash('Access denied.', 'danger')
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated_function


def parse_date_value(value, label='Date', required=False):
    if not value:
        if required:
            return None, f'{label} is required.'
        return None, None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date(), None
    except ValueError:
        return None, f'{label} must be a valid date.'


def parse_float_value(value, label, required=False):
    if value in (None, ''):
        if required:
            return None, f'{label} is required.'
        return None, None
    try:
        return float(value), None
    except ValueError:
        return None, f'{label} must be a valid number.'


def return_issued_books_for_student(student_id):
    active_issues = BookIssue.query.filter_by(student_id=student_id, status='issued').all()
    for issue in active_issues:
        issue.status = 'returned'
        issue.return_date = datetime.now()
        if issue.book:
            issue.book.available_copies = min(issue.book.total_copies, issue.book.available_copies + 1)


def delete_student_related_records(student_id):
    """Remove records that reference a student before removing the student row.

    The application supports both SQLite and PostgreSQL, and existing databases
    may not have been created with cascading foreign keys.  Keep the cleanup
    explicit so deleting a student works consistently on every supported schema.
    """
    return_issued_books_for_student(student_id)
    for model in (BookIssue, IDCard, Attendance, Mark, Fee):
        model.query.filter_by(student_id=student_id).delete(synchronize_session=False)


def ensure_permission_records():
    permission_by_name = {permission.name: permission for permission in Permission.query.all()}
    created = False
    for code, description in PERMISSION_DEFINITIONS:
        if code not in permission_by_name:
            permission = Permission(name=code, description=description)
            db.session.add(permission)
            permission_by_name[code] = permission
            created = True
    db.session.flush()
    if created:
        db.session.commit()
    return permission_by_name


def get_role_permissions(permission_by_name):
    if RolePermission.query.count() == 0:
        for role, permissions in DEFAULT_ROLE_PERMISSIONS.items():
            for permission_name in permissions:
                db.session.add(RolePermission(role=role, permission_id=permission_by_name[permission_name].id))
        db.session.commit()

    roles = {'admin': [], 'teacher': [], 'student': []}
    role_permissions = RolePermission.query.join(Permission).all()
    for role_permission in role_permissions:
        if role_permission.role in roles:
            roles[role_permission.role].append(role_permission.permission.name)
    roles['admin'] = DEFAULT_ROLE_PERMISSIONS['admin']
    return roles

# ============================================
# DASHBOARD WITH CHARTS DATA
# ============================================
@admin.route('')
@admin.route('/')
@login_required
@admin_required
def index():
    return redirect(url_for('admin.dashboard'))

@admin.route('/dashboard')
@login_required
@admin_required
def dashboard():
    stats = {
        'students': Student.query.count(),
        'teachers': Teacher.query.count(),
        'classes': Class.query.count(),
        'subjects': Subject.query.count(),
        'exams': Exam.query.count(),
        'users': User.query.count()
    }
    recent_students = Student.query.order_by(Student.id.desc()).limit(5).all()
    announcements = Announcement.query.filter_by(is_active=True).order_by(Announcement.created_at.desc()).limit(5).all()
    
    # Chart data
    fee_stats = {
        'paid': Fee.query.filter_by(status='Paid').count(),
        'pending': Fee.query.filter_by(status='Pending').count(),
        'overdue': Fee.query.filter_by(status='Overdue').count()
    }
    
    # Attendance last 7 days
    from datetime import date, timedelta
    today = date.today()
    attendance_data = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        present = Attendance.query.filter_by(date=d, status='Present').count()
        absent = Attendance.query.filter_by(date=d, status='Absent').count()
        attendance_data.append({'date': d.strftime('%a'), 'present': present, 'absent': absent})
    
    return render_template('admin/dashboard.html', 
                           stats=stats, 
                           recent_students=recent_students,
                           announcements=announcements,
                           fee_stats=fee_stats,
                           attendance_data=attendance_data)

# ============================================
# STUDENTS CRUD
# ============================================
@admin.route('/students')
@login_required
@admin_required
def students():
    students = Student.query.all()
    departments = Department.query.all()
    return render_template('admin/students/list.html', students=students, departments=departments)

@admin.route('/students/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_student():
    classes = Class.query.all()
    departments = Department.query.all()
    if request.method == 'POST':
        user = User(
            username=request.form['username'],
            email=request.form['email'],
            role='student',
            is_approved=True
        )
        user.set_password(request.form['password'])
        db.session.add(user)
        db.session.flush()
        
        student = Student(
            user_id=user.id,
            first_name=request.form['first_name'],
            last_name=request.form['last_name'],
            roll_no=request.form['roll_no'],
            enrollment_no=request.form.get('enrollment_no'),
            class_id=request.form.get('class_id') or None,
            department_id=request.form.get('department_id') or None,
            gender=request.form.get('gender'),
            dob=datetime.strptime(request.form['dob'], '%Y-%m-%d').date() if request.form.get('dob') else None,
            blood_group=request.form.get('blood_group'),
            phone=request.form.get('phone'),
            address=request.form.get('address'),
            parent_name=request.form.get('parent_name'),
            parent_phone=request.form.get('parent_phone'),
            admission_date=datetime.strptime(request.form['admission_date'], '%Y-%m-%d').date() if request.form.get('admission_date') else None
        )
        db.session.add(student)
        db.session.commit()
        flash('Student added successfully!', 'success')
        return redirect(url_for('admin.students'))
    return render_template('admin/students/form.html', classes=classes, departments=departments, student=None)

@admin.route('/students/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_student(id):
    student = Student.query.get_or_404(id)
    classes = Class.query.all()
    departments = Department.query.all()
    if request.method == 'POST':
        student.first_name = request.form['first_name']
        student.last_name = request.form['last_name']
        student.roll_no = request.form['roll_no']
        student.enrollment_no = request.form.get('enrollment_no')
        student.class_id = request.form.get('class_id') or None
        student.department_id = request.form.get('department_id') or None
        student.gender = request.form.get('gender')
        student.dob = datetime.strptime(request.form['dob'], '%Y-%m-%d').date() if request.form.get('dob') else None
        student.blood_group = request.form.get('blood_group')
        student.phone = request.form.get('phone')
        student.address = request.form.get('address')
        student.parent_name = request.form.get('parent_name')
        student.parent_phone = request.form.get('parent_phone')
        student.admission_date = datetime.strptime(request.form['admission_date'], '%Y-%m-%d').date() if request.form.get('admission_date') else None
        
        # Handle photo upload
        if 'photo' in request.files:
            try:
                save_student_photo(student, request.files.get('photo'))
            except ValueError as error:
                flash(str(error), 'danger')
                return render_template('admin/students/form.html', classes=classes, departments=departments, student=student)
        
        db.session.commit()
        flash('Student updated successfully!', 'success')
        return redirect(url_for('admin.students'))
    return render_template('admin/students/form.html', classes=classes, departments=departments, student=student)

@admin.route('/students/delete/<int:id>', methods=['POST'])
@login_required
@admin_required
def delete_student(id):
    student = Student.query.get_or_404(id)
    user = db.session.get(User, student.user_id)
    delete_student_related_records(student.id)
    db.session.delete(student)
    # Ensure the dependent profile is gone before deleting its required user.
    # This also makes the ordering deterministic on databases enforcing FKs.
    db.session.flush()
    if user:
        db.session.delete(user)
    db.session.commit()
    flash('Student deleted successfully!', 'success')
    return redirect(url_for('admin.students'))

@admin.route('/students/export')
@login_required
@admin_required
def export_students():
    students = Student.query.all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Roll No', 'First Name', 'Last Name', 'Class', 'Gender', 'Parent Name', 'Parent Phone'])
    for s in students:
        writer.writerow([s.id, s.roll_no, s.first_name, s.last_name, 
                         f"{s.enrolled_class.grade}-{s.enrolled_class.section}" if s.enrolled_class else 'N/A',
                         s.gender or '', s.parent_name or '', s.parent_phone or ''])
    output.seek(0)
    return Response(output, mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=students.csv'})

# ============================================
# TEACHERS CRUD
# ============================================
@admin.route('/teachers')
@login_required
@admin_required
def teachers():
    teachers = Teacher.query.all()
    departments = Department.query.all()
    return render_template('admin/teachers/list.html', teachers=teachers, departments=departments)

@admin.route('/teachers/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_teacher():
    departments = Department.query.all()
    if request.method == 'POST':
        user = User(
            username=request.form['username'],
            email=request.form['email'],
            role='teacher',
            is_approved=True
        )
        user.set_password(request.form['password'])
        db.session.add(user)
        db.session.flush()
        
        teacher = Teacher(
            user_id=user.id,
            first_name=request.form['first_name'],
            last_name=request.form['last_name'],
            department_id=request.form.get('department_id') or None,
            qualification=request.form.get('qualification'),
            specialization=request.form.get('specialization'),
            phone=request.form.get('phone'),
            joining_date=datetime.strptime(request.form['joining_date'], '%Y-%m-%d').date() if request.form.get('joining_date') else None
        )
        db.session.add(teacher)
        db.session.commit()
        flash('Teacher added successfully!', 'success')
        return redirect(url_for('admin.teachers'))
    return render_template('admin/teachers/form.html', teacher=None, departments=departments)

@admin.route('/teachers/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_teacher(id):
    teacher = Teacher.query.get_or_404(id)
    departments = Department.query.all()
    if request.method == 'POST':
        teacher.first_name = request.form['first_name']
        teacher.last_name = request.form['last_name']
        teacher.department_id = request.form.get('department_id') or None
        teacher.qualification = request.form.get('qualification')
        teacher.specialization = request.form.get('specialization')
        teacher.phone = request.form.get('phone')
        teacher.joining_date = datetime.strptime(request.form['joining_date'], '%Y-%m-%d').date() if request.form.get('joining_date') else None
        db.session.commit()
        flash('Teacher updated successfully!', 'success')
        return redirect(url_for('admin.teachers'))
    return render_template('admin/teachers/form.html', teacher=teacher, departments=departments)

@admin.route('/teachers/delete/<int:id>', methods=['POST'])
@login_required
@admin_required
def delete_teacher(id):
    teacher = Teacher.query.get_or_404(id)
    if teacher.classes_managed or teacher.assigned_homework or teacher.class_incharge or teacher.headed_department:
        flash('Cannot delete a teacher who is assigned to classes, timetable entries, departments, or homework.', 'warning')
        return redirect(url_for('admin.teachers'))
    user = db.session.get(User, teacher.user_id)
    db.session.delete(teacher)
    if user:
        db.session.delete(user)
    db.session.commit()
    flash('Teacher deleted successfully!', 'success')
    return redirect(url_for('admin.teachers'))

# ============================================
# CLASSES CRUD
# ============================================
@admin.route('/classes')
@login_required
@admin_required
def classes():
    classes = Class.query.all()
    departments = Department.query.all()
    return render_template('admin/classes/list.html', classes=classes, departments=departments)

@admin.route('/classes/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_class():
    departments = Department.query.all()
    teachers = Teacher.query.all()
    if request.method == 'POST':
        cls = Class(
            grade=request.form['grade'],
            section=request.form['section'],
            department_id=request.form.get('department_id') or None,
            class_teacher_id=request.form.get('class_teacher_id') or None
        )
        db.session.add(cls)
        db.session.commit()
        flash('Class added successfully!', 'success')
        return redirect(url_for('admin.classes'))
    return render_template('admin/classes/form.html', cls=None, departments=departments, teachers=teachers)

@admin.route('/classes/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_class(id):
    cls = Class.query.get_or_404(id)
    departments = Department.query.all()
    teachers = Teacher.query.all()
    if request.method == 'POST':
        cls.grade = request.form['grade']
        cls.section = request.form['section']
        cls.department_id = request.form.get('department_id') or None
        cls.class_teacher_id = request.form.get('class_teacher_id') or None
        db.session.commit()
        flash('Class updated successfully!', 'success')
        return redirect(url_for('admin.classes'))
    return render_template('admin/classes/form.html', cls=cls, departments=departments, teachers=teachers)

@admin.route('/classes/delete/<int:id>', methods=['POST'])
@login_required
@admin_required
def delete_class(id):
    cls = Class.query.get_or_404(id)
    if cls.students or cls.time_table or cls.homework_list:
        flash('Cannot delete a class with students, timetable entries, or homework assigned.', 'warning')
        return redirect(url_for('admin.classes'))
    db.session.delete(cls)
    db.session.commit()
    flash('Class deleted successfully!', 'success')
    return redirect(url_for('admin.classes'))

# ============================================
# SUBJECTS CRUD
# ============================================
@admin.route('/subjects')
@login_required
@admin_required
def subjects():
    subjects = Subject.query.all()
    departments = Department.query.all()
    return render_template('admin/subjects/list.html', subjects=subjects, departments=departments)

@admin.route('/subjects/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_subject():
    departments = Department.query.all()
    if request.method == 'POST':
        subject = Subject(
            name=request.form['name'],
            code=request.form['code'],
            department_id=request.form.get('department_id') or None
        )
        db.session.add(subject)
        db.session.commit()
        flash('Subject added successfully!', 'success')
        return redirect(url_for('admin.subjects'))
    return render_template('admin/subjects/form.html', subject=None, departments=departments)

@admin.route('/subjects/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_subject(id):
    subject = Subject.query.get_or_404(id)
    departments = Department.query.all()
    if request.method == 'POST':
        subject.name = request.form['name']
        subject.code = request.form['code']
        subject.department_id = request.form.get('department_id') or None
        db.session.commit()
        flash('Subject updated successfully!', 'success')
        return redirect(url_for('admin.subjects'))
    return render_template('admin/subjects/form.html', subject=subject, departments=departments)

@admin.route('/subjects/delete/<int:id>', methods=['POST'])
@login_required
@admin_required
def delete_subject(id):
    subject = Subject.query.get_or_404(id)
    if subject.marks or subject.time_table or subject.homework_list:
        flash('Cannot delete a subject with marks, timetable entries, or homework assigned.', 'warning')
        return redirect(url_for('admin.subjects'))
    db.session.delete(subject)
    db.session.commit()
    flash('Subject deleted successfully!', 'success')
    return redirect(url_for('admin.subjects'))

# ============================================
# EXAMS
# ============================================
@admin.route('/exams')
@login_required
@admin_required
def exams():
    exams = Exam.query.all()
    return render_template('admin/exams/list.html', exams=exams)

@admin.route('/exams/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_exam():
    if request.method == 'POST':
        exam_date, error = parse_date_value(request.form.get('date'), 'Exam date')
        if error:
            flash(error, 'danger')
            return render_template('admin/exams/form.html', exam=None)
        exam = Exam(
            name=request.form['name'],
            date=exam_date
        )
        db.session.add(exam)
        db.session.commit()
        flash('Exam added successfully!', 'success')
        return redirect(url_for('admin.exams'))
    return render_template('admin/exams/form.html', exam=None)


@admin.route('/exams/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_exam(id):
    exam = Exam.query.get_or_404(id)
    if request.method == 'POST':
        exam_date, error = parse_date_value(request.form.get('date'), 'Exam date')
        if error:
            flash(error, 'danger')
            return render_template('admin/exams/form.html', exam=exam)
        exam.name = request.form['name']
        exam.date = exam_date
        db.session.commit()
        flash('Exam updated successfully!', 'success')
        return redirect(url_for('admin.exams'))
    return render_template('admin/exams/form.html', exam=exam)


@admin.route('/exams/delete/<int:id>', methods=['POST'])
@login_required
@admin_required
def delete_exam(id):
    exam = Exam.query.get_or_404(id)
    if exam.marks:
        flash('Cannot delete an exam with marks recorded.', 'warning')
        return redirect(url_for('admin.exams'))
    db.session.delete(exam)
    db.session.commit()
    flash('Exam deleted successfully!', 'success')
    return redirect(url_for('admin.exams'))

# ============================================
# ATTENDANCE MARKING SYSTEM
# ============================================
@admin.route('/attendance')
@login_required
@admin_required
def attendance_report():
    classes = Class.query.all()
    departments = Department.query.all()
    selected_class = request.args.get('class_id')
    selected_date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    date_obj, error = parse_date_value(selected_date, 'Attendance date') if selected_date else (None, None)
    if error:
        flash(error, 'danger')
        return redirect(url_for('admin.attendance_report'))
    
    query = Attendance.query
    if selected_class:
        query = query.join(Student).filter(Student.class_id == selected_class)
    if date_obj:
        query = query.filter(Attendance.date == date_obj)
    
    attendance = query.order_by(Attendance.date.desc()).limit(100).all()
    return render_template('admin/attendance/report.html', 
                           attendance=attendance, 
                           classes=classes, 
                           departments=departments,
                           selected_class=selected_class,
                           selected_date=selected_date)

@admin.route('/attendance/mark', methods=['GET', 'POST'])
@login_required
@admin_required
def mark_attendance():
    classes = Class.query.all()
    selected_class = request.args.get('class_id')
    selected_date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    students = []
    existing_attendance = {}
    
    if selected_class:
        students = Student.query.filter_by(class_id=selected_class).order_by(Student.roll_no).all()
        date_obj, error = parse_date_value(selected_date, 'Attendance date', required=True)
        if error:
            flash(error, 'danger')
            return redirect(url_for('admin.mark_attendance'))
        for s in students:
            att = Attendance.query.filter_by(student_id=s.id, date=date_obj).first()
            if att:
                existing_attendance[s.id] = att.status
    
    if request.method == 'POST':
        date_obj, error = parse_date_value(request.form.get('date'), 'Attendance date', required=True)
        if error:
            flash(error, 'danger')
            return redirect(url_for('admin.mark_attendance'))
        class_id = request.form['class_id']
        students = Student.query.filter_by(class_id=class_id).all()
        
        for student in students:
            status = request.form.get(f'status_{student.id}', 'Absent')
            existing = Attendance.query.filter_by(student_id=student.id, date=date_obj).first()
            if existing:
                existing.status = status
            else:
                att = Attendance(student_id=student.id, date=date_obj, status=status)
                db.session.add(att)
        
        db.session.commit()
        flash(f'Attendance marked for {len(students)} students!', 'success')
        return redirect(url_for('admin.attendance_report', class_id=class_id, date=request.form['date']))
    
    return render_template('admin/attendance/mark.html', 
                           classes=classes, 
                           students=students,
                           selected_class=selected_class,
                           selected_date=selected_date,
                           existing_attendance=existing_attendance)

@admin.route('/attendance/export')
@login_required
@admin_required
def export_attendance():
    class_id = request.args.get('class_id')
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    
    query = Attendance.query.join(Student)
    if class_id:
        query = query.filter(Student.class_id == class_id)
    if date_from:
        date_from_obj, error = parse_date_value(date_from, 'Start date')
        if error:
            flash(error, 'danger')
            return redirect(url_for('admin.attendance_report'))
        query = query.filter(Attendance.date >= date_from_obj)
    if date_to:
        date_to_obj, error = parse_date_value(date_to, 'End date')
        if error:
            flash(error, 'danger')
            return redirect(url_for('admin.attendance_report'))
        query = query.filter(Attendance.date <= date_to_obj)
    
    attendance = query.order_by(Attendance.date.desc()).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date', 'Roll No', 'Student Name', 'Class', 'Department', 'Status'])
    for a in attendance:
        writer.writerow([
            a.date.strftime('%Y-%m-%d'),
            a.student.roll_no,
            f"{a.student.first_name} {a.student.last_name}",
            f"{a.student.enrolled_class.grade}-{a.student.enrolled_class.section}" if a.student.enrolled_class else 'N/A',
            a.student.department.name if a.student.department else 'N/A',
            a.status
        ])
    output.seek(0)
    return Response(output, mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=attendance.csv'})

# ============================================
# FEES MANAGEMENT
# ============================================
@admin.route('/fees')
@login_required
@admin_required
def fees_management():
    status_filter = request.args.get('status')
    query = Fee.query
    if status_filter in FEE_STATUSES:
        query = query.filter_by(status=status_filter)
    else:
        status_filter = None
    fees = query.order_by(Fee.due_date.desc()).all()
    return render_template('admin/fees/list.html', fees=fees, status_filter=status_filter, statuses=FEE_STATUSES)


def render_fee_form(fee=None):
    students = Student.query.order_by(Student.roll_no, Student.first_name).all()
    return render_template('admin/fees/form.html', fee=fee, students=students, statuses=FEE_STATUSES)


def apply_fee_form(fee):
    student_id = request.form.get('student_id', type=int)
    student = db.session.get(Student, student_id) if student_id else None
    if not student:
        return 'Please select a valid student.'

    amount, error = parse_float_value(request.form.get('amount'), 'Amount', required=True)
    if error:
        return error
    if amount < 0:
        return 'Amount cannot be negative.'

    due_date, error = parse_date_value(request.form.get('due_date'), 'Due date')
    if error:
        return error

    paid_date, error = parse_date_value(request.form.get('paid_date'), 'Paid date')
    if error:
        return error

    status = request.form.get('status') or 'Pending'
    if status not in FEE_STATUSES:
        return 'Invalid fee status.'

    title = (request.form.get('title') or '').strip()
    if not title:
        return 'Title is required.'

    fee.student_id = student.id
    fee.title = title
    fee.amount = amount
    fee.due_date = due_date
    fee.status = status
    fee.paid_date = paid_date or (date.today() if status == 'Paid' else None)
    if status != 'Paid':
        fee.paid_date = None
    return None


@admin.route('/fees/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_fee():
    if request.method == 'POST':
        fee = Fee()
        error = apply_fee_form(fee)
        if error:
            flash(error, 'danger')
            return render_fee_form(fee)
        db.session.add(fee)
        db.session.commit()
        flash('Fee record added successfully!', 'success')
        return redirect(url_for('admin.fees_management'))
    return render_fee_form()


@admin.route('/fees/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_fee(id):
    fee = Fee.query.get_or_404(id)
    if request.method == 'POST':
        error = apply_fee_form(fee)
        if error:
            flash(error, 'danger')
            return render_fee_form(fee)
        db.session.commit()
        flash('Fee record updated successfully!', 'success')
        return redirect(url_for('admin.fees_management'))
    return render_fee_form(fee)


@admin.route('/fees/delete/<int:id>', methods=['POST'])
@login_required
@admin_required
def delete_fee(id):
    fee = Fee.query.get_or_404(id)
    db.session.delete(fee)
    db.session.commit()
    flash('Fee record deleted successfully!', 'success')
    return redirect(url_for('admin.fees_management'))

@admin.route('/fees/export')
@login_required
@admin_required
def export_fees():
    status = request.args.get('status')
    query = Fee.query
    if status in FEE_STATUSES:
        query = query.filter_by(status=status)
    fees = query.order_by(Fee.due_date.desc()).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Student', 'Roll No', 'Amount', 'Due Date', 'Status', 'Paid Date'])
    for f in fees:
        writer.writerow([
            f.id,
            f"{f.student.first_name} {f.student.last_name}",
            f.student.roll_no,
            f.amount,
            f.due_date.strftime('%Y-%m-%d') if f.due_date else 'N/A',
            f.status,
            f.paid_date.strftime('%Y-%m-%d') if f.paid_date else 'N/A'
        ])
    output.seek(0)
    return Response(output, mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=fees.csv'})

# ============================================
# USERS
# ============================================
@admin.route('/users')
@login_required
@admin_required
def users():
    users = User.query.all()
    return render_template('admin/users/list.html', users=users)

@admin.route('/users/approvals')
@login_required
@admin_required
def approvals():
    pending_users = User.query.filter_by(is_approved=False).all()
    return render_template('admin/users/approvals.html', pending_users=pending_users)

@admin.route('/users/approve/<int:id>', methods=['POST'])
@login_required
@admin_required
def approve_user(id):
    user = User.query.get_or_404(id)
    user.is_approved = True
    db.session.commit()

    flash(f'User {user.username} approved successfully!', 'success')
    return redirect(url_for('admin.approvals'))

@admin.route('/users/reject/<int:id>', methods=['POST'])
@login_required
@admin_required
def reject_user(id):
    user = User.query.get_or_404(id)
    
    # Cleanup profile data
    if user.role == 'student':
        student = Student.query.filter_by(user_id=user.id).first()
        if student:
            delete_student_related_records(student.id)
            db.session.delete(student)
            db.session.flush()
    elif user.role == 'teacher':
        teacher = Teacher.query.filter_by(user_id=user.id).first()
        if teacher: db.session.delete(teacher)
        
    db.session.delete(user)
    db.session.commit()
    flash(f'User {user.username} rejected and removed.', 'warning')
    return redirect(url_for('admin.approvals'))



# ============================================
# ANNOUNCEMENTS
# ============================================
@admin.route('/announcements')
@login_required
@admin_required
def announcements():
    announcements = Announcement.query.order_by(Announcement.created_at.desc()).all()
    return render_template('admin/announcements/list.html', announcements=announcements)

@admin.route('/announcements/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_announcement():
    if request.method == 'POST':
        announcement = Announcement(
            title=request.form['title'],
            content=request.form['content'],
            priority=request.form.get('priority', 'normal'),
            target_role=request.form.get('target_role', 'all'),
            created_by=current_user.id
        )
        db.session.add(announcement)
        db.session.commit()
        flash('Announcement created!', 'success')
        return redirect(url_for('admin.announcements'))
    return render_template('admin/announcements/form.html', announcement=None)

@admin.route('/announcements/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_announcement(id):
    announcement = Announcement.query.get_or_404(id)
    if request.method == 'POST':
        announcement.title = request.form['title']
        announcement.content = request.form['content']
        announcement.priority = request.form.get('priority', 'normal')
        announcement.target_role = request.form.get('target_role', 'all')
        announcement.is_active = 'is_active' in request.form
        db.session.commit()
        flash('Announcement updated!', 'success')
        return redirect(url_for('admin.announcements'))
    return render_template('admin/announcements/form.html', announcement=announcement)

@admin.route('/announcements/delete/<int:id>', methods=['POST'])
@login_required
@admin_required
def delete_announcement(id):
    announcement = Announcement.query.get_or_404(id)
    db.session.delete(announcement)
    db.session.commit()
    flash('Announcement deleted!', 'success')
    return redirect(url_for('admin.announcements'))

# ============================================
# LIBRARY MANAGEMENT
# ============================================
@admin.route('/library')
@login_required
@admin_required
def library():
    books = Book.query.all()
    return render_template('admin/library/list.html', books=books)

@admin.route('/library/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_book():
    if request.method == 'POST':
        book = Book(
            title=request.form['title'],
            author=request.form.get('author'),
            isbn=request.form.get('isbn'),
            category=request.form.get('category'),
            total_copies=int(request.form.get('total_copies', 1)),
            available_copies=int(request.form.get('total_copies', 1))
        )
        db.session.add(book)
        db.session.commit()
        flash('Book added!', 'success')
        return redirect(url_for('admin.library'))
    return render_template('admin/library/form.html', book=None)

@admin.route('/library/issue', methods=['GET', 'POST'])
@login_required
@admin_required
def issue_book():
    books = Book.query.filter(Book.available_copies > 0).all()
    students = Student.query.all()
    if request.method == 'POST':
        book_id = request.form.get('book_id', type=int)
        book = db.session.get(Book, book_id) if book_id else None
        if book and book.available_copies > 0:
            issue = BookIssue(
                book_id=book.id,
                student_id=request.form['student_id'],
                due_date=datetime.now() + timedelta(days=14)
            )
            book.available_copies -= 1
            db.session.add(issue)
            db.session.commit()
            flash('Book issued!', 'success')
        return redirect(url_for('admin.library'))
    return render_template('admin/library/issue.html', books=books, students=students)

@admin.route('/library/return/<int:id>', methods=['POST'])
@login_required
@admin_required
def return_book(id):
    issue = BookIssue.query.get_or_404(id)
    if issue.status == 'returned':
        flash('Book issue is already marked as returned.', 'info')
        return redirect(url_for('admin.library_issues'))
    issue.status = 'returned'
    issue.return_date = datetime.now()
    issue.book.available_copies = min(issue.book.total_copies, issue.book.available_copies + 1)
    db.session.commit()
    flash('Book returned!', 'success')
    return redirect(url_for('admin.library_issues'))

@admin.route('/library/delete/<int:id>', methods=['POST'])
@login_required
@admin_required
def delete_book(id):
    book = Book.query.get_or_404(id)
    if book.issues:
        flash('Books with issue history cannot be deleted.', 'warning')
        return redirect(url_for('admin.library'))
    db.session.delete(book)
    db.session.commit()
    flash('Book deleted!', 'success')
    return redirect(url_for('admin.library'))

@admin.route('/library/issues')
@login_required
@admin_required
def library_issues():
    issues = BookIssue.query.filter_by(status='issued').all()
    return render_template('admin/library/issues.html', issues=issues)

# ============================================
# TIMETABLE
# ============================================
@admin.route('/timetable')
@login_required
@admin_required
def timetable():
    classes = Class.query.all()
    return render_template('admin/timetable/list.html', classes=classes)

@admin.route('/timetable/view/<int:class_id>')
@login_required
@admin_required
def view_timetable(class_id):
    cls = Class.query.get_or_404(class_id)
    timetable = TimeTable.query.filter_by(class_id=class_id).all()
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
    return render_template('admin/timetable/view.html', cls=cls, timetable=timetable, days=days)

@admin.route('/timetable/add/<int:class_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def add_timetable_entry(class_id):
    cls = Class.query.get_or_404(class_id)
    subjects = Subject.query.all()
    teachers = Teacher.query.all()
    if request.method == 'POST':
        entry = TimeTable(
            class_id=class_id,
            subject_id=request.form['subject_id'],
            teacher_id=request.form['teacher_id'],
            day_of_week=request.form['day'],
            start_time=datetime.strptime(request.form['start_time'], '%H:%M').time(),
            end_time=datetime.strptime(request.form['end_time'], '%H:%M').time()
        )
        db.session.add(entry)
        db.session.commit()
        flash('Timetable entry added!', 'success')
        return redirect(url_for('admin.view_timetable', class_id=class_id))
    return render_template('admin/timetable/form.html', cls=cls, subjects=subjects, teachers=teachers)

# ============================================
# REPORT CARD
# ============================================
@admin.route('/reportcard/<int:student_id>')
@login_required
@admin_required
def report_card(student_id):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.lib import colors
    
    student = Student.query.get_or_404(student_id)
    marks = student.marks
    school = get_school_details()
    
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    
    # Header
    p.setFont("Helvetica-Bold", 20)
    p.drawCentredString(width/2, height - 50, "REPORT CARD")
    p.setFont("Helvetica", 12)
    p.drawCentredString(width/2, height - 70, school['name'])
    if school['address']:
        p.drawCentredString(width/2, height - 88, school['address'])
    
    # Student Info
    p.setFont("Helvetica-Bold", 12)
    p.drawString(50, height - 120, f"Name: {student.first_name} {student.last_name}")
    p.drawString(50, height - 140, f"Roll No: {student.roll_no}")
    class_name = f"{student.enrolled_class.grade}-{student.enrolled_class.section}" if student.enrolled_class else "N/A"
    p.drawString(50, height - 160, f"Class: {class_name}")
    
    # Marks Table
    y = height - 215
    p.setFont("Helvetica-Bold", 10)
    p.drawString(50, y, "Subject")
    p.drawString(200, y, "Exam")
    p.drawString(350, y, "Score")
    p.drawString(450, y, "Grade")
    
    y -= 20
    p.setFont("Helvetica", 10)
    total = 0
    count = 0
    for m in marks:
        percentage = (m.score_obtained / m.max_score) * 100 if m.max_score else 0
        grade = 'A+' if percentage >= 90 else 'A' if percentage >= 80 else 'B' if percentage >= 70 else 'C' if percentage >= 60 else 'D' if percentage >= 50 else 'F'
        p.drawString(50, y, m.subject.name)
        p.drawString(200, y, m.exam.name)
        p.drawString(350, y, f"{m.score_obtained}/{m.max_score}")
        p.drawString(450, y, grade)
        total += percentage
        count += 1
        y -= 15
    
    if count > 0:
        avg = total / count
        y -= 20
        p.setFont("Helvetica-Bold", 12)
        p.drawString(50, y, f"Overall Percentage: {avg:.2f}%")
    
    p.save()
    buffer.seek(0)
    return Response(buffer, mimetype='application/pdf', 
                   headers={'Content-Disposition': f'attachment; filename=report_card_{student.roll_no}.pdf'})

# ============================================
# CALENDAR / EVENTS
# ============================================
@admin.route('/calendar')
@login_required
@admin_required
def calendar():
    return render_template('admin/calendar/view.html')

@admin.route('/calendar/events')
@login_required
@admin_required
def calendar_events():
    events = Event.query.all()
    event_list = []
    for e in events:
        event_list.append({
            'id': e.id,
            'title': e.title,
            'start': e.start_date.isoformat(),
            'end': e.end_date.isoformat() if e.end_date else e.start_date.isoformat(),
            'color': e.color or '#E10600',
            'allDay': e.all_day
        })
    return jsonify(event_list)

@admin.route('/calendar/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_event():
    if request.method == 'POST':
        event = Event(
            title=request.form['title'],
            description=request.form.get('description'),
            event_type=request.form.get('event_type'),
            start_date=datetime.strptime(request.form['start_date'], '%Y-%m-%dT%H:%M') if 'T' in request.form.get('start_date', '') else datetime.strptime(request.form['start_date'], '%Y-%m-%d'),
            end_date=datetime.strptime(request.form['end_date'], '%Y-%m-%dT%H:%M') if request.form.get('end_date') and 'T' in request.form.get('end_date', '') else (datetime.strptime(request.form['end_date'], '%Y-%m-%d') if request.form.get('end_date') else None),
            color=request.form.get('color', '#E10600'),
            all_day='all_day' in request.form,
            target_role=request.form.get('target_role', 'all'),
            created_by=current_user.id
        )
        db.session.add(event)
        db.session.commit()
        flash('Event added!', 'success')
        return redirect(url_for('admin.calendar'))
    return render_template('admin/calendar/form.html', event=None)

@admin.route('/calendar/delete/<int:id>', methods=['POST'])
@login_required
@admin_required
def delete_event(id):
    event = Event.query.get_or_404(id)
    db.session.delete(event)
    db.session.commit()
    flash('Event deleted!', 'success')
    return redirect(url_for('admin.calendar'))

# ============================================
# DEPARTMENTS
# ============================================
@admin.route('/departments')
@login_required
@admin_required
def departments():
    departments = Department.query.all()
    return render_template('admin/departments/list.html', departments=departments)

@admin.route('/departments/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_department():
    teachers = Teacher.query.all()
    if request.method == 'POST':
        dept = Department(
            name=request.form['name'],
            code=request.form.get('code'),
            description=request.form.get('description'),
            head_teacher_id=request.form.get('head_teacher_id') or None
        )
        db.session.add(dept)
        db.session.commit()
        flash('Department added!', 'success')
        return redirect(url_for('admin.departments'))
    return render_template('admin/departments/form.html', department=None, teachers=teachers)

@admin.route('/departments/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_department(id):
    dept = Department.query.get_or_404(id)
    teachers = Teacher.query.all()
    if request.method == 'POST':
        dept.name = request.form['name']
        dept.code = request.form.get('code')
        dept.description = request.form.get('description')
        dept.head_teacher_id = request.form.get('head_teacher_id') or None
        db.session.commit()
        flash('Department updated!', 'success')
        return redirect(url_for('admin.departments'))
    return render_template('admin/departments/form.html', department=dept, teachers=teachers)

@admin.route('/departments/delete/<int:id>', methods=['POST'])
@login_required
@admin_required
def delete_department(id):
    dept = Department.query.get_or_404(id)
    if dept.students or dept.teachers or dept.classes or dept.subjects or dept.head_teacher:
        flash('Cannot delete a department while students, teachers, classes, subjects, or a head teacher are assigned.', 'warning')
        return redirect(url_for('admin.departments'))
    db.session.delete(dept)
    db.session.commit()
    flash('Department deleted!', 'success')
    return redirect(url_for('admin.departments'))

# ============================================
# HOMEWORK
# ============================================
@admin.route('/homework')
@login_required
@admin_required
def homework():
    homework = Homework.query.order_by(Homework.due_date.desc()).all()
    return render_template('admin/homework/list.html', homework=homework, today=date.today())

@admin.route('/homework/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_homework():
    classes = Class.query.all()
    subjects = Subject.query.all()
    teachers = Teacher.query.all()
    if request.method == 'POST':
        due_date, error = parse_date_value(request.form.get('due_date'), 'Due date', required=True)
        if error:
            flash(error, 'danger')
            return render_template('admin/homework/form.html', homework=None, classes=classes, subjects=subjects, teachers=teachers)
        hw = Homework(
            class_id=request.form['class_id'],
            subject_id=request.form['subject_id'],
            teacher_id=request.form['teacher_id'],
            title=request.form['title'],
            description=request.form.get('description'),
            due_date=due_date
        )
        db.session.add(hw)
        db.session.commit()
        flash('Homework assigned!', 'success')
        return redirect(url_for('admin.homework'))
    return render_template('admin/homework/form.html', homework=None, classes=classes, subjects=subjects, teachers=teachers)

@admin.route('/homework/delete/<int:id>', methods=['POST'])
@login_required
@admin_required
def delete_homework(id):
    hw = Homework.query.get_or_404(id)
    db.session.delete(hw)
    db.session.commit()
    flash('Homework deleted!', 'success')
    return redirect(url_for('admin.homework'))

# ============================================
# EXPORT ROUTES
# ============================================
@admin.route('/teachers/export')
@login_required
@admin_required
def export_teachers():
    dept_id = request.args.get('department_id')
    query = Teacher.query
    if dept_id:
        query = query.filter_by(department_id=dept_id)
    teachers = query.all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Name', 'Department', 'Qualification', 'Specialization', 'Phone', 'Joining Date'])
    for t in teachers:
        writer.writerow([
            t.id,
            f"{t.first_name} {t.last_name}",
            t.department.name if t.department else 'N/A',
            t.qualification or '',
            t.specialization or '',
            t.phone or '',
            t.joining_date.strftime('%Y-%m-%d') if t.joining_date else 'N/A'
        ])
    output.seek(0)
    return Response(output, mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=teachers.csv'})

@admin.route('/library/export')
@login_required
@admin_required
def export_library():
    books = Book.query.all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Title', 'Author', 'ISBN', 'Category', 'Total Copies', 'Available'])
    for b in books:
        writer.writerow([b.id, b.title, b.author or '', b.isbn or '', b.category or '', b.total_copies, b.available_copies])
    output.seek(0)
    return Response(output, mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=library_books.csv'})

@admin.route('/homework/export')
@login_required
@admin_required
def export_homework():
    class_id = request.args.get('class_id')
    query = Homework.query
    if class_id:
        query = query.filter_by(class_id=class_id)
    homework = query.order_by(Homework.due_date.desc()).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Title', 'Class', 'Subject', 'Teacher', 'Due Date', 'Assigned Date'])
    for h in homework:
        writer.writerow([
            h.title,
            f"{h.class_info.grade}-{h.class_info.section}" if h.class_info else 'N/A',
            h.subject.name if h.subject else 'N/A',
            f"{h.teacher.first_name} {h.teacher.last_name}" if h.teacher else 'N/A',
            h.due_date.strftime('%Y-%m-%d'),
            h.assigned_date.strftime('%Y-%m-%d') if h.assigned_date else 'N/A'
        ])
    output.seek(0)
    return Response(output, mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=homework.csv'})

@admin.route('/classes/export')
@login_required
@admin_required
def export_classes():
    classes = Class.query.all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Grade/Year', 'Section', 'Department', 'Class Teacher', 'Students Count'])
    for c in classes:
        writer.writerow([
            c.grade,
            c.section,
            c.department.name if c.department else 'N/A',
            f"{c.class_teacher.first_name} {c.class_teacher.last_name}" if c.class_teacher else 'N/A',
            len(c.students)
        ])
    output.seek(0)
    return Response(output, mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=classes.csv'})

@admin.route('/subjects/export')
@login_required
@admin_required
def export_subjects():
    subjects = Subject.query.all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Code', 'Name', 'Department'])
    for s in subjects:
        writer.writerow([s.code, s.name, s.department.name if s.department else 'General'])
    output.seek(0)
    return Response(output, mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=subjects.csv'})

# ============================================
# ANALYTICS DASHBOARDS
# ============================================
@admin.route('/analytics')
@login_required
@admin_required
def analytics():
    return redirect(url_for('admin.attendance_analytics'))

@admin.route('/analytics/attendance')
@login_required
@admin_required
def attendance_analytics():
    from datetime import date, timedelta
    from sqlalchemy import func
    
    today = date.today()
    
    # Last 30 days trend
    daily_data = []
    for i in range(29, -1, -1):
        d = today - timedelta(days=i)
        present = Attendance.query.filter_by(date=d, status='Present').count()
        absent = Attendance.query.filter_by(date=d, status='Absent').count()
        late = Attendance.query.filter_by(date=d, status='Late').count()
        total = present + absent + late
        daily_data.append({
            'date': d.strftime('%m/%d'),
            'present': present,
            'absent': absent,
            'late': late,
            'percentage': round((present / total * 100), 1) if total > 0 else 0
        })
    
    # Class-wise attendance today
    classes = Class.query.all()
    class_data = []
    for c in classes:
        student_ids = [s.id for s in c.students]
        if student_ids:
            present = Attendance.query.filter(Attendance.student_id.in_(student_ids), Attendance.date == today, Attendance.status == 'Present').count()
            total = len(student_ids)
            class_data.append({
                'name': f"{c.grade}-{c.section}",
                'present': present,
                'total': total,
                'percentage': round((present / total * 100), 1) if total > 0 else 0
            })
    
    # Overall stats
    total_students = Student.query.count()
    total_present_today = Attendance.query.filter_by(date=today, status='Present').count()
    
    return render_template('admin/analytics/attendance.html',
                           daily_data=daily_data,
                           class_data=class_data,
                           total_students=total_students,
                           total_present_today=total_present_today)

@admin.route('/analytics/performance')
@login_required
@admin_required
def performance_analytics():
    from app.models import Mark
    from sqlalchemy import func
    
    # Subject-wise averages
    subjects = Subject.query.all()
    subject_data = []
    for s in subjects:
        marks = Mark.query.filter_by(subject_id=s.id).all()
        if marks:
            avg = sum([(m.score_obtained / m.max_score * 100) if m.max_score else 0 for m in marks]) / len(marks)
            subject_data.append({'name': s.name, 'average': round(avg, 1)})
    
    # Top 10 students by average
    students = Student.query.all()
    student_scores = []
    for st in students:
        marks = st.marks
        if marks:
            avg = sum([(m.score_obtained / m.max_score * 100) if m.max_score else 0 for m in marks]) / len(marks)
            student_scores.append({
                'name': f"{st.first_name} {st.last_name}",
                'roll_no': st.roll_no,
                'class': f"{st.enrolled_class.grade}-{st.enrolled_class.section}" if st.enrolled_class else 'N/A',
                'average': round(avg, 1)
            })
    top_students = sorted(student_scores, key=lambda x: x['average'], reverse=True)[:10]
    
    # Grade distribution
    grade_dist = {'A+': 0, 'A': 0, 'B': 0, 'C': 0, 'D': 0, 'F': 0}
    from app.models import Mark
    all_marks = Mark.query.all()
    for m in all_marks:
        pct = (m.score_obtained / m.max_score) * 100 if m.max_score else 0
        if pct >= 90: grade_dist['A+'] += 1
        elif pct >= 80: grade_dist['A'] += 1
        elif pct >= 70: grade_dist['B'] += 1
        elif pct >= 60: grade_dist['C'] += 1
        elif pct >= 50: grade_dist['D'] += 1
        else: grade_dist['F'] += 1
    
    return render_template('admin/analytics/performance.html',
                           subject_data=subject_data,
                           top_students=top_students,
                           grade_dist=grade_dist)

@admin.route('/analytics/departments')
@login_required
@admin_required
def department_analytics():
    from datetime import date, timedelta
    
    departments = Department.query.all()
    dept_data = []
    
    for d in departments:
        students = Student.query.filter_by(department_id=d.id).all()
        teachers = Teacher.query.filter_by(department_id=d.id).all()
        classes = Class.query.filter_by(department_id=d.id).all()
        subjects = Subject.query.filter_by(department_id=d.id).all()
        
        # Attendance rate (last 7 days)
        student_ids = [s.id for s in students]
        if student_ids:
            today = date.today()
            week_ago = today - timedelta(days=7)
            present = Attendance.query.filter(
                Attendance.student_id.in_(student_ids),
                Attendance.date >= week_ago,
                Attendance.status == 'Present'
            ).count()
            total_records = Attendance.query.filter(
                Attendance.student_id.in_(student_ids),
                Attendance.date >= week_ago
            ).count()
            att_rate = round((present / total_records * 100), 1) if total_records > 0 else 0
        else:
            att_rate = 0
        
        # Fee collection
        fees = Fee.query.join(Student).filter(Student.department_id == d.id).all()
        paid = sum([1 for f in fees if f.status == 'Paid'])
        fee_rate = round((paid / len(fees) * 100), 1) if fees else 0
        
        dept_data.append({
            'name': d.name,
            'code': d.code,
            'students': len(students),
            'teachers': len(teachers),
            'classes': len(classes),
            'subjects': len(subjects),
            'attendance_rate': att_rate,
            'fee_collection': fee_rate,
            'head': f"{d.head_teacher.first_name} {d.head_teacher.last_name}" if d.head_teacher else 'Not Assigned'
        })
    
    return render_template('admin/analytics/departments.html', dept_data=dept_data)

# ============================================
# PERMISSIONS MANAGEMENT
# ============================================
@admin.route('/permissions', methods=['GET', 'POST'])
@login_required
@admin_required
def permissions():
    permission_by_name = ensure_permission_records()
    
    if request.method == 'POST':
        for role in ('teacher', 'student'):
            RolePermission.query.filter_by(role=role).delete()
            for permission_name in permission_by_name:
                if request.form.get(f'{role}_{permission_name}') == 'on':
                    db.session.add(RolePermission(role=role, permission_id=permission_by_name[permission_name].id))
        RolePermission.query.filter_by(role='admin').delete()
        for permission_name in DEFAULT_ROLE_PERMISSIONS['admin']:
            db.session.add(RolePermission(role='admin', permission_id=permission_by_name[permission_name].id))
        db.session.commit()
        flash('Permissions updated successfully!', 'success')
        return redirect(url_for('admin.permissions'))

    roles = get_role_permissions(permission_by_name)
    return render_template('admin/permissions.html', all_permissions=PERMISSION_DEFINITIONS, roles=roles)

# ============================================
# NOTICE BOARD / ANNOUNCEMENTS API
# ============================================
@admin.route('/notices/widget')
@login_required
def notices_widget():
    notices = Announcement.query.filter_by(is_active=True).order_by(Announcement.created_at.desc()).limit(5).all()
    return render_template('admin/partials/notice_widget.html', notices=notices)
