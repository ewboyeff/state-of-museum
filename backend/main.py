from fastapi import FastAPI, HTTPException, Depends, Header, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List
from collections import defaultdict
import httpx
import asyncio
import json
import os
import secrets
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Museum Audio Guide API")

# CORS — ALLOWED_ORIGINS env orqali sozlash mumkin (production da domenni yozing)
_raw_origins = os.getenv("ALLOWED_ORIGINS", "*")
_origins = ["*"] if _raw_origins == "*" else [o.strip() for o in _raw_origins.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)

AISHA_BASE_URL  = "https://back.aisha.group"
AISHA_API_KEY   = os.getenv("AISHA_API_KEY")
ADMIN_USERNAME  = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD  = os.getenv("ADMIN_PASSWORD")
FRONTEND_URL    = os.getenv("FRONTEND_URL", "")
if not ADMIN_PASSWORD:
    raise RuntimeError("ADMIN_PASSWORD muhit o'zgaruvchisi .env da sozlanmagan!")

# ── Rate limiter (like endpoint uchun) ───────────────────────
_like_rate: dict = defaultdict(list)

def _check_like_rate(ip: str) -> bool:
    now = time.time()
    _like_rate[ip] = [t for t in _like_rate[ip] if now - t < 60]
    if len(_like_rate[ip]) >= 10:
        return False
    _like_rate[ip].append(now)
    return True

# ── Data directory ────────────────────────────────────────────
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

BOLIMLAR_FILE    = DATA_DIR / "bolimlar.json"
VITRINAS_FILE    = DATA_DIR / "vitrinas.json"
EKSPONATLAR_FILE = DATA_DIR / "eksponatlar.json"
LIKES_FILE       = DATA_DIR / "likes.json"
VISITS_FILE      = DATA_DIR / "visits.json"

UPLOAD_DIR = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

def _load_json(path: Path) -> list:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except Exception:
        return []

def _load_json_dict(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def _save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

bolimlar_db: list    = _load_json(BOLIMLAR_FILE)
vitrinas_db: list    = _load_json(VITRINAS_FILE)
eksponatlar_db: list = _load_json(EKSPONATLAR_FILE)
likes_db: dict       = _load_json_dict(LIKES_FILE)
visits_db: dict      = _load_json_dict(VISITS_FILE)  # {"2026-06-02": {"views":{"1":5}, "audio":{"1":3}}}

# ── Admin auth (token-based session) ─────────────────────────
admin_sessions: dict = {}  # token -> expiry (unix timestamp)

def _new_token() -> str:
    token = secrets.token_urlsafe(32)
    admin_sessions[token] = time.time() + 86400  # 24 hours
    return token

def _verify_token(token: str) -> bool:
    exp = admin_sessions.get(token)
    if not exp:
        return False
    if time.time() > exp:
        admin_sessions.pop(token, None)
        return False
    return True

def require_admin(authorization: str = Header(default="")):
    token = authorization.removeprefix("Bearer ").strip()
    if not _verify_token(token):
        raise HTTPException(status_code=401, detail="Unauthorized")

# ── Server-side audio cache ───────────────────────────────────
CACHE_FILE = Path(__file__).parent / "audio_cache.json"

def _load_cache() -> dict:
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8")) if CACHE_FILE.exists() else {}
    except Exception:
        return {}

def _save_cache(cache: dict) -> None:
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

audio_cache: dict = _load_cache()
print(f"Audio cache loaded: {len(audio_cache)} entries")


class TTSRequest(BaseModel):
    transcript: str
    language: str
    exhibit_id: Optional[int] = None   # used as cache key
    mood: str = "Neutral"
    speed: float = 1.0


EXHIBITS = [
    {
        "id": 1,
        "emoji": "🪨",
        "era": {"uz": "TOSH DAVRI", "ru": "КАМЕННЫЙ ВЕК", "en": "STONE AGE"},
        "name": {"uz": "Tosh bolta", "ru": "Каменный топор", "en": "Stone Axe"},
        "date": {"uz": "M.av. 8000–3000 yil", "ru": "8000–3000 до н.э.", "en": "8000–3000 BC"},
        "text": {
            "uz": "Bu tosh bolta miloddan avvalgi 8000 yildan 3000 yilgacha bo'lgan tosh davrida O'rta Osiyo hududida yashovchi qadimgi odamlar tomonidan keng qo'llanilgan. Kremens va chaqmoqtosh kabi qattiq toshlar qo'lda ishlanib, o'tkir qirra hosil qilingan. Ustalar toshni boshqa tosh bilan urib, kerakli shakl va o'tkir tomonni yaratgan. Bu asbob asosan ov paytida hayvonlarni so'yish, yog'och kesish va tuproq qazishda foydalanilgan. Tosh boltaning sopiga yog'och yoki suyak bog'langan, bu esa uni tutish va ishlatishni osonlashtirgan. Bunday tosh qurollar O'rta Osiyoning Samarqand, Toshkent va Farg'ona vodiysi hududlarida topilgan. Bu topilma qadimgi odamlarning aql-zakovati va hunarmandchilik mahoratini yaqqol namoyon etadi.",
            "ru": "Этот каменный топор широко использовался древними людьми Средней Азии в период каменного века — от восьми тысяч до трёх тысяч лет до нашей эры. Кремниевые и кварцевые камни обрабатывались вручную путём откалывания, чтобы создать острый рабочий край. Мастера умело придавали камню нужную форму, используя другой твёрдый камень в качестве инструмента. Топор применялся для охоты, разделки туш животных, рубки деревьев и обработки почвы. Деревянная или костяная рукоять привязывалась к каменному лезвию с помощью жил или растительных волокон. Подобные орудия были найдены на территории Самарканда, Ташкента и Ферганской долины. Эта находка ярко свидетельствует о высоком интеллекте и мастерстве древних людей Центральной Азии.",
            "en": "This stone axe was widely used by ancient people of Central Asia during the Stone Age, from eight thousand to three thousand years before the common era. Flint and quartz stones were hand-knapped by striking them with another hard stone to create a sharp working edge. Skilled craftsmen shaped the stone precisely to produce the desired form and cutting surface. The axe was used for hunting, butchering animals, chopping wood, and breaking ground. A wooden or bone handle was attached to the stone blade using sinew or plant fibres. Similar tools have been discovered in the regions of Samarkand, Tashkent, and the Fergana Valley. This artefact vividly demonstrates the intelligence and craftsmanship of the ancient peoples of Central Asia.",
        },
        "facts": {
            "uz": [["Davr", "Tosh davri"], ["Yosh", "~10,000 yil"], ["Material", "Kremens"], ["Topilgan", "Samarqand"]],
            "ru": [["Период", "Каменный век"], ["Возраст", "~10 000 лет"], ["Материал", "Кремний"], ["Найден", "Самарканд"]],
            "en": [["Period", "Stone Age"], ["Age", "~10,000 yrs"], ["Material", "Flint"], ["Found in", "Samarkand"]],
        },
    },
    {
        "id": 2,
        "emoji": "🏺",
        "era": {"uz": "BRONZA DAVRI", "ru": "БРОНЗОВЫЙ ВЕК", "en": "BRONZE AGE"},
        "name": {"uz": "Sopol idish", "ru": "Глиняный сосуд", "en": "Clay Vessel"},
        "date": {"uz": "M.av. 3000–1200 yil", "ru": "3000–1200 до н.э.", "en": "3000–1200 BC"},
        "text": {
            "uz": "Bu sopol idish bronza davrida kulolchilik san'atining rivojlanganini ko'rsatadi. Geometrik naqshlar bilan bezatilgan. Asosan don va suv saqlash uchun ishlatilgan.",
            "ru": "Этот сосуд свидетельствует о развитии гончарства в бронзовом веке. Украшен геометрическими узорами. Использовался для хранения зерна и воды.",
            "en": "This vessel demonstrates pottery art development in the Bronze Age. Decorated with geometric patterns. Used for storing grain and water.",
        },
        "facts": {
            "uz": [["Davr", "Bronza davri"], ["Yosh", "~4,500 yil"], ["Material", "Sopol"], ["Topilgan", "Buxoro"]],
            "ru": [["Период", "Бронзовый век"], ["Возраст", "~4 500 лет"], ["Материал", "Глина"], ["Найден", "Бухара"]],
            "en": [["Period", "Bronze Age"], ["Age", "~4,500 yrs"], ["Material", "Clay"], ["Found in", "Bukhara"]],
        },
    },
    {
        "id": 3,
        "emoji": "⚔️",
        "era": {"uz": "TEMIR DAVRI", "ru": "ЖЕЛЕЗНЫЙ ВЕК", "en": "IRON AGE"},
        "name": {"uz": "Temir qilich", "ru": "Железный меч", "en": "Iron Sword"},
        "date": {"uz": "M.av. 1200–300 yil", "ru": "1200–300 до н.э.", "en": "1200–300 BC"},
        "text": {
            "uz": "Bu temir qilich O'rta Osiyodagi dastlabki metallurgiya rivojlanishini ifodalaydi. Nozik o'ymakorlik bilan bezatilgan. Yuqori toifali jangchilar uchun yaratilgan.",
            "ru": "Меч отражает раннее развитие металлургии в Средней Азии. Украшен тонкой резьбой. Изготовлен для воинов высшего ранга.",
            "en": "This sword reflects early metallurgy development in Central Asia. Decorated with fine carvings. Crafted for high-ranking warriors.",
        },
        "facts": {
            "uz": [["Davr", "Temir davri"], ["Yosh", "~2,800 yil"], ["Material", "Temir"], ["Topilgan", "Farg'ona"]],
            "ru": [["Период", "Железный век"], ["Возраст", "~2 800 лет"], ["Материал", "Железо"], ["Найден", "Фергана"]],
            "en": [["Period", "Iron Age"], ["Age", "~2,800 yrs"], ["Material", "Iron"], ["Found in", "Fergana"]],
        },
    },
    {
        "id": 4,
        "emoji": "🪙",
        "era": {"uz": "YUNON-BAQTRIYA", "ru": "ГРЕКО-БАКТРИЯ", "en": "GRECO-BACTRIAN"},
        "name": {"uz": "Oltin tanga", "ru": "Золотая монета", "en": "Gold Coin"},
        "date": {"uz": "M.av. 250–125 yil", "ru": "250–125 до н.э.", "en": "250–125 BC"},
        "text": {
            "uz": "Bu oltin tanga Yunon-Baqtriya shohligi davrida zarb etilgan. Tangada yunoncha yozuv va shoh tasviri tushirilgan. Ipak yo'lida muhim to'lov vositasi bo'lgan.",
            "ru": "Монета отчеканена в период Греко-Бактрийского царства. На ней изображены греческая надпись и портрет царя. Была важным средством оплаты на Шёлковом пути.",
            "en": "This coin was minted during the Greco-Bactrian Kingdom. Features a Greek inscription and king's portrait. Was an important payment on the Silk Road.",
        },
        "facts": {
            "uz": [["Davr", "M.av. III asr"], ["Yosh", "~2,200 yil"], ["Material", "Oltin"], ["Topilgan", "Termiz"]],
            "ru": [["Период", "III в. до н.э."], ["Возраст", "~2 200 лет"], ["Материал", "Золото"], ["Найден", "Термез"]],
            "en": [["Period", "3rd c. BC"], ["Age", "~2,200 yrs"], ["Material", "Gold"], ["Found in", "Termez"]],
        },
    },
    {
        "id": 5,
        "emoji": "📜",
        "era": {"uz": "O'RTA ASRLAR", "ru": "СРЕДНИЕ ВЕКА", "en": "MIDDLE AGES"},
        "name": {"uz": "Qo'lyozma", "ru": "Рукопись", "en": "Manuscript"},
        "date": {"uz": "IX–XII asr", "ru": "IX–XII век", "en": "9th–12th century"},
        "text": {
            "uz": "Bu qo'lyozma O'rta Osiyo Islom oltin asrida yaratilgan. Al-Xorazmiy va Ibn Sino kabi buyuk olimlar shu davr vakillari. Tibbiyot, matematika va astronomiya bo'yicha bilimlarni jamlaydi.",
            "ru": "Рукопись создана в золотой век ислама Средней Азии. Аль-Хорезми и Ибн Сина — учёные этой эпохи. Содержит знания по медицине, математике и астрономии.",
            "en": "This manuscript was created during the Islamic Golden Age in Central Asia. Al-Khwarizmi and Ibn Sina were scholars of this era. Compiles knowledge in medicine, mathematics, and astronomy.",
        },
        "facts": {
            "uz": [["Davr", "Islom oltin asri"], ["Yosh", "~900 yil"], ["Material", "Pergament"], ["Topilgan", "Xiva"]],
            "ru": [["Период", "Золотой век ислама"], ["Возраст", "~900 лет"], ["Материал", "Пергамент"], ["Найден", "Хива"]],
            "en": [["Period", "Islamic Golden Age"], ["Age", "~900 yrs"], ["Material", "Parchment"], ["Found in", "Khiva"]],
        },
    },
]


@app.get("/api/config")
def get_config():
    return {"frontend_url": FRONTEND_URL}

@app.get("/api/exhibits")
def get_exhibits(vitrina_id: Optional[int] = None):
    # real data bor bo'lsa undan, yo'q bo'lsa demo EXHIBITS (vitrina filtersiz)
    if eksponatlar_db:
        active = eksponatlar_db
        if vitrina_id:
            active = [e for e in active if e.get("vitrina_id") == vitrina_id]
    else:
        active = EXHIBITS  # demo: vitrina filter ishlamaydi, lekin hech bo'lmasa ko'rinadi
    return [{**ex, "likes": likes_db.get(str(ex["id"]), 0)} for ex in active]

@app.post("/api/exhibits/{exhibit_id}/like")
def like_exhibit(exhibit_id: int, request: Request):
    ip = request.client.host if request.client else "unknown"
    if not _check_like_rate(ip):
        raise HTTPException(429, "Juda ko'p so'rov. Bir daqiqa kutib turing.")
    key = str(exhibit_id)
    likes_db[key] = likes_db.get(key, 0) + 1
    _save_json(LIKES_FILE, likes_db)
    return {"ok": True, "likes": likes_db[key]}

@app.get("/api/admin/likes")
def get_admin_likes(_=Depends(require_admin)):
    active = eksponatlar_db if eksponatlar_db else EXHIBITS
    result = []
    for ex in active:
        result.append({
            "id":    ex["id"],
            "name":  ex.get("name", {}),
            "era":   ex.get("era", {}),
            "image_url": ex.get("image_url", ""),
            "likes": likes_db.get(str(ex["id"]), 0),
        })
    return sorted(result, key=lambda x: x["likes"], reverse=True)


@app.post("/api/tts")
async def text_to_speech(body: TTSRequest):
    # ── 1. Check server cache first ──────────────────────────
    cache_key = f"{body.exhibit_id}_{body.language}" if body.exhibit_id else None

    if cache_key and cache_key in audio_cache:
        print(f"Cache HIT: {cache_key}")
        return {"audio_url": audio_cache[cache_key], "cached": True}

    print(f"Cache MISS: {cache_key} — calling Aisha API")

    # ── 2. Call Aisha API ─────────────────────────────────────
    if not AISHA_API_KEY:
        raise HTTPException(status_code=500, detail="AISHA_API_KEY not configured")

    headers = {"X-Api-Key": AISHA_API_KEY}

    if body.language == "uz":
        data = {
            "transcript": body.transcript,
            "model": "Gulnoza",
            "mood": body.mood,
            "speed": str(body.speed),
        }
    elif body.language == "ru":
        data = {
            "transcript": body.transcript,
            "language": "ru",
            "speed": str(body.speed),
        }
    else:  # en
        data = {
            "transcript": body.transcript,
            "language": body.language,
        }

    # retry up to 3 times on 429
    response = None
    async with httpx.AsyncClient(timeout=30.0) as client:
        for attempt in range(3):
            response = await client.post(
                f"{AISHA_BASE_URL}/api/v1/tts/post/",
                headers=headers,
                data=data,
            )
            if response.status_code != 429:
                break
            print(f"Rate limited (attempt {attempt + 1}), retrying in 2s...")
            await asyncio.sleep(2)

    if response.status_code not in (200, 201):
        raise HTTPException(
            status_code=response.status_code,
            detail=f"Aisha TTS error: {response.text}",
        )

    result = response.json()
    print("Aisha response:", result)

    audio_url = (
        result.get("audio_path")
        or result.get("audio_url")
        or result.get("url")
        or result.get("path")
        or result.get("audio")
        or result.get("link")
        or result.get("file_url")
        or result.get("result")
    )

    if not audio_url:
        raise HTTPException(status_code=502, detail=f"No audio URL in response: {result}")

    if not str(audio_url).startswith("http"):
        audio_url = f"{AISHA_BASE_URL}{audio_url}"

    # ── 3. Save to server cache ───────────────────────────────
    if cache_key:
        audio_cache[cache_key] = audio_url
        _save_cache(audio_cache)
        print(f"Cache SAVED: {cache_key} → {audio_url}")

    return {"audio_url": audio_url, "cached": False}


# ── Cache status endpoint ─────────────────────────────────────
@app.get("/api/cache")
def get_cache_status():
    active = eksponatlar_db if eksponatlar_db else EXHIBITS
    total  = len(active) * 3
    return {
        "ready": len(audio_cache),
        "total": total,
        "percent": round(len(audio_cache) / total * 100) if total else 0,
        "entries": audio_cache,
    }


# ── Background cache warm-up ──────────────────────────────────
async def _call_tts(exhibit: dict, lang: str) -> Optional[str]:
    """Call Aisha API for one exhibit+language and return audio URL."""
    headers = {"X-Api-Key": AISHA_API_KEY}
    text_obj = exhibit.get("text", {})

    if lang == "uz":
        transcript = text_obj.get("uz") or text_obj.get("ru") or text_obj.get("en") or ""
        data = {"transcript": transcript, "model": "Gulnoza", "mood": "Neutral", "speed": "1.0"}
    elif lang == "ru":
        transcript = text_obj.get("ru") or text_obj.get("uz") or ""
        data = {"transcript": transcript, "language": "ru", "speed": "1.0"}
    else:
        transcript = text_obj.get("en") or text_obj.get("uz") or ""
        data = {"transcript": transcript, "language": "en"}

    if not transcript:
        print(f"[warm] Skip {exhibit.get('id')}_{lang}: no text")
        return None

    async with httpx.AsyncClient(timeout=40.0) as client:
        for attempt in range(3):
            r = await client.post(f"{AISHA_BASE_URL}/api/v1/tts/post/", headers=headers, data=data)
            if r.status_code != 429:
                break
            await asyncio.sleep(2 ** attempt)  # 1s, 2s, 4s exponential backoff

    if r.status_code not in (200, 201):
        print(f"[warm] Error {r.status_code} for {exhibit['id']}_{lang}: {r.text[:120]}")
        return None

    result = r.json()
    url = (result.get("audio_path") or result.get("audio_url") or result.get("url")
           or result.get("path") or result.get("audio"))
    if url and not url.startswith("http"):
        url = f"{AISHA_BASE_URL}{url}"
    return url


async def warm_cache():
    """Generate all missing exhibit×language audio files — 3 parallel workers."""
    if not AISHA_API_KEY:
        return

    active = eksponatlar_db if eksponatlar_db else EXHIBITS
    missing = [
        (ex, lg)
        for ex in active
        for lg in ("uz", "ru", "en")
        if f"{ex['id']}_{lg}" not in audio_cache
    ]

    if not missing:
        print(f"[warm] All {len(audio_cache)} audio files already cached ✓")
        return

    total = len(active) * 3
    print(f"[warm] Generating {len(missing)} missing files (3 parallel workers)...")

    sem = asyncio.Semaphore(3)  # max 3 concurrent Aisha requests

    async def _fetch_one(ex, lg):
        async with sem:
            key = f"{ex['id']}_{lg}"
            url = await _call_tts(ex, lg)
            if url:
                audio_cache[key] = url
                _save_cache(audio_cache)
                print(f"[warm] ✓ {key}")
            else:
                print(f"[warm] ✗ {key} failed")

    await asyncio.gather(*[_fetch_one(ex, lg) for ex, lg in missing])
    print(f"[warm] Done. Cache: {len(audio_cache)}/{total}")


@app.post("/api/cache/warm")
async def trigger_warm_cache(_=Depends(require_admin)):
    asyncio.create_task(warm_cache())
    return {"message": "Cache warm-up started in background. Check /api/cache for progress."}


# ══════════════════════════════════════════════════════════════
#  ADMIN API
# ══════════════════════════════════════════════════════════════

class TrackRequest(BaseModel):
    exhibit_id: int
    action: str = "view"  # "view" | "audio"

@app.post("/api/track")
def track_event(body: TrackRequest):
    today = datetime.now().strftime("%Y-%m-%d")
    if today not in visits_db:
        visits_db[today] = {"views": {}, "audio": {}}
    section = "audio" if body.action == "audio" else "views"
    key = str(body.exhibit_id)
    visits_db[today][section][key] = visits_db[today][section].get(key, 0) + 1
    _save_json(VISITS_FILE, visits_db)
    return {"ok": True}

@app.get("/api/admin/stats/visits")
def get_visit_stats(_=Depends(require_admin)):
    today = datetime.now().strftime("%Y-%m-%d")
    today_data = visits_db.get(today, {"views": {}, "audio": {}})
    all_views: dict = {}
    all_audio: dict = {}
    for day in visits_db.values():
        for k, v in day.get("views", {}).items():
            all_views[k] = all_views.get(k, 0) + v
        for k, v in day.get("audio", {}).items():
            all_audio[k] = all_audio.get(k, 0) + v
    active = eksponatlar_db if eksponatlar_db else EXHIBITS
    ex_map = {str(e["id"]): e for e in active}
    def make_top(counts):
        return sorted([
            {"id": int(k), "count": v, "name": ex_map.get(k, {}).get("name", {})}
            for k, v in counts.items()
        ], key=lambda x: x["count"], reverse=True)[:5]
    return {
        "today_views": sum(today_data["views"].values()),
        "today_audio": sum(today_data["audio"].values()),
        "top_viewed":  make_top(all_views),
        "top_audio":   make_top(all_audio),
    }

class LoginRequest(BaseModel):
    username: str
    password: str

class BolimNomi(BaseModel):
    uz: str = ""
    ru: str = ""
    en: str = ""

class BolimRequest(BaseModel):
    nomi: BolimNomi
    tavsif: BolimNomi = BolimNomi()
    masul_ism: str = ""
    masul_familya: str = ""
    masul_tel: str = ""

class VitrinaNomi(BaseModel):
    uz: str = ""
    ru: str = ""
    en: str = ""

class VitrinaRequest(BaseModel):
    bolim_id: int
    nomi: VitrinaNomi
    joy: str = ""

class EksponatRequest(BaseModel):
    vitrina_id: int
    bolim_id: int
    image_url: str = ""
    era:  BolimNomi = BolimNomi()
    name: BolimNomi = BolimNomi()
    date: BolimNomi = BolimNomi()
    text: BolimNomi = BolimNomi()
    tartib: int = 0

@app.post("/api/admin/login")
def admin_login(body: LoginRequest):
    if body.username != ADMIN_USERNAME or body.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Login yoki parol noto'g'ri")
    return {"token": _new_token(), "username": ADMIN_USERNAME}

@app.post("/api/admin/logout")
def admin_logout(authorization: str = Header(default="")):
    token = authorization.removeprefix("Bearer ").strip()
    admin_sessions.pop(token, None)
    return {"ok": True}

@app.get("/api/admin/stats")
def admin_stats(_=Depends(require_admin)):
    return {
        "bolimlar":    len(bolimlar_db),
        "vitrinalar":  len(vitrinas_db),
        "eksponatlar": len(eksponatlar_db),
        "audio_cache": len(audio_cache),
    }

@app.get("/api/admin/cache")
def admin_cache_list(_=Depends(require_admin)):
    active = eksponatlar_db if eksponatlar_db else EXHIBITS
    ex_map = {str(e["id"]): e for e in active}
    entries = []
    for k, v in audio_cache.items():
        parts = k.rsplit("_", 1)
        ex_id  = parts[0] if len(parts) == 2 else k
        lang   = parts[1] if len(parts) == 2 else ""
        ex     = ex_map.get(ex_id, {})
        entries.append({
            "key":      k,
            "url":      v,
            "lang":     lang,
            "ex_id":    ex_id,
            "ex_name":  ex.get("name", {}).get("uz") or ex.get("name", {}).get("ru") or f"#{ex_id}",
            "ex_era":   ex.get("era",  {}).get("uz", ""),
        })
    entries.sort(key=lambda e: (int(e["ex_id"]) if e["ex_id"].isdigit() else 0, e["lang"]))
    return {"count": len(entries), "entries": entries}

@app.delete("/api/admin/cache")
def admin_cache_clear(_=Depends(require_admin)):
    global audio_cache
    audio_cache = {}
    _save_cache(audio_cache)
    return {"ok": True, "message": "Cache tozalandi"}

# ── Bo'limlar ────────────────────────────────────────────────

@app.get("/api/admin/bolimlar")
def get_bolimlar(_=Depends(require_admin)):
    result = []
    for b in bolimlar_db:
        vit_count = len([v for v in vitrinas_db if v.get("bolim_id") == b["id"]])
        result.append({**b, "vitrina_count": vit_count})
    return result

@app.post("/api/admin/bolimlar", status_code=201)
def create_bolim(body: BolimRequest, _=Depends(require_admin)):
    new_id = max((b["id"] for b in bolimlar_db), default=0) + 1
    bolim = {
        "id": new_id,
        "nomi":      {"uz": body.nomi.uz, "ru": body.nomi.ru, "en": body.nomi.en},
        "tavsif":    {"uz": body.tavsif.uz, "ru": body.tavsif.ru, "en": body.tavsif.en},
        "masul_ism": body.masul_ism,
        "masul_familya": body.masul_familya,
        "masul_tel": body.masul_tel,
        "created_at": datetime.now().strftime("%Y-%m-%d"),
    }
    bolimlar_db.append(bolim)
    _save_json(BOLIMLAR_FILE, bolimlar_db)
    return bolim

@app.put("/api/admin/bolimlar/{bolim_id}")
def update_bolim(bolim_id: int, body: BolimRequest, _=Depends(require_admin)):
    for i, b in enumerate(bolimlar_db):
        if b["id"] == bolim_id:
            bolimlar_db[i].update({
                "nomi":      {"uz": body.nomi.uz, "ru": body.nomi.ru, "en": body.nomi.en},
                "tavsif":    {"uz": body.tavsif.uz, "ru": body.tavsif.ru, "en": body.tavsif.en},
                "masul_ism": body.masul_ism,
                "masul_familya": body.masul_familya,
                "masul_tel": body.masul_tel,
            })
            _save_json(BOLIMLAR_FILE, bolimlar_db)
            return bolimlar_db[i]
    raise HTTPException(404, "Bo'lim topilmadi")

@app.delete("/api/admin/bolimlar/{bolim_id}")
def delete_bolim(bolim_id: int, _=Depends(require_admin)):
    global bolimlar_db
    bolimlar_db = [b for b in bolimlar_db if b["id"] != bolim_id]
    _save_json(BOLIMLAR_FILE, bolimlar_db)
    return {"ok": True}

# ── Vitrinalar ───────────────────────────────────────────────

@app.get("/api/vitrina/{vitrina_id}")
def get_vitrina_public(vitrina_id: int):
    v = next((v for v in vitrinas_db if v["id"] == vitrina_id), None)
    if not v:
        raise HTTPException(404, "Vitrina topilmadi")
    return {"id": v["id"], "nomi": v.get("nomi", {})}

@app.get("/api/admin/vitrinalar")
def get_vitrinalar(_=Depends(require_admin)):
    result = []
    for v in vitrinas_db:
        bolim = next((b for b in bolimlar_db if b["id"] == v.get("bolim_id")), None)
        result.append({**v, "bolim_nomi": bolim["nomi"]["uz"] if bolim else "—"})
    return result

@app.post("/api/admin/vitrinalar", status_code=201)
def create_vitrina(body: VitrinaRequest, _=Depends(require_admin)):
    new_id = max((v["id"] for v in vitrinas_db), default=0) + 1
    vitrina = {
        "id": new_id,
        "bolim_id": body.bolim_id,
        "nomi": {"uz": body.nomi.uz, "ru": body.nomi.ru, "en": body.nomi.en},
        "joy": body.joy,
        "qr_code": f"vitrina_{new_id}",
        "exhibits": [],
        "created_at": datetime.now().strftime("%Y-%m-%d"),
    }
    vitrinas_db.append(vitrina)
    _save_json(VITRINAS_FILE, vitrinas_db)
    return vitrina

@app.put("/api/admin/vitrinalar/{vitrina_id}")
def update_vitrina(vitrina_id: int, body: VitrinaRequest, _=Depends(require_admin)):
    for i, v in enumerate(vitrinas_db):
        if v["id"] == vitrina_id:
            vitrinas_db[i].update({
                "bolim_id": body.bolim_id,
                "nomi": {"uz": body.nomi.uz, "ru": body.nomi.ru, "en": body.nomi.en},
                "joy": body.joy,
            })
            _save_json(VITRINAS_FILE, vitrinas_db)
            return vitrinas_db[i]
    raise HTTPException(404, "Vitrina topilmadi")

@app.delete("/api/admin/vitrinalar/{vitrina_id}")
def delete_vitrina(vitrina_id: int, _=Depends(require_admin)):
    global vitrinas_db
    vitrinas_db = [v for v in vitrinas_db if v["id"] != vitrina_id]
    _save_json(VITRINAS_FILE, vitrinas_db)
    return {"ok": True}

# ── Eksponatlar ───────────────────────────────────────────────

@app.get("/api/admin/eksponatlar")
def get_eksponatlar(vitrina_id: Optional[int] = None, bolim_id: Optional[int] = None, _=Depends(require_admin)):
    result = eksponatlar_db
    if vitrina_id:
        result = [e for e in result if e.get("vitrina_id") == vitrina_id]
    if bolim_id:
        result = [e for e in result if e.get("bolim_id") == bolim_id]
    return sorted(result, key=lambda e: (e.get("bolim_id", 0), e.get("vitrina_id", 0), e.get("tartib", 0)))

@app.post("/api/admin/upload")
async def upload_image(file: UploadFile = File(...), _=Depends(require_admin)):
    if not file.content_type.startswith("image/"):
        raise HTTPException(400, "Faqat rasm fayllari qabul qilinadi")
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "jpg"
    if ext not in ("jpg", "jpeg", "png", "webp", "gif"):
        raise HTTPException(400, "Ruxsat etilgan formatlar: jpg, png, webp")
    filename = f"{uuid.uuid4().hex}.{ext}"
    dest = UPLOAD_DIR / filename
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"url": f"/uploads/{filename}"}

@app.post("/api/admin/eksponatlar", status_code=201)
def create_eksponat(body: EksponatRequest, _=Depends(require_admin)):
    global eksponatlar_db
    new_id = max((e["id"] for e in eksponatlar_db), default=0) + 1
    eksponat = {
        "id":         new_id,
        "vitrina_id": body.vitrina_id,
        "bolim_id":   body.bolim_id,
        "image_url":  body.image_url,
        "era":        {"uz": body.era.uz,  "ru": body.era.ru,  "en": body.era.en},
        "name":       {"uz": body.name.uz, "ru": body.name.ru, "en": body.name.en},
        "date":       {"uz": body.date.uz, "ru": body.date.ru, "en": body.date.en},
        "text":       {"uz": body.text.uz, "ru": body.text.ru, "en": body.text.en},
        "tartib":     body.tartib,
        "created_at": datetime.now().strftime("%Y-%m-%d"),
    }
    eksponatlar_db.append(eksponat)
    _save_json(EKSPONATLAR_FILE, eksponatlar_db)
    return eksponat

@app.put("/api/admin/eksponatlar/{eksponat_id}")
def update_eksponat(eksponat_id: int, body: EksponatRequest, _=Depends(require_admin)):
    for i, e in enumerate(eksponatlar_db):
        if e["id"] == eksponat_id:
            update = {
                "vitrina_id": body.vitrina_id,
                "bolim_id":   body.bolim_id,
                "era":        {"uz": body.era.uz,  "ru": body.era.ru,  "en": body.era.en},
                "name":       {"uz": body.name.uz, "ru": body.name.ru, "en": body.name.en},
                "date":       {"uz": body.date.uz, "ru": body.date.ru, "en": body.date.en},
                "text":       {"uz": body.text.uz, "ru": body.text.ru, "en": body.text.en},
                "tartib":     body.tartib,
            }
            if body.image_url:
                update["image_url"] = body.image_url
            eksponatlar_db[i].update(update)
            _save_json(EKSPONATLAR_FILE, eksponatlar_db)
            return eksponatlar_db[i]
    raise HTTPException(404, "Eksponat topilmadi")

@app.delete("/api/admin/eksponatlar/{eksponat_id}")
def delete_eksponat(eksponat_id: int, _=Depends(require_admin)):
    global eksponatlar_db
    eksponatlar_db = [e for e in eksponatlar_db if e["id"] != eksponat_id]
    _save_json(EKSPONATLAR_FILE, eksponatlar_db)
    # Also remove from audio cache
    keys_to_del = [k for k in audio_cache if k.startswith(f"{eksponat_id}_")]
    for k in keys_to_del:
        audio_cache.pop(k, None)
    if keys_to_del:
        _save_cache(audio_cache)
    return {"ok": True}


# ── Serve frontend & admin ────────────────────────────────────
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
ADMIN_FILE   = Path(__file__).parent / "admin.html"

app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
app.mount("/static",  StaticFiles(directory=str(FRONTEND_DIR)), name="static")

@app.get("/", response_class=FileResponse)
def serve_index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))

@app.get("/admin", response_class=FileResponse)
@app.get("/admin/", response_class=FileResponse)
def serve_admin():
    return FileResponse(str(ADMIN_FILE))
