import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.auth import create_access_token, get_current_admin, verify_password
from app.database import get_connection, init_db
from app.extractor import extract_text_from_bytes
from app.rag import chunk_text, generate_answer, generate_embedding, search_chunks_by_role

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATASET_DIR = BASE_DIR / "dataset"
UPLOAD_DIR = BASE_DIR / "uploads"
STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="Modul 2 AI - Custom Chatbot RAG Berbasis Role",
    version="2.0.0",
)

app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def seed_default_documents() -> None:
    if not DATASET_DIR.exists():
        return

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS cnt FROM documents")
    if cur.fetchone()["cnt"] > 0:
        conn.close()
        return

    # Map: filename -> list of role names that can access
    DOSEN_ONLY_FILES = {"Panduan_Internal_Dosen.txt"}
    MAHASISWA_ONLY_FILES = {
        "Alur_Menghubungi_SSC.txt",
        "SSC_Operating_Hours.txt",
        "SK-TAK-2022.pdf",
        "SK_TAK_TUNC_2025.pdf",
    }

    # Get all roles
    cur.execute("SELECT id, name FROM roles")
    all_roles = {row["name"].lower(): row["id"] for row in cur.fetchall()}

    for file_path in sorted(DATASET_DIR.iterdir()):
        if not file_path.is_file() or file_path.suffix.lower() not in {".txt", ".md", ".pdf", ".docx", ".csv", ".xlsx"}:
            continue

        file_bytes = file_path.read_bytes()
        try:
            extracted_text = extract_text_from_bytes(file_bytes, file_path.name)
        except Exception:
            continue
        if not extracted_text:
            continue

        chunks = chunk_text(extracted_text)
        if not chunks:
            continue

        safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", file_path.name)
        stored_filename = f"default_{safe_name}"
        (UPLOAD_DIR / stored_filename).write_bytes(file_bytes)

        doc_title = file_path.stem.replace("_", " ")
        ext = file_path.suffix.lstrip(".").lower() or "txt"
        now = datetime.now(timezone.utc).isoformat()

        cur.execute(
            "INSERT INTO documents (title, filename, file_type, total_chunks, uploaded_at) VALUES (?, ?, ?, ?, ?)",
            (doc_title, stored_filename, ext, len(chunks), now),
        )
        doc_id = cur.lastrowid

        # Assign roles based on file type
        fname = file_path.name
        if fname in DOSEN_ONLY_FILES:
            # Only dosen role
            assigned_roles = ["dosen"]
        elif fname in MAHASISWA_ONLY_FILES:
            # Both mahasiswa and dosen can access
            assigned_roles = ["mahasiswa", "dosen"]
        else:
            # Default: all roles
            assigned_roles = list(all_roles.keys())

        for role_name in assigned_roles:
            role_id = all_roles.get(role_name.lower())
            if role_id:
                cur.execute(
                    "INSERT OR IGNORE INTO document_roles (document_id, role_id) VALUES (?, ?)",
                    (doc_id, role_id),
                )

        for idx, ch in enumerate(chunks):
            emb = generate_embedding(ch)
            cur.execute(
                "INSERT INTO document_chunks (document_id, chunk_index, text, embedding_json) VALUES (?, ?, ?, ?)",
                (doc_id, idx, ch, json.dumps(emb)),
            )

    conn.commit()
    conn.close()


@app.on_event("startup")
def on_startup():
    init_db()
    seed_default_documents()


# ---------- Schemas ----------

class LoginRequest(BaseModel):
    username: str
    password: str


class RoleCreateRequest(BaseModel):
    name: str
    description: str = ""


class RoleUpdateRequest(BaseModel):
    name: str
    description: str = ""


class ChatRequest(BaseModel):
    question: str
    role: str = "mahasiswa"


class DocumentRolesUpdateRequest(BaseModel):
    role_ids: List[int]


# ---------- Page Routes ----------

@app.get("/", include_in_schema=False)
def serve_chat_page():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/admin", include_in_schema=False)
def serve_admin_page():
    return FileResponse(str(STATIC_DIR / "admin.html"))


# ---------- Auth Routes ----------

@app.post("/api/auth/login")
def admin_login(payload: LoginRequest):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, username, password_hash FROM admins WHERE username = ?", (payload.username.strip(),))
    admin = cur.fetchone()
    conn.close()

    if not admin or not verify_password(payload.password, admin["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Username atau password admin salah.",
        )

    token = create_access_token(admin["username"], admin["id"])
    return {
        "success": True,
        "token": token,
        "username": admin["username"],
        "role": "admin",
    }


@app.get("/api/auth/me")
def get_me(admin: dict = Depends(get_current_admin)):
    return {"success": True, "admin": admin}


# ---------- Role Routes ----------

@app.get("/api/roles")
def list_roles():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT r.id, r.name, r.description, r.created_at,
               COUNT(dr.document_id) AS document_count
        FROM roles r
        LEFT JOIN document_roles dr ON dr.role_id = r.id
        GROUP BY r.id
        ORDER BY r.id ASC
        """
    )
    roles = [dict(row) for row in cur.fetchall()]
    conn.close()
    return {"success": True, "roles": roles}


@app.post("/api/roles", status_code=status.HTTP_201_CREATED)
def create_role(payload: RoleCreateRequest, _admin: dict = Depends(get_current_admin)):
    role_name = payload.name.strip().lower()
    if not role_name:
        raise HTTPException(status_code=400, detail="Nama role tidak boleh kosong.")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM roles WHERE LOWER(name) = LOWER(?)", (role_name,))
    if cur.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail=f"Role '{role_name}' sudah ada.")

    now = datetime.now(timezone.utc).isoformat()
    cur.execute(
        "INSERT INTO roles (name, description, created_at) VALUES (?, ?, ?)",
        (role_name, payload.description.strip(), now),
    )
    role_id = cur.lastrowid
    conn.commit()
    conn.close()

    return {
        "success": True,
        "role": {"id": role_id, "name": role_name, "description": payload.description.strip()},
    }


@app.put("/api/roles/{role_id}")
def update_role(role_id: int, payload: RoleUpdateRequest, _admin: dict = Depends(get_current_admin)):
    role_name = payload.name.strip().lower()
    if not role_name:
        raise HTTPException(status_code=400, detail="Nama role tidak boleh kosong.")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM roles WHERE id = ?", (role_id,))
    if not cur.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Role tidak ditemukan.")

    cur.execute("SELECT id FROM roles WHERE LOWER(name) = LOWER(?) AND id != ?", (role_name, role_id))
    if cur.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail=f"Nama role '{role_name}' sudah digunakan.")

    cur.execute(
        "UPDATE roles SET name = ?, description = ? WHERE id = ?",
        (role_name, payload.description.strip(), role_id),
    )
    conn.commit()
    conn.close()
    return {"success": True, "message": "Role berhasil diperbarui."}


@app.delete("/api/roles/{role_id}")
def delete_role(role_id: int, _admin: dict = Depends(get_current_admin)):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM roles WHERE id = ?", (role_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Role tidak ditemukan.")

    # Prevent deleting core roles
    if row["name"].lower() in ("mahasiswa", "dosen"):
        conn.close()
        raise HTTPException(status_code=400, detail=f"Role '{row['name']}' adalah role bawaan dan tidak dapat dihapus.")

    cur.execute("DELETE FROM roles WHERE id = ?", (role_id,))
    conn.commit()
    conn.close()
    return {"success": True, "message": f"Role '{row['name']}' berhasil dihapus."}


# ---------- Document Routes (Admin Only) ----------

@app.get("/api/documents")
def list_documents(_admin: dict = Depends(get_current_admin)):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM documents ORDER BY id DESC")
    docs = [dict(r) for r in cur.fetchall()]

    for doc in docs:
        cur.execute(
            """
            SELECT r.id, r.name
            FROM roles r
            JOIN document_roles dr ON dr.role_id = r.id
            WHERE dr.document_id = ?
            ORDER BY r.name ASC
            """,
            (doc["id"],),
        )
        doc["roles"] = [dict(r) for r in cur.fetchall()]

    conn.close()
    return {"success": True, "documents": docs}


@app.get("/api/documents/{doc_id}/chunks")
def get_document_chunks(doc_id: int, _admin: dict = Depends(get_current_admin)):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, title, filename, file_type, total_chunks FROM documents WHERE id = ?", (doc_id,))
    doc = cur.fetchone()
    if not doc:
        conn.close()
        raise HTTPException(status_code=404, detail="Dokumen tidak ditemukan.")

    cur.execute(
        "SELECT chunk_index, text FROM document_chunks WHERE document_id = ? ORDER BY chunk_index ASC",
        (doc_id,),
    )
    chunks = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {"success": True, "document": dict(doc), "chunks": chunks}


@app.post("/api/documents/upload", status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(""),
    role_ids: str = Form(...),
    _admin: dict = Depends(get_current_admin),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="File wajib dipilih.")

    try:
        parsed_ids: List[int] = (
            json.loads(role_ids) if role_ids.strip().startswith("[")
            else [int(x.strip()) for x in role_ids.split(",") if x.strip()]
        )
    except Exception:
        raise HTTPException(status_code=400, detail="Format role_ids tidak valid.")

    if not parsed_ids:
        raise HTTPException(status_code=400, detail="Pilih minimal satu role untuk dokumen ini.")

    file_bytes = await file.read()
    try:
        extracted_text = extract_text_from_bytes(file_bytes, file.filename)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))

    if not extracted_text:
        raise HTTPException(status_code=400, detail="Teks tidak dapat diekstrak dari dokumen ini.")

    chunks = chunk_text(extracted_text)
    if not chunks:
        raise HTTPException(status_code=400, detail="Dokumen tidak menghasilkan chunk teks.")

    safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", file.filename)
    stored_filename = f"{int(time.time())}_{safe_name}"
    (UPLOAD_DIR / stored_filename).write_bytes(file_bytes)

    doc_title = title.strip() or Path(file.filename).stem
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "txt"
    now = datetime.now(timezone.utc).isoformat()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "INSERT INTO documents (title, filename, file_type, total_chunks, uploaded_at) VALUES (?, ?, ?, ?, ?)",
        (doc_title, stored_filename, ext, len(chunks), now),
    )
    doc_id = cur.lastrowid

    for rid in parsed_ids:
        cur.execute("SELECT id FROM roles WHERE id = ?", (rid,))
        if cur.fetchone():
            cur.execute(
                "INSERT OR IGNORE INTO document_roles (document_id, role_id) VALUES (?, ?)",
                (doc_id, rid),
            )

    for idx, ch in enumerate(chunks):
        emb = generate_embedding(ch)
        cur.execute(
            "INSERT INTO document_chunks (document_id, chunk_index, text, embedding_json) VALUES (?, ?, ?, ?)",
            (doc_id, idx, ch, json.dumps(emb)),
        )

    conn.commit()
    conn.close()

    return {
        "success": True,
        "message": f"Dokumen '{doc_title}' berhasil diunggah ({len(chunks)} chunks).",
        "document_id": doc_id,
    }


@app.patch("/api/documents/{doc_id}/roles")
def update_document_roles(doc_id: int, payload: DocumentRolesUpdateRequest, _admin: dict = Depends(get_current_admin)):
    """Update the roles that can access a document."""
    if not payload.role_ids:
        raise HTTPException(status_code=400, detail="Pilih minimal satu role.")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, title FROM documents WHERE id = ?", (doc_id,))
    doc = cur.fetchone()
    if not doc:
        conn.close()
        raise HTTPException(status_code=404, detail="Dokumen tidak ditemukan.")

    # Delete existing role assignments
    cur.execute("DELETE FROM document_roles WHERE document_id = ?", (doc_id,))

    # Insert new assignments
    for rid in payload.role_ids:
        cur.execute("SELECT id FROM roles WHERE id = ?", (rid,))
        if cur.fetchone():
            cur.execute(
                "INSERT OR IGNORE INTO document_roles (document_id, role_id) VALUES (?, ?)",
                (doc_id, rid),
            )

    conn.commit()
    conn.close()
    return {"success": True, "message": f"Role akses dokumen '{doc['title']}' berhasil diperbarui."}


@app.patch("/api/documents/{doc_id}/toggle")
def toggle_document_status(doc_id: int, _admin: dict = Depends(get_current_admin)):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, title, is_active FROM documents WHERE id = ?", (doc_id,))
    doc = cur.fetchone()
    if not doc:
        conn.close()
        raise HTTPException(status_code=404, detail="Dokumen tidak ditemukan.")

    new_status = 0 if doc["is_active"] else 1
    cur.execute("UPDATE documents SET is_active = ? WHERE id = ?", (new_status, doc_id))
    conn.commit()
    conn.close()

    state_label = "diaktifkan" if new_status == 1 else "dinonaktifkan"
    return {
        "success": True,
        "is_active": bool(new_status),
        "message": f"Dokumen '{doc['title']}' berhasil {state_label}.",
    }


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: int, _admin: dict = Depends(get_current_admin)):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, filename, title FROM documents WHERE id = ?", (doc_id,))
    doc = cur.fetchone()
    if not doc:
        conn.close()
        raise HTTPException(status_code=404, detail="Dokumen tidak ditemukan.")

    cur.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    conn.commit()
    conn.close()

    file_path = UPLOAD_DIR / doc["filename"]
    if file_path.exists():
        file_path.unlink(missing_ok=True)

    return {"success": True, "message": f"Dokumen '{doc['title']}' berhasil dihapus."}


# ---------- Chat Route (Public, Role-Filtered) ----------

@app.post("/api/chat")
def chat_with_rag(payload: ChatRequest):
    question = payload.question.strip()
    role_name = payload.role.strip().lower()

    if not question:
        raise HTTPException(status_code=400, detail="Pertanyaan tidak boleh kosong.")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM roles WHERE LOWER(name) = LOWER(?)", (role_name,))
    role_row = cur.fetchone()
    conn.close()

    if not role_row:
        raise HTTPException(status_code=404, detail=f"Role '{role_name}' tidak ditemukan.")

    relevant_chunks = search_chunks_by_role(question, role_row["name"], top_k=7, min_score=0.16)
    result = generate_answer(question, role_row["name"], relevant_chunks)

    return {
        "success": True,
        "role": role_row["name"],
        "answer": result["answer"],
        "sources": result["sources"],
    }


def _parse_duration_seconds(dur: str) -> float:
    if not dur:
        return 0.0
    total = 0.0
    for val, unit in re.findall(r"(\d+(?:\.\d+)?)(ms|h|m|s)", dur.lower()):
        num = float(val)
        if unit == "h":
            total += num * 3600
        elif unit == "m":
            total += num * 60
        elif unit == "s":
            total += num
        elif unit == "ms":
            total += num / 1000.0
    return total


def _format_remaining_duration(seconds: float) -> str:
    if seconds <= 0:
        return "Sudah reset"
    secs = int(round(seconds))
    if secs < 60:
        return f"{secs}d"
    mins, rem_s = divmod(secs, 60)
    if mins < 60:
        return f"{mins}m {rem_s}d" if rem_s else f"{mins}m"
    hours, rem_m = divmod(mins, 60)
    return f"{hours}j {rem_m}m"


@app.get("/api/admin/groq-quota")
def get_groq_quota(_admin: dict = Depends(get_current_admin)):
    load_dotenv(override=True)
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    configured_model = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
    has_api_key = bool(api_key and api_key not in ("gsk_masukkan_api_key_groq_anda_di_sini", "your_groq_api_key_here"))

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT model, limit_requests, remaining_requests, reset_requests,
               limit_tokens, remaining_tokens, reset_tokens, created_at
        FROM groq_usage_logs
        WHERE limit_requests IS NOT NULL OR limit_tokens IS NOT NULL
        ORDER BY id DESC
        LIMIT 1
        """
    )
    latest_row = cur.fetchone()
    latest = dict(latest_row) if latest_row else None

    if latest:
        try:
            recorded_at = datetime.fromisoformat(latest["created_at"])
            elapsed = max(0.0, (datetime.now(timezone.utc) - recorded_at).total_seconds())
        except Exception:
            elapsed = 0.0

        req_reset_sec = _parse_duration_seconds(latest.get("reset_requests", ""))
        req_rem_sec = max(0.0, req_reset_sec - elapsed)
        if latest.get("limit_requests") and req_reset_sec > 0 and req_rem_sec <= 0:
            latest["remaining_requests"] = latest["limit_requests"]
            latest["reset_requests_label"] = "Sudah reset"
        else:
            latest["reset_requests_label"] = _format_remaining_duration(req_rem_sec) if req_reset_sec > 0 else "-"

        tok_reset_sec = _parse_duration_seconds(latest.get("reset_tokens", ""))
        tok_rem_sec = max(0.0, tok_reset_sec - elapsed)
        if latest.get("limit_tokens") and tok_reset_sec > 0 and tok_rem_sec <= 0:
            latest["remaining_tokens"] = latest["limit_tokens"]
            latest["reset_tokens_label"] = "Sudah reset"
        else:
            latest["reset_tokens_label"] = _format_remaining_duration(tok_rem_sec) if tok_reset_sec > 0 else "-"

    today_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cur.execute(
        """
        SELECT COUNT(*) AS requests_today,
               COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens_today,
               COALESCE(SUM(completion_tokens), 0) AS completion_tokens_today,
               COALESCE(SUM(total_tokens), 0) AS total_tokens_today
        FROM groq_usage_logs
        WHERE created_at LIKE ?
        """,
        (f"{today_prefix}%",),
    )
    today_row = dict(cur.fetchone())

    cur.execute(
        """
        SELECT COUNT(*) AS total_requests,
               COALESCE(SUM(total_tokens), 0) AS total_tokens
        FROM groq_usage_logs
        """
    )
    total_row = dict(cur.fetchone())

    cur.execute(
        """
        SELECT id, model, prompt_tokens, completion_tokens, total_tokens, status, created_at
        FROM groq_usage_logs
        ORDER BY id DESC
        LIMIT 10
        """
    )
    recent_logs = [dict(r) for r in cur.fetchall()]
    conn.close()

    return {
        "success": True,
        "has_api_key": has_api_key,
        "configured_model": configured_model,
        "latest": latest,
        "today": today_row,
        "total": total_row,
        "recent_logs": recent_logs,
    }


@app.get("/api/public/documents/{doc_id}")
def get_public_document(doc_id: int, role: str = "mahasiswa"):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT d.id, d.title, d.filename, d.file_type, d.total_chunks
        FROM documents d
        JOIN document_roles dr ON dr.document_id = d.id
        JOIN roles r ON r.id = dr.role_id
        WHERE d.id = ? AND LOWER(r.name) = LOWER(?) AND d.is_active = 1
        """,
        (doc_id, role.strip().lower()),
    )
    doc = cur.fetchone()
    if not doc:
        conn.close()
        raise HTTPException(status_code=404, detail="Dokumen tidak ditemukan atau tidak dapat diakses dengan role ini.")

    file_path = UPLOAD_DIR / doc["filename"]
    full_text = ""
    if file_path.exists():
        try:
            full_text = extract_text_from_bytes(file_path.read_bytes(), doc["filename"])
        except Exception:
            full_text = ""

    if not full_text:
        cur.execute(
            "SELECT text FROM document_chunks WHERE document_id = ? ORDER BY chunk_index ASC",
            (doc_id,),
        )
        full_text = "\n\n".join(r["text"] for r in cur.fetchall())

    conn.close()

    return {
        "success": True,
        "document": dict(doc),
        "url": f"/uploads/{doc['filename']}",
        "content": full_text,
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port)

