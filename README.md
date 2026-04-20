# AttendAI — Smart Face Recognition Attendance System

AttendAI is a modern, AI-powered attendance management system built for educational institutions to automate and secure student tracking. It utilizes state-of-the-art computer vision models (ArcFace) to identify enrolled students and mark their attendance instantly using a synchronized, asynchronous processing pipeline.

## 🌟 Key Features

* **AI Face Verification**: Automated check-in for students using facial embeddings processed entirely on the backend to prevent tampering.
* **Role-Based Access Control**: Highly tailored dashboard systems with access restricted to explicitly defined roles: Admins, Teachers, and Students.
* **Asynchronous Processing**: Deep learning facial extractions and verifications run completely in the background via **Celery & Redis**, ensuring a smooth footprint without server gridlocks.
* **Live Projection Mode**: Secure physical-class attendance sessions where instructors generate randomly rotating 6-digit PINs and QR Codes that self-delete immediately after class ends. 
* **Dynamic Aesthetics**: Fully responsive UI/UX built with TailwindCSS, utilizing fluid glassmorphism and real-time Toast AJAX notifications.
* **Production-Ready**: Comes packaged entirely within a Docker ecosystem carrying Nginx, PostgreSQL, Redis, and Gunicorn setups seamlessly integrated.

## 🛠 Tech Stack

* **Backend Framework**: Django 6.0.
* **Computer Vision**: DeepFace (ArcFace Embedding Models)
* **Background Tasks**: Celery with Redis Broker
* **Database**: PostgreSQL 15
* **Frontend**: Vanilla JavaScript + Tailwind CSS
* **Deployment/DevOps**: Docker, Docker Compose, Nginx, Gunicorn

---

## 🚀 Quick Start Guide

### 1. Prerequisites
Ensure the following tools are installed on your host system:
- [Docker](https://docs.docker.com/get-docker/)

### 2. Environment Setup
Clone the repository and set up your `.env` variables from the example setup.
```bash
git clone https://github.com/muhammadjon-merzaqulov/Face-Based-Attendance-System.git
cd cloud_computing
```

*Note: Ensure your `.env` contains valid production secrets as laid out in the project.*

### 3. Build and Run via Docker
To boot up the entire ecosystem (Django, Celery Worker, PostgreSQL, Redis, Nginx):

```bash
# Build and boot the stack in detached mode
docker-compose up -d --build
```

### 4. Database Initialization
Once the containers are successfully running, execute database migrations and create an initial superuser account.

```bash
# Migrate the PostgreSQL database
docker-compose exec web python manage.py migrate

# Create Admin User
docker-compose exec web python manage.py createsuperuser
```

### 5. Accessing the Application
Your app is now securely hosted via Nginx proxy defaults on port 80.
- Navigate to `http://localhost/` in your browser.
- Login using the admin credentials you just generated.

---

## 🏗 System Architecture

1. **Web (Gunicorn/Django)**: Runs the main Python application handling views, ORM connections, models, and HTTP routes.
2. **Celery**: Runs in a separate bounded container parsing heavy jobs such as AI facial embedding generations and facial similarity searches.
3. **Redis**: Acts as the high-speed data flow queue between Django and the Celery worker.
4. **PostgreSQL**: Hardened persistent storage for user objects, attendance records, log traces, and face encoding blobs.
5. **Nginx**: Reverse proxies static and media files securely, keeping Django away from public-facing file-serving bottlenecks. Serves standalone beautiful 50x error pages during maintenance.

---

## 🛡 License
This project is open-source and structured for Cloud Computing, Security, and Computer Vision demonstrations. 
