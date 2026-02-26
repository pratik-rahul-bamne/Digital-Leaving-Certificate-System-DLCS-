-- College Leaving Certificate System — PostgreSQL Schema

-- Admin Users
CREATE TABLE IF NOT EXISTS admin_users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Students
CREATE TABLE IF NOT EXISTS students (
    student_id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    father_name VARCHAR(200) NOT NULL,
    mother_name VARCHAR(200),
    dob DATE NOT NULL,
    gender VARCHAR(20),
    address TEXT,
    course VARCHAR(200) NOT NULL,
    department VARCHAR(200) NOT NULL,
    admission_year INT NOT NULL,
    admission_type VARCHAR(50) DEFAULT 'First Year',
    passing_year INT,
    leaving_year INT NOT NULL,
    leaving_date DATE,
    reason_for_leaving TEXT,
    conduct VARCHAR(100) DEFAULT 'Good',
    academic_status VARCHAR(100) DEFAULT 'Regular',
    gap_year_applicable BOOLEAN DEFAULT FALSE,
    gap_years INT DEFAULT 0,
    gap_certificate_path TEXT,
    is_deleted BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Certificate counter sequence
CREATE SEQUENCE IF NOT EXISTS cert_number_seq START 1001;

-- Certificates
CREATE TABLE IF NOT EXISTS certificates (
    certificate_id SERIAL PRIMARY KEY,
    student_id INT NOT NULL REFERENCES students(student_id),
    certificate_number VARCHAR(50) UNIQUE NOT NULL,
    issue_date DATE NOT NULL DEFAULT CURRENT_DATE,
    generated_by VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
