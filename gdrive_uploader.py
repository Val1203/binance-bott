# gdrive_uploader.py
import os, json, base64
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.service_account import Credentials

SCOPES = ['https://www.googleapis.com/auth/drive.file']  # accès aux fichiers créés par l'app

def _load_sa_info():
    raw = os.environ['GDRIVE_SA_JSON'].strip()
    # Accepte JSON brut ou base64
    if raw.startswith('{'):
        return json.loads(raw)
    return json.loads(base64.b64decode(raw).decode())

def _drive_service():
    sa_info = _load_sa_info()
    creds = Credentials.from_service_account_info(sa_info, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds, cache_discovery=False)

def upload_to_gdrive(local_path: str, dest_name: str = None, folder_id: str = None):
    """Envoie (ou met à jour) un fichier Excel dans le dossier Drive."""
    service = _drive_service()
    if dest_name is None:
        dest_name = os.path.basename(local_path)
    if folder_id is None:
        folder_id = os.environ['GDRIVE_FOLDER_ID']

    # Cherche s’il existe déjà un fichier du même nom dans le dossier
    q = f"name='{dest_name}' and '{folder_id}' in parents and trashed=false"
    existing = service.files().list(q=q, spaces='drive', fields="files(id,name)").execute().get('files', [])

    media = MediaFileUpload(
        local_path,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        resumable=True
    )

    if existing:
        file_id = existing[0]['id']
        service.files().update(fileId=file_id, media_body=media).execute()
        return file_id
    else:
        metadata = {'name': dest_name, 'parents': [folder_id]}
        file = service.files().create(body=metadata, media_body=media, fields='id').execute()
        return file['id']
