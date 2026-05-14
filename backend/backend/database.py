"""Database connection module with optimized connection pooling."""
from motor.motor_asyncio import AsyncIOMotorClient
import os

mongo_url = os.environ['MONGO_URL']

# Connection pool ottimizzato per produzione
# - maxPoolSize: max connessioni simultanee (default 100, troppo per un VPS piccolo)
# - minPoolSize: connessioni pronte in pool (evita latenza cold start)
# - maxIdleTimeMS: chiude connessioni inattive dopo 30s
# - serverSelectionTimeoutMS: timeout selezione server
# - connectTimeoutMS: timeout connessione iniziale
# - socketTimeoutMS: timeout operazioni socket
# - retryWrites/retryReads: resilienza automatica su errori transitori
mongo_client = AsyncIOMotorClient(
    mongo_url,
    maxPoolSize=25,
    minPoolSize=3,
    maxIdleTimeMS=30000,
    serverSelectionTimeoutMS=5000,
    connectTimeoutMS=5000,
    socketTimeoutMS=20000,
    retryWrites=True,
    retryReads=True,
)
db = mongo_client[os.environ['DB_NAME']]
