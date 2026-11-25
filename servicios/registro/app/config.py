import os

MONGO_URI = os.getenv(
    "MONGO_URI",
    "mongodb://mongo1:27017,mongo2:27017,mongo3:27017/?replicaSet=rs0",
)
MONGO_W = os.getenv("MONGO_W", "majority")
MONGO_WTIMEOUT_MS = int(os.getenv("MONGO_WTIMEOUT_MS", "2000"))
MONGO_TIMEOUT_MS = int(os.getenv("MONGO_TIMEOUT_MS", "2000"))
LOCK_MS = int(os.getenv("LOCK_MS", "120000"))
DB_NOMBRE = "plataforma"
