import io
import os
import mimetypes
from typing import Dict, List

import requests
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

load_dotenv()

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "secret")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REFRESH_TOKEN = os.getenv("GOOGLE_REFRESH_TOKEN")
DRIVE_MEME_FOLDER_ID = os.getenv("DRIVE_MEME_FOLDER_ID")
ADMIN_IDS = set(
    x.strip() for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()
)
PORT = int(os.getenv("PORT", "3000"))

if not all([
    TELEGRAM_BOT_TOKEN,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_REFRESH_TOKEN,
    DRIVE_MEME_FOLDER_ID
]):
    raise RuntimeError("Missing required environment variables")

upload_mode_by_user: Dict[str, bool] = {}
user_page_map: Dict[str, int] = {}


def is_admin(user_id: int) -> bool:
    return str(user_id) in ADMIN_IDS


def telegram_api(method: str) -> str:
    return f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"


def telegram_file_url(file_path: str) -> str:
    return f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"


def get_drive_service():
    creds = Credentials(
        token=None,
        refresh_token=GOOGLE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=["https://www.googleapis.com/auth/drive.file"],
    )
    return build("drive", "v3", credentials=creds)


def send_message(chat_id: int, text: str):
    requests.post(telegram_api("sendMessage"), json={
        "chat_id": chat_id,
        "text": text
    }, timeout=60)


def send_photo(chat_id: int, image_bytes: bytes, filename: str, caption: str = ""):
    files = {
        "photo": (filename, image_bytes)
    }
    data = {
        "chat_id": str(chat_id)
    }
    if caption:
        data["caption"] = caption

    requests.post(
        telegram_api("sendPhoto"),
        data=data,
        files=files,
        timeout=120
    )


def send_media_group(chat_id: int, items: List[dict], caption: str = ""):
    media = []
    files = {}

    for i, item in enumerate(items):
        attach_name = f"file{i}"
        media_item = {
            "type": "photo",
            "media": f"attach://{attach_name}"
        }
        if i == 0 and caption:
            media_item["caption"] = caption
        media.append(media_item)
        files[attach_name] = (item["name"], item["bytes"])

    requests.post(
        telegram_api("sendMediaGroup"),
        data={
            "chat_id": str(chat_id),
            "media": __import__("json").dumps(media)
        },
        files=files,
        timeout=180
    )


def get_telegram_file(file_id: str) -> dict:
    resp = requests.get(telegram_api("getFile"), params={"file_id": file_id}, timeout=60)
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram getFile failed: {data}")
    return data["result"]


def download_telegram_file(file_path: str) -> bytes:
    resp = requests.get(telegram_file_url(file_path), timeout=120)
    resp.raise_for_status()
    return resp.content


def list_meme_files() -> List[dict]:
    service = get_drive_service()
    query = (
        f"'{DRIVE_MEME_FOLDER_ID}' in parents "
        f"and trashed = false "
        f"and mimeType contains 'image/'"
    )

    files = []
    page_token = None

    while True:
        result = service.files().list(
            q=query,
            fields="nextPageToken, files(id, name, mimeType)",
            pageSize=1000,
            pageToken=page_token,
            orderBy="name_natural"
        ).execute()

        files.extend(result.get("files", []))
        page_token = result.get("nextPageToken")
        if not page_token:
            break

    return files


def download_drive_file(file_id: str) -> bytes:
    service = get_drive_service()
    request_media = service.files().get_media(fileId=file_id)
    return request_media.execute()


def upload_buffer_to_drive(file_bytes: bytes, file_name: str, mime_type: str):
    service = get_drive_service()
    media = MediaIoBaseUpload(
        io.BytesIO(file_bytes),
        mimetype=mime_type,
        resumable=False
    )
    metadata = {
        "name": file_name,
        "parents": [DRIVE_MEME_FOLDER_ID]
    }

    result = service.files().create(
        body=metadata,
        media_body=media,
        fields="id,name"
    ).execute()

    return result


def get_next_meme_file_name(index: int, mime_type: str = "", original_name: str = "") -> str:
    ext = ".jpg"

    if mime_type:
        guessed = mimetypes.guess_extension(mime_type)
        if guessed:
            ext = guessed
    elif original_name:
        guessed_type, _ = mimetypes.guess_type(original_name)
        if guessed_type:
            guessed_ext = mimetypes.guess_extension(guessed_type)
            if guessed_ext:
                ext = guessed_ext

    return f"meme_{index}{ext}"


def pick_largest_photo(photos: List[dict]):
    if not photos:
        return None
    return photos[-1]


def handle_meme_page(chat_id: int, from_id: int, page: int):
    files = list_meme_files()

    if not files:
        send_message(chat_id, "Chưa có meme nào trong Drive.")
        return

    page_size = 10
    start = page * page_size
    end = start + page_size

    if start >= len(files):
        send_message(chat_id, "Đã hết ảnh rồi.")
        return

    batch = files[start:end]
    user_page_map[str(from_id)] = page

    if len(batch) == 1:
        one = batch[0]
        image_bytes = download_drive_file(one["id"])
        send_photo(
            chat_id,
            image_bytes,
            one["name"],
            f'{one["name"]}\nHiển thị {start + 1}-{start + len(batch)}/{len(files)}'
        )
        return

    media_items = []
    for f in batch:
        media_items.append({
            "name": f["name"],
            "bytes": download_drive_file(f["id"])
        })

    send_media_group(
        chat_id,
        media_items,
        f"Hiển thị {start + 1}-{start + len(batch)}/{len(files)}"
    )
    send_message(
        chat_id,
        f"Trang {page + 1}. Hiển thị {start + 1}-{start + len(batch)}/{len(files)} ảnh.\nDùng /next để xem tiếp."
    )


def handle_admin_upload_message(msg: dict) -> bool:
    chat_id = msg["chat"]["id"]
    from_id = msg["from"]["id"]

    if not is_admin(from_id):
        return False

    if not upload_mode_by_user.get(str(from_id), False):
        return False

    file_id = None
    original_name = None
    mime_type = None

    if "photo" in msg and msg["photo"]:
        largest = pick_largest_photo(msg["photo"])
        file_id = largest["file_id"]
        original_name = "telegram_photo.jpg"
        mime_type = "image/jpeg"
    elif "document" in msg:
        doc = msg["document"]
        doc_mime = doc.get("mime_type", "")
        if not doc_mime.startswith("image/"):
            send_message(chat_id, "File này không phải ảnh.")
            return True
        file_id = doc["file_id"]
        original_name = doc.get("file_name", "image")
        mime_type = doc_mime
    else:
        return False

    try:
        existing_files = list_meme_files()
        next_index = len(existing_files)

        tg_file = get_telegram_file(file_id)
        file_bytes = download_telegram_file(tg_file["file_path"])

        new_name = get_next_meme_file_name(next_index, mime_type, original_name)
        uploaded = upload_buffer_to_drive(file_bytes, new_name, mime_type)

        send_message(chat_id, f'Đã upload: {uploaded["name"]}')
    except Exception as e:
        print("UPLOAD_ERROR:", e)
        send_message(chat_id, "Upload lỗi. Kiểm tra log local.")

    return True


def handle_command(msg: dict) -> bool:
    chat_id = msg["chat"]["id"]
    from_id = msg["from"]["id"]
    text = (msg.get("text") or "").strip()

    if text == "/start":
        send_message(
            chat_id,
            "Bot meme V1\n\n"
            "Lệnh user:\n"
            "/meme10 - xem 10 ảnh đầu\n"
            "/next - xem 10 ảnh tiếp\n"
            "/count - xem tổng số ảnh\n\n"
            "Lệnh admin:\n"
            "/upload_on\n"
            "/upload_off\n"
            "/whoami"
        )
        return True

    if text == "/count":
        files = list_meme_files()
        send_message(chat_id, f"Hiện có {len(files)} ảnh meme.")
        return True

    if text == "/meme10":
        handle_meme_page(chat_id, from_id, 0)
        return True

    if text == "/next":
        current_page = user_page_map.get(str(from_id), 0)
        handle_meme_page(chat_id, from_id, current_page + 1)
        return True

    if text == "/upload_on":
        if not is_admin(from_id):
            send_message(chat_id, "Bạn không phải admin.")
            return True
        upload_mode_by_user[str(from_id)] = True
        send_message(chat_id, "Đã bật chế độ upload. Giờ hãy gửi ảnh hàng loạt.")
        return True

    if text == "/upload_off":
        if not is_admin(from_id):
            send_message(chat_id, "Bạn không phải admin.")
            return True
        upload_mode_by_user[str(from_id)] = False
        send_message(chat_id, "Đã tắt chế độ upload.")
        return True

    if text == "/whoami":
        send_message(chat_id, f"telegram_user_id = {from_id}")
        return True

    return False


@app.get("/")
def health():
    return "meme bot is running", 200


@app.post(f"/telegram/{WEBHOOK_SECRET}")
def telegram_webhook():
    update = request.get_json(silent=True) or {}

    try:
        msg = update.get("message")
        if not msg:
            return jsonify({"ok": True})

        if handle_command(msg):
            return jsonify({"ok": True})

        if handle_admin_upload_message(msg):
            return jsonify({"ok": True})

    except Exception as e:
        print("WEBHOOK_ERROR:", e)

    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=True)
