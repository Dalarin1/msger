import  os
from datetime import timedelta
SECRET_KEY = os.environ.get("SECRET_KEY", "change_me_in_production_please_for_32+_char_password")
PEPPER_KEY = os.environ.get("PEPPER_KEY", "change_me_in_production_please")
ALGORITHM = "HS256"
ACCESS_TOKEN_TTL = timedelta(minutes=15)
REFRESH_TOKEN_TTL = timedelta(days=30)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_FOLDER = os.path.join(BASE_DIR, "database")
from dotenv import load_dotenv
load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_FOLDER_DEFAULT = os.path.join(BASE_DIR, "database")

DB_PATH = os.environ.get("DB_PATH")
if DB_PATH:
    DB_PATH = os.path.abspath(os.path.join(BASE_DIR, DB_PATH))
else:
    DB_PATH = os.path.join(DATABASE_FOLDER_DEFAULT, "app.db")

DATABASE_FOLDER = os.path.dirname(DB_PATH)
STATIC_FILES_FLD = os.path.join(BASE_DIR, "static")
ALEMBIC_INI = os.path.join(BASE_DIR, "alembic.ini")


ATTACHEMENTS_FLD = os.path.join(BASE_DIR, "attachments")
USER_IMAGES_FLD = os.path.join(ATTACHEMENTS_FLD, "images")
USER_AUDIO_FLD = os.path.join(ATTACHEMENTS_FLD, "audios")
USER_VIDEO_FLD = os.path.join(ATTACHEMENTS_FLD, "videos")
USER_FILES_FLD = os.path.join(ATTACHEMENTS_FLD, "others")

MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 МБ
MAX_AUDIO_SIZE = 30 * 1024 * 1024  # 30 МБ
MAX_VIDEO_SIZE = 100 * 1024 * 1024  # 100 МБ
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500 МБ

ALLOWED_EXTENSIONS = {
    "image": {".jpg", ".jpeg", ".png", ".gif", ".jfif", ".webp", ".svg"},
    "video": {".mp4", ".webm"},
    "audio": {".mp3", ".wav", ".ogg"},
}

MAX_SIZES = {
    "image": MAX_IMAGE_SIZE,
    "video": MAX_VIDEO_SIZE,
    "audio": MAX_AUDIO_SIZE,
    "file": MAX_FILE_SIZE,
}

FOLDERS = {
    "image": USER_IMAGES_FLD,
    "video": USER_VIDEO_FLD,
    "audio": USER_AUDIO_FLD,
    "file": USER_FILES_FLD,
}

URL_PREFIXES = {
    "image": "/img",
    "video": "/video",
    "audio": "/audio",
    "file": "/file",
}