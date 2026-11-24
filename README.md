# Custom AI Chatbot RAG Berbasis Role (RBAC) - FastAPI & Railway Deployment

Aplikasi **Custom AI Chatbot RAG Berbasis Role** yang dibangun menggunakan **Python FastAPI**, **SQLite**, **PyJWT**, dan **Groq Cloud LLM**, serta siap dideploy ke **Railway**. Sistem ini menerapkan prinsip **Role-Based Access Control (RBAC)** pada tingkat dokumen dan mesin RAG.

---

## Fitur Utama

- **Role-Based Access Control (RBAC) pada RAG**:
  - Panel Admin dilengkapi **Manajemen Role** untuk menambah dan menghapus role baru (role default: `mahasiswa` dan `dosen`).
  - Pemilihan role akses dokumen saat proses upload menggunakan checkbox multi-role.
  - Fitur ubah/edit role dokumen langsung dari daftar dokumen tanpa perlu upload ulang.
- **Pemisahan Akses Dokumen Sensitif**:
  - Dokumen sensitif seperti `Panduan_Internal_Dosen.txt` (kebijakan penilaian, remediasi/ujian susulan, rasio bimbingan TA, aturan BKD) hanya dapat diakses oleh role `dosen`.
  - Saat chatbot ditanya menggunakan role `mahasiswa`, dokumen internal dosen **tidak akan pernah muncul atau diakses** oleh mesin pencari RAG.
  - Saat chatbot ditanya menggunakan role `dosen`, chatbot menjawab akurat lengkap beserta sumber referensi dokumen tersebut.
- **Pencarian Hybrid (Dense Embedding + Lexical Scoring)**:
  - Menggunakan cosine similarity (embedding 384-dimensi) dikombinasikan dengan pembobotan kata kunci dan frasa (*lexical bonus*) untuk akurasi pencarian konteks.
- **Integrasi Groq Cloud LLM**:
  - Menggunakan model Groq (`qwen/qwen3.8-27b`) dengan latensi ultra rendah, dilengkapi pencatatan kuota API (RPD/TPM) dan token usage di database.
- **Ekstraksi Multi-Format**:
  - Mendukung otomatisasi ekstraksi file PDF, DOCX, XLSX, CSV, dan TXT dengan *table-aware chunking*.
- **Antarmuka Web Modern & Responsif**:
  - Halaman publik (`/`) dilengkapi **Role Selector Tabs (🎓 Mahasiswa / 👨‍🏫 Dosen)** interaktif, kartu sambutan, dan modal pratinjau dokumen sumber dengan verifikasi akses role.
  - Dashboard Admin (`/admin`) dengan otentikasi JWT, tab Knowledge Base, tab Manajemen Role, modal popup Chunks, Chatbot tester multi-role, dan tracking kuota Groq.
- **Deployment-Ready ke Cloud (Railway)**:
  - Dilengkapi `Dockerfile`, `railway.json`, `Procfile`, dan panduan deployment lengkap.

---

## Struktur Folder

```text
Deployment-Fast-API-ke-Railway_AI/
├── app/
│   ├── __init__.py
│   ├── auth.py          # Autentikasi Admin, hashing PBKDF2 & token JWT
│   ├── database.py      # SQLite schema, koneksi, & seeding role (mahasiswa, dosen)
│   ├── extractor.py     # Parser PDF, DOCX, XLSX, CSV, TXT
│   ├── main.py          # REST API FastAPI, role management & document RBAC
│   └── rag.py           # Mesin RAG (chunking, similarity search by role, Groq LLM)
├── dataset/             # File referensi akademik default (PDF & TXT)
│   ├── Alur_Menghubungi_SSC.txt
│   ├── Panduan_Internal_Dosen.txt   # Dokumen khusus role dosen
│   ├── SK-TAK-2022.pdf
│   ├── SK_TAK_TUNC_2025.pdf
│   └── SSC_Operating_Hours.txt
├── static/
│   ├── index.html       # Antarmuka Chatbot Publik dengan Pemilih Role
│   └── admin.html       # Dashboard Admin (Knowledge Base & Manajemen Role)
├── uploads/             # Direktori penyimpanan dokumen
├── .dockerignore
├── .env.example         # Template konfigurasi environment
├── .gitignore
├── Dockerfile           # Konfigurasi container untuk Railway
├── Procfile
├── railway.json         # Konfigurasi deploy Railway
├── requirements.txt
└── README.md
```

---

## Panduan Menjalankan Secara Lokal

### 1. Kloning Repositori
```bash
git clone https://github.com/DesykaWidya17/Deployment-Fast-API-ke-Railway_AI.git
cd Deployment-Fast-API-ke-Railway_AI
```

### 2. Buat & Aktifkan Virtual Environment
**Windows (PowerShell / Command Prompt):**
```bash
python -m venv venv
venv\Scripts\activate
```

**macOS / Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Pasang Dependensi
```bash
pip install -r requirements.txt
```

### 4. Konfigurasi Environment (`.env`)
Salin file `.env.example` menjadi `.env`:
```bash
cp .env.example .env
```
Isi variabel berikut:
```ini
GROQ_API_KEY=gsk_masukkan_api_key_groq_anda_di_sini
GROQ_MODEL=qwen/qwen3.8-27b
JWT_SECRET=modul2ai-super-secret-jwt-key-2026
ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin123
DB_PATH=modul2ai.db
```

### 5. Jalankan Server
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## Panduan Deployment ke Railway

1. **Push Proyek ke GitHub**:
   ```bash
   git add .
   git commit -m "Deployment: FastAPI Chatbot RAG RBAC ke Railway"
   git push origin main
   ```

2. **Buka Railway Dashboard**:
   - Buka [railway.com](https://railway.com/) dan login menggunakan akun GitHub.
   - Klik **New Project** > **Deploy from GitHub repo**.
   - Pilih repositori `Deployment-Fast-API-ke-Railway_AI`.

3. **Konfigurasi Environment Variables di Railway**:
   Masuk ke tab **Variables** pada dashboard Railway dan tambahkan:
   - `GROQ_API_KEY` = `gsk_...` (API Key Groq aktif Anda)
   - `GROQ_MODEL` = `qwen/qwen3.8-27b`
   - `JWT_SECRET` = `modul2ai-super-secret-jwt-key-2026`
   - `ADMIN_USERNAME` = `admin`
   - `ADMIN_PASSWORD` = `admin123`
   - `DB_PATH` = `modul2ai.db`

4. **Generate Public Domain**:
   - Di tab **Settings** > **Networking**, klik **Generate Domain**.
   - Akses aplikasi melalui URL Railway yang diberikan (contoh: `https://xxxx.up.railway.app`).

---

## Pengujian RBAC (Role-Based Access Control)

1. **Uji Akses Role Mahasiswa**:
   - Buka halaman Chatbot publik, pilih tab **🎓 Mahasiswa**.
   - Tanyakan: *"Bagaimana kebijakan penilaian dan komponen nilai akhir mahasiswa?"* atau *"Berapa rasio bimbingan tugas akhir per dosen?"*
   - **Hasil**: Chatbot tidak menemukan dokumen `Panduan Internal Dosen`, dan hanya memberikan jawaban umum atau menyatakan informasi belum tersedia.

2. **Uji Akses Role Dosen**:
   - Pilih tab **👨‍🏫 Dosen**.
   - Ajukan pertanyaan yang sama: *"Bagaimana kebijakan penilaian dan komponen nilai akhir mahasiswa?"*
   - **Hasil**: Chatbot menjawab secara lengkap dengan rincian persentase (UTS 30%, UAS 40%, Tugas 20%, Kehadiran 10%) dan menyertakan sumber referensi **Panduan Internal Dosen**.

3. **Uji Panel Admin**:
   - Akses `/admin` dan login (`admin` / `admin123`).
   - Buka tab **Manajemen Role**: Anda dapat menambahkan role baru (misal: `tendik`, `alumni`) atau menghapus role kustom.
   - Buka tab **Knowledge Base**: Klik tombol **Edit Role** pada dokumen untuk mengubah hak akses role secara dinamis.
