# EduShieldAI 🛡️
### AI-Assisted Student Phone-Number Change Security Management System

EduShieldAI is a web-based student account security and phone-number change management platform designed for educational institutions.

The system combines **dual OTP verification, behavioural risk assessment using machine learning, role-based access control, and mentor review** to help protect student accounts against unauthorized phone-number changes.

The application follows a human-in-the-loop security model: the AI system provides risk assessment and supporting information, while an authorized mentor makes the final approval or rejection decision.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Key Features](#2-key-features)
3. [System Architecture](#3-system-architecture)
4. [Technology Stack](#4-technology-stack)
5. [Project Structure](#5-project-structure)
6. [Prerequisites](#6-prerequisites)
7. [Installation and Setup](#7-installation-and-setup)
8. [Database Configuration](#8-database-configuration)
9. [Environment Configuration](#9-environment-configuration)
10. [Running the Application](#10-running-the-application)
11. [Accessing the Application](#11-accessing-the-application)
12. [Application Workflow](#12-application-workflow)
13. [Machine Learning Module](#13-machine-learning-module)
14. [Optional External Services](#14-optional-external-services)
15. [Running Tests](#15-running-tests)
16. [Common Errors and Troubleshooting](#16-common-errors-and-troubleshooting)
17. [Security Considerations](#17-security-considerations)
18. [Development Guidelines](#18-development-guidelines)
19. [Known Limitations](#19-known-limitations)
20. [Future Enhancements](#20-future-enhancements)
21. [Contributors](#21-contributors)

---

# 1. Project Overview

Educational institutions increasingly rely on digital platforms to manage student information and account access. A change to a student's registered mobile number can introduce security risks if the request is not properly authenticated and reviewed.

EduShieldAI addresses this problem by introducing multiple verification and review mechanisms before a phone-number change is finalized.

The platform is designed around the following principles:

- Verify the student's identity using independent verification mechanisms.
- Evaluate suspicious behavioural patterns using machine learning.
- Provide mentors with relevant information to review requests.
- Restrict sensitive operations through role-based authorization.
- Maintain accountability through request records and audit information.
- Prevent an AI model from making final administrative decisions.

### Core workflow

**Student Request → SMS OTP Verification → Email OTP Verification → AI Risk Assessment → Mentor Review → Approval or Rejection**

The registered phone number should only be updated after authorized approval and completion of all required security checks.

---

# 2. Key Features

The following describes the intended and implemented feature areas. Individual capabilities should be considered available only when supported by the current application configuration.

### Student Module
- Student authentication.
- Phone-number change request submission.
- OTP verification.
- Request status tracking.
- Access to relevant notifications.
- Security-related interactions where supported.

### Mentor Module
- Mentor authentication.
- Access to assigned phone-change requests.
- Review of student request information.
- Access to available AI risk assessment information.
- Request approval or rejection.
- Review-related actions where supported.

### Administrator Module
- Administrative dashboard.
- User and account management.
- Mentor management and assignment.
- Request monitoring.
- Administrative operations and analytics where implemented.

### Security Module
- SMS OTP verification.
- Email OTP verification.
- Role-based access control.
- Backend-side validation.
- Behavioural risk assessment.
- Request and audit tracking where implemented.

### Machine Learning Module
- Behavioural feature processing.
- Risk assessment.
- Risk classification.
- Supporting information for human review.

**Important:** Machine learning is used for decision support. It does not replace the mentor's authority to approve or reject a phone-change request.

---

# 3. System Architecture

EduShieldAI uses a two-application Flask architecture.

### Frontend Application

The frontend is responsible for:
- User-facing pages.
- Login interfaces.
- Student, mentor, and administrator dashboards.
- HTML rendering through Jinja templates.
- CSS styling and JavaScript interactions.
- Communicating with the backend through API requests.

Default development port: `5002`

### Backend Application

The backend is responsible for:
- Authentication.
- Authorization.
- API endpoints.
- Phone-change request processing.
- OTP-related operations.
- Machine-learning integration.
- Mentor review operations.
- Database interactions.
- Other application services.

Default development port: `5000`

### Database

MySQL is used for persistent application data.

### Architecture Overview

```text
                  STUDENT / MENTOR / ADMIN
                            |
                            v
                  FRONTEND FLASK APP
                       Port 5002
                            |
                            | HTTP API Requests
                            v
                   BACKEND FLASK APP
                       Port 5000
                            |
             +--------------+--------------+
             |              |              |
             v              v              v
        Authentication   OTP Module    ML Assessment
             |              |              |
             +--------------+--------------+
                            |
                            v
                       MYSQL DATABASE
                            |
                            v
                     Mentor Review
                            |
                            v
                  Approval / Rejection
```

The diagram represents the logical application architecture. Actual component connections should be verified against the current implementation.

---

# 4. Technology Stack

| Component | Technology |
|---|---|
| Backend | Python, Flask |
| Frontend server | Python, Flask |
| Frontend rendering | HTML, Jinja |
| Styling | CSS |
| Client-side functionality | JavaScript |
| Database | MySQL |
| Machine Learning | Python-based ML components |
| API communication | HTTP |
| External access (optional) | Cloudflare Tunnel |
| Optional request routing | Cloudflare Worker |
| Version control | Git and GitHub |

Refer to the dependency files in the repository for the exact installed library versions.

---

# 5. Project Structure

The project uses separate frontend and backend applications.

A simplified view of the repository is:

```text
EduShieldAI/
│
├── backend/
│   ├── app.py
│   ├── requirements.txt
│   ├── ...
│   └── ...
│
├── frontend-flask/
│   ├── app.py
│   ├── templates/
│   │   ├── admin-dashboard.html
│   │   ├── ...
│   │   └── ...
│   ├── static/
│   │   ├── css/
│   │   ├── js/
│   │   └── ...
│   └── ...
│
├── worker/
│   ├── src/
│   │   └── index.js
│   ├── wrangler.toml
│   └── ...
│
├── start-cloudflare-tunnel.ps1
├── START.bat
├── documentation/
│
└── README.md
```

This is a simplified structure. Consult the repository for the complete directory and file listing.

---

# 6. Prerequisites

Install the following before running the project.

| Software | Purpose |
|---|---|
| Python 3 | Running Flask applications and ML components |
| pip | Python package installation |
| MySQL Server | Database management |
| MySQL Workbench (optional) | Database administration |
| Git | Repository cloning and version control |
| Node.js (optional) | Running the Cloudflare Worker tooling |
| Cloudflared (optional) | Creating a Cloudflare Tunnel |

You should also have:
- A stable internet connection for configured external services.
- Access to the required environment configuration.
- The database schema or initialization scripts supplied with the project.

Check your installations:

```powershell
python --version
pip --version
git --version
mysql --version
```

For optional Worker development:

```powershell
node --version
npm --version
```

---

# 7. Installation and Setup

## Step 1 — Clone the repository

```powershell
git clone https://github.com/saisuryakarthik/EduShield-AI-.git
```

Move into the project directory:

```powershell
cd "EduShield-AI-"
```

If the repository contains a nested project directory, enter the directory containing `backend` and `frontend-flask`.

## Step 2 — Create a Python virtual environment

From the project root:

```powershell
python -m venv .venv
```

Activate it:

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Then activate the environment again:

```powershell
.\.venv\Scripts\Activate.ps1
```

A successful activation should display `(.venv)` in the terminal prompt.

## Step 3 — Install backend dependencies

Navigate to the backend directory:

```powershell
cd backend
```

If `requirements.txt` exists:

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Return to the project root:

```powershell
cd ..
```

## Step 4 — Install frontend dependencies

Navigate to the frontend directory:

```powershell
cd frontend-flask
```

If the directory contains its own `requirements.txt`:

```powershell
pip install -r requirements.txt
```

If both applications share one dependency file, install the dependencies specified by the repository's setup instructions instead of installing conflicting versions.

Return to the project root:

```powershell
cd ..
```

---

# 8. Database Configuration

EduShieldAI uses MySQL for persistent data storage.

### Step 1 — Start MySQL Server

Make sure the MySQL service is running.

You can use MySQL Workbench or the MySQL command-line client.

### Step 2 — Create or select the project database

Use the database name and schema supplied by the project configuration or SQL initialization scripts.

For example, if the actual schema uses a database named `edushieldai`:

```sql
CREATE DATABASE IF NOT EXISTS edushieldai;
```

Do not create a second database if the existing project already uses a different configured database name.

### Step 3 — Initialize the schema

Locate the project's SQL schema or initialization scripts.

Execute the appropriate script using MySQL Workbench or:

```powershell
mysql -u YOUR_MYSQL_USER -p YOUR_DATABASE_NAME < schema.sql
```

Replace the example values with your actual database username, database name, and schema filename.

### Step 4 — Verify the database

Connect to MySQL and execute:

```sql
SHOW DATABASES;
```

Select the configured database:

```sql
USE YOUR_DATABASE_NAME;
```

Inspect its tables:

```sql
SHOW TABLES;
```

Confirm that the required tables exist before starting the backend.

**Important:** Do not manually create guessed tables or columns. Use the schema and migrations included in the repository.

---

# 9. Environment Configuration

The applications may require environment variables for database connectivity, authentication, OTP delivery, and external services.

Create the appropriate local environment configuration using the variable names expected by the actual application code.

### Backend configuration

The backend should be configured with the database connection information and required application settings.

Typical configuration categories include:

```env
DB_HOST=localhost
DB_PORT=3306
DB_USER=your_mysql_user
DB_PASSWORD=your_mysql_password
DB_NAME=your_database_name
```

These are illustrative names. Use the exact variable names read by the backend configuration.

### Frontend configuration

The frontend uses the following backend URL setting:

```env
EDUSHIELD_BACKEND_URL=http://127.0.0.1:5000/api
```

If the frontend uses this variable with a different API path in your checkout, preserve the actual configured value.

### External service configuration

Depending on enabled features, additional configuration may be required for:

- SMS provider credentials.
- Email delivery provider credentials.
- Application secret keys.
- Cloudflare Worker URL.
- Secure tunnel registration.
- ML model file locations.

### Important security rules

- Never commit `.env` files.
- Never upload API keys or passwords to GitHub.
- Never share OTP values or session secrets.
- Use `.env.example` files containing placeholder values only.
- Keep development and production configuration separate.

---

# 10. Running the Application

EduShieldAI has two Flask applications. Both need to be running for the normal frontend-to-backend workflow.

## Option A — Run using START.bat

If the repository's `START.bat` is configured for your environment:

```powershell
.\START.bat
```

Check the output of each process. Confirm that the frontend and backend both start successfully.

## Option B — Start the backend and frontend separately

This is useful when debugging errors.

### Terminal 1 — Backend

Open PowerShell in the project root.

Activate the virtual environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

Navigate to the backend:

```powershell
cd backend
```

Start Flask:

```powershell
python app.py
```

Expected development address:

```text
http://127.0.0.1:5000
```

### Terminal 2 — Frontend

Open a second PowerShell terminal in the project root.

Activate the virtual environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

Configure the backend URL if required:

```powershell
$env:EDUSHIELD_BACKEND_URL="http://127.0.0.1:5000/api"
```

Navigate to the frontend:

```powershell
cd frontend-flask
```

Start the frontend:

```powershell
python app.py
```

Expected development address:

```text
http://127.0.0.1:5002
```

Keep both terminals running while using the application.

**Note:** If the repository has additional startup requirements, follow its existing configuration rather than assuming the commands above cover every optional service.

---

# 11. Accessing the Application

Once both Flask applications have started, open:

| Application | Local URL |
|---|---|
| Frontend | http://127.0.0.1:5002 |
| Backend | http://127.0.0.1:5000 |

The frontend is the primary interface for users.

The backend exposes application API routes. Do not assume that opening the backend root URL is equivalent to opening the frontend.

Use the configured accounts and roles available in your development database.

---

# 12. Application Workflow

The intended core phone-change workflow is:

```text
START
  |
  v
Student Login
  |
  v
Submit Phone-Change Request
  |
  v
Backend Validation
  |
  v
SMS OTP Verification
  |
  v
Email OTP Verification
  |
  v
AI Behavioural Risk Assessment
  |
  v
Mentor Assignment
  |
  v
Mentor Review
  |
  +-----------------------+
  |                       |
  v                       v
APPROVED                REJECTED
  |                       |
  v                       v
Required Security       Existing Phone
Checks                  Number Preserved
  |                       |
  v                       v
Update Phone Number     Notify Student
  |                       |
  v                       v
Audit / Notification      END
  |
  v
 END
```

The workflow requires both OTP verifications before AI assessment.

The AI model provides risk information to support the mentor's decision. It does not independently approve or reject a request.

The phone-number update must be performed only after authorized approval and the required security checks.

---

# 13. Machine Learning Module

EduShieldAI includes Python-based machine-learning functionality for behavioural risk assessment.

The purpose of the ML component is to evaluate available security and behavioural indicators and provide risk-related information for human review.

The exact algorithm, feature set, preprocessing pipeline, model storage format, and inference integration must be determined from the current ML implementation.

Potential categories of information include:

- Authentication activity.
- Device information.
- Location-related indicators.
- Failed login activity.
- Phone-change history.
- Security verification information.

The ML pipeline can be described at a high level as:

```text
Input Data
    |
    v
Feature Extraction
    |
    v
Preprocessing
    |
    v
ML Model Inference
    |
    v
Risk Assessment
    |
    v
Database Persistence
    |
    v
Mentor Review
```

**Important:** Do not assume that every potential feature is used by the trained model. Do not report accuracy, precision, recall, training dataset size, or other performance measurements unless they have been experimentally verified.

---

# 14. Optional External Services

Some project capabilities may rely on external services.

These are optional deployment or integration components and should only be enabled when configured.

## SMS and Email Delivery

OTP delivery requires valid provider configuration.

If messages are not being delivered:
1. Verify provider credentials.
2. Check the provider's account status.
3. Inspect application logs.
4. Confirm recipient details are valid.
5. Check provider restrictions and delivery limits.
6. Verify that the configured sender is authorized.

Do not expose provider credentials when sharing logs or screenshots.

## Cloudflare Tunnel

Cloudflare Tunnel can expose a locally running application through a public URL for remote testing.

For example, to expose the frontend:

```powershell
cloudflared tunnel --url http://127.0.0.1:5002
```

This creates a temporary Quick Tunnel URL.

The URL may change when a new tunnel is started.

For Worker-based routing, the Worker and tunnel-registration configuration must also be running and correctly configured.

A tunnel does not automatically:
- Configure the backend.
- Fix email provider restrictions.
- Make a local database publicly accessible.
- Provide production-grade hosting.

Do not expose development services publicly without appropriate authentication and security controls.

## Cloudflare Worker

The optional Worker is located in:

```text
worker/
```

Its entry point is:

```text
worker/src/index.js
```

Its configuration is:

```text
worker/wrangler.toml
```

Worker development requires Node.js and the relevant Wrangler tooling.

Consult the Worker configuration and deployment instructions before deploying or changing its configuration.

---

# 15. Running Tests

Automated tests are important for checking that existing functionality continues to work after changes.

Run tests from the directory containing the relevant test suite.

For a standard Python unittest suite:

```powershell
python -m unittest discover -s tests -v
```

To execute an individual test module:

```powershell
python -m unittest tests.test_admin_dashboard_requests -v
```

```powershell
python -m unittest tests.test_request_detail_hold -v
```

These example test commands assume the corresponding test files are present in your current checkout.

### What should be tested?

- Authentication.
- Role-based authorization.
- Student request submission.
- SMS OTP verification.
- Email OTP verification.
- Request ownership.
- Mentor assignment.
- Mentor approval and rejection.
- Phone-number update restrictions.
- AI assessment integration.
- Audit logging.
- Error handling.
- Database failure handling.

A passing unit-test suite does not automatically prove that external integrations or production deployment are working.

---

# 16. Common Errors and Troubleshooting

This section covers common development and configuration problems.

## Error 1 — `ModuleNotFoundError`

**Example:**

```text
ModuleNotFoundError: No module named 'flask'
```

**Cause:**

The required Python package is not installed in the active environment.

**Solution:**

Activate the project's virtual environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install the appropriate dependencies:

```powershell
pip install -r requirements.txt
```

Run the command from the directory containing the relevant dependency file.

---

## Error 2 — MySQL Connection Refused

**Example:**

```text
Can't connect to MySQL server
```

**Possible causes:**
- MySQL service is stopped.
- Incorrect database host.
- Incorrect port.
- Incorrect database credentials.
- Database configuration is missing.

**Solution:**

1. Start the MySQL service.
2. Verify the host and port.
3. Verify the configured username and password.
4. Confirm that the database exists.
5. Check that the backend loads the correct environment configuration.

---

## Error 3 — `Unknown database`

**Example:**

```text
Unknown database '...'
```

**Cause:**

The configured database name does not exist in MySQL.

**Solution:**

Inspect the database configuration and create or initialize the correct database using the project's supplied SQL scripts.

Do not create a database with a guessed name without checking the backend configuration.

---

## Error 4 — `Table doesn't exist`

**Example:**

```text
Table 'database_name.table_name' doesn't exist
```

**Cause:**

The database schema has not been initialized, or the application is connected to the wrong database.

**Solution:**

1. Inspect the configured database name.
2. Execute the project's schema or migration scripts.
3. Run `SHOW TABLES;`.
4. Verify that the expected tables exist.
5. Restart the backend.

---

## Error 5 — Frontend Cannot Connect to Backend

**Symptoms:**
- Dashboard does not load.
- API requests fail.
- Login redirects unexpectedly.
- Browser displays a connection error.

**Possible causes:**
- Backend is not running.
- Backend is listening on another port.
- `EDUSHIELD_BACKEND_URL` is incorrect.
- The API base path is incorrect.
- Firewall or network configuration is blocking the request.

**Solution:**

Verify the backend is running:


http://127.0.0.1:5000


Check the frontend configuration:


$env:EDUSHIELD_BACKEND_URL="http://127.0.0.1:5000/api"


Restart the frontend after changing its environment variables.

---

## Error 6 — Port Already in Use

**Example:**

```text
Address already in use
```

**Cause:**

Another process is already using the required port.

**Solution:**

Find the process:


netstat -ano | findstr :5000


Or for the frontend:


netstat -ano | findstr :5002


Identify the process ID and stop it only if you are certain it is safe to do so:

taskkill /PID PROCESS_ID /F

Replace `PROCESS_ID` with the actual process ID.

Then restart the application.

---

## Error 7 — HTTP 500 Internal Server Error

**Possible causes:**
- Missing template variables.
- Database query failure.
- Backend API error.
- Unexpected null values.
- Template rendering problems.
- Unhandled Python exceptions.

**Solution:**

1. Check the Flask terminal output.
2. Read the complete Python traceback.
3. Identify the exact file and line number.
4. Inspect the route and template involved.
5. Verify that every required template variable is supplied.
6. Check backend API responses.
7. Reproduce the error after applying a fix.

Do not suppress the error without fixing its underlying cause.

---

## Error 8 — HTTP 401 Unauthorized

**Possible causes:**
- Invalid authentication credentials.
- Missing authentication token or session.
- Expired session.
- Incorrect API authorization configuration.
- External provider authentication failure.

**Solution:**

Check whether the error originates from:
- EduShieldAI authentication.
- Backend API authorization.
- An external integration.

Verify the appropriate configuration and login state.

For external services, check the provider's authentication and account restrictions.

Never share API keys or access tokens when requesting help.

---

## Error 9 — HTTP 403 Forbidden

**Cause:**

The authenticated user may not have permission to access the requested resource.

**Solution:**

Check:
- User role.
- Backend authorization rules.
- Resource ownership.
- Mentor assignment.
- Session identity.

Do not bypass authorization checks to make the page load.

---

## Error 10 — OTP Not Received

**Possible causes:**
- SMS or email provider configuration is missing.
- Invalid recipient information.
- Provider account restrictions.
- Network failure.
- Delivery limits.
- Provider-side rejection.

**Solution:**

1. Verify the configured provider.
2. Inspect the application logs.
3. Check the provider dashboard.
4. Verify that the recipient information is correct.
5. Check provider delivery status.
6. Confirm that the OTP-generation operation completed successfully.

Never log or share actual OTP values.

---

## Error 11 — Cloudflare Worker Returns `tunnel_not_registered`

**Cause:**

The Worker cannot find a currently registered tunnel destination.

**Solution:**

1. Start the local Flask service that should receive the traffic.
2. Start the appropriate Cloudflare Tunnel.
3. Verify that the tunnel-registration process has completed.
4. Confirm that the Worker has received the current destination.
5. Check the Worker configuration and logs.

Remember that a Quick Tunnel destination is temporary and may change when restarted.

---

## Error 12 — `[ERROR] CLOUDFLARE_WORKER_URL is not set`

**Cause:**

The PowerShell process does not have the required environment variable.

**Solution:**

Set the variable in the current PowerShell session using the configured Worker URL:


$env:CLOUDFLARE_WORKER_URL="YOUR_CONFIGURED_WORKER_URL"


Then run the relevant script again.

Do not commit private Worker configuration or secret values to GitHub.

---

## Error 13 — Email Provider Returns HTTP 401

**Possible causes:**
- Invalid API credentials.
- Provider account restrictions.
- Outbound IP address not authorized.
- Sender configuration problem.

**Solution:**

1. Verify the provider account.
2. Check API credentials without exposing them.
3. Review provider security and IP-allowlist settings.
4. Confirm the sender is authorized.
5. Inspect the provider's error response.

A Cloudflare Tunnel does not automatically fix outbound email-provider IP restrictions.

---

## Error 14 — Machine Learning Model Loading Failure

**Possible causes:**
- Model file is missing.
- Incorrect model path.
- Incompatible library version.
- Model serialization issue.
- Incorrect input feature format.

**Solution:**

1. Verify the model file exists.
2. Check the configured model path.
3. Confirm required ML dependencies are installed.
4. Verify that inference receives the expected input features.
5. Inspect the traceback.
6. Check that the saved model and runtime versions are compatible.

Do not replace the model or invent a fallback prediction without understanding the intended behaviour.

---

# 17. Security Considerations

Because EduShieldAI handles student account and authentication information, security must be considered throughout development and deployment.

Important requirements include:

- Enforce authentication on protected routes.
- Enforce role-based authorization on the backend.
- Verify resource ownership.
- Restrict mentor access to appropriately assigned requests.
- Validate user inputs on the server.
- Use parameterized database queries.
- Protect session cookies.
- Apply CSRF protection to applicable state-changing operations.
- Rate-limit OTP and authentication operations.
- Never expose passwords, OTPs, session tokens, or API credentials in logs.
- Protect sensitive information in notifications and reports.
- Preserve audit history.
- Prevent unauthorized phone-number updates.
- Never allow an AI prediction to bypass mentor approval.

### Development versus production

Flask development servers are intended for local development and testing.

A production deployment should use:
- A production WSGI server.
- HTTPS.
- Secure environment configuration.
- Appropriate database permissions.
- Secure session settings.
- Monitoring and backups.
- Properly configured external services.

Do not deploy the development configuration directly to production.

---

# 18. Development Guidelines

Before modifying the project:

1. Inspect the existing source code.
2. Understand the current architecture.
3. Review the database schema.
4. Identify existing functionality.
5. Avoid duplicating existing modules.
6. Preserve existing routes and template variables where possible.
7. Use environment variables for configuration.
8. Add tests for security-sensitive changes.
9. Test both frontend and backend workflows.
10. Verify that existing features continue to work.

### Git workflow

Check the current status:


git status

Create a feature branch:

git checkout -b feature/your-feature-name

After making and testing changes:

git add .
git commit -m "Describe the implemented change"


Push the branch:

git push -u origin feature/your-feature-name


Avoid committing:
- `.env` files.
- Database dumps containing student information.
- API credentials.
- OTP values.
- Session secrets.
- Private production configuration.

---

# 19. Known Limitations

The availability of a feature depends on the current implementation and its external configuration.

Potential limitations to check include:

- External SMS and email delivery depends on provider availability and credentials.
- Cloudflare Quick Tunnels are temporary.
- ML output quality depends on the training data, feature quality, and model evaluation.
- A locally running application is not equivalent to a production deployment.
- Some administrative or monitoring capabilities may require additional configuration.
- Integration and performance claims must be supported by actual testing.

Do not treat planned features as implemented functionality.

---

# 20. Future Enhancements

Potential areas for future development include:

- Advanced behavioural anomaly detection.
- Explainable AI assessments.
- Model versioning and monitoring.
- Model evaluation dashboards.
- Improved administrative analytics.
- Bulk student record import.
- Advanced mentor inbox filtering.
- Persistent in-app notifications.
- Structured audit reporting.
- Emergency account recovery.
- Mobile-first UI improvements.
- Progressive Web App support.
- Automated overdue-request reminders.
- Improved deployment and monitoring infrastructure.

These are proposed enhancements and should not be interpreted as completed features unless implemented and tested.

---

# 21. Contributors

EduShieldAI is developed as an academic special project.

Add the verified team member names, student IDs, and supervisor details here before final submission.

### Project Institution

Faculty of Science & Technology
The ICFAI Foundation for Higher Education  
Hyderabad, Telangana, India

---

## Support and Contributions

For bugs, feature requests, or development questions:

1. Reproduce the issue.
2. Collect the relevant error message or traceback.
3. Identify the affected application (frontend, backend, database, or external service).
4. Remove passwords, OTPs, tokens, and personal student information from logs.
5. Document the steps required to reproduce the issue.
6. Submit the issue or discuss it with the project development team.

---

**EduShieldAI — Making student account changes more secure through verification, behavioural intelligence, and human oversight.**