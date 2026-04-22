```
graph TD
    subgraph Client ["Client Side"]
        UI[Frontend Layer<br>QR Scan & Image Capture]
    end

    subgraph Server ["Backend Layer"]
        Django[Django Backend<br>HTTP, Auth, Delegation]
    end

    subgraph Data ["Database Layer"]
        DB[(Database<br>Users & Attendance)]
    end

    subgraph AsyncQueue ["Asynchronous Processing"]
        Redis[Redis<br>Message Broker / Queue]
        Celery[Celery Workers<br>DeepFace Facial Recognition]
    end

    User((User)) -->|Uses| UI
    UI -->|HTTP Requests| Django
    Django <-->|Read / Write| DB
    Django -->|Send Tasks| Redis
    Redis -->|Consume Tasks| Celery
    Celery -->|Update Records| DB
```
