# Digital Leaving Certificate System (DLCS)

A secure, feature-rich web application for managing student registrations, generating and verifying digital leaving certificates, and maintaining comprehensive audit logs.

## Features

- **Student Management**: Add, view, edit, and delete student records with comprehensive details.
- **Certificate Generation**: Generate secure, tamper-proof digital leaving certificates with QR codes.
- **Certificate Verification**: Verify certificate authenticity using a dedicated verification portal.
- **Bulk Operations**: Generate certificates for multiple students at once.
- **User Roles**: Differentiated access for Students, College Admins, and System Admins.
- **Audit Logging**: Comprehensive logging of all critical actions performed by users.
- **Secure Authentication**: Password hashing, session management, and CSRF protection.
- **File Handling**: Secure upload and management of supporting documents (e.g., gap certificates).

## Tech Stack

- **Backend**: Python 3.x, Flask
- **Database**: SQLite
- **Frontend**: HTML, CSS, JavaScript
- **Libraries**: Chart.js (Analytics), qrcode (QR generation), Pillow (Image validation)
- **Deployment**: Vercel (Serverless)

## Deployment

### Prerequisites

- Python 3.8+
- pip

### Installation

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd Digital-Leaving-Certificate-System-DLCS
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Run the application locally:
   ```bash
   python app.py
   ```
   The application will be accessible at `http://localhost:5000`.

### Vercel Deployment

1. Ensure you have the Vercel CLI installed (`npm i -g vercel`).
2. Run `vercel` in the project root.
3. Follow the prompts to link your Git repository and deploy.

## Security Features

- **SQL Injection Prevention**: All database queries use parameterized statements.
- **XSS Protection**: Input sanitization and secure rendering of user content.
- **CSRF Protection**: CSRF tokens implemented for all state-changing requests.
- **File Upload Security**: File type validation using magic bytes (Pillow) and secure filename sanitization.
- **Error Handling**: Generic error messages to prevent information leakage.
- **Password Security**: Passwords are hashed using bcrypt.
- **Access Control**: Role-based access control (RBAC) enforced at the route level.

## License

[MIT License](LICENSE)