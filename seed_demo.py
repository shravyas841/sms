#!/usr/bin/env python3
"""
Demo seed script - Creates demo users for all dashboards (Admin, Teacher, Student)
Run: DATABASE_URL=sqlite:///site.db python seed_demo.py
"""
from app import create_app, db
from app.models import User, Student, Teacher, Department, Class, Subject, Attendance
from app.demo import DEMO_ACCOUNTS
from datetime import date, timedelta
import random

def seed_database(app=None):
    app = app or create_app()
    with app.app_context():
        print("\n🌱 Seeding demo data...\n")
        
        # Create all tables first
        db.create_all()
        print("✓ Database tables created\n")
        
        # ============ DEPARTMENTS ============
        depts = []
        dept_data = [
            ('Computer Science', 'CS'),
            ('Science', 'SC'),
            ('Commerce', 'CM')
        ]
        
        for dept_name, code in dept_data:
            dept = Department.query.filter_by(code=code).first()
            if not dept:
                dept = Department(name=dept_name, code=code)
                db.session.add(dept)
                print(f"✓ Created department: {dept_name}")
            depts.append(dept)
        
        db.session.commit()
        
        # ============ CLASSES ============
        classes = []
        for dept in depts:
            for section in ['A', 'B']:
                cls = Class.query.filter_by(grade='10', section=section, department_id=dept.id).first()
                if not cls:
                    cls = Class(grade='10', section=section, department_id=dept.id)
                    db.session.add(cls)
                classes.append(cls)
        
        db.session.commit()
        print(f"✓ Created {len(classes)} classes")
        
        # ============ SUBJECTS ============
        subject_data = [
            ('Mathematics', 'MTH'),
            ('English', 'ENG'),
            ('Science', 'SCI'),
            ('History', 'HIS'),
            ('Geography', 'GEO'),
        ]
        
        for subject_name, code in subject_data:
            subj = Subject.query.filter_by(code=code).first()
            if not subj:
                subj = Subject(name=subject_name, code=code, department_id=depts[0].id)
                db.session.add(subj)
        
        db.session.commit()
        print(f"✓ Created {len(subject_data)} subjects")
        
        # ============ ADMIN USER ============
        admin = User.query.filter_by(email=DEMO_ACCOUNTS[0]['login']).first()
        if not admin:
            admin = User(
                username='admin',
                email=DEMO_ACCOUNTS[0]['login'],
                role='admin',
                is_approved=True
            )
            db.session.add(admin)
            print("✓ Admin user created")
        admin.role = 'admin'
        admin.is_approved = True
        admin.set_password(DEMO_ACCOUNTS[0]['password'])
        db.session.commit()
        print(f"  ├─ Email: {DEMO_ACCOUNTS[0]['login']}")
        print(f"  └─ Password: {DEMO_ACCOUNTS[0]['password']}")
        
        # ============ TEACHER USERS ============
        teachers_data = [
            ('john_teacher', 'john@demo.com', 'John', 'Doe'),
            ('sarah_teacher', 'sarah@demo.com', 'Sarah', 'Williams'),
            ('mike_teacher', 'mike@demo.com', 'Mike', 'Johnson'),
        ]
        
        print("\n✓ Teachers created:")
        for username, email, first_name, last_name in teachers_data:
            teacher_user = User.query.filter_by(email=email).first()
            if not teacher_user:
                teacher_user = User(
                    username=username,
                    email=email,
                    role='teacher',
                    is_approved=True
                )
                teacher_user.set_password('teacher123')
                db.session.add(teacher_user)
                db.session.flush()
            else:
                teacher_user.role = 'teacher'
                teacher_user.is_approved = True
                teacher_user.set_password('teacher123')

            teacher = Teacher.query.filter_by(user_id=teacher_user.id).first()
            if not teacher:
                teacher = Teacher(
                    user_id=teacher_user.id,
                    first_name=first_name,
                    last_name=last_name,
                    department_id=depts[0].id,
                    phone='98' + ''.join([str(random.randint(0, 9)) for _ in range(8)]),
                    joining_date=date.today() - timedelta(days=365)
                )
                db.session.add(teacher)
            else:
                teacher.first_name = first_name
                teacher.last_name = last_name
                teacher.department_id = depts[0].id
            db.session.commit()
            print(f"  ├─ {first_name} {last_name} ({email}) / teacher123")
        
        # ============ STUDENT USERS ============
        students_data = [
            ('alice_student', 'alice@demo.com', 'Alice', 'Smith', '101'),
            ('bob_student', 'bob@demo.com', 'Bob', 'Brown', '102'),
            ('carol_student', 'carol@demo.com', 'Carol', 'Davis', '103'),
            ('david_student', 'david@demo.com', 'David', 'Miller', '104'),
            ('emma_student', 'emma@demo.com', 'Emma', 'Wilson', '105'),
        ]
        
        print("\n✓ Students created:")
        for username, email, first_name, last_name, roll_no in students_data:
            student_user = User.query.filter_by(email=email).first()
            if not student_user:
                student_user = User(
                    username=username,
                    email=email,
                    role='student',
                    is_approved=True
                )
                student_user.set_password('student123')
                db.session.add(student_user)
                db.session.flush()
            else:
                student_user.role = 'student'
                student_user.is_approved = True
                student_user.set_password('student123')

            student = Student.query.filter_by(user_id=student_user.id).first()
            if not student:
                student = Student(
                    user_id=student_user.id,
                    first_name=first_name,
                    last_name=last_name,
                    roll_no=roll_no,
                    enrollment_no=f'ENR{roll_no}2024',
                    class_id=classes[0].id,
                    department_id=depts[0].id,
                    gender='Male' if username.startswith('bob') or username.startswith('david') else 'Female',
                    admission_date=date.today() - timedelta(days=180),
                    phone='99' + ''.join([str(random.randint(0, 9)) for _ in range(8)]),
                    parent_name=f'Parent of {first_name}',
                    parent_phone='91' + ''.join([str(random.randint(0, 9)) for _ in range(8)]),
                    address='Demo Address, City'
                )
                db.session.add(student)
            else:
                student.first_name = first_name
                student.last_name = last_name
                student.roll_no = roll_no
                student.enrollment_no = f'ENR{roll_no}2024'
                student.class_id = classes[0].id
                student.department_id = depts[0].id
            db.session.commit()
            print(f"  ├─ {first_name} {last_name} (Roll: {roll_no}, {email}) / student123")
        
        # ============ SAMPLE ATTENDANCE DATA ============
        print("\n✓ Adding sample attendance data...")
        students = Student.query.all()
        for student in students:
            existing = Attendance.query.filter_by(student_id=student.id).count()
            if existing < 5:
                for i in range(10):
                    att_date = date.today() - timedelta(days=i)
                    status = random.choice(['Present', 'Present', 'Present', 'Absent', 'Late'])
                    attendance = Attendance(
                        student_id=student.id,
                        date=att_date,
                        status=status
                    )
                    db.session.add(attendance)
        
        db.session.commit()
        
        print("\n" + "="*60)
        print("🎉 DEMO DATA SEEDED SUCCESSFULLY!")
        print("="*60)
        print("\n📋 DASHBOARD LOGIN CREDENTIALS:\n")
        
        print("👨‍💼 ADMIN DASHBOARD")
        print("   URL: http://127.0.0.1:5000/admin/dashboard")
        print(f"   Email: {DEMO_ACCOUNTS[0]['login']}")
        print(f"   Password: {DEMO_ACCOUNTS[0]['password']}\n")
        
        print("👨‍🏫 TEACHER DASHBOARD")
        print("   URL: http://127.0.0.1:5000/teacher/dashboard")
        print("   Sample Teachers:")
        for username, email, first_name, last_name in teachers_data:
            print(f"   ├─ Email: {email}")
            print(f"   │  Password: teacher123")
        print()
        
        print("👨‍🎓 STUDENT DASHBOARD")
        print("   URL: http://127.0.0.1:5000/student/dashboard")
        print("   Sample Students:")
        for username, email, first_name, last_name, roll_no in students_data:
            print(f"   ├─ Email: {email} (Roll: {roll_no})")
            print(f"   │  Password: student123")
        
        print("\n" + "="*60)

if __name__ == '__main__':
    seed_database()
