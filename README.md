# O'zbekiston Davlat Tarixi Muzeyi — Audio Guide

A QR-code audio guide web application for the State History Museum of Uzbekistan.
Supports three languages (Uzbek, Russian, English) with AI-powered TTS narration via the Aisha API.

---

## Project Structure

```
museum-guide/
├── backend/
│   ├── main.py        # FastAPI server
│   └── .env           # API key (do not commit)
├── frontend/
│   └── index.html     # Single-page app
└── README.md
```

---

## Backend Setup

### 1. Install dependencies

```bash
cd backend
pip install fastapi uvicorn httpx python-multipart python-dotenv
```

### 2. Configure API key

Open `backend/.env` and set your Aisha API key:

```
AISHA_API_KEY=your_key_here
```

The default key is already filled in. To get a new key visit https://aisha.group.

### 3. Start the server

```bash
cd backend
uvicorn main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`.

- `GET  /api/exhibits` — returns all 5 exhibit objects
- `POST /api/tts`      — converts exhibit text to speech, returns `{ audio_url }`

---

## Frontend Setup

No build step required — it is a single HTML file.

1. Make sure the backend is running on port 8000.
2. Open `frontend/index.html` directly in any modern browser:
   - Double-click the file, **or**
   - Serve it with a simple server to avoid CORS issues with `file://` origins:
     ```bash
     cd frontend
     python -m http.server 3000
     # then open http://localhost:3000
     ```

---

## Changing the API Key

Edit `backend/.env`:

```
AISHA_API_KEY=NYwvH84s.NewKeyHere
```

Restart the backend server after saving.

---

## QR Code Tips

### Option A — One general QR for the whole guide

Generate a QR code pointing to `http://<your-server-ip>:3000/index.html`
(or your hosted URL). Place it at the museum entrance.

### Option B — Per-exhibit QR codes

You can extend the frontend to auto-open a specific exhibit by passing a URL
parameter, e.g. `index.html?exhibit=3`. Then add to the JS init:

```js
const params = new URLSearchParams(location.search);
const id = parseInt(params.get('exhibit'));
if (id) {
  await loadExhibits();
  selectLanguage('uz');          // or detect browser language
  const ex = exhibits.find(e => e.id === id);
  if (ex) openExhibit(ex);
}
```

Generate a QR code per exhibit pointing to `index.html?exhibit=1`, etc.
Place each QR next to the physical exhibit.

### Free QR generators

- https://qr.io
- https://www.qrcode-monkey.com

---

## Language Support

| Language | TTS Model        |
|----------|-----------------|
| Uzbek    | Gulnoza (Aisha) |
| Russian  | Aisha default   |
| English  | Aisha default   |
