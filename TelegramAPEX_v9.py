"""TELEGRAM APEX MEDIA BROWSER v10.1 - ULTRA EDITION"""

import sys, os, subprocess, importlib.util as _ilu

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        import io
        try:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
        except Exception: pass

_REQUIRED = {"telethon":"telethon","PIL":"pillow","cryptg":"cryptg",
             "pyaes":"pyaes","rsa":"rsa","flask":"flask"}
_OPTIONAL = {"webview":"pywebview"}

def _bootstrap():
    if getattr(sys, "frozen", False): return
    missing = [pkg for mod,pkg in _REQUIRED.items() if _ilu.find_spec(mod) is None]
    if missing:
        print(f"[APEX] Installing: {', '.join(missing)} ...")
        for pkg in missing:
            subprocess.check_call([sys.executable,"-m","pip","install",pkg,"--quiet"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("[APEX] Required packages installed.")
    for mod,pkg in _OPTIONAL.items():
        if _ilu.find_spec(mod) is None:
            try:
                subprocess.check_call([sys.executable,"-m","pip","install",pkg,"--quiet"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                print(f"[APEX] Optional '{pkg}' unavailable - browser mode will be used.")

_bootstrap()

import json, asyncio, threading, logging, time, shutil, hashlib, mimetypes
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from collections import deque, OrderedDict

from flask import Flask, jsonify, request, Response, send_file, stream_with_context
try:
    import webview
    WEBVIEW_OK = True
except ImportError:
    WEBVIEW_OK = False

try:
    from PIL import Image, ImageDraw
    PIL_OK = True
except ImportError:
    PIL_OK = False

from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, ServerError, TimedOutError
from telethon.tl.types import (
    MessageMediaDocument, MessageMediaPhoto,
    DocumentAttributeVideo, DocumentAttributeAudio,
    DocumentAttributeFilename, PhotoSize,
    InputMessagesFilterPhotoVideo, InputMessagesFilterDocument,
)

logging.getLogger("telethon").setLevel(logging.ERROR)
logging.getLogger("werkzeug").setLevel(logging.ERROR)
log = logging.getLogger("apex10")
logging.basicConfig(level=logging.WARNING, format="[APEX] %(levelname)s %(message)s")

# -- Paths (SESSION stored next to config, NOT in download folder) --------------
_DIR        = os.path.dirname(os.path.abspath(sys.argv[0] if getattr(sys,"frozen",False) else __file__))
CONFIG_FILE = os.path.join(_DIR, "config_v10.json")
QUEUE_FILE  = os.path.join(_DIR, "queue_v10.json")
DL_DB_FILE  = os.path.join(_DIR, "downloaded_v10.json")
# FIX: session lives next to the exe/script - never changes, so login persists
SESSION_FILE = os.path.join(_DIR, "apex_session")

# -- Version / update checking (points at your GitHub repo's releases) ---------
APP_VERSION = "10.1.0"
GITHUB_REPO = "YOUR_GITHUB_USERNAME/TelegramAPEX"  # edit after you create the repo

PRESETS = {
    "Ultra5G":  {"connections":8,"concurrent_files":8,"workers":20,"request_size":1024*1024},
    "Turbo":    {"connections":5,"concurrent_files":4,"workers":10,"request_size":512*1024},
    "Balanced": {"connections":3,"concurrent_files":2,"workers":6, "request_size":256*1024},
    "Safe":     {"connections":2,"concurrent_files":1,"workers":3, "request_size":128*1024},
}
DEFAULT_CFG = {
    "api_id":"","api_hash":"",
    "download_folder": os.path.join(os.path.expanduser("~"),"TelegramDownloads"),
    "preset":"Turbo","bandwidth_kbps":0,"theme":"dark",
    "max_concurrent":0,  # 0 = use preset's concurrent_files value
    "auto_watch":False,  # auto-download new incoming media as it arrives
}

API_ID=0; API_HASH=""; DOWNLOAD_FOLDER=""
CONNECTIONS=5; CONCURRENT_FILES=4; WORKERS=10; BANDWIDTH_KBPS=0
THUMB_DIR=""; REQ_SIZE=512*1024

def load_cfg():
    if os.path.exists(CONFIG_FILE):
        try:
            c = json.load(open(CONFIG_FILE,"r",encoding="utf-8"))
            for k,v in DEFAULT_CFG.items(): c.setdefault(k,v)
            return c
        except Exception: pass
    return dict(DEFAULT_CFG)

def save_cfg(c): json.dump(c, open(CONFIG_FILE,"w",encoding="utf-8"), indent=2)

def _apply_cfg(c):
    global API_ID, API_HASH, DOWNLOAD_FOLDER
    global CONNECTIONS, CONCURRENT_FILES, WORKERS, BANDWIDTH_KBPS, THUMB_DIR, REQ_SIZE
    API_ID          = int(c["api_id"]) if str(c.get("api_id","")).strip().isdigit() else 0
    API_HASH        = c.get("api_hash","")
    DOWNLOAD_FOLDER = c.get("download_folder", DEFAULT_CFG["download_folder"]) or DEFAULT_CFG["download_folder"]
    os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
    p               = PRESETS.get(c.get("preset","Turbo"), PRESETS["Turbo"])
    CONNECTIONS     = p["connections"]
    CONCURRENT_FILES= p["concurrent_files"]
    WORKERS         = p["workers"]
    REQ_SIZE        = p["request_size"]
    try:
        _mc = int(c.get("max_concurrent",0) or 0)
    except (TypeError, ValueError):
        _mc = 0
    if _mc > 0:
        CONCURRENT_FILES = max(1, min(_mc, 16))
    BANDWIDTH_KBPS  = int(c.get("bandwidth_kbps",0))
    THUMB_DIR       = os.path.join(DOWNLOAD_FOLDER,"thumbs")
    os.makedirs(THUMB_DIR, exist_ok=True)
    # NOTE: SESSION_FILE intentionally NOT updated here

CFG = load_cfg(); _apply_cfg(CFG)

def _ensure_dirs():
    for s in ["videos","photos","audios","docs","thumbs"]:
        os.makedirs(os.path.join(DOWNLOAD_FOLDER,s), exist_ok=True)

# -- Persistence ---------------------------------------------------------------
def _lj(path, default):
    try:
        if os.path.exists(path): return json.load(open(path,"r",encoding="utf-8"))
    except Exception: pass
    return default

def _sj(path, data):
    try: json.dump(data, open(path,"w",encoding="utf-8"))
    except Exception: pass

_dl_db: set = set(_lj(DL_DB_FILE, []))
def is_done(i):   return str(i) in _dl_db
def mark_done(i): _dl_db.add(str(i)); _sj(DL_DB_FILE, list(_dl_db))

FAV_DB_FILE = os.path.join(_DIR, "favorites_v10.json")
_fav_db: set = set(_lj(FAV_DB_FILE, []))
def is_fav(i): return str(i) in _fav_db
def toggle_fav(i):
    s=str(i)
    if s in _fav_db: _fav_db.discard(s); on=False
    else: _fav_db.add(s); on=True
    _sj(FAV_DB_FILE, list(_fav_db))
    return on

def persist_q(items):
    _sj(QUEUE_FILE, [{"id":x["id"],"chat_id":x["chat_id"],"type":x["type"],
                      "orig_name":x.get("orig_name",""),"size_mb":x.get("size_mb",0)} for x in items])
def clear_q():
    try:
        if os.path.exists(QUEUE_FILE): os.remove(QUEUE_FILE)
    except Exception: pass

# -- LRU Cache -----------------------------------------------------------------
class LRUCache:
    def __init__(self, cap=500):
        self._d = OrderedDict(); self._cap = cap
    def get(self, k):
        if k not in self._d: return None
        self._d.move_to_end(k); return self._d[k]
    def put(self, k, v):
        self._d[k] = v; self._d.move_to_end(k)
        if len(self._d) > self._cap: self._d.popitem(last=False)

# -- SSE Event Bus -------------------------------------------------------------
class EventBus:
    def __init__(self):
        self._subs = []; self._lock = threading.Lock()
    def subscribe(self):
        q = deque()
        with self._lock: self._subs.append(q)
        return q
    def unsubscribe(self, q):
        with self._lock:
            try: self._subs.remove(q)
            except ValueError: pass
    def emit(self, event: str, data: dict):
        msg = f"event: {event}\ndata: {json.dumps(data)}\n\n"
        with self._lock:
            for q in self._subs: q.append(msg)

bus = EventBus()

# -- Turbo Downloader ----------------------------------------------------------
CHUNK_MIN = 128*1024; CHUNK_MAX = 8*1024*1024; PAR_MIN = 8*1024*1024

def _verify_media_integrity(path):
    """Best-effort corruption check via ffprobe: catches files that have the
    right byte count but a broken/unreadable container (e.g. a segment-boundary
    mismatch in parallel downloads). Returns True (assume OK) if ffprobe isn't
    installed, since we can't verify either way - this is a bonus safety net,
    not the only line of defense."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe: return True
    try:
        r = subprocess.run(
            [ffprobe,"-v","error","-show_entries","format=duration",
             "-of","default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=20)
        if r.returncode != 0: return False
        if r.stderr.strip(): return False
        dur_str = r.stdout.strip()
        return bool(dur_str) and float(dur_str) > 0
    except Exception:
        return True  # verification itself failed - don't punish the download for that

class TurboDownloader:
    def __init__(self, client):
        self.client  = client
        self.io_pool = ThreadPoolExecutor(max_workers=24, thread_name_prefix="apex_io")
        self._cancel = set()
        self._active_streams = 0  # in-flight downloads, for fair bandwidth division

    def cancel(self, msg_id): self._cancel.add(msg_id)

    async def download(self, msg, filepath, on_prog=None, mtype=None):
        if not msg.media: return None
        self._active_streams += 1
        try:
            size   = self._sz(msg.media)
            is_doc = isinstance(msg.media, MessageMediaDocument)
            last_err = None
            for attempt in range(3):
                if msg.id in self._cancel:
                    self._cancel.discard(msg.id)
                    raise asyncio.CancelledError()
                try:
                    if is_doc and size >= PAR_MIN:
                        try:
                            return await asyncio.wait_for(self._parallel(msg,filepath,size,on_prog,mtype), timeout=900)
                        except asyncio.CancelledError:
                            raise
                        except Exception as e:
                            log.warning(f"Parallel failed ({e}), stream fallback")
                        shutil.rmtree(filepath+".parts", ignore_errors=True)
                        try:
                            if os.path.exists(filepath): os.remove(filepath)
                        except Exception: pass
                    return await asyncio.wait_for(self._stream(msg,filepath,size,on_prog,mtype), timeout=3600)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    last_err = e
                    if attempt < 2:
                        log.warning(f"Download attempt {attempt+1} failed for msg {msg.id} ({e}), retrying...")
                        await asyncio.sleep(3*(attempt+1))
                    else:
                        raise last_err
        finally:
            self._active_streams = max(0, self._active_streams-1)

    def _sz(self, media):
        if hasattr(media,"document"): return media.document.size
        if hasattr(media,"photo"):
            return max((s.size for s in media.photo.sizes if hasattr(s,"size")), default=0)
        return 0

    def _adapt_chunk(self, samples):
        if not samples: return CHUNK_MIN
        avg = sum(samples)/len(samples)
        if avg < 2:  return CHUNK_MIN
        if avg < 6:  return 512*1024
        if avg < 15: return 1*1024*1024
        if avg < 30: return 2*1024*1024
        if avg < 60: return 4*1024*1024
        return CHUNK_MAX

    def _throttle(self, n):
        if BANDWIDTH_KBPS <= 0: return 0
        share = max(1, self._active_streams)
        return n/((BANDWIDTH_KBPS/share)*1024)

    async def _stream(self, msg, filepath, size, on_prog, mtype=None):
        done=0; start=time.monotonic(); samples=deque(maxlen=8)
        cs=REQ_SIZE; tmp=filepath+".tmp"
        try:
            with open(tmp,"wb") as f:
                async for chunk in self.client.iter_download(msg.media, chunk_size=cs, request_size=cs):
                    if msg.id in self._cancel:
                        self._cancel.discard(msg.id); raise asyncio.CancelledError()
                    await self.client.loop.run_in_executor(self.io_pool, f.write, chunk)
                    done += len(chunk)
                    el = time.monotonic()-start
                    if el > 0.2:
                        spd=(done/1_048_576)/el; samples.append(spd); cs=self._adapt_chunk(samples)
                    delay=self._throttle(len(chunk))
                    if delay: await asyncio.sleep(delay)
                    if on_prog and size:
                        spd2=samples[-1] if samples else 0
                        pct=min(int(done/size*100),99)
                        eta=int((size-done)/(done/el)) if done>0 and el>0.5 else 0
                        on_prog(pct,spd2,done,size,eta)
            if size and done < size:
                raise IOError(f"Incomplete download: got {done} of {size} bytes (connection likely dropped early)")
            if mtype in ("video","audio") and not _verify_media_integrity(tmp):
                raise IOError("Downloaded file failed integrity check (corrupt/unreadable media container)")
            if os.path.exists(filepath): os.remove(filepath)
            os.rename(tmp,filepath)
        except Exception:
            for p in [tmp,filepath]:
                try:
                    if os.path.exists(p): os.remove(p)
                except Exception: pass
            raise
        return filepath

    async def _seg(self, msg, offset, limit, ppath, idx, shared, lock, start, total_size, on_prog):
        BACKS=[3,10,30]
        for attempt in range(4):
            try:
                w=0; cs=REQ_SIZE; samples=deque(maxlen=4)
                with open(ppath,"wb") as f:
                    async for chunk in self.client.iter_download(
                            msg.media, offset=offset, limit=limit, chunk_size=cs, request_size=cs):
                        if msg.id in self._cancel:
                            self._cancel.discard(msg.id); raise asyncio.CancelledError()
                        f.write(chunk); w+=len(chunk)
                        async with lock: shared[idx]=w
                        el=time.monotonic()-start
                        if el>0.2:
                            async with lock: td=sum(shared)
                            spd=(td/1_048_576)/el; samples.append(spd); cs=self._adapt_chunk(samples)
                        delay=self._throttle(len(chunk))
                        if delay: await asyncio.sleep(delay)
                        if on_prog and total_size:
                            async with lock: td2=sum(shared)
                            el2=time.monotonic()-start
                            spd2=(td2/1_048_576)/el2 if el2>0.5 else 0
                            pct=min(int(td2/total_size*100),99)
                            eta=int((total_size-td2)/(td2/el2)) if td2>0 and el2>0.5 else 0
                            on_prog(pct,spd2,td2,total_size,eta)
                        if w>=limit: break
                return
            except asyncio.CancelledError: raise
            except (FloodWaitError,ServerError,TimedOutError,asyncio.TimeoutError,OSError) as e:
                wait=BACKS[min(attempt,2)]
                if isinstance(e,FloodWaitError): wait=max(wait,e.seconds+2)
                if attempt<3: await asyncio.sleep(wait)
                else: raise
            except Exception as e:
                log.error(f"Seg {idx} fatal: {e}"); raise

    async def _parallel(self, msg, filepath, size, on_prog, mtype=None):
        n=min(WORKERS,8); ALIGN=4096
        seg=((size+n-1)//n); seg=((seg+ALIGN-1)//ALIGN)*ALIGN
        parts=filepath+".parts"; os.makedirs(parts,exist_ok=True)
        actual_n=0; shared=[0]*n; lock=asyncio.Lock(); start=time.monotonic(); tasks=[]
        for i in range(n):
            offset=i*seg
            if offset>=size: break
            actual_n+=1
            limit=min(seg,size-offset); ppath=os.path.join(parts,f"{i:03d}")
            tasks.append(asyncio.wait_for(
                self._seg(msg,offset,limit,ppath,i,shared,lock,start,size,on_prog),timeout=600))
        results=await asyncio.gather(*tasks,return_exceptions=True)
        errors=[r for r in results if isinstance(r,Exception)]
        if errors: shutil.rmtree(parts,ignore_errors=True); raise errors[0]
        def _assemble():
            tmp=filepath+".tmp"
            with open(tmp,"wb") as out:
                for i in range(actual_n):
                    p=os.path.join(parts,f"{i:03d}")
                    if os.path.exists(p):
                        with open(p,"rb") as pf: shutil.copyfileobj(pf,out,8*1024*1024)
            final_size=os.path.getsize(tmp)
            if size and final_size < size:
                shutil.rmtree(parts,ignore_errors=True)
                try: os.remove(tmp)
                except Exception: pass
                raise IOError(f"Incomplete assembled download: got {final_size} of {size} bytes")
            if mtype in ("video","audio") and not _verify_media_integrity(tmp):
                shutil.rmtree(parts,ignore_errors=True)
                try: os.remove(tmp)
                except Exception: pass
                raise IOError("Assembled file failed integrity check (corrupt/unreadable media container - "
                               "likely a segment-boundary mismatch in parallel download)")
            shutil.rmtree(parts,ignore_errors=True)
            if os.path.exists(filepath): os.remove(filepath)
            os.rename(tmp,filepath)
        await self.client.loop.run_in_executor(self.io_pool,_assemble)
        if on_prog:
            el=time.monotonic()-start; spd=(size/1_048_576)/el if el>0 else 0
            on_prog(100,spd,size,size,0)
        return filepath

# -- Backend -------------------------------------------------------------------
class Backend:
    def __init__(self):
        self.loop=asyncio.new_event_loop()
        self.client=None; self.me=None; self.turbo=None
        self._sema=None; self._new_cb=None
        self._ready=threading.Event()
        self._phone_result=None; self._code_result=None; self._pwd_result=None
        self._phone_ev=threading.Event(); self._code_ev=threading.Event(); self._pwd_ev=threading.Event()

    def start(self):
        threading.Thread(target=self._run,daemon=True,name="apex_tg").start()
        self._ready.wait(timeout=8)

    def _run(self):
        asyncio.set_event_loop(self.loop)
        # FIX: SESSION_FILE is fixed path next to exe - login persists across restarts
        self.client=TelegramClient(
            SESSION_FILE, API_ID, API_HASH,
            connection_retries=20, flood_sleep_threshold=60,
            request_retries=10, sequential_updates=False, auto_reconnect=True)
        self.loop.set_exception_handler(lambda l,c: log.debug(f"Loop exc: {c}"))
        self._sema =asyncio.Semaphore(CONCURRENT_FILES)
        self.turbo =TurboDownloader(self.client)
        self._ready.set()
        try: self.loop.run_forever()
        except Exception as e: log.error(f"Loop exited: {e}")

    def run(self, coro): return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def provide_phone(self, phone): self._phone_result=phone; self._phone_ev.set()
    def provide_code(self, code):   self._code_result=code;   self._code_ev.set()
    def provide_password(self, pwd): self._pwd_result=pwd;    self._pwd_ev.set()

    def _phone_cb(self):
        self._phone_ev.wait(timeout=180); self._phone_ev.clear()
        return self._phone_result or ""

    def _code_cb(self):
        self._code_ev.wait(timeout=180); self._code_ev.clear()
        return self._code_result or ""

    def _pwd_cb(self):
        # Telethon only calls this when the account has 2FA enabled.
        # Tell the UI to show the password field, then wait for it.
        bus.emit("auth_step", {"step":"2fa"})
        self._pwd_ev.wait(timeout=180); self._pwd_ev.clear()
        return self._pwd_result or ""

    async def _connect(self):
        # Ensure client is connected to Telegram servers first
        if not self.client.is_connected():
            await self.client.connect()
        # Only show auth prompt if NOT already authorized
        if not await self.client.is_user_authorized():
            bus.emit("auth_step", {"step":"phone"})
        await self.client.start(phone=self._phone_cb, code_callback=self._code_cb, password=self._pwd_cb)
        self.me = await self.client.get_me()
        return self.me

    def connect(self, on_done):
        f = self.run(self._connect())
        f.add_done_callback(
            lambda f: on_done(True,f.result()) if not f.exception()
                 else on_done(False,str(f.exception())))

    def _dtype(self, d):
        from telethon.tl.types import User, Chat, Channel
        e = d.entity
        if isinstance(e, User):    return "BOT" if e.bot else "DM"
        if isinstance(e, Chat):    return "GROUP"
        if isinstance(e, Channel): return "CHANNEL" if e.broadcast else "SUPERGROUP"
        return "OTHER"

    async def _dialogs(self, on_batch):
        result=[]; batch=[]
        try:
            async for d in self.client.iter_dialogs(limit=500):
                try:
                    e={"id":d.id,"name":d.name or "Unknown","type":self._dtype(d),"unread":d.unread_count}
                    result.append(e); batch.append(e)
                    if len(batch)>=20: on_batch(list(batch)); batch.clear()
                except Exception as ex: log.warning(f"Skip dialog: {ex}")
        except Exception as ex: log.error(f"Dialogs: {ex}")
        if batch: on_batch(batch)
        return result

    def load_dialogs(self, on_done, on_batch):
        f=self.run(self._dialogs(on_batch))
        f.add_done_callback(lambda f:on_done(f.result() if not f.exception() else []))

    def _mtype(self, msg):
        if not msg.media: return "text"
        if isinstance(msg.media, MessageMediaPhoto): return "photo"
        if isinstance(msg.media, MessageMediaDocument):
            for a in msg.media.document.attributes:
                if isinstance(a, DocumentAttributeVideo): return "video"
                if isinstance(a, DocumentAttributeAudio): return "audio"
            return "document"
        return "other"

    def _msize(self, msg):
        try:
            if isinstance(msg.media, MessageMediaDocument):
                return msg.media.document.size/1_048_576
        except Exception: pass
        return 0.0

    def _oname(self, msg):
        if isinstance(msg.media, MessageMediaDocument):
            for a in msg.media.document.attributes:
                if isinstance(a, DocumentAttributeFilename): return a.file_name
        return ""

    def _mime(self, msg):
        try:
            if isinstance(msg.media, MessageMediaDocument):
                return msg.media.document.mime_type or ""
        except Exception: pass
        return ""

    def _item(self, msg, chat_id, mt):
        return {"id":msg.id,"chat_id":chat_id,"type":mt,
                "date":msg.date.isoformat() if msg.date else "",
                "size_mb":self._msize(msg),"caption":msg.text or "",
                "orig_name":self._oname(msg),"mime":self._mime(msg),"msg":msg}

    # Pagination: `before_id` returns items strictly older than that message ID.
    # (Telethon's max_id keeps messages with ID <= max_id, so the caller should
    # pass smallest_id_seen - 1 to avoid re-fetching the boundary item.)
    async def _media(self, chat_id, limit, before_id):
        items=[]; seen=set()
        try:
            entity = await self.client.get_entity(chat_id)
            kw = dict(limit=limit)
            if before_id: kw["max_id"] = before_id
            # Photos + videos
            async for msg in self.client.iter_messages(
                    entity, filter=InputMessagesFilterPhotoVideo(), **kw):
                t=self._mtype(msg)
                if t in ("photo","video"): items.append(self._item(msg,chat_id,t)); seen.add(msg.id)
            # Documents / audio
            async for msg in self.client.iter_messages(
                    entity, filter=InputMessagesFilterDocument(),
                    limit=max(20,limit//2), **({"max_id":before_id} if before_id else {})):
                if msg.id not in seen:
                    t=self._mtype(msg)
                    if t in ("video","audio","document"):
                        items.append(self._item(msg,chat_id,t)); seen.add(msg.id)
        except Exception as e: log.error(f"Media error for {chat_id}: {e}")
        items.sort(key=lambda x:x["date"],reverse=True)
        return items[:limit]

    def load_media(self, chat_id, limit, before_id, on_done):
        f=self.run(self._media(chat_id,limit,before_id))
        f.add_done_callback(lambda f:on_done(f.result() if not f.exception() else []))

    async def _thumb(self, msg, iid):
        p=os.path.join(THUMB_DIR,f"t{iid}.jpg")
        if os.path.exists(p) and os.path.getsize(p)>0: return p
        try:
            await self.client.download_media(msg,file=p,thumb=-1)
            if os.path.exists(p) and os.path.getsize(p)>0:
                return p
            # No embedded thumbnail available. Only fall back to a full
            # download for small photos - never for video/audio/documents,
            # which could be huge and would stall the whole thumbnail queue.
            if isinstance(msg.media, MessageMediaPhoto):
                sz=self._sz(msg.media)
                if sz and sz < 3*1024*1024:
                    await self.client.download_media(msg,file=p)
            return p if os.path.exists(p) and os.path.getsize(p)>0 else None
        except Exception: return None

    async def _thumbs(self, tasks, on_each):
        sem=asyncio.Semaphore(12)
        async def _one(msg,iid):
            async with sem: on_each(iid,await self._thumb(msg,iid))
        await asyncio.gather(*[_one(m,i) for m,i in tasks],return_exceptions=True)

    def get_thumbs(self, tasks, on_each): self.run(self._thumbs(tasks,on_each))

    def _best_photo(self, pm):
        sz=[s for s in pm.photo.sizes if isinstance(s,PhotoSize)]
        return max(sz,key=lambda s:s.size) if sz else None

    def _audio_ext(self, msg):
        if isinstance(msg.media, MessageMediaDocument):
            mime=getattr(msg.media.document,"mime_type","") or ""
            for k,v in [("flac",".flac"),("ogg",".ogg"),("opus",".opus"),("mp4a",".m4a")]:
                if k in mime: return v
        return ".mp3"

    async def _do_dl(self, msg, mtype, on_prog):
        if is_done(msg.id): return None,"[already saved]"
        sub={"video":"videos","photo":"photos","audio":"audios","document":"docs"}.get(mtype,"docs")
        orig=self._oname(msg)
        if orig:
            name=orig
        else:
            ts=datetime.now().strftime("%Y%m%d_%H%M%S")
            ext={"video":".mp4","photo":".jpg","document":".bin"}.get(mtype,self._audio_ext(msg))
            if mtype=="audio": ext=self._audio_ext(msg)
            name=f"{mtype}_{msg.id}_{ts}{ext}"
        path=os.path.join(DOWNLOAD_FOLDER,sub,name)
        if os.path.exists(path) and os.path.getsize(path)>0:
            base,ext2=os.path.splitext(path); path=f"{base}_{msg.id}{ext2}"
        acquired=False
        try:
            await asyncio.wait_for(self._sema.acquire(),timeout=120)
            acquired=True
            if mtype=="photo":
                best=self._best_photo(msg.media)
                if best: await self.client.download_media(msg,file=path,thumb=best)
                else:    await self.client.download_media(msg,file=path)
            else:
                if self.turbo is None: raise RuntimeError("Not connected")
                await self.turbo.download(msg,path,on_prog,mtype)
        finally:
            if acquired: self._sema.release()
        mark_done(msg.id)
        return path, name

    def download(self, msg, mtype, on_prog, on_done):
        BACKS=[2,8,30,60]
        async def _retry():
            last=None
            for attempt in range(4):
                try: return await self._do_dl(msg,mtype,on_prog)
                except FloodWaitError as e:
                    wait=max(BACKS[min(attempt,3)],e.seconds+2)
                    await asyncio.sleep(wait); last=e
                except (ServerError,TimedOutError,OSError) as e:
                    await asyncio.sleep(BACKS[min(attempt,3)]); last=e
                except asyncio.CancelledError: raise
                except Exception as e:
                    last=e
                    if attempt<3: await asyncio.sleep(BACKS[attempt])
                    else: break
            raise last or RuntimeError("Failed after retries")
        def _cb(f):
            try:    on_done(True,*f.result())
            except asyncio.CancelledError: on_done(False,"Cancelled","")
            except Exception as e: on_done(False,str(e),"")
        f=self.run(_retry()); f.add_done_callback(_cb)

    def set_new_cb(self, cb): self._new_cb=cb

    def start_watching(self):
        @self.client.on(events.NewMessage)
        async def _h(ev):
            if not self._new_cb: return
            msg=ev.message; t=self._mtype(msg)
            if t not in ("photo","video","audio","document"): return
            try:
                chat=await ev.get_chat()
                cn=getattr(chat,"title",None) or getattr(chat,"username","?")
            except Exception: cn="?"
            item=self._item(msg,ev.chat_id,t); item["chat_name"]=cn
            self._new_cb(item)

# -- App State -----------------------------------------------------------------
class AppState:
    def __init__(self):
        self.be=Backend()
        self.connected=False; self.me_info={}
        self.dialogs=[]; self.media_cache={}; self.msg_cache={}
        self.thumb_cache=LRUCache(500)
        self.dl_queue=[]; self.dl_active=False; self.dl_total=0
        self.active_dl={}  # id -> item dict, for concurrent in-flight downloads
        self.paused=False
        self.session_files=0; self.session_bytes=0
        self.session_start=time.monotonic()
        self.speed_history=deque([0]*30,maxlen=30)
        self.current_dl_name=""
        self.download_log=[]  # session history for CSV export: {id,name,size_mb,path,time}

state = AppState()

# -- Flask App -----------------------------------------------------------------
app = Flask(__name__, static_folder=None)

@app.after_request
def add_no_cache(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response
app.secret_key = hashlib.md5(b"apex_v10_secret").hexdigest()

def fmt_sz(mb):
    if mb>=1024: return f"{mb/1024:.2f} GB"
    return f"{mb:.1f} MB" if mb>=0.1 else "<0.1 MB"

def fmt_eta(s):
    if s<=0: return ""
    m,sec=divmod(int(s),60)
    return f"{m}m {sec:02d}s" if m else f"{sec}s"

# SSE
@app.route("/api/events")
def sse():
    q=bus.subscribe()
    def gen():
        try:
            yield "retry: 1000\n\n"
            while True:
                if q: yield q.popleft()
                else:  yield ":\n\n"
                time.sleep(0.05)
        except GeneratorExit: bus.unsubscribe(q)
    return Response(stream_with_context(gen()),
        content_type="text/event-stream",
        headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

# Config
@app.route("/api/config", methods=["GET"])
def api_config():
    c=dict(CFG); c.pop("api_hash",None)
    c["configured"]=bool(API_ID and API_HASH)
    c["connected"]=state.connected
    return jsonify(c)

@app.route("/api/config", methods=["POST"])
def api_save_config():
    global CFG
    data=request.json or {}
    if not data.get("api_hash","").strip():
        data["api_hash"]=CFG.get("api_hash","")
    CFG.update(data); save_cfg(CFG); _apply_cfg(CFG)
    state.connected=False; state.me_info={}
    return jsonify({"ok":True})

# Connect
@app.route("/api/reconnect", methods=["POST"])
def api_reconnect():
    state.connected = False
    return api_connect()

@app.route("/api/connect", methods=["POST"])
def api_connect():
    if state.connected:
        return jsonify({"ok":True,"already":True})
    # Cleanly reinitialize backend if a previous attempt left a broken client
    if state.be.client is not None:
        try:
            state.be.run(state.be.client.disconnect())
        except Exception: pass
        try: state.be.loop.call_soon_threadsafe(state.be.loop.stop)
        except Exception: pass
        import time as _t; _t.sleep(0.5)
        state.be.__init__()
    state.be.start()
    def on_done(ok,result):
        if ok:
            state.connected=True; me=result
            state.me_info={
                "id":me.id,
                "name":((me.first_name or "")+" "+(me.last_name or "")).strip(),
                "username":me.username or "",
                "phone":me.phone or "",
            }
            bus.emit("connected",state.me_info)
            state.be.set_new_cb(_on_new_media)
            state.be.start_watching()
            _ensure_dirs()
        else:
            bus.emit("connect_error",{"msg":str(result)})
    state.be.connect(on_done)
    return jsonify({"ok":True,"waiting":True})

@app.route("/api/auth/phone", methods=["POST"])
def api_auth_phone():
    state.be.provide_phone(request.json.get("phone",""))
    return jsonify({"ok":True})

@app.route("/api/auth/code", methods=["POST"])
def api_auth_code():
    state.be.provide_code(request.json.get("code",""))
    return jsonify({"ok":True})

@app.route("/api/auth/password", methods=["POST"])
def api_auth_password():
    # 2FA support
    state.be.provide_password(request.json.get("password",""))
    return jsonify({"ok":True})

@app.route("/api/me")
def api_me():
    return jsonify(state.me_info)

# Dialogs
@app.route("/api/dialogs")
def api_dialogs():
    if not state.connected: return jsonify({"error":"not connected"}),400
    result_holder=[None]; done_ev=threading.Event()
    def on_batch(batch): bus.emit("dialogs_batch",{"dialogs":batch})
    def on_done(dialogs):
        state.dialogs=dialogs; result_holder[0]=dialogs
        done_ev.set(); bus.emit("dialogs_done",{"count":len(dialogs)})
    state.be.load_dialogs(on_done,on_batch)
    done_ev.wait(timeout=60)
    return jsonify({"dialogs":result_holder[0] or [],"count":len(result_holder[0] or [])})

# Media - paginate strictly older items via before_id (see _media docstring above)
@app.route("/api/media/<chat_id>")
def api_media(chat_id):
    try: chat_id = int(chat_id)
    except ValueError: return jsonify({"error":"invalid chat_id"}),400
    if not state.connected: return jsonify({"error":"not connected"}),400
    limit     = int(request.args.get("limit",50))
    before_id = int(request.args.get("before_id", request.args.get("min_id",0)))
    refresh   = request.args.get("refresh")=="1"
    if refresh:
        state.media_cache[chat_id]=[]
        before_id=0
    done_ev=threading.Event(); result_holder=[None]
    def on_done(items):
        if chat_id not in state.media_cache: state.media_cache[chat_id]=[]
        existing_ids={i["id"] for i in state.media_cache[chat_id]}
        safe=[]
        for item in items:
            msg=item.pop("msg",None)
            if item["id"] in existing_ids: continue  # skip dupes across pages
            if msg: state.msg_cache[item["id"]]=msg
            item["done"]=is_done(item["id"])
            item["favorite"]=is_fav(item["id"])
            safe.append(item)
        state.media_cache[chat_id].extend(safe)
        result_holder[0]=safe; done_ev.set()
    state.be.load_media(chat_id,limit,before_id,on_done)
    done_ev.wait(timeout=60)
    return jsonify({"items":result_holder[0] or []})

# Thumbnails
def _locate_downloaded_path(msg_id):
    """Find an already-downloaded file for this message id, either from this
    session's download log or by reconstructing the expected path from any
    cached media item (covers files downloaded in a previous session)."""
    log_entry = next((r for r in state.download_log if r["id"]==msg_id), None)
    if log_entry and log_entry.get("path") and os.path.exists(log_entry["path"]):
        return log_entry["path"]
    for items in state.media_cache.values():
        for it in items:
            if it.get("id")==msg_id and it.get("orig_name"):
                sub={"video":"videos","photo":"photos","audio":"audios","document":"docs"}.get(it.get("type"),"docs")
                base_path=os.path.join(DOWNLOAD_FOLDER,sub,it["orig_name"])
                b,e=os.path.splitext(base_path)
                for cand in (base_path, f"{b}_{msg_id}{e}"):
                    if os.path.exists(cand) and os.path.getsize(cand)>0:
                        return cand
    return None

def _generate_thumb_ffmpeg(src_path, out_path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg: return False
    try:
        r = subprocess.run(
            [ffmpeg,"-y","-i",src_path,"-ss","00:00:01.000","-vframes","1",
             "-vf","scale=320:-1", out_path],
            capture_output=True, timeout=20)
        return r.returncode==0 and os.path.exists(out_path) and os.path.getsize(out_path)>0
    except Exception:
        return False

@app.route("/api/thumb/<int:msg_id>")
def api_thumb(msg_id):
    p=os.path.join(THUMB_DIR,f"t{msg_id}.jpg")
    if os.path.exists(p) and os.path.getsize(p)>0:
        return send_file(p,mimetype="image/jpeg")
    msg=state.msg_cache.get(msg_id)
    if msg:
        done_ev=threading.Event(); path_holder=[None]
        def on_each(iid,path): path_holder[0]=path; done_ev.set()
        state.be.get_thumbs([(msg,msg_id)],on_each)
        done_ev.wait(timeout=15)
        if path_holder[0] and os.path.exists(path_holder[0]):
            return send_file(path_holder[0],mimetype="image/jpeg")
    # Telegram-side thumbnail missing entirely - if the file is already
    # downloaded, generate a real thumbnail locally instead of showing nothing.
    local_path=_locate_downloaded_path(msg_id)
    if local_path and local_path.lower().endswith((".mp4",".mkv",".mov",".avi",".webm",".m4v")):
        if _generate_thumb_ffmpeg(local_path, p):
            return send_file(p,mimetype="image/jpeg")
    return "",404

async def _anext_or_none(agen):
    try: return await agen.__anext__()
    except StopAsyncIteration: return None

@app.route("/api/stream/<int:item_id>")
def api_stream(item_id):
    mtype = request.args.get("type","video")
    orig_name = request.args.get("name","") or None

    # 1) Prefer an already-downloaded file on disk - fast path, full native seeking.
    local_path=None
    log_entry=next((r for r in state.download_log if r["id"]==item_id), None)
    if log_entry and log_entry.get("path") and os.path.exists(log_entry["path"]):
        local_path=log_entry["path"]
    elif orig_name:
        sub={"video":"videos","photo":"photos","audio":"audios","document":"docs"}.get(mtype,"docs")
        base_path=os.path.join(DOWNLOAD_FOLDER,sub,orig_name)
        b,e=os.path.splitext(base_path)
        for cand in (base_path, f"{b}_{item_id}{e}"):
            if os.path.exists(cand) and os.path.getsize(cand)>0:
                local_path=cand; break
    if local_path:
        mime=mimetypes.guess_type(local_path)[0] or "application/octet-stream"
        return send_file(local_path, mimetype=mime, conditional=True)

    # 2) Not downloaded yet - stream directly from Telegram, honoring Range requests
    #    so the <video>/<audio> tag can seek without downloading the whole file first.
    if not state.connected: return jsonify({"error":"Not connected"}),400
    msg=state.msg_cache.get(item_id)
    if not msg or not msg.media:
        return jsonify({"error":"Not available yet - open this chat's media grid first"}),404
    if not state.be.turbo:
        return jsonify({"error":"Not connected"}),400
    size=state.be.turbo._sz(msg.media)
    if not size:
        return jsonify({"error":"Unknown file size, cannot stream"}),500

    range_header=request.headers.get("Range")
    if range_header:
        try:
            rng=range_header.split("=")[1]
            start_s,end_s=rng.split("-")
            start=int(start_s) if start_s else 0
            end=int(end_s) if end_s else size-1
        except Exception:
            start,end=0,size-1
    else:
        start,end=0,size-1
    end=min(end,size-1); start=max(0,min(start,end))
    length=end-start+1

    def generate():
        agen=state.be.client.iter_download(msg.media, offset=start, limit=length, request_size=256*1024)
        try:
            while True:
                fut=state.be.run(_anext_or_none(agen))
                chunk=fut.result(timeout=30)
                if chunk is None: break
                yield bytes(chunk)
        finally:
            try: state.be.run(agen.aclose())
            except Exception: pass

    mime=mimetypes.guess_type(orig_name or "")[0] or ("video/mp4" if mtype=="video" else "application/octet-stream")
    headers={"Content-Type":mime,"Accept-Ranges":"bytes","Content-Length":str(length)}
    status=200
    if range_header:
        headers["Content-Range"]=f"bytes {start}-{end}/{size}"
        status=206
    return Response(stream_with_context(generate()), status=status, headers=headers)

# Download
@app.route("/api/download", methods=["POST"])
def api_download():
    if not state.connected: return jsonify({"error":"not connected"}),400
    data=request.json or {}
    ids=data.get("ids",[]); chat_id=data.get("chat_id")
    cached=state.media_cache.get(chat_id,[])
    id_set=set(ids)
    items=[i for i in cached if i["id"] in id_set]
    new_items=[i for i in items if not is_done(i["id"])]
    skip=len(items)-len(new_items)
    if not new_items: return jsonify({"ok":True,"queued":0,"skipped":skip})
    state.dl_queue.extend(new_items)
    state.dl_total=len(state.dl_queue)
    persist_q(state.dl_queue)
    if not state.dl_active: _process_queue()
    return jsonify({"ok":True,"queued":len(new_items),"skipped":skip})

@app.route("/api/download/cancel/<int:msg_id>", methods=["POST"])
def api_cancel(msg_id):
    if state.be.turbo: state.be.turbo.cancel(msg_id)
    bus.emit("dl_cancelled",{"id":msg_id})
    return jsonify({"ok":True})

@app.route("/api/download/cancel_all", methods=["POST"])
def api_cancel_all():
    for _id in list(state.active_dl.keys()):
        if state.be.turbo: state.be.turbo.cancel(_id)
    state.dl_queue.clear(); persist_q(state.dl_queue)
    bus.emit("dl_cancelled",{"id":None,"all":True})
    return jsonify({"ok":True})

@app.route("/api/download/pause", methods=["POST"])
def api_pause():
    state.paused=True
    bus.emit("dl_paused",{})
    return jsonify({"ok":True})

@app.route("/api/download/resume", methods=["POST"])
def api_resume():
    state.paused=False
    bus.emit("dl_resumed",{})
    _process_queue()
    return jsonify({"ok":True})

def _remaining():
    return len(state.dl_queue) + len(state.active_dl)

def _process_queue():
    """Keep up to CONCURRENT_FILES downloads in flight at once, refilling
    a slot as soon as it frees up. Safe to call repeatedly/re-entrantly."""
    if not state.dl_queue and not state.active_dl:
        state.dl_active=False; clear_q()
        bus.emit("dl_all_done",{
            "files":state.session_files,
            "mb":round(state.session_bytes/1_048_576,1),
            "folder":DOWNLOAD_FOLDER})
        return
    state.dl_active=True
    while (not state.paused) and state.dl_queue and len(state.active_dl) < max(1,CONCURRENT_FILES):
        item=state.dl_queue.pop(0); persist_q(state.dl_queue)
        state.active_dl[item["id"]]=item
        name=item.get("orig_name") or f"{item['type']} #{item['id']}"
        state.current_dl_name=name
        bus.emit("dl_start",{
            "id":item["id"],"name":name,"type":item["type"],
            "size_mb":item.get("size_mb",0),
            "active":len(state.active_dl),"remaining":_remaining(),
            "queue_total":state.dl_total})
        msg=state.msg_cache.get(item["id"])
        if not msg:
            state.active_dl.pop(item["id"],None)
            bus.emit("dl_error",{"id":item["id"],"name":name,"msg":"Message not cached"})
            continue

        def on_prog(pct,spd,dl,tot,eta,_id=item["id"]):
            state.speed_history.append(spd)
            bus.emit("dl_progress",{
                "id":_id,"pct":pct,"spd":round(spd,2),
                "dl_mb":round(dl/1_048_576,2),"tot_mb":round(tot/1_048_576,2),
                "eta":fmt_eta(eta),"active":len(state.active_dl),
                "remaining":_remaining(),"queue_total":state.dl_total})

        def on_done(ok,path,name_,_item=item):
            _id=_item["id"]
            state.active_dl.pop(_id,None)
            if ok and path:
                state.session_files+=1
                sz=os.path.getsize(path) if path and os.path.exists(path) else 0
                state.session_bytes+=sz
                state.download_log.append({
                    "id":_id,"name":name_ or _item.get("orig_name") or f"#{_id}",
                    "size_mb":round(sz/1_048_576,2),"path":path,
                    "time":datetime.now().isoformat(timespec="seconds")})
                bus.emit("dl_done",{
                    "id":_id,"name":name_ or _item.get("orig_name") or f"#{_id}",
                    "path":path,"size_mb":round(sz/1_048_576,2),
                    "remaining":_remaining(),"queue_total":state.dl_total})
            elif ok and path is None:
                bus.emit("dl_skipped",{"id":_id,"name":name_})
            else:
                bus.emit("dl_error",{"id":_id,"name":_item.get("orig_name") or f"#{_id}","msg":str(path)})
            _process_queue()

        state.be.download(msg,item["type"],on_prog,on_done)

def _on_new_media(item):
    """Called from the Telethon event loop thread when a new media message
    arrives in a watched chat. Caches the message and notifies the UI;
    optionally auto-queues it for download if enabled in settings."""
    msg=item.get("msg")
    if msg is not None: state.msg_cache[item["id"]]=msg
    payload={k:v for k,v in item.items() if k!="msg"}
    chat_id=item["chat_id"]
    state.media_cache.setdefault(chat_id,[]).insert(0,payload)
    bus.emit("new_media",payload)
    if CFG.get("auto_watch") and not is_done(item["id"]):
        state.dl_queue.append(payload)
        state.dl_total=len(state.dl_queue)+len(state.active_dl)+state.session_files
        persist_q(state.dl_queue)
        if not state.dl_active: _process_queue()

# Stats
@app.route("/api/search")
def api_search():
    if not state.connected: return jsonify({"error":"not connected"}),400
    q = request.args.get("q","").lower()
    chat_id = int(request.args.get("chat_id",0))
    cached = state.media_cache.get(chat_id, [])
    results = [i for i in cached if q in (i.get("orig_name","") or "").lower() or q in i.get("type","").lower()]
    return jsonify({"items": results, "count": len(results)})

@app.route("/api/stats")
def api_stats():
    elapsed=int(time.monotonic()-state.session_start)
    h,r=divmod(elapsed,3600); m,s=divmod(r,60)
    speeds=list(state.speed_history)
    avg_spd=sum(speeds)/len(speeds) if speeds else 0
    return jsonify({
        "files":state.session_files,"mb":round(state.session_bytes/1_048_576,1),
        "elapsed":f"{h}h {m:02d}m {s:02d}s" if h else f"{m}m {s:02d}s",
        "avg_spd":round(avg_spd,2),"speed_history":[round(x,2) for x in speeds[-20:]],
        "queue_len":len(state.dl_queue),"folder":DOWNLOAD_FOLDER})

@app.route("/api/open_folder", methods=["POST"])
def api_open_folder():
    body=request.json or {}
    folder=body.get("folder") or DOWNLOAD_FOLDER
    os.makedirs(folder,exist_ok=True)
    try:
        if sys.platform=="win32":    os.startfile(folder)
        elif sys.platform=="darwin": subprocess.Popen(["open",folder])
        else:                        subprocess.Popen(["xdg-open",folder])
    except Exception as e: return jsonify({"ok":False,"error":str(e)})
    return jsonify({"ok":True})

@app.route("/api/favorite", methods=["POST"])
def api_favorite():
    data=request.json or {}
    item_id=data.get("id")
    if item_id is None: return jsonify({"ok":False,"error":"Missing id"}),400
    on=toggle_fav(item_id)
    return jsonify({"ok":True,"favorite":on})

@app.route("/api/clear_history", methods=["POST"])
def api_clear_history():
    global _dl_db
    _dl_db=set(); _sj(DL_DB_FILE,[])
    return jsonify({"ok":True})

@app.route("/api/export_history")
def api_export_history():
    import csv, io
    buf=io.StringIO()
    w=csv.writer(buf)
    w.writerow(["id","name","size_mb","path","downloaded_at"])
    for row in state.download_log:
        w.writerow([row["id"],row["name"],row["size_mb"],row["path"],row["time"]])
    out=buf.getvalue()
    fname=f"apex_download_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(out, mimetype="text/csv",
        headers={"Content-Disposition":f'attachment; filename="{fname}"'})

# -- 4K upscaling (FFmpeg-based resize/interpolation, NOT AI super-resolution) --
def ffmpeg_available():
    return shutil.which("ffmpeg") is not None

_gpu_encoder_cache = {"checked": False, "encoder": None, "label": None}

def detect_gpu_encoder():
    """Detect an available hardware video encoder. Prefers NVIDIA NVENC (fast on
    RTX/GTX cards), falls back to Intel QuickSync or AMD AMF, then None (CPU)."""
    if _gpu_encoder_cache["checked"]:
        return _gpu_encoder_cache["encoder"], _gpu_encoder_cache["label"]
    encoder=None; label=None
    if ffmpeg_available():
        try:
            out = subprocess.run(["ffmpeg","-hide_banner","-encoders"],
                                  capture_output=True, text=True, timeout=10).stdout
            for cand, lbl in (("hevc_nvenc","NVIDIA NVENC (HEVC)"),
                               ("h264_nvenc","NVIDIA NVENC"),
                               ("h264_qsv","Intel QuickSync"),
                               ("h264_amf","AMD AMF")):
                if cand in out:
                    encoder, label = cand, lbl
                    break
        except Exception: pass
    _gpu_encoder_cache.update(checked=True, encoder=encoder, label=label)
    return encoder, label

def _venc_args(encoder):
    if encoder and encoder.endswith("_nvenc"):
        return ["-c:v",encoder,"-preset","p5","-rc","vbr","-cq","19","-b:v","0"]
    if encoder=="h264_qsv":
        return ["-c:v","h264_qsv","-global_quality","19"]
    if encoder=="h264_amf":
        return ["-c:v","h264_amf","-quality","quality","-rc","cqp","-qp_i","19","-qp_p","19"]
    return ["-c:v","libx264","-preset","medium","-crf","18"]

def _probe_duration_sec(path):
    ffprobe = shutil.which("ffprobe")
    if not ffprobe: return 0
    try:
        out = subprocess.run(
            [ffprobe,"-v","error","-show_entries","format=duration",
             "-of","default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=15)
        return float(out.stdout.strip())
    except Exception:
        return 0

def _ffmpeg_upscale_pass(src_path, out_path, encoder, dur, item_id):
    """Runs one ffmpeg encode pass, streaming progress via SSE. Returns True on success."""
    cmd = ["ffmpeg","-y","-i",src_path,
           "-vf","scale=3840:2160:force_original_aspect_ratio=decrease:flags=lanczos,"
                 "pad=3840:2160:(ow-iw)/2:(oh-ih)/2:color=black",
           *_venc_args(encoder),
           "-c:a","copy","-progress","pipe:1","-nostats", out_path]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             text=True, bufsize=1)
    for line in proc.stdout:
        line=line.strip()
        if line.startswith("out_time_ms=") and dur>0:
            try:
                us=int(line.split("=")[1])
                pct=max(0,min(99,int((us/1_000_000)/dur*100)))
                bus.emit("upscale_progress",{"id":item_id,"pct":pct})
            except Exception: pass
        elif line=="progress=end":
            break
    proc.wait(timeout=30)
    return proc.returncode==0 and os.path.exists(out_path) and os.path.getsize(out_path)>0

def _run_upscale(item_id, src_path):
    name=os.path.basename(src_path)
    if not ffmpeg_available():
        bus.emit("upscale_error",{"id":item_id,"name":name,
            "msg":"ffmpeg not found. Install it from ffmpeg.org and add it to your system PATH."})
        return
    base,_ = os.path.splitext(src_path)
    out_path = f"{base}_4K.mp4"
    dur = _probe_duration_sec(src_path)
    encoder, label = detect_gpu_encoder()
    bus.emit("upscale_start",{"id":item_id,"name":name,
        "engine": f"GPU ({label})" if encoder else "CPU (no GPU encoder detected)"})
    try:
        ok = _ffmpeg_upscale_pass(src_path, out_path, encoder, dur, item_id)
        if not ok and encoder:
            # GPU path failed (driver/codec edge case) - fall back to CPU once.
            log.warning(f"GPU encode ({encoder}) failed for {name}, retrying on CPU")
            bus.emit("upscale_progress",{"id":item_id,"pct":0})
            try:
                if os.path.exists(out_path): os.remove(out_path)
            except Exception: pass
            ok = _ffmpeg_upscale_pass(src_path, out_path, None, dur, item_id)
        if ok:
            bus.emit("upscale_done",{"id":item_id,"name":os.path.basename(out_path),"path":out_path})
        else:
            try:
                if os.path.exists(out_path): os.remove(out_path)
            except Exception: pass
            bus.emit("upscale_error",{"id":item_id,"name":name,"msg":"ffmpeg failed on both GPU and CPU paths"})
    except Exception as e:
        bus.emit("upscale_error",{"id":item_id,"name":name,"msg":str(e)})

@app.route("/api/gpu_status")
def api_gpu_status():
    encoder,label = detect_gpu_encoder()
    return jsonify({"available":bool(encoder),"encoder":encoder,"label":label})

# -- True AI upscaling via Real-ESRGAN-ncnn-vulkan (adds real detail, GPU-accelerated
#    via Vulkan). NOT bundled - it's a ~70MB third-party binary+model; auto-detected
#    if the user has downloaded it. See README "AI Upscale setup". --------------------
def realesrgan_path():
    exe_name = "realesrgan-ncnn-vulkan.exe" if sys.platform=="win32" else "realesrgan-ncnn-vulkan"
    try:
        base_dir = os.path.dirname(os.path.abspath(
            sys.executable if getattr(sys,"frozen",False) else os.path.abspath(__file__)))
    except Exception:
        base_dir = os.getcwd()
    local = os.path.join(base_dir,"tools","realesrgan",exe_name)
    if os.path.exists(local): return local
    return shutil.which(exe_name)

def ai_upscale_available():
    return realesrgan_path() is not None

@app.route("/api/ai_upscale_status")
def api_ai_upscale_status():
    p = realesrgan_path()
    return jsonify({"available": p is not None, "path": p})

def _probe_fps(path):
    ffprobe = shutil.which("ffprobe")
    if not ffprobe: return "30"
    try:
        r = subprocess.run([ffprobe,"-v","error","-select_streams","v:0",
            "-show_entries","stream=r_frame_rate","-of","default=noprint_wrappers=1:nokey=1",path],
            capture_output=True, text=True, timeout=10)
        return r.stdout.strip() or "30"
    except Exception:
        return "30"

def _run_ai_upscale(item_id, src_path):
    name=os.path.basename(src_path)
    resr = realesrgan_path()
    if not resr:
        bus.emit("upscale_error",{"id":item_id,"name":name,
            "msg":"Real-ESRGAN not found. See README 'AI Upscale setup' - it's a one-time manual download (not bundled, ~70MB)."})
        return
    if not ffmpeg_available():
        bus.emit("upscale_error",{"id":item_id,"name":name,"msg":"ffmpeg not found."})
        return
    base,_ = os.path.splitext(src_path)
    out_path = f"{base}_4K_AI.mp4"
    work = f"{base}_ai_work"
    frames_in = os.path.join(work,"in"); frames_out = os.path.join(work,"out")
    try:
        shutil.rmtree(work, ignore_errors=True)
        os.makedirs(frames_in, exist_ok=True); os.makedirs(frames_out, exist_ok=True)
        fps = _probe_fps(src_path)
        dur = _probe_duration_sec(src_path)

        bus.emit("upscale_start",{"id":item_id,"name":name,
            "engine":"AI (Real-ESRGAN, GPU) — extracting frames"})
        bus.emit("upscale_progress",{"id":item_id,"pct":1})

        # 1) Extract every frame as a JPEG (quality 2 = near-lossless)
        subprocess.run(["ffmpeg","-y","-i",src_path,"-qscale:v","2",
                         os.path.join(frames_in,"f_%06d.jpg")],
                        capture_output=True, timeout=1800)
        total_frames = len([f for f in os.listdir(frames_in) if f.endswith(".jpg")])
        if total_frames==0:
            raise RuntimeError("Frame extraction produced no frames - is this a valid video file?")

        # 2) Run Real-ESRGAN over the whole folder; poll output count for progress
        bus.emit("upscale_progress",{"id":item_id,"pct":3})
        proc = subprocess.Popen([resr,"-i",frames_in,"-o",frames_out,
                                  "-n","realesrgan-x4plus","-s","4"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        while proc.poll() is None:
            done = len(os.listdir(frames_out)) if os.path.exists(frames_out) else 0
            pct = 3 + min(82, int(done/max(total_frames,1)*82))
            bus.emit("upscale_progress",{"id":item_id,"pct":pct})
            time.sleep(1.5)
        if proc.returncode not in (0,None):
            raise RuntimeError(f"Real-ESRGAN exited with code {proc.returncode}")

        # 3) Re-encode AI-upscaled frames into a 4K video, reattaching original audio
        encoder,_ = detect_gpu_encoder()
        bus.emit("upscale_progress",{"id":item_id,"pct":86})
        cmd = ["ffmpeg","-y","-framerate",fps,"-i",os.path.join(frames_out,"f_%06d.jpg"),
               "-i",src_path,"-map","0:v:0","-map","1:a:0?",
               "-vf","scale=3840:2160:force_original_aspect_ratio=decrease:flags=lanczos,"
                     "pad=3840:2160:(ow-iw)/2:(oh-ih)/2:color=black",
               *_venc_args(encoder), "-c:a","aac","-b:a","192k","-shortest",
               "-progress","pipe:1","-nostats", out_path]
        proc2 = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  text=True, bufsize=1)
        for line in proc2.stdout:
            line=line.strip()
            if line.startswith("out_time_ms=") and dur>0:
                try:
                    us=int(line.split("=")[1])
                    pct=86+max(0,min(13,int((us/1_000_000)/dur*13)))
                    bus.emit("upscale_progress",{"id":item_id,"pct":pct})
                except Exception: pass
            elif line=="progress=end":
                break
        proc2.wait(timeout=120)
        if proc2.returncode!=0 or not os.path.exists(out_path) or os.path.getsize(out_path)==0:
            raise RuntimeError("Final video encode failed")

        bus.emit("upscale_progress",{"id":item_id,"pct":100})
        bus.emit("upscale_done",{"id":item_id,"name":os.path.basename(out_path),"path":out_path})
    except Exception as e:
        bus.emit("upscale_error",{"id":item_id,"name":name,"msg":str(e)})
    finally:
        shutil.rmtree(work, ignore_errors=True)

@app.route("/api/ai_upscale", methods=["POST"])
def api_ai_upscale():
    data=request.json or {}
    src=data.get("path",""); item_id=data.get("id","")
    if not src: return jsonify({"ok":False,"error":"Missing file path"}),400
    try:
        real_src=os.path.realpath(src)
        real_root=os.path.realpath(DOWNLOAD_FOLDER)
        if not (real_src==real_root or real_src.startswith(real_root+os.sep)):
            return jsonify({"ok":False,"error":"File must be inside your download folder"}),400
        if not os.path.exists(real_src):
            return jsonify({"ok":False,"error":"File not found on disk"}),404
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)}),400
    if not ai_upscale_available():
        return jsonify({"ok":False,"error":"Real-ESRGAN not installed. See README 'AI Upscale setup'."}),400
    if not ffmpeg_available():
        return jsonify({"ok":False,"error":"ffmpeg not installed or not in PATH"}),400
    threading.Thread(target=_run_ai_upscale,args=(item_id,real_src),daemon=True).start()
    return jsonify({"ok":True})

@app.route("/api/ffmpeg_status")
def api_ffmpeg_status():
    return jsonify({"available":ffmpeg_available()})

@app.route("/api/upscale", methods=["POST"])
def api_upscale():
    data=request.json or {}
    src=data.get("path",""); item_id=data.get("id","")
    if not src: return jsonify({"ok":False,"error":"Missing file path"}),400
    try:
        real_src=os.path.realpath(src)
        real_root=os.path.realpath(DOWNLOAD_FOLDER)
        if not (real_src == real_root or real_src.startswith(real_root+os.sep)):
            return jsonify({"ok":False,"error":"File must be inside your download folder"}),400
        if not os.path.exists(real_src):
            return jsonify({"ok":False,"error":"File not found on disk"}),404
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)}),400
    if not ffmpeg_available():
        return jsonify({"ok":False,"error":"ffmpeg not installed or not in PATH. Get it at ffmpeg.org/download.html"}),400
    threading.Thread(target=_run_upscale,args=(item_id,real_src),daemon=True).start()
    return jsonify({"ok":True})

@app.route("/api/check_update")
def api_check_update():
    if "YOUR_GITHUB_USERNAME" in GITHUB_REPO:
        return jsonify({"ok":False,"error":"GITHUB_REPO not configured"})
    try:
        import urllib.request, json as _json
        req=urllib.request.Request(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
            headers={"User-Agent":"TelegramAPEX-Updater"})
        with urllib.request.urlopen(req,timeout=5) as r:
            data=_json.loads(r.read().decode())
        latest=(data.get("tag_name") or "").lstrip("vV")
        return jsonify({
            "ok":True,"current":APP_VERSION,"latest":latest or APP_VERSION,
            "update_available":bool(latest) and latest!=APP_VERSION,
            "url":data.get("html_url","")})
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)})

@app.route("/")
def index():
    resp = Response(HTML_UI, content_type="text/html; charset=utf-8")
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


HTML_UI = """<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>APEX v10 ULTRA - Telegram Media Browser</title>
<style>
/* ===================== DESIGN TOKENS ===================== */
:root{
  --bg0:#04070d;--bg1:#070c16;--bg2:#0b1220;--bg3:#111b2e;--bg4:#18263f;--bg5:#1f3050;
  --acc:#38bdf8;--acc2:#818cf8;--acc3:#2dd4bf;--acc4:#a78bfa;
  --grn:#22c55e;--yel:#fbbf24;--red:#f87171;--org:#fb923c;--pnk:#f472b6;
  --tx1:#f0f6ff;--tx2:#8fa3bf;--tx3:#3d5270;
  --card:#070d1a;--card2:#0c1525;
  --r:14px;--rsm:8px;--rxs:5px;
  --sh:0 8px 40px #00000099;
  --glow-acc:0 0 30px #38bdf840;--glow-grn:0 0 30px #22c55e40;
  --tr:0.16s cubic-bezier(.4,0,.2,1);
  --glass:rgba(255,255,255,0.035);--gb:rgba(255,255,255,0.07);
  --sidebar-w:300px;
}
[data-theme="light"]{
  --bg0:#f0f4fa;--bg1:#e4eaf5;--bg2:#d5dff0;--bg3:#c0cde3;--bg4:#a8bcda;--bg5:#8fa8cc;
  --card:#fff;--card2:#eef2fc;--tx1:#0d1829;--tx2:#2d4060;--tx3:#6080a0;
  --glass:rgba(255,255,255,.6);--gb:rgba(0,0,0,.08);
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;overflow:hidden;font-family:'Segoe UI',system-ui,-apple-system,sans-serif;background:var(--bg0);color:var(--tx1);font-size:14px}
::-webkit-scrollbar{width:4px;height:4px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--bg4);border-radius:2px}
::-webkit-scrollbar-thumb:hover{background:var(--bg5)}

/* ===================== LAYOUT ===================== */
#app{display:flex;flex-direction:column;height:100vh;overflow:hidden}
#topbar{height:58px;background:linear-gradient(90deg,var(--bg1) 0%,var(--bg2) 100%);
  border-bottom:1px solid var(--gb);display:flex;align-items:center;
  padding:0 16px 0 0;gap:0;flex-shrink:0;position:relative;z-index:200}
#body{flex:1;display:flex;overflow:hidden;min-height:0}
#sidebar{width:var(--sidebar-w);min-width:var(--sidebar-w);background:var(--bg1);
  border-right:1px solid var(--gb);display:flex;flex-direction:column;overflow:hidden;
  transition:width .3s cubic-bezier(.4,0,.2,1),min-width .3s cubic-bezier(.4,0,.2,1)}
#sidebar.collapsed{width:0;min-width:0;overflow:hidden}
#main{flex:1;display:flex;flex-direction:column;overflow:hidden;min-width:0}
#toolbar{background:var(--bg1);border-bottom:1px solid var(--gb);
  padding:8px 14px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;flex-shrink:0}
#media-area{flex:1;overflow-y:auto;padding:16px;background:var(--bg0);position:relative;scroll-behavior:smooth}
#dl-panel{background:linear-gradient(135deg,var(--bg1),var(--bg2));
  border-top:1px solid var(--gb);padding:10px 16px;display:none;flex-direction:column;gap:7px;flex-shrink:0}
#dl-panel.active{display:flex}
#botbar{height:28px;background:var(--bg2);border-top:1px solid var(--gb);
  display:flex;align-items:center;padding:0 14px;gap:14px;font-size:11px;color:var(--tx3);flex-shrink:0}

/* ===================== PARTICLES & CANVAS ===================== */
#particles{position:fixed;inset:0;pointer-events:none;z-index:0}
#aurora{position:fixed;inset:0;pointer-events:none;z-index:0;opacity:.18}

/* ===================== LOGO ===================== */
.logo-wrap{width:var(--sidebar-w);min-width:var(--sidebar-w);height:100%;
  display:flex;align-items:center;padding:0 16px;gap:10px;
  border-right:1px solid var(--gb);flex-shrink:0;position:relative;
  background:linear-gradient(135deg,rgba(56,189,248,.06),rgba(129,140,248,.04));
  transition:width .3s cubic-bezier(.4,0,.2,1);overflow:hidden}
.logo-icon{width:36px;height:36px;flex-shrink:0;position:relative}
.logo-icon svg{width:36px;height:36px;filter:drop-shadow(0 0 12px #38bdf890)}
.logo-text{display:flex;flex-direction:column;white-space:nowrap;overflow:hidden}
.logo-name{font-size:17px;font-weight:900;letter-spacing:-.5px;line-height:1;
  background:linear-gradient(135deg,var(--acc) 0%,var(--acc2) 50%,var(--acc4) 100%);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
  background-size:200% auto;animation:gradShift 4s linear infinite}
.logo-sub{font-size:9px;color:var(--tx3);letter-spacing:1.5px;text-transform:uppercase;font-weight:600;margin-top:2px}
.logo-wrap::after{content:'';position:absolute;left:0;top:0;right:0;height:2px;
  background:linear-gradient(90deg,transparent,#38bdf860,transparent);
  animation:scanline 3s linear infinite;pointer-events:none}

/* ===================== TOPBAR ===================== */
#topbar-right{display:flex;align-items:center;gap:8px;flex:1;padding:0 0 0 14px}
#conn-badge{display:flex;align-items:center;gap:7px;background:var(--bg3);
  padding:5px 13px;border-radius:20px;font-size:12px;cursor:default;border:1px solid var(--gb);transition:var(--tr)}
#conn-dot{width:8px;height:8px;border-radius:50%;background:var(--tx3);transition:var(--tr);flex-shrink:0}
#conn-dot.connected{background:var(--grn);box-shadow:0 0 0 3px #22c55e25,0 0 12px var(--grn);animation:connPop .4s ease,heartbeat 2s ease infinite 1s}
#conn-dot.connecting{background:var(--yel);animation:pulse 1.2s infinite}
#conn-status{font-size:12px;font-weight:600;color:var(--tx2)}
#me-badge{display:flex;align-items:center;gap:7px;background:var(--bg3);
  padding:5px 12px;border-radius:20px;font-size:12px;border:1px solid var(--gb);
  animation:slideInRight .3s ease}
#me-avatar{width:22px;height:22px;border-radius:50%;background:linear-gradient(135deg,var(--acc),var(--acc2));
  display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:800;color:#000;flex-shrink:0}
#me-name{font-size:12px;font-weight:600;color:var(--tx1);max-width:120px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tb-spacer{flex:1}
.icon-btn{background:none;border:none;color:var(--tx2);cursor:pointer;
  padding:7px 10px;border-radius:var(--rsm);font-size:18px;display:flex;
  align-items:center;justify-content:center;transition:all .2s ease;position:relative;
  white-space:nowrap;min-width:38px;min-height:38px;user-select:none;-webkit-user-select:none;line-height:1}
.icon-btn:hover{background:var(--bg3);color:var(--tx1);transform:translateY(-1px)}
.icon-btn:active{transform:scale(.92)}
.icon-btn.active-nav{background:var(--acc);color:#000}
.icon-btn .badge{position:absolute;top:3px;right:3px;background:var(--red);color:#fff;
  border-radius:8px;padding:1px 5px;font-size:9px;font-weight:800;line-height:1.4;animation:badgePop .35s ease}
#topbar::after{content:'';position:absolute;inset:0;
  background:linear-gradient(90deg,#38bdf805,#818cf808,#2dd4bf05,#a78bfa05,#38bdf805);
  background-size:400% 100%;animation:gradFlow 8s ease infinite;pointer-events:none;z-index:-1}

/* ===================== STATS BAR ===================== */
#stats-bar{padding:24px;display:none;flex-direction:column;gap:22px;max-width:900px;margin:0 auto;width:100%;
  animation:fadeIn .25s ease}
.stats-dashboard-hdr h2{font-size:19px;font-weight:900;margin:0 0 2px}
.stats-dashboard-hdr .sub{font-size:12px;color:var(--tx3)}
.stats-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
.stat-c{background:var(--bg3);border-radius:10px;padding:10px 14px;border:1px solid var(--gb);
  transition:var(--tr);position:relative;overflow:hidden}
.stat-c:hover{border-color:var(--acc);transform:translateY(-1px)}
.stat-c::before{content:'';position:absolute;inset:0;
  background:linear-gradient(135deg,rgba(56,189,248,.04),transparent);pointer-events:none}
.stat-l{font-size:10px;color:var(--tx3);text-transform:uppercase;letter-spacing:.8px;font-weight:700;margin-bottom:4px}
.stat-v{font-size:22px;font-weight:900;color:var(--tx1);transition:all .4s ease;font-variant-numeric:tabular-nums}
.stat-v.a{color:var(--acc)}
.stat-v.g{color:var(--grn)}
.stat-mini-bar{height:3px;background:var(--bg4);border-radius:2px;margin-top:6px;overflow:hidden}
.stat-mini-fill{height:100%;background:linear-gradient(90deg,var(--acc),var(--acc2));border-radius:2px;
  transition:width .6s cubic-bezier(.4,0,.2,1)}
.stats-breakdown{background:var(--bg2);border:1px solid var(--gb);border-radius:12px;padding:16px}
.stats-breakdown-hdr{font-size:12px;font-weight:800;color:var(--tx2);margin-bottom:12px;letter-spacing:.3px}
.sb-row{display:flex;align-items:center;gap:10px;margin-bottom:9px}
.sb-label{font-size:12px;color:var(--tx2);width:90px;flex-shrink:0}
.sb-count{font-size:12px;color:var(--tx1);font-weight:700;width:32px;text-align:right;flex-shrink:0;font-variant-numeric:tabular-nums}
.stats-speed-panel{background:var(--bg2);border:1px solid var(--gb);border-radius:12px;padding:16px}
.stats-speed-panel canvas{width:100%;height:90px;border-radius:8px}

/* ===================== MAIN TAB BAR ===================== */
#main-tabs{display:flex;align-items:center;gap:2px;padding:0 20px;background:var(--bg1);
  border-bottom:1px solid var(--gb);flex-shrink:0;position:relative}
.main-tab{background:none;border:none;color:var(--tx3);font-size:13px;font-weight:700;
  padding:13px 18px;cursor:pointer;display:flex;align-items:center;gap:7px;
  position:relative;transition:color .18s ease;white-space:nowrap}
.main-tab-ico{font-size:14px}
.main-tab:hover{color:var(--tx1)}
.main-tab.active{color:var(--acc)}
.main-tab .badge{position:static;margin-left:2px;background:var(--red);color:#fff;
  border-radius:8px;padding:1px 6px;font-size:9px;font-weight:800}
.main-tab-indicator{position:absolute;bottom:0;left:0;height:2.5px;width:0;
  background:linear-gradient(90deg,var(--acc),var(--acc2));border-radius:2px;
  transition:left .25s cubic-bezier(.4,0,.2,1),width .25s cubic-bezier(.4,0,.2,1)}

/* ===================== SIDEBAR ===================== */
#sidebar-header{padding:10px 12px;border-bottom:1px solid var(--gb);flex-shrink:0;display:flex;flex-direction:column;gap:8px}
.search-wrap{position:relative}
.search-icon{position:absolute;left:10px;top:50%;transform:translateY(-50%);color:var(--tx3);font-size:13px;pointer-events:none}
#search-box{width:100%;background:var(--bg2);border:1.5px solid var(--bg3);
  border-radius:var(--rsm);padding:8px 10px 8px 32px;color:var(--tx1);
  font-size:13px;outline:none;transition:var(--tr)}
#search-box:focus{border-color:var(--acc);box-shadow:0 0 0 3px #38bdf815}
#search-box::placeholder{color:var(--tx3)}
.sidebar-tabs{display:flex;gap:4px}
.stab{flex:1;padding:5px 4px;border-radius:var(--rxs);border:none;
  background:transparent;color:var(--tx3);font-size:11px;font-weight:700;
  cursor:pointer;transition:var(--tr);text-align:center}
.stab.active{background:var(--bg3);color:var(--acc)}
.stab:hover:not(.active){color:var(--tx2)}
#dialog-list{flex:1;overflow-y:auto;padding:4px}
.dialog-item{display:flex;align-items:center;gap:10px;padding:9px 10px;
  border-radius:10px;cursor:pointer;transition:all .18s ease;
  border:1px solid transparent;margin-bottom:1px;position:relative;overflow:hidden}
.dialog-item::before{content:'';position:absolute;left:-100%;top:0;bottom:0;width:100%;
  background:linear-gradient(90deg,transparent,rgba(56,189,248,.06),transparent);
  transition:left .4s ease}
.dialog-item:hover::before{left:100%}
.dialog-item:hover{background:var(--bg3);transform:translateX(2px)}
.dialog-item.active{background:linear-gradient(135deg,#38bdf810,#818cf808);
  border-color:#38bdf825;box-shadow:inset 3px 0 0 var(--acc)}
.d-avatar{width:40px;height:40px;border-radius:50%;display:flex;align-items:center;
  justify-content:center;font-weight:900;font-size:16px;flex-shrink:0;transition:transform .2s ease}
.dialog-item:hover .d-avatar{transform:scale(1.08)}
.d-info{flex:1;min-width:0}
.d-name{font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.d-sub{font-size:10px;color:var(--tx3);margin-top:2px;display:flex;align-items:center;gap:4px}
.d-type-pill{font-size:9px;font-weight:700;padding:1px 5px;border-radius:4px;text-transform:uppercase;letter-spacing:.4px}
.d-unread{background:linear-gradient(135deg,var(--acc),var(--acc2));color:#000;
  border-radius:10px;padding:2px 7px;font-size:10px;font-weight:800;min-width:20px;text-align:center;flex-shrink:0}

/* ===================== TOOLBAR ===================== */
.filter-tabs{display:flex;gap:2px;background:var(--bg2);border-radius:24px;padding:3px;border:1px solid var(--gb)}
.ftab{padding:5px 13px;border-radius:18px;border:none;background:none;color:var(--tx2);
  font-size:12px;font-weight:700;cursor:pointer;transition:all .2s ease;white-space:nowrap;display:flex;align-items:center;gap:5px}
.ftab.active{background:linear-gradient(135deg,var(--acc),var(--acc2));color:#000;box-shadow:0 2px 10px #38bdf840}
.ftab:hover:not(.active){background:var(--bg3);color:var(--tx1);transform:translateY(-1px)}
.ftab .cnt{font-size:9px;opacity:.7;font-weight:800}
.tb-btn{background:var(--bg3);border:1px solid var(--gb);color:var(--tx1);
  padding:6px 13px;border-radius:var(--rsm);font-size:12px;font-weight:700;cursor:pointer;
  transition:all .18s ease;white-space:nowrap;display:flex;align-items:center;gap:6px;position:relative;overflow:hidden}
.tb-btn::after{content:'';position:absolute;inset:0;background:radial-gradient(circle at center,rgba(255,255,255,.15) 0%,transparent 70%);
  transform:scale(0);opacity:0;transition:transform .3s,opacity .3s;border-radius:inherit}
.tb-btn:active::after{transform:scale(2);opacity:1;transition:none}
.tb-btn:hover{background:var(--bg4);transform:translateY(-1px);box-shadow:0 4px 12px #00000040}
.tb-btn.primary{background:linear-gradient(135deg,var(--acc),var(--acc2));color:#000;border-color:transparent;box-shadow:0 2px 12px #38bdf840}
.tb-btn.primary:hover{box-shadow:var(--glow-acc),0 6px 20px #38bdf840}
.tb-btn.danger{background:linear-gradient(135deg,var(--red),#ff5555);color:#fff;border-color:transparent}
.tb-btn:disabled{opacity:.3;cursor:not-allowed;transform:none}
#sel-info{font-size:12px;color:var(--tx3);min-width:70px;font-weight:600}
.sort-sel{background:var(--bg3);border:1px solid var(--gb);color:var(--tx2);
  padding:6px 10px;border-radius:var(--rsm);font-size:12px;outline:none;cursor:pointer;transition:var(--tr)}
.sort-sel:hover{border-color:var(--acc)}

/* view mode */
.view-toggle{display:flex;gap:2px;background:var(--bg2);border-radius:8px;padding:2px;border:1px solid var(--gb)}
.vtab{padding:5px 8px;border-radius:6px;border:none;background:none;color:var(--tx3);
  font-size:13px;cursor:pointer;transition:var(--tr)}
.vtab.active{background:var(--bg4);color:var(--acc)}

/* ===================== MEDIA GRID ===================== */
#media-grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fill,minmax(185px,1fr))}
#media-grid.list-view{grid-template-columns:1fr}
#empty-state{display:flex;flex-direction:column;align-items:center;justify-content:center;
  min-height:320px;color:var(--tx3);gap:16px;text-align:center;padding:40px}
.empty-icon{font-size:56px;animation:float 3s ease-in-out infinite}
.empty-title{font-size:18px;font-weight:700;color:var(--tx2)}
.empty-sub{font-size:13px;max-width:300px;line-height:1.7;color:var(--tx3)}
#load-more-wrap{display:flex;justify-content:center;padding:20px}
.load-more-btn{background:var(--bg3);border:1px solid var(--bg4);color:var(--tx2);
  padding:10px 32px;border-radius:20px;cursor:pointer;font-size:13px;font-weight:700;
  transition:all .2s ease;position:relative;overflow:hidden}
.load-more-btn:hover{background:var(--bg4);color:var(--tx1);border-color:var(--acc);box-shadow:var(--glow-acc);transform:translateY(-2px)}
.load-more-btn:disabled{opacity:.6;cursor:default;transform:none;box-shadow:none}

/* ===================== DOWNLOADS TAB ===================== */
#downloads-view{padding:20px;display:flex;flex-direction:column;gap:22px;max-width:900px;margin:0 auto;width:100%}
.dlv-section-title{font-size:13px;font-weight:800;color:var(--tx1);letter-spacing:.3px;
  display:flex;align-items:center;gap:8px;margin-bottom:10px}
.dlv-section-title span{font-weight:700;color:var(--acc);font-size:12px;background:var(--bg3);
  padding:1px 8px;border-radius:10px}
.dlv-note{font-size:11px;color:var(--tx3);line-height:1.6;margin-bottom:10px;max-width:640px}
.dlv-note a{color:var(--acc)}
.dlv-list{display:flex;flex-direction:column;gap:8px}
.dlv-empty{color:var(--tx3);font-size:12px;padding:14px;text-align:center;background:var(--bg2);border-radius:var(--rsm)}
.dlv-row{display:flex;align-items:center;gap:10px;background:var(--bg2);border:1px solid var(--gb);
  border-radius:var(--rsm);padding:9px 12px;animation:fadeIn .2s ease}
.dlv-name{font-size:12px;color:var(--tx1);font-weight:600;max-width:340px;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap;flex-shrink:0}
.dlv-meta{font-size:11px;color:var(--tx3);white-space:nowrap;flex-shrink:0}
.dlv-status{font-size:11px;color:var(--acc);white-space:nowrap;font-weight:700}

/* ===================== MEDIA CARD ===================== */
.media-card{background:var(--card);border-radius:var(--r);overflow:hidden;cursor:pointer;
  border:1.5px solid var(--gb);position:relative;display:flex;flex-direction:column;
  box-shadow:0 4px 16px #00000055;
  transition:transform .22s cubic-bezier(.2,0,.1,1),box-shadow .22s cubic-bezier(.2,0,.1,1),border-color .18s;
  transform-style:preserve-3d;will-change:transform;animation:cardIn .3s cubic-bezier(.2,0,.1,1) both}
.media-card::before{content:'';position:absolute;inset:0;border-radius:var(--r);
  background:linear-gradient(135deg,rgba(255,255,255,.055) 0%,transparent 55%);pointer-events:none;z-index:1}
.media-card::after{content:'';position:absolute;inset:0;border-radius:var(--r);
  box-shadow:inset 0 1px 0 rgba(255,255,255,.07),inset 0 -1px 0 rgba(0,0,0,.25);pointer-events:none;z-index:2}
.media-card:hover{transform:translateY(-7px) scale(1.025);
  box-shadow:0 24px 56px #00000088,0 0 0 1px #38bdf828,var(--glow-acc);border-color:#38bdf835}
.media-card.selected{border-color:var(--acc);box-shadow:0 8px 24px #00000060,0 0 0 2px #38bdf845,var(--glow-acc);background:var(--card2)}
.media-card.done .card-name::after{content:' ✓';color:var(--grn);font-weight:800}
.media-card.done{border-color:#22c55e30}

/* List view card */
#media-grid.list-view .media-card{flex-direction:row;height:64px}
#media-grid.list-view .card-thumb{width:80px;min-width:80px;aspect-ratio:unset;height:100%}
#media-grid.list-view .card-body{flex:1;padding:8px 12px;display:flex;align-items:center;gap:12px}
#media-grid.list-view .card-actions{margin-left:auto;flex-shrink:0}

/* Thumb */
.card-thumb{width:100%;aspect-ratio:16/10;background:var(--bg2);position:relative;overflow:hidden;flex-shrink:0}
.card-thumb img{width:100%;height:100%;object-fit:cover;transition:transform .4s ease}
.media-card:hover .card-thumb img{transform:scale(1.1)}
.card-placeholder{width:100%;height:100%;display:flex;align-items:center;justify-content:center;
  font-size:40px;opacity:.2;background:linear-gradient(135deg,var(--bg2),var(--bg3));transition:opacity .2s}
.media-card:hover .card-placeholder{opacity:.35}
.card-hover-overlay{position:absolute;inset:0;background:linear-gradient(transparent 30%,rgba(0,0,0,.88));
  opacity:0;transition:opacity .22s;display:flex;align-items:flex-end;padding:10px;z-index:3}
.media-card:hover .card-hover-overlay{opacity:1}
.card-hover-name{color:#fff;font-size:11px;font-weight:700;text-shadow:0 1px 4px #000;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;width:100%}
.card-rim{position:absolute;inset:-1px;border-radius:var(--r);pointer-events:none;z-index:6;
  opacity:0;transition:opacity .2s;box-shadow:0 0 0 1.5px var(--acc),0 0 18px #38bdf825}
.media-card:hover .card-rim{opacity:1}
.card-badge{position:absolute;top:7px;left:7px;padding:2px 8px;border-radius:8px;
  font-size:9px;font-weight:800;letter-spacing:.5px;text-transform:uppercase;z-index:5;backdrop-filter:blur(6px)}
.badge-video   {background:rgba(129,140,248,.85);color:#fff}
.badge-photo   {background:rgba(56,189,248,.85);color:#000}
.badge-audio   {background:rgba(167,139,250,.85);color:#fff}
.badge-document{background:rgba(45,212,191,.85);color:#000}
.card-dur{position:absolute;bottom:7px;right:7px;background:rgba(0,0,0,.72);color:#fff;
  border-radius:5px;padding:2px 6px;font-size:10px;font-weight:700;z-index:5;backdrop-filter:blur(4px)}
.card-sel{position:absolute;top:7px;right:7px;width:22px;height:22px;border-radius:50%;
  border:2px solid rgba(255,255,255,.45);background:rgba(0,0,0,.4);
  display:flex;align-items:center;justify-content:center;font-size:11px;
  z-index:5;transition:all .18s ease;color:transparent}
.media-card.selected .card-sel{background:var(--acc);border-color:var(--acc);color:#000;transform:scale(1.1)}
.card-star{position:absolute;bottom:7px;left:7px;width:24px;height:24px;border-radius:50%;
  border:none;background:rgba(0,0,0,.45);backdrop-filter:blur(6px);color:rgba(255,255,255,.5);
  font-size:13px;display:flex;align-items:center;justify-content:center;cursor:pointer;
  z-index:6;transition:all .18s ease;line-height:1}
.card-star:hover{background:rgba(0,0,0,.65);color:#fbbf24;transform:scale(1.15)}
.card-star.on{color:#fbbf24;background:rgba(251,191,36,.18)}


/* Card body */
.card-body{padding:10px 12px;display:flex;flex-direction:column;gap:5px;flex:1}
.card-name{font-size:12px;font-weight:700;color:var(--tx1);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:1.3}
.card-meta{display:flex;gap:8px;flex-wrap:wrap}
.card-meta span{font-size:10px;color:var(--tx3);display:flex;align-items:center;gap:3px}
.card-actions{display:flex;gap:6px;margin-top:auto}
.card-btn{flex:1;background:var(--bg3);border:1px solid var(--gb);color:var(--tx2);
  padding:5px 0;border-radius:6px;font-size:11px;font-weight:700;cursor:pointer;
  transition:all .18s ease;text-align:center;position:relative;overflow:hidden}
.card-btn::after{content:'';position:absolute;inset:0;
  background:radial-gradient(circle at center,rgba(56,189,248,.2) 0%,transparent 70%);
  transform:scale(0);opacity:0;transition:transform .25s,opacity .25s;border-radius:inherit}
.card-btn:active::after{transform:scale(2.5);opacity:1;transition:none}
.card-btn:hover{background:var(--bg4);color:var(--tx1);transform:translateY(-1px)}
.card-btn.done-btn{background:linear-gradient(135deg,#22c55e20,#22c55e10);border-color:#22c55e40;color:var(--grn)}
.card-btn.preview-btn{flex:0;padding:5px 10px}
.card-prog{position:absolute;bottom:0;left:0;height:3px;width:0%;
  background:linear-gradient(90deg,var(--acc),var(--acc2));
  transition:width .3s ease;border-radius:0 2px 2px 0;
  box-shadow:0 0 8px var(--acc)}
.card-skeleton{background:linear-gradient(90deg,var(--bg2) 25%,var(--bg3) 50%,var(--bg2) 75%);
  background-size:200% 100%;animation:shimmerBg 1.4s ease-in-out infinite;border-radius:var(--r)}

/* ===================== DOWNLOAD PANEL ===================== */
#dl-hdr{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
#dl-label{font-size:11px;font-weight:800;color:var(--acc);letter-spacing:1.5px;
  text-transform:uppercase;display:flex;align-items:center;gap:8px}
#dl-label::before{content:'';width:8px;height:8px;border-radius:50%;
  background:var(--acc);animation:dlPulse 1s ease-in-out infinite;flex-shrink:0}
#dl-fname{font-size:12px;font-weight:700;color:var(--tx1);max-width:320px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#dl-speed{font-size:13px;font-weight:800;color:var(--grn);min-width:80px;text-align:right;
  font-variant-numeric:tabular-nums}
#dl-eta{font-size:11px;color:var(--tx3);min-width:50px}
#dl-qinfo{font-size:11px;color:var(--acc2);background:var(--bg3);padding:2px 8px;border-radius:10px}
.dl-row{display:flex;align-items:center;gap:10px}
.dl-file-row{display:flex;align-items:center;gap:10px;padding:2px 0;
  animation:fadeIn .2s ease}
.dl-file-name{font-size:11px;color:var(--tx2);max-width:220px;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap;flex-shrink:0}
.dl-file-pct{font-size:10px;color:var(--tx3);min-width:30px;text-align:right;
  font-variant-numeric:tabular-nums;flex-shrink:0}
.dl-file-spd{font-size:10px;color:var(--tx3);min-width:56px;text-align:right;
  flex-shrink:0;font-variant-numeric:tabular-nums}
.prog-track{flex:1;height:6px;background:var(--bg3);border-radius:4px;overflow:hidden;position:relative}
.prog-fill{height:100%;background:linear-gradient(90deg,var(--acc),var(--acc2));
  border-radius:4px;transition:width .2s ease;position:relative}
.prog-fill::after{content:'';position:absolute;inset:0;
  background:linear-gradient(90deg,transparent,rgba(255,255,255,.3),transparent);
  background-size:200% 100%;animation:shimmer 1.5s linear infinite}
#dl-bar-wrap{position:relative}

/* ===================== STATS BAR ===================== */
.stat-c{cursor:default}

/* ===================== MODALS ===================== */
.overlay{position:fixed;inset:0;background:rgba(0,0,0,.75);backdrop-filter:blur(8px);
  display:flex;align-items:center;justify-content:center;z-index:9999;padding:20px;
  animation:fadeIn .2s ease}
.modal{background:linear-gradient(135deg,var(--bg1),var(--bg2));
  border:1px solid var(--gb);border-radius:18px;padding:28px;
  max-width:480px;width:100%;box-shadow:0 40px 80px #00000090,0 0 0 1px rgba(255,255,255,.05);
  position:relative;max-height:90vh;overflow-y:auto;animation:modalIn .3s cubic-bezier(.2,0,.1,1)}
.modal-hdr{display:flex;align-items:flex-start;gap:14px;margin-bottom:22px}
.modal-icon{width:44px;height:44px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:22px;flex-shrink:0}
.modal-icon.blue{background:linear-gradient(135deg,#38bdf820,#38bdf810);border:1px solid #38bdf830}
.modal-icon.purple{background:linear-gradient(135deg,#818cf820,#818cf810);border:1px solid #818cf830}
.modal h2{font-size:18px;font-weight:800;color:var(--tx1);margin-bottom:4px}
.sub{font-size:12px;color:var(--tx3);line-height:1.5}
.form-lbl{display:block;font-size:12px;font-weight:700;color:var(--tx2);margin-bottom:6px;margin-top:14px;text-transform:uppercase;letter-spacing:.6px}
.form-inp{width:100%;background:var(--bg3);border:1.5px solid var(--bg4);border-radius:var(--rsm);
  padding:10px 14px;color:var(--tx1);font-size:14px;outline:none;transition:var(--tr);font-family:inherit}
.form-inp:focus{border-color:var(--acc);box-shadow:0 0 0 3px #38bdf815}
.form-note{font-size:11px;color:var(--tx3);margin-top:6px;line-height:1.6}
.form-note a{color:var(--acc);text-decoration:none}
.divider{border:none;border-top:1px solid var(--gb);margin:16px 0}
.modal-btns{display:flex;gap:10px;margin-top:20px;justify-content:flex-end}
.btn{padding:9px 20px;border-radius:var(--rsm);font-size:13px;font-weight:700;cursor:pointer;transition:all .18s ease;border:none;font-family:inherit}
.btn:hover{transform:translateY(-1px)}
.btn:active{transform:scale(.96)}
.btn-p{background:linear-gradient(135deg,var(--acc),var(--acc2));color:#000;box-shadow:0 2px 12px #38bdf840}
.btn-p:hover{box-shadow:var(--glow-acc),0 6px 20px #38bdf840}
.btn-s{background:var(--bg3);border:1px solid var(--gb);color:var(--tx1)}
.btn-s:hover{background:var(--bg4)}
.preset-row{display:flex;gap:8px;margin-top:4px;flex-wrap:wrap}
.preset-btn{flex:1 1 calc(50% - 4px);min-width:110px;padding:9px 4px;border-radius:var(--rsm);border:1.5px solid var(--bg4);
  background:var(--bg3);color:var(--tx2);font-size:12px;font-weight:700;cursor:pointer;transition:all .18s ease;text-align:center}
.preset-btn:hover{border-color:var(--acc);color:var(--tx1);transform:translateY(-1px)}
.preset-btn.on{background:linear-gradient(135deg,var(--acc)20,var(--acc)10);border-color:var(--acc);color:var(--acc)}
.preview-info{margin-top:14px;padding-top:14px;border-top:1px solid var(--gb)}
.preview-name{font-size:14px;font-weight:700;color:var(--tx1);margin-bottom:6px;word-break:break-all}
.preview-meta{display:flex;gap:14px;flex-wrap:wrap}
.preview-meta span{font-size:12px;color:var(--tx3);background:var(--bg3);padding:3px 10px;border-radius:8px}

/* ===================== CONTEXT MENU ===================== */
#ctx{position:fixed;z-index:9998;background:var(--bg1);border:1px solid var(--gb);
  border-radius:12px;padding:6px;box-shadow:var(--sh),0 0 0 1px rgba(255,255,255,.04);
  display:none;min-width:180px;backdrop-filter:blur(16px);animation:popIn .15s ease}
.ctx-i{padding:8px 13px;border-radius:6px;cursor:pointer;font-size:13px;
  display:flex;align-items:center;gap:10px;transition:var(--tr);font-weight:500;color:var(--tx1)}
.ctx-i:hover{background:var(--bg3);transform:translateX(2px)}
.ctx-i.red{color:var(--red)}
.ctx-sep{border:none;border-top:1px solid var(--gb);margin:4px 0}

/* ===================== NOTIFICATIONS ===================== */
#notif-panel{position:fixed;right:14px;top:62px;width:300px;
  background:var(--bg1);border:1px solid var(--gb);border-radius:12px;
  box-shadow:var(--sh);z-index:9990;display:none;flex-direction:column;overflow:hidden;
  animation:slideDown .2s ease}
#notif-panel.show{display:flex}
.notif-hdr{padding:12px 14px;border-bottom:1px solid var(--gb);font-size:12px;
  font-weight:800;color:var(--tx2);display:flex;justify-content:space-between;align-items:center}
#notif-list{overflow-y:auto;max-height:300px}
.notif-item{padding:10px 14px;border-bottom:1px solid var(--gb);font-size:12px;
  display:flex;gap:10px;align-items:flex-start;transition:var(--tr);animation:slideInRight .2s ease}
.notif-item:hover{background:var(--bg2)}
.notif-ic{font-size:16px;flex-shrink:0;margin-top:1px}
.notif-body{flex:1;line-height:1.5}
.notif-time{font-size:10px;color:var(--tx3);flex-shrink:0}

/* ===================== TOASTS ===================== */
#toasts{position:fixed;right:18px;bottom:40px;z-index:99999;display:flex;flex-direction:column;gap:8px;align-items:flex-end;pointer-events:none}
.toast{display:flex;align-items:center;gap:10px;padding:11px 16px;border-radius:12px;
  font-size:13px;font-weight:600;min-width:200px;max-width:340px;pointer-events:auto;
  box-shadow:0 8px 30px #00000060;border:1px solid var(--gb);backdrop-filter:blur(16px);
  animation:toastIn .3s cubic-bezier(.2,0,.1,1)}
.toast.out{animation:toastOut .3s cubic-bezier(.4,0,1,1) forwards}
.toast.s{background:linear-gradient(135deg,#22c55e18,#22c55e10);border-color:#22c55e40;color:var(--grn)}
.toast.e{background:linear-gradient(135deg,#f8717118,#f8717110);border-color:#f8717140;color:var(--red)}
.toast.w{background:linear-gradient(135deg,#fbbf2418,#fbbf2410);border-color:#fbbf2440;color:var(--yel)}
.toast-msg{flex:1;line-height:1.4}
.toast-x{cursor:pointer;opacity:.6;transition:opacity .15s;font-size:14px;padding:0 2px;color:var(--tx2)}
.toast-x:hover{opacity:1}

/* ===================== BOTBAR ===================== */
#bot-status{color:var(--tx3);font-size:11px}
#bot-hist{max-width:45%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--tx3)}

/* ===================== KEYFRAMES ===================== */
@keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.5;transform:scale(.85)}}
@keyframes heartbeat{0%,100%{box-shadow:0 0 0 3px #22c55e25,0 0 12px var(--grn)}50%{box-shadow:0 0 0 5px #22c55e15,0 0 20px var(--grn)}}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes spinCCW{to{transform:rotate(-360deg)}}
@keyframes fadeIn{from{opacity:0}to{opacity:1}}
@keyframes fadeInUp{from{opacity:0;transform:translateY(18px)}to{opacity:1;transform:none}}
@keyframes slideDown{from{opacity:0;transform:translateY(-10px)}to{opacity:1;transform:none}}
@keyframes cardIn{from{opacity:0;transform:translateY(16px) scale(.95)}to{opacity:1;transform:translateY(0) scale(1)}}
@keyframes slideInLeft{from{opacity:0;transform:translateX(-22px)}to{opacity:1;transform:none}}
@keyframes slideInRight{from{opacity:0;transform:translateX(14px)}to{opacity:1;transform:none}}
@keyframes popIn{0%{transform:scale(.7);opacity:0}70%{transform:scale(1.06)}100%{transform:scale(1);opacity:1}}
@keyframes modalIn{0%{transform:scale(.92) translateY(20px);opacity:0}100%{transform:scale(1) translateY(0);opacity:1}}
@keyframes shimmerBg{0%{background-position:200% 0}100%{background-position:-200% 0}}
@keyframes shimmer{0%{background-position:200% 0}100%{background-position:-200% 0}}
@keyframes borderGlow{0%,100%{box-shadow:inset 3px 0 0 var(--acc),0 0 8px #38bdf820}50%{box-shadow:inset 3px 0 0 var(--acc),0 0 20px #38bdf840}}
@keyframes float{0%,100%{transform:translateY(0)}50%{transform:translateY(-8px)}}
@keyframes gradFlow{0%{background-position:0% 50%}50%{background-position:100% 50%}100%{background-position:0% 50%}}
@keyframes gradShift{0%{background-position:0% 50%}100%{background-position:200% 50%}}
@keyframes ripple{0%{transform:scale(0);opacity:.6}100%{transform:scale(2.5);opacity:0}}
@keyframes badgePop{0%{transform:scale(0) rotate(-20deg)}70%{transform:scale(1.2) rotate(5deg)}100%{transform:scale(1) rotate(0)}}
@keyframes scanline{0%{transform:translateY(-200%);opacity:0}40%{opacity:1}60%{opacity:1}100%{transform:translateY(200%);opacity:0}}
@keyframes connPop{0%{transform:scale(.8);opacity:0}60%{transform:scale(1.15)}100%{transform:scale(1);opacity:1}}
@keyframes dlPulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.4;transform:scale(.7)}}
@keyframes toastIn{from{transform:translateX(110%);opacity:0}to{transform:translateX(0);opacity:1}}
@keyframes toastOut{from{transform:translateX(0);opacity:1}to{transform:translateX(110%);opacity:0}}
@keyframes orbitRing{from{transform:rotate(-30deg)}to{transform:rotate(330deg)}}
@keyframes orbitRing2{from{transform:rotate(60deg)}to{transform:rotate(420deg)}}
@keyframes counterOrbit{from{transform:rotate(150deg)}to{transform:rotate(-210deg)}}
@keyframes logoGlow{0%,100%{filter:drop-shadow(0 0 10px #38bdf870)}50%{filter:drop-shadow(0 0 22px #38bdf8cc)}}
@keyframes numberTick{0%{transform:translateY(-20px);opacity:0}100%{transform:translateY(0);opacity:1}}
@keyframes progressPop{0%{transform:scaleX(0)}100%{transform:scaleX(1)}}
@keyframes auroraMove{0%{transform:translateX(-20%) translateY(0) rotate(-8deg)}50%{transform:translateX(10%) translateY(-5%) rotate(5deg)}100%{transform:translateX(-20%) translateY(0) rotate(-8deg)}}
@keyframes auroraMove2{0%{transform:translateX(20%) translateY(5%) rotate(5deg)}50%{transform:translateX(-5%) translateY(-10%) rotate(-8deg)}100%{transform:translateX(20%) translateY(5%) rotate(5deg)}}

/* ===================== APPLIED ANIMATIONS ===================== */
.logo-icon svg{animation:logoGlow 3s ease-in-out infinite}
.logo-icon .orbit-1{animation:orbitRing 10s linear infinite;transform-origin:18px 18px}
.logo-icon .orbit-2{animation:orbitRing2 14s linear infinite;transform-origin:18px 18px}
.logo-icon .orbit-3{animation:counterOrbit 7s linear infinite;transform-origin:18px 18px}
.spin{animation:spin .8s linear infinite}
.card-in{animation:cardIn .28s cubic-bezier(.2,0,.1,1) forwards}
.dialog-item.active{animation:borderGlow 3s ease-in-out infinite}
#dl-panel.active .prog-fill{animation:shimmer 1.6s linear infinite}
.ftab.active{animation:none}

/* Staggered card entry */
.media-card:nth-child(1){animation-delay:.02s}
.media-card:nth-child(2){animation-delay:.04s}
.media-card:nth-child(3){animation-delay:.06s}
.media-card:nth-child(4){animation-delay:.08s}
.media-card:nth-child(5){animation-delay:.10s}
.media-card:nth-child(n+6){animation-delay:.12s}

/* Scrollbar */
#dialog-list::-webkit-scrollbar{width:3px}
#media-area::-webkit-scrollbar{width:5px}
</style>
</head>
<body>

<!-- AURORA BACKGROUND -->
<canvas id="aurora"></canvas>
<!-- PARTICLES -->
<canvas id="particles"></canvas>

<div id="app">

<!-- TOPBAR -->
<div id="topbar">
  <div class="logo-wrap" id="logo-wrap">
    <div class="logo-icon">
      <svg viewBox="0 0 36 36" fill="none" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <linearGradient id="lg1" x1="0" y1="0" x2="36" y2="36" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stop-color="#38bdf8"/><stop offset="50%" stop-color="#818cf8"/><stop offset="100%" stop-color="#a78bfa"/>
          </linearGradient>
          <linearGradient id="lg2" x1="36" y1="0" x2="0" y2="36" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stop-color="#2dd4bf" stop-opacity=".7"/><stop offset="100%" stop-color="#38bdf8" stop-opacity="0"/>
          </linearGradient>
          <filter id="glow"><feGaussianBlur stdDeviation="1.5" result="blur"/>
            <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
        </defs>
        <path d="M20 3L6 20h10l-2 13L30 16H20L22 3Z" fill="url(#lg1)" filter="url(#glow)" opacity=".95"/>
        <path d="M20 6L9 20h9l-1.5 9L27 18h-9L20 6Z" fill="rgba(255,255,255,0.22)"/>
        <ellipse class="orbit-1" cx="18" cy="18" rx="16" ry="5" stroke="url(#lg1)" stroke-width="1" fill="none" opacity=".5" transform="rotate(-30 18 18)"/>
        <ellipse class="orbit-2" cx="18" cy="18" rx="16" ry="5" stroke="url(#lg2)" stroke-width=".8" fill="none" opacity=".35" transform="rotate(60 18 18)"/>
        <circle class="orbit-3" cx="18" cy="3" r="1.5" fill="#38bdf8" opacity=".8"/>
      </svg>
    </div>
    <div class="logo-text">
      <div class="logo-name">APEX</div>
      <div class="logo-sub">v10 Ultra · Media Browser</div>
    </div>
  </div>

  <div id="topbar-right">
    <div id="conn-badge">
      <div id="conn-dot"></div>
      <span id="conn-status">Disconnected</span>
    </div>
    <div id="me-badge" style="display:none">
      <div id="me-avatar">?</div>
      <span id="me-name">—</span>
    </div>
    <div class="tb-spacer"></div>
    <button class="icon-btn" title="Notifications" onclick="toggleNotif()" id="notif-btn">
      🔔<span class="badge" id="notif-badge" style="display:none">0</span>
    </button>
    <button class="icon-btn" title="Open Download Folder" onclick="openFolder()">📂</button>
    <button class="icon-btn" title="Toggle Sidebar" onclick="toggleSidebar()">☰</button>
    <input id="media-search-inp" class="search-inp" placeholder="🔍 Search media..." style="width:170px;margin-right:6px;padding:5px 10px;font-size:12px;border-radius:8px;border:1px solid var(--gb);background:var(--bg3);color:var(--tx1);" oninput="searchMedia()" autocomplete="off">
<button class="icon-btn" title="Reconnect to Telegram" onclick="reconnect()" style="margin-right:2px">🔄</button>
    <button class="icon-btn" title="Toggle Theme" onclick="toggleTheme()">🌙</button>
  </div>
</div>

<!-- MAIN TABS -->
<div id="main-tabs">
  <button class="main-tab active" data-tab="media" onclick="switchTab('media')">
    <span class="main-tab-ico">📁</span> Media
  </button>
  <button class="main-tab" data-tab="downloads" onclick="switchTab('downloads')">
    <span class="main-tab-ico">⬇</span> Downloads<span class="badge" id="dl-nav-badge" style="display:none">0</span>
  </button>
  <button class="main-tab" data-tab="stats" onclick="switchTab('stats')">
    <span class="main-tab-ico">📊</span> Stats
  </button>
  <button class="main-tab" data-tab="settings" onclick="switchTab('settings')">
    <span class="main-tab-ico">⚙️</span> Settings
  </button>
  <div class="main-tab-indicator" id="main-tab-indicator"></div>
</div>

<div id="body">
  <!-- SIDEBAR -->
  <div id="sidebar">
    <div id="sidebar-header">
      <div class="search-wrap">
        <span class="search-icon">🔍</span>
        <input id="search-box" type="text" placeholder="Search chats..." oninput="filterDialogs(this.value)" autocomplete="off">
      </div>
      <div class="sidebar-tabs">
        <button class="stab active" onclick="setSidebarTab('all',this)">All</button>
        <button class="stab" onclick="setSidebarTab('DM',this)">DMs</button>
        <button class="stab" onclick="setSidebarTab('GROUP',this)">Groups</button>
        <button class="stab" onclick="setSidebarTab('CHANNEL',this)">Channels</button>
      </div>
    </div>
    <div id="dialog-list">
      <div id="dlg-empty" style="padding:28px;text-align:center;color:var(--tx3);font-size:13px;line-height:2">
        ⚡ Connect to load chats
      </div>
    </div>
  </div>

  <!-- MAIN -->
  <div id="main">
    <div id="toolbar">
      <div class="filter-tabs">
        <button class="ftab active" data-f="all" onclick="setFilter(this)">All <span class="cnt" id="cnt-all"></span></button>
        <button class="ftab" data-f="favorite" onclick="setFilter(this)">★ Favorites <span class="cnt" id="cnt-favorite"></span></button>
        <button class="ftab" data-f="video" onclick="setFilter(this)">🎬 Video <span class="cnt" id="cnt-video"></span></button>
        <button class="ftab" data-f="photo" onclick="setFilter(this)">🖼 Photo <span class="cnt" id="cnt-photo"></span></button>
        <button class="ftab" data-f="audio" onclick="setFilter(this)">🎵 Audio <span class="cnt" id="cnt-audio"></span></button>
        <button class="ftab" data-f="document" onclick="setFilter(this)">📄 Doc <span class="cnt" id="cnt-document"></span></button>
      </div>
      <select class="sort-sel" onchange="sortMedia(this.value)" title="Sort">
        <option value="date-desc">Newest first</option>
        <option value="date-asc">Oldest first</option>
        <option value="size-desc">Largest first</option>
        <option value="size-asc">Smallest first</option>
      </select>
      <div class="view-toggle">
        <button class="vtab active" id="vt-grid" onclick="setView('grid')" title="Grid view">⊞</button>
        <button class="vtab" id="vt-list" onclick="setView('list')" title="List view">☰</button>
      </div>
      <button class="tb-btn" id="refresh-media-btn" onclick="refreshMedia()" title="Reload this chat's media from scratch">🔄 Refresh</button>
      <div class="tb-spacer"></div>
      <span id="sel-info">0 selected</span>
      <button class="tb-btn" onclick="selectAll()" title="Ctrl+A">☑ All</button>
      <button class="tb-btn" onclick="clearSel()" title="Esc">✕ Clear</button>
      <button class="tb-btn primary" onclick="dlSelected()" id="dl-sel-btn" disabled>⚡ Download</button>
      <button class="tb-btn" onclick="dlAll()">⬇ All</button>
      <button class="tb-btn" id="pause-btn" onclick="togglePause()" title="Pause/resume the download queue">⏸ Pause</button>
    </div>

    <div id="media-area">
      <div id="media-grid"></div>
      <div id="empty-state">
        <div class="empty-icon">📡</div>
        <div class="empty-title">No chat selected</div>
        <div class="empty-sub">Pick a chat from the sidebar to browse and download its media files</div>
      </div>
      <div id="load-more-wrap" style="display:none">
        <button class="load-more-btn" id="load-more-btn" onclick="loadMore()">↻ Load More</button>
      </div>
      <div id="downloads-view" style="display:none">
        <div class="dlv-section">
          <div class="dlv-section-title">⬇ Active <span id="dlv-active-count">0</span></div>
          <div id="dlv-active-list" class="dlv-list"><div class="dlv-empty">Nothing downloading right now</div></div>
        </div>
        <div class="dlv-section">
          <div class="dlv-section-title">⏳ Queued <span id="dlv-queued-count">0</span></div>
        </div>
        <div class="dlv-section">
          <div class="dlv-section-title">✅ Completed this session <span id="dlv-completed-count">0</span>
            <button class="tb-btn" style="margin-left:auto" onclick="exportHistory()">⬇ Export CSV</button>
          </div>
          <div class="dlv-note">"Upscale to 4K" resizes video to 3840×2160 using FFmpeg (Lanczos interpolation) - it sharpens and smooths, but it doesn't invent detail the source doesn't have. Requires <a href="https://ffmpeg.org/download.html" target="_blank" rel="noopener">ffmpeg</a> installed and on your system PATH. <span id="gpu-status-note">Checking for GPU acceleration…</span></div>
          <div id="dlv-completed-list" class="dlv-list"><div class="dlv-empty">No completed downloads yet this session</div></div>
        </div>
      </div>
      <div id="stats-bar" style="display:none">
        <div class="stats-dashboard-hdr">
          <h2>📊 Session Statistics</h2>
          <div class="sub">Live numbers for this running session</div>
        </div>
        <div class="stats-grid">
          <div class="stat-c">
            <div class="stat-l">Files Downloaded</div>
            <div class="stat-v a" id="st-files">0</div>
            <div class="stat-mini-bar"><div class="stat-mini-fill" id="smf-files" style="width:0%"></div></div>
          </div>
          <div class="stat-c">
            <div class="stat-l">Total Size</div>
            <div class="stat-v" id="st-size">0 MB</div>
            <div class="stat-mini-bar"><div class="stat-mini-fill" id="smf-size" style="width:0%;background:linear-gradient(90deg,var(--acc3),var(--grn))"></div></div>
          </div>
          <div class="stat-c">
            <div class="stat-l">Avg Speed</div>
            <div class="stat-v g" id="st-spd">—</div>
            <div class="stat-mini-bar"><div class="stat-mini-fill" id="smf-spd" style="width:0%;background:linear-gradient(90deg,var(--grn),var(--yel))"></div></div>
          </div>
          <div class="stat-c">
            <div class="stat-l">Session Time</div>
            <div class="stat-v" id="st-time">0m 00s</div>
          </div>
        </div>
        <div class="stats-breakdown">
          <div class="stats-breakdown-hdr">Loaded media breakdown (current chat)</div>
          <div class="sb-row"><span class="sb-label">🎬 Video</span><div class="prog-track"><div class="prog-fill" id="sb-video" style="width:0%"></div></div><span class="sb-count" id="sb-video-n">0</span></div>
          <div class="sb-row"><span class="sb-label">🖼 Photo</span><div class="prog-track"><div class="prog-fill" id="sb-photo" style="width:0%"></div></div><span class="sb-count" id="sb-photo-n">0</span></div>
          <div class="sb-row"><span class="sb-label">🎵 Audio</span><div class="prog-track"><div class="prog-fill" id="sb-audio" style="width:0%"></div></div><span class="sb-count" id="sb-audio-n">0</span></div>
          <div class="sb-row"><span class="sb-label">📄 Doc</span><div class="prog-track"><div class="prog-fill" id="sb-document" style="width:0%"></div></div><span class="sb-count" id="sb-document-n">0</span></div>
          <div class="sb-row"><span class="sb-label">★ Favorites</span><div class="prog-track"><div class="prog-fill" id="sb-favorite" style="width:0%;background:linear-gradient(90deg,#fbbf24,#f59e0b)"></div></div><span class="sb-count" id="sb-favorite-n">0</span></div>
        </div>
        <div class="stats-speed-panel">
          <div class="stats-breakdown-hdr">Download speed</div>
          <canvas id="mini-speed-chart" width="640" height="90"></canvas>
        </div>
      </div>
    </div>

    <!-- DOWNLOAD PANEL -->
    <div id="dl-panel">
      <div id="dl-hdr">
        <div id="dl-label">DOWNLOADING</div>
        <div id="dl-fname">—</div>
        <div class="tb-spacer"></div>
        <div id="dl-speed">—</div>
        <div id="dl-eta"></div>
        <div id="dl-qinfo"></div>
        <button class="icon-btn" onclick="cancelDl()" title="Cancel all active">✕</button>
      </div>
      <div id="dl-file-rows"><!-- one row per concurrently-active download, built by JS --></div>
      <div id="dl-rows">
        <div class="dl-row">
          <span style="font-size:10px;color:var(--tx3);white-space:nowrap">Queue</span>
          <div class="prog-track"><div class="prog-fill" id="q-fill" style="width:0%;background:linear-gradient(90deg,var(--acc3),var(--grn))!important"></div></div>
          <canvas id="speed-canvas" width="120" height="28" style="border-radius:4px"></canvas>
        </div>
      </div>
    </div>

    <div id="botbar">
      <span id="bot-status">Ready</span>
      <span style="flex:1"></span>
      <span id="bot-hist" style="max-width:45%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"></span>
      <span id="bot-count" style="color:var(--tx3)"></span>
    </div>
  </div>
</div>
</div><!-- #app -->

<!-- NOTIFICATIONS -->
<div id="notif-panel">
  <div class="notif-hdr">
    <span>🔔 Notifications</span>
    <button class="icon-btn" style="padding:2px 6px;font-size:11px" onclick="clearNotifs()">Clear all</button>
  </div>
  <div id="notif-list"><div style="padding:20px;text-align:center;color:var(--tx3);font-size:12px">No notifications yet</div></div>
</div>

<!-- TOASTS -->
<div id="toasts"></div>

<!-- CONTEXT MENU -->
<div id="ctx">
  <div class="ctx-i" onclick="ctxDl()">⬇ Download</div>
  <div class="ctx-i" onclick="ctxPreview()">👁 Preview</div>
  <div class="ctx-i" onclick="ctxSel()">☑ Select / Deselect</div>
  <hr class="ctx-sep">
  <div class="ctx-i" onclick="ctxCopy()">📋 Copy filename</div>
  <div class="ctx-i" onclick="ctxCopyDate()">📅 Copy date</div>
  <hr class="ctx-sep">
  <div class="ctx-i red" onclick="ctxMarkDone()">✓ Mark as done</div>
</div>

<!-- AUTH MODAL -->
<div id="auth-modal" class="overlay" style="display:none">
  <div class="modal">
    <div class="modal-hdr">
      <div class="modal-icon blue">📱</div>
      <div><h2>Sign in to Telegram</h2>
        <div class="sub">Official Telegram API — your data stays on your device</div></div>
    </div>
    <div id="auth-phone-step">
      <label class="form-lbl">Phone Number</label>
      <input class="form-inp" id="auth-phone" type="tel" placeholder="+1 234 567 8900" autocomplete="tel">
      <div class="form-note">Include country code. <a href="https://my.telegram.org" target="_blank">Get API credentials here</a></div>
      <div class="modal-btns">
        <button class="btn btn-s" onclick="closeAuth()">Cancel</button>
        <button class="btn btn-p" onclick="doPhone()">Send Code →</button>
      </div>
    </div>
    <div id="auth-code-step" style="display:none">
      <label class="form-lbl">Verification Code</label>
      <input class="form-inp" id="auth-code" type="text" placeholder="12345" maxlength="6" autocomplete="one-time-code">
      <div class="form-note">Check your Telegram app for the 5-digit code</div>
      <div class="modal-btns">
        <button class="btn btn-s" onclick="closeAuth()">Cancel</button>
        <button class="btn btn-p" onclick="doCode()">Verify →</button>
      </div>
    </div>
    <div id="auth-2fa-step" style="display:none">
      <label class="form-lbl">2FA Password</label>
      <input class="form-inp" id="auth-2fa" type="password" placeholder="Your 2FA password">
      <div class="form-note">This is the password you set in Telegram Settings → Privacy → Two-Step Verification</div>
      <div class="modal-btns">
        <button class="btn btn-s" onclick="closeAuth()">Cancel</button>
        <button class="btn btn-p" onclick="do2FA()">Confirm →</button>
      </div>
    </div>
  </div>
</div>

<!-- SETTINGS MODAL -->
<div id="settings-modal" class="overlay" style="display:none">
  <div class="modal">
    <div class="modal-hdr">
      <div class="modal-icon purple">⚙️</div>
      <div><h2>Settings</h2><div class="sub">Configure your Telegram API credentials and download options</div></div>
    </div>
    <label class="form-lbl">API ID</label>
    <input class="form-inp" id="s-id" type="text" placeholder="12345678" autocomplete="off">
    <label class="form-lbl">API Hash <span style="color:var(--tx3);font-weight:400;text-transform:none">(leave blank to keep existing)</span></label>
    <input class="form-inp" id="s-hash" type="password" placeholder="••••••••••••••••" autocomplete="off">
    <label class="form-lbl">Download Folder</label>
    <input class="form-inp" id="s-folder" type="text" placeholder="C:/Users/you/Downloads/Telegram">
    <hr class="divider">
    <label class="form-lbl">Download Preset</label>
    <div class="preset-row">
      <button class="preset-btn" id="pr-Ultra5G" onclick="setPr('Ultra5G')">🚀 5G Ultra<br><span style="font-size:10px;font-weight:500;opacity:.7">8 conn · max speed</span></button>
      <button class="preset-btn on" id="pr-Turbo" onclick="setPr('Turbo')">⚡ Turbo<br><span style="font-size:10px;font-weight:500;opacity:.7">5 conn · fast</span></button>
      <button class="preset-btn" id="pr-Balanced" onclick="setPr('Balanced')">⚖️ Balanced<br><span style="font-size:10px;font-weight:500;opacity:.7">3 conn · stable</span></button>
      <button class="preset-btn" id="pr-Safe" onclick="setPr('Safe')">🛡 Safe<br><span style="font-size:10px;font-weight:500;opacity:.7">2 conn · slow</span></button>
    </div>
    <label class="form-lbl">Bandwidth Cap (KB/s · 0 = unlimited)</label>
    <input class="form-inp" id="s-bw" type="number" min="0" placeholder="0">
    <label class="form-lbl">Max Simultaneous Downloads <span style="color:var(--tx3);font-weight:400;text-transform:none">(0 = use preset default)</span></label>
    <input class="form-inp" id="s-concurrent" type="number" min="0" max="16" placeholder="0">
    <label class="form-lbl" style="display:flex;align-items:center;gap:8px">
      <input type="checkbox" id="s-autowatch" style="width:auto"> Auto-download new incoming media</label>
    <hr class="divider">
    <button class="btn btn-s" onclick="clearHistory()" style="font-size:11px;width:100%">🗑 Clear Download History</button>
    <button class="btn btn-s" onclick="exportHistory()" style="font-size:11px;width:100%;margin-top:6px">⬇ Export Session History (CSV)</button>
    <div class="modal-btns">
      <button class="btn btn-s" onclick="closeSettings()">Cancel</button>
      <button class="btn btn-p" onclick="saveSettings()">✔ Save & Reconnect</button>
    </div>
  </div>
</div>

<!-- PREVIEW MODAL -->
<div id="preview-modal" class="overlay" style="display:none">
  <div class="modal" style="max-width:680px">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
      <h2 style="font-size:16px">Preview</h2>
      <div style="display:flex;gap:8px">
        <button class="tb-btn primary" onclick="dlPreviewItem()">⬇ Download</button>
        <button class="btn btn-s" onclick="closePreview()">✕ Close</button>
      </div>
    </div>
    <div id="preview-wrap"></div>
    <div class="preview-info">
      <div class="preview-name" id="prev-name"></div>
      <div class="preview-meta">
        <span id="prev-size"></span>
        <span id="prev-date"></span>
        <span id="prev-type"></span>
      </div>
    </div>
  </div>
</div>

<script>
/* ===================== FAILSAFE - runs before anything else ===================== */
// Ensure buttons always work even if main JS fails
window.onerror = function(msg, src, line, col, err) {
  console.error('JS Error:', msg, 'at', src, line);
  return false;
};
// EARLY definition so Settings button works before rest of JS loads
window.showSettings = function(){
  var modal=document.getElementById('settings-modal');
  if(!modal) return;
  modal.style.display='flex';
  setTimeout(function(){var e=document.getElementById('s-id');if(e&&!e.value)e.focus();},100);
  fetch('/api/config').then(function(r){return r.json();}).then(function(cfg){
    var e;
    e=document.getElementById('s-id');     if(e) e.value=cfg.api_id||'';
    e=document.getElementById('s-hash');   if(e) e.value='';
    e=document.getElementById('s-folder'); if(e) e.value=cfg.download_folder||'';
    e=document.getElementById('s-bw');     if(e) e.value=cfg.bandwidth_kbps||0;
    e=document.getElementById('s-concurrent'); if(e) e.value=cfg.max_concurrent||0;
    e=document.getElementById('s-autowatch');  if(e) e.checked=!!cfg.auto_watch;
    if(typeof setPr==='function') setPr(cfg.preset||'Turbo');
  }).catch(function(){});
};
window.closeSettings = function(){
  var modal=document.getElementById('settings-modal');
  if(modal) modal.style.display='none';
};

/* ===================== STATE ===================== */
/* Safe localStorage wrapper - never crashes even if storage is blocked */
function _ls(key, def_){ try{ return localStorage.getItem(key)||def_; }catch(e){ return def_; } }
function _lsSet(key, val){ try{ localStorage.setItem(key, val); }catch(e){} }

const S = {
  connected:false, me:{}, dialogs:[], filteredDialogs:[],
  sidebarTab:'all', currentChat:null, media:[], selected:new Set(),
  filter:'all', sortBy:'date-desc', minId:0, loading:false,
  dlActive:false, curDlId:null, activeDl:new Map(), paused:false,
  queueRemaining:0, completedLog:[], gpuChecked:false, upscaleMode:new Map(), lastHasMore:false,
  statsVisible:false, sidebarOpen:true,
  theme:_ls('apex-theme','dark'),
  viewMode:_ls('apex-view','grid'),
  preset:'Turbo', speedHist:new Array(30).fill(0),
  ctxItem:null, previewItem:null,
  notifs:[], unreadNotifs:0,
  typeCounts:{all:0,video:0,photo:0,audio:0,document:0,favorite:0},
  sessionMaxSpd:0, sessionMaxFiles:0,
};

/* ===================== INIT ===================== */
document.addEventListener('DOMContentLoaded',()=>{
  applyTheme(S.theme);
  setView(S.viewMode, false);
  try{ initAurora(); }catch(e){ console.warn('Aurora init failed:',e); }
  try{ initParticles(); }catch(e){ console.warn('Particles init failed:',e); }
  startSSE();
  loadCfg();
  checkForUpdate();
  moveTabIndicator('media');
  setTimeout(function(){ if(!S.connected) showSettings(); },2000);
  setInterval(refreshStats, 2500);
  document.addEventListener('click', e=>{
    if(!document.getElementById('ctx').contains(e.target)) hideCtx();
    if(!document.getElementById('notif-panel').contains(e.target)&&
       !document.getElementById('notif-btn').contains(e.target))
      document.getElementById('notif-panel').classList.remove('show');
  });
  document.addEventListener('keydown', handleKeys);
  document.getElementById('auth-phone').addEventListener('keydown',e=>{if(e.key==='Enter')doPhone();});
  document.getElementById('auth-code').addEventListener('keydown',e=>{if(e.key==='Enter')doCode();});
  document.getElementById('auth-2fa').addEventListener('keydown',e=>{if(e.key==='Enter')do2FA();});
});

/* ===================== AURORA BACKGROUND ===================== */
function initAurora(){
  const c=document.getElementById('aurora'); if(!c) return;
  const ctx=c.getContext('2d');
  const resize=()=>{c.width=window.innerWidth;c.height=window.innerHeight;};
  window.addEventListener('resize',resize); resize();
  let t=0;
  (function draw(){
    c.width=c.width;
    const theme=document.documentElement.getAttribute('data-theme');
    if(theme==='light'){requestAnimationFrame(draw);return;}
    t+=0.003;
    // Layer 1
    const g1=ctx.createRadialGradient(
      c.width*(0.3+Math.sin(t)*0.2), c.height*(0.3+Math.cos(t*0.7)*0.15), 0,
      c.width*(0.3+Math.sin(t)*0.2), c.height*(0.3+Math.cos(t*0.7)*0.15), c.width*0.55);
    g1.addColorStop(0,'rgba(56,189,248,0.07)'); g1.addColorStop(1,'rgba(56,189,248,0)');
    ctx.fillStyle=g1; ctx.fillRect(0,0,c.width,c.height);
    // Layer 2
    const g2=ctx.createRadialGradient(
      c.width*(0.7+Math.cos(t*1.1)*0.18), c.height*(0.6+Math.sin(t*0.8)*0.2), 0,
      c.width*(0.7+Math.cos(t*1.1)*0.18), c.height*(0.6+Math.sin(t*0.8)*0.2), c.width*0.5);
    g2.addColorStop(0,'rgba(129,140,248,0.06)'); g2.addColorStop(1,'rgba(129,140,248,0)');
    ctx.fillStyle=g2; ctx.fillRect(0,0,c.width,c.height);
    // Layer 3
    const g3=ctx.createRadialGradient(
      c.width*(0.5+Math.sin(t*0.6)*0.3), c.height*(0.8+Math.cos(t*1.2)*0.1), 0,
      c.width*(0.5+Math.sin(t*0.6)*0.3), c.height*(0.8+Math.cos(t*1.2)*0.1), c.width*0.4);
    g3.addColorStop(0,'rgba(45,212,191,0.04)'); g3.addColorStop(1,'rgba(45,212,191,0)');
    ctx.fillStyle=g3; ctx.fillRect(0,0,c.width,c.height);
    requestAnimationFrame(draw);
  })();
}

/* ===================== PARTICLES ===================== */
function initParticles(){
  const c=document.getElementById('particles'); if(!c) return;
  const ctx=c.getContext('2d');
  const cols=['#38bdf8','#818cf8','#2dd4bf','#a78bfa','#f472b6','#22c55e'];
  const resize=()=>{c.width=window.innerWidth;c.height=window.innerHeight;};
  window.addEventListener('resize',resize); resize();
  // Main drift particles
  const pts=Array.from({length:40},()=>({
    x:Math.random()*c.width, y:Math.random()*c.height,
    vx:(Math.random()-.5)*.28, vy:(Math.random()-.5)*.18,
    r:Math.random()*1.8+.4,
    col:cols[Math.floor(Math.random()*cols.length)],
    a:Math.random()*.4+.1, pulse:Math.random()*Math.PI*2,
  }));
  // Shooting stars
  let stars=[];
  function spawnStar(){
    if(stars.length<3 && Math.random()<.008){
      stars.push({
        x:Math.random()*c.width, y:Math.random()*c.height*.5,
        vx:2+Math.random()*3, vy:.5+Math.random(),
        len:60+Math.random()*80, life:1, col:cols[Math.floor(Math.random()*3)]
      });
    }
    stars=stars.filter(s=>s.life>0);
  }
  (function draw(){
    ctx.clearRect(0,0,c.width,c.height);
    const theme=document.documentElement.getAttribute('data-theme');
    const opacity=theme==='light'?0.06:0.38;
    spawnStar();
    // Draw connection lines
    for(let i=0;i<pts.length;i++) for(let j=i+1;j<pts.length;j++){
      const dx=pts[i].x-pts[j].x, dy=pts[i].y-pts[j].y, d=Math.sqrt(dx*dx+dy*dy);
      if(d<140){
        ctx.beginPath(); ctx.moveTo(pts[i].x,pts[i].y); ctx.lineTo(pts[j].x,pts[j].y);
        const alpha=Math.round((1-d/140)*opacity*255).toString(16).padStart(2,'0');
        ctx.strokeStyle=pts[i].col+alpha; ctx.lineWidth=.5; ctx.stroke();
      }
    }
    // Draw particles
    for(const p of pts){
      p.x=(p.x+p.vx+c.width)%c.width; p.y=(p.y+p.vy+c.height)%c.height;
      p.pulse+=0.04;
      const pr=p.r*(1+Math.sin(p.pulse)*0.3);
      ctx.beginPath(); ctx.arc(p.x,p.y,pr,0,Math.PI*2);
      const a=Math.round((p.a+Math.sin(p.pulse)*0.08)*opacity*255*2.5).toString(16).padStart(2,'0');
      ctx.fillStyle=p.col+a; ctx.fill();
    }
    // Draw shooting stars
    for(const s of stars){
      ctx.beginPath();
      ctx.moveTo(s.x,s.y); ctx.lineTo(s.x-s.len*s.vx/Math.sqrt(s.vx*s.vx+s.vy*s.vy),s.y-s.len*s.vy/Math.sqrt(s.vx*s.vx+s.vy*s.vy));
      const sg=ctx.createLinearGradient(s.x,s.y,s.x-s.len,s.y-s.len*.5);
      sg.addColorStop(0,s.col+Math.round(s.life*180).toString(16).padStart(2,'0'));
      sg.addColorStop(1,s.col+'00');
      ctx.strokeStyle=sg; ctx.lineWidth=1.5; ctx.stroke();
      s.x+=s.vx; s.y+=s.vy; s.life-=0.025;
    }
    requestAnimationFrame(draw);
  })();
}

/* ===================== THEME ===================== */
function toggleTheme(){
  try{
    S.theme=S.theme==='dark'?'light':'dark';
    _lsSet('apex-theme',S.theme); applyTheme(S.theme);
  }catch(e){ console.warn('Theme toggle error:',e); }
}
function applyTheme(t){
  document.documentElement.setAttribute('data-theme',t);
  const btn=document.querySelector('[onclick="toggleTheme()"]');
  if(btn) btn.textContent=t==='dark'?'☀️':'🌙';
}

/* ===================== VIEW MODE ===================== */
function setView(mode, save=true){
  S.viewMode=mode;
  if(save) _lsSet('apex-view',mode);
  const grid=document.getElementById('media-grid');
  grid.className=mode==='list'?'list-view':'';
  document.getElementById('vt-grid').classList.toggle('active',mode==='grid');
  document.getElementById('vt-list').classList.toggle('active',mode==='list');
}

/* ===================== SSE ===================== */
function startSSE(){
  const es=new EventSource('/api/events');
  es.addEventListener('connected',e=>{
    const d=JSON.parse(e.data); S.connected=true; S.me=d;
    setConn('connected',d.name||d.phone||'Connected');
    const av=document.getElementById('me-avatar');
    const nm=document.getElementById('me-name');
    const mb=document.getElementById('me-badge');
    if(av) av.textContent=(d.name||'?')[0].toUpperCase();
    if(nm) nm.textContent=d.name||d.phone||'';
    if(mb){mb.style.display='flex';}
    toast('Connected as '+(d.name||d.phone),'s');
    addNotif('✅','Connected','Signed in as '+(d.name||d.phone));
    loadDialogs();
  });
  es.addEventListener('connect_error',e=>{
    const d=JSON.parse(e.data); setConn('err','Error');
    toast('Connection error: '+d.msg,'e',7000);
    setTimeout(function(){ showSettings(); },800);
  });
  es.addEventListener('auth_step',e=>{
    const d=JSON.parse(e.data);
    if(d.step==='phone') showAuth('phone');
    else if(d.step==='2fa'){ showAuth('2fa'); toast('Two-step verification: enter your password','w',8000); }
  });
  es.addEventListener('dialogs_batch',e=>{
    const d=JSON.parse(e.data); S.dialogs.push(...d.dialogs); renderDialogs();
  });
  es.addEventListener('dialogs_done',e=>{
    const d=JSON.parse(e.data); setBotStatus(d.count+' chats loaded');
  });
  es.addEventListener('dl_start',e=>{
    const d=JSON.parse(e.data); S.dlActive=true;
    S.activeDl.set(d.id,{name:d.name,pct:0,spd:0,eta:''});
    S.queueRemaining=d.remaining;
    document.getElementById('dl-panel').classList.add('active');
    document.getElementById('dl-fname').textContent=
      S.activeDl.size>1 ? (S.activeDl.size+' files downloading') : d.name;
    document.getElementById('dl-qinfo').textContent=d.remaining+' left · '+d.active+' active';
    setBotStatus('Downloading: '+d.name);
    setCardProg(d.id,0);
    renderDlFileRows();
    updateDlNavBadge();
    renderDownloadsView();
  });
  es.addEventListener('dl_progress',e=>{
    const d=JSON.parse(e.data);
    const row=S.activeDl.get(d.id);
    if(row){ row.pct=d.pct; row.spd=d.spd; row.eta=d.eta||''; }
    S.queueRemaining=d.remaining;
    document.getElementById('dl-qinfo').textContent=d.remaining+' left · '+d.active+' active';
    document.getElementById('q-fill').style.width=
      Math.round(((d.queue_total-d.remaining)/Math.max(d.queue_total,1))*100)+'%';
    // aggregate speed = sum of all in-flight downloads
    let totalSpd=0; S.activeDl.forEach(r=>totalSpd+=(r.spd||0));
    document.getElementById('dl-speed').textContent=totalSpd.toFixed(2)+' MB/s';
    document.getElementById('dl-eta').textContent=d.eta||'';
    S.speedHist.push(totalSpd); S.speedHist=S.speedHist.slice(-30);
    if(totalSpd>S.sessionMaxSpd) S.sessionMaxSpd=totalSpd;
    drawSpeedGraph();
    setCardProg(d.id,d.pct);
    updateDlFileRow(d.id);
    renderDownloadsView();
  });
  es.addEventListener('dl_done',e=>{
    const d=JSON.parse(e.data);
    S.activeDl.delete(d.id);
    S.completedLog.push({id:d.id,name:d.name,size_mb:d.size_mb,path:d.path,
      time:new Date().toLocaleString()});
    toast('Downloaded: '+d.name,'s');
    document.getElementById('bot-hist').textContent='✓ '+d.name;
    markCardDone(d.id);
    addNotif('✅','Downloaded',d.name);
    spawnCompleteParticles();
    renderDlFileRows();
    updateDlNavBadge();
    renderDownloadsView();
  });
  es.addEventListener('dl_skipped',e=>{
    const d=JSON.parse(e.data); S.activeDl.delete(d.id);
    toast('Already done: '+d.name,'w'); renderDlFileRows(); updateDlNavBadge(); renderDownloadsView();
  });
  es.addEventListener('dl_error',e=>{
    const d=JSON.parse(e.data); S.activeDl.delete(d.id);
    toast('Failed: '+d.name+(d.msg?' - '+d.msg:''),'e');
    addNotif('❌','Download Failed',d.name);
    renderDlFileRows(); updateDlNavBadge(); renderDownloadsView();
  });
  es.addEventListener('dl_cancelled',()=>{ toast('Download cancelled','w'); });
  es.addEventListener('dl_paused',()=>{
    S.paused=true; const b=document.getElementById('pause-btn'); if(b) b.textContent='▶ Resume';
  });
  es.addEventListener('dl_resumed',()=>{
    S.paused=false; const b=document.getElementById('pause-btn'); if(b) b.textContent='⏸ Pause';
  });
  es.addEventListener('new_media',e=>{
    const d=JSON.parse(e.data);
    toast('📥 New '+d.type+' in '+(d.chat_name||'a chat'),'s',6000);
    addNotif('📥','New media',(d.chat_name||'')+': '+(d.orig_name||d.type));
    if(S.currentChat && S.currentChat.id==d.chat_id){
      S.media.unshift(d);
      recomputeCounts();
      const grid=document.getElementById('media-grid');
      if(grid) grid.prepend(makeCard(d));
    }
  });
  es.addEventListener('dl_all_done',e=>{
    const d=JSON.parse(e.data);
    S.dlActive=false; S.curDlId=null; S.activeDl.clear(); S.queueRemaining=0;
    renderDlFileRows();
    updateDlNavBadge();
    renderDownloadsView();
    document.getElementById('q-fill').style.width='100%';
    document.getElementById('dl-speed').textContent='Done ✓';
    document.getElementById('dl-eta').textContent='';
    toast('🎉 All done! '+d.files+' files · '+d.mb+' MB','s',7000);
    setBotStatus('✓ Complete — '+d.files+' files downloaded');
    addNotif('🎉','All Done',d.files+' files, '+d.mb+' MB');
    spawnCompleteParticles();
    setTimeout(()=>{
      document.getElementById('dl-panel').classList.remove('active');
      document.getElementById('q-fill').style.width='0%';
      document.getElementById('dl-speed').textContent='—';
    },4000);
  });
  es.addEventListener('upscale_start',e=>{
    const d=JSON.parse(e.data);
    toast('🎞 Upscaling "'+d.name+'" to 4K via '+(d.engine||'ffmpeg')+'…','s',6000);
    const mode=S.upscaleMode.get(String(d.id))||'fast';
    const btn=document.getElementById((mode==='ai'?'dlv-ai-upscale-btn-':'dlv-upscale-btn-')+d.id);
    if(btn){ btn.disabled=true; btn.textContent='⏳ 0%'; }
  });
  es.addEventListener('upscale_progress',e=>{
    const d=JSON.parse(e.data);
    const mode=S.upscaleMode.get(String(d.id))||'fast';
    const btn=document.getElementById((mode==='ai'?'dlv-ai-upscale-btn-':'dlv-upscale-btn-')+d.id);
    if(btn){ btn.textContent='⏳ '+d.pct+'%'; }
  });
  es.addEventListener('upscale_done',e=>{
    const d=JSON.parse(e.data);
    toast('✅ 4K upscale finished: '+d.name,'s',7000);
    addNotif('🎞','4K upscale complete',d.name);
    const mode=S.upscaleMode.get(String(d.id))||'fast';
    const btn=document.getElementById((mode==='ai'?'dlv-ai-upscale-btn-':'dlv-upscale-btn-')+d.id);
    if(btn){ btn.disabled=true; btn.textContent='✅ Done'; }
    S.upscaleMode.delete(String(d.id));
  });
  es.addEventListener('upscale_error',e=>{
    const d=JSON.parse(e.data);
    toast('❌ 4K upscale failed: '+(d.msg||'unknown error'),'e',9000);
    const mode=S.upscaleMode.get(String(d.id))||'fast';
    const btn=document.getElementById((mode==='ai'?'dlv-ai-upscale-btn-':'dlv-upscale-btn-')+d.id);
    if(btn){ btn.disabled=false; btn.textContent=(mode==='ai'?'🧠 AI Upscale':'⬆ Upscale to 4K'); }
    S.upscaleMode.delete(String(d.id));
  });
  es.onerror=()=>{ if(S.connected) setConn('connecting','Reconnecting...'); };
}

/* Burst particles on download complete */
function spawnCompleteParticles(){
  const c=document.getElementById('particles'); if(!c) return;
  // momentarily boost opacity of a pulse ring near dl panel
  const dlp=document.getElementById('dl-panel');
  if(!dlp) return;
  const flash=document.createElement('div');
  flash.style.cssText='position:fixed;inset:0;pointer-events:none;z-index:9998;'+
    'background:radial-gradient(ellipse at 50% 90%,rgba(34,197,94,.08),transparent 60%);'+
    'animation:fadeIn .1s ease,fadeOut .6s ease .2s forwards';
  const style=document.createElement('style');
  style.textContent='@keyframes fadeOut{to{opacity:0}}';
  document.head.appendChild(style);
  document.body.appendChild(flash);
  setTimeout(()=>{flash.remove();style.remove();},900);
}

/* ===================== CONFIG / CONNECT ===================== */
async function loadCfg(attempt=0){
  let c;
  try{
    const r=await fetch('/api/config');
    if(!r.ok) throw new Error('HTTP '+r.status);
    c=await r.json();
  } catch(e){
    // Retry up to 10 times with increasing delay
    if(attempt<10){ setTimeout(()=>loadCfg(attempt+1), 500+attempt*200); return; }
    // After all retries failed, still show settings so user can interact
    showSettings();
    toast('Could not reach server. Check console window is still open.','e',8000);
    return;
  }
  S.preset=c.preset||'Turbo';
  if(!c.configured){
    showSettings();
    toast('Welcome! Enter your Telegram API ID and Hash to get started.','w',12000);
  } else {
    setConn('connecting','Connecting...');
    fetch('/api/connect',{method:'POST'});
  }
}

function setConn(st,txt){
  const dot=document.getElementById('conn-dot');
  const lbl=document.getElementById('conn-status');
  dot.style.cssText=''; dot.className='';
  if(st==='connected') dot.classList.add('connected');
  else if(st==='connecting') dot.classList.add('connecting');
  else{ dot.style.background='var(--red)'; dot.style.boxShadow='0 0 10px var(--red)'; }
  lbl.textContent=txt;
}

/* ===================== AUTH ===================== */
function showAuth(step){
  document.getElementById('auth-modal').style.display='flex';
  document.getElementById('auth-phone-step').style.display=step==='phone'?'':'none';
  document.getElementById('auth-code-step').style.display=step==='code'?'':'none';
  document.getElementById('auth-2fa-step').style.display=step==='2fa'?'':'none';
  setTimeout(()=>{
    const el=document.getElementById(step==='phone'?'auth-phone':step==='code'?'auth-code':'auth-2fa');
    if(el) el.focus();
  },120);
}
function closeAuth(){ document.getElementById('auth-modal').style.display='none'; }
async function doPhone(){
  const p=document.getElementById('auth-phone').value.trim();
  if(!p){toast('Enter your phone number','w');return;}
  await fetch('/api/auth/phone',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({phone:p})});
  showAuth('code'); toast('Code sent — check your Telegram app','s');
}
async function doCode(){
  const c=document.getElementById('auth-code').value.trim();
  if(!c){toast('Enter the code','w');return;}
  await fetch('/api/auth/code',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:c})});
  closeAuth(); toast('Verifying...','w');
}
async function do2FA(){
  const p=document.getElementById('auth-2fa').value;
  if(!p){toast('Enter your 2FA password','w');return;}
  await fetch('/api/auth/password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:p})});
  closeAuth(); toast('Verifying 2FA...','w');
}

/* ===================== DIALOGS ===================== */
async function loadDialogs(){
  S.dialogs=[]; S.filteredDialogs=[];
  const ph=document.getElementById('dlg-empty');
  if(ph) ph.innerHTML='<div style="display:flex;align-items:center;gap:8px;justify-content:center;padding:20px"><div class="spin" style="width:18px;height:18px;border:2px solid var(--bg4);border-top-color:var(--acc);border-radius:50%"></div> Loading chats...</div>';
  fetch('/api/dialogs');
}
function setSidebarTab(type,btn){
  S.sidebarTab=type;
  document.querySelectorAll('.stab').forEach(b=>b.classList.remove('active'));
  if(btn) btn.classList.add('active');
  renderDialogs();
}
function filterDialogs(q){
  const lq=q.toLowerCase();
  S.filteredDialogs=q?S.dialogs.filter(d=>d.name.toLowerCase().includes(lq)):[];
  renderDialogs();
}
function renderDialogs(){
  const q=document.getElementById('search-box').value;
  let list=q?S.filteredDialogs:S.dialogs;
  if(S.sidebarTab!=='all') list=list.filter(d=>{
    if(S.sidebarTab==='GROUP') return d.type==='GROUP'||d.type==='SUPERGROUP';
    if(S.sidebarTab==='CHANNEL') return d.type==='CHANNEL';
    return d.type===S.sidebarTab;
  });
  const el=document.getElementById('dialog-list');
  if(!list.length){
    el.innerHTML='<div style="padding:20px;text-align:center;color:var(--tx3);font-size:12px">No chats found</div>'; return;
  }
  const cols=['#38bdf8','#818cf8','#2dd4bf','#a78bfa','#f472b6','#fb923c','#22c55e','#f87171'];
  const typeCol={DM:'#38bdf820',GROUP:'#22c55e20',CHANNEL:'#818cf820',SUPERGROUP:'#a78bfa20',BOT:'#fb923c20'};
  const typeLabel={DM:'DM',GROUP:'Group',CHANNEL:'Channel',SUPERGROUP:'Supergroup',BOT:'Bot',OTHER:'Chat'};
  const typeTxtCol={DM:'var(--acc)',GROUP:'var(--grn)',CHANNEL:'var(--acc2)',SUPERGROUP:'var(--acc4)',BOT:'var(--org)'};
  el.innerHTML=list.slice(0,300).map((d,i)=>{
    const col=cols[Math.abs(d.id)%cols.length];
    const init=(d.name||'?')[0].toUpperCase();
    const active=S.currentChat&&S.currentChat.id===d.id;
    const nameAttr=JSON.stringify(d.name).replace(/&/g,'&amp;').replace(/"/g,'&quot;');
    return `<div class="dialog-item${active?' active':''}" onclick="openChat(${d.id},${nameAttr})" style="animation-delay:${Math.min(i,15)*0.025}s">
      <div class="d-avatar" style="background:${col}22;color:${col};box-shadow:0 2px 8px ${col}30">${init}</div>
      <div class="d-info">
        <div class="d-name">${esc(d.name)}</div>
        <div class="d-sub">
          <span class="d-type-pill" style="background:${typeCol[d.type]||'#38bdf820'};color:${typeTxtCol[d.type]||'var(--acc)'}">${typeLabel[d.type]||d.type}</span>
        </div>
      </div>
      ${d.unread>0?`<div class="d-unread">${d.unread>99?'99+':d.unread}</div>`:''}
    </div>`;
  }).join('');
}

/* ===================== MEDIA LOADING ===================== */
async function openChat(chatId,chatName){
  if(S.loading) return;
  S.currentChat={id:chatId,name:chatName};
  S.media=[]; S.selected.clear(); S.minId=0;
  S.typeCounts={all:0,video:0,photo:0,audio:0,document:0,favorite:0};
  const grid=document.getElementById('media-grid');
  grid.innerHTML='';
  document.getElementById('empty-state').style.display='none';
  document.getElementById('load-more-wrap').style.display='none';
  updateSel(); updateCounts();
  renderDialogs();
  setBotStatus('Loading '+chatName+'...');
  await loadMedia();
}

async function loadMedia(forceRefresh){
  if(!S.currentChat||S.loading) return;
  S.loading=true;
  const grid=document.getElementById('media-grid');
  if(!S.media.length){
    // Show skeleton loaders
    grid.innerHTML=Array.from({length:8},()=>'<div class="card-skeleton" style="height:220px"></div>').join('');
  }
  let data;
  try{
    const refreshQ = forceRefresh ? '&refresh=1' : '';
    const r=await fetch(`/api/media/${S.currentChat.id}?limit=50&before_id=${S.minId}${refreshQ}`);
    if(!r.ok) throw new Error('HTTP '+r.status);
    data=await r.json();
  }catch(e){
    S.loading=false;
    toast('Failed to load media: '+e.message,'e');
    setBotStatus('Error loading media');
    grid.innerHTML='';
    return;
  }
  S.loading=false;
  if(!S.minId) grid.innerHTML='';
  if(!data.items||!data.items.length){
    if(!S.media.length){
      document.getElementById('empty-state').style.display='flex';
      document.getElementById('empty-state').innerHTML=
        '<div class="empty-icon">📭</div><div class="empty-title">No media found</div><div class="empty-sub">This chat has no downloadable media files</div>';
    }
    document.getElementById('load-more-wrap').style.display='none';
    setBotStatus(S.media.length?'No more media to load':'No media in this chat'); return;
  }
  const knownIds=new Set(S.media.map(i=>i.id));
  const fresh=data.items.filter(i=>!knownIds.has(i.id));
  const ids=data.items.map(i=>i.id);
  S.minId=Math.max(0,Math.min(...ids)-1);
  S.media.push(...fresh);
  recomputeCounts();
  renderCards(fresh,grid);
  setBotStatus(`${S.media.length} items loaded from ${S.currentChat.name}`);
  document.getElementById('bot-count').textContent=S.media.length+' items';
  const lmWrap=document.getElementById('load-more-wrap');
  const lmBtn=document.getElementById('load-more-btn');
  const hasMore=data.items.length>=50;
  S.lastHasMore=hasMore;
  lmWrap.style.display=hasMore?'flex':'none';
  if(lmBtn && hasMore) lmBtn.textContent=`↻ Load More (${S.media.length} loaded)`;
}

function renderCards(items,grid){
  const frag=document.createDocumentFragment();
  for(const item of items){
    if(S.filter!=='all'&&item.type!==S.filter) continue;
    frag.appendChild(makeCard(item));
  }
  grid.appendChild(frag);
  setTimeout(()=>loadThumbs(items),80);
}

function makeCard(item){
  const d=document.createElement('div');
  d.className='media-card'+(item.done?' done':'');
  d.dataset.id=item.id; d.dataset.type=item.type; d.dataset.fav=item.favorite?'1':'0';
  const icons={video:'🎬',photo:'🖼️',audio:'🎵',document:'📄'};
  const labels={video:'VIDEO',photo:'PHOTO',audio:'AUDIO',document:'DOC'};
  const name=item.orig_name||`${item.type}_${item.id}`;
  const size=item.size_mb>.09?(item.size_mb>=1024?(item.size_mb/1024).toFixed(2)+' GB':item.size_mb.toFixed(1)+' MB'):'';
  const date=item.date?new Date(item.date).toLocaleDateString('en-GB',{day:'2-digit',month:'short',year:'2-digit'}):'';
  d.innerHTML=`
    <div class="card-thumb" id="th-${item.id}">
      <div class="card-placeholder">${icons[item.type]||'📁'}</div>
      <div class="card-hover-overlay"><div class="card-hover-name">${esc(name)}</div></div>
      <div class="card-badge badge-${item.type}">${labels[item.type]||item.type}</div>
      <button class="card-star${item.favorite?' on':''}" onclick="event.stopPropagation();toggleFavorite(${item.id},this)" title="Favorite">★</button>
      <div class="card-sel" id="sel-${item.id}">✓</div>
    </div>
    <div class="card-rim"></div>
    <div class="card-body">
      <div class="card-name" title="${esc(name)}">${esc(name.length>28?name.slice(0,26)+'…':name)}</div>
      <div class="card-meta">
        ${size?`<span>💾 ${size}</span>`:''}
        ${date?`<span>📅 ${date}</span>`:''}
        ${item.mime?`<span>${item.mime.split('/')[1]||''}</span>`:''}
      </div>
      <div class="card-actions">
        <button class="card-btn${item.done?' done-btn':''}" onclick="event.stopPropagation();dlOne(${item.id})" title="Download">
          ${item.done?'✓ Done':'⬇ DL'}
        </button>
        <button class="card-btn preview-btn" onclick="event.stopPropagation();previewItem(${item.id})" title="Preview">👁</button>
      </div>
    </div>
    <div class="card-prog" id="prog-${item.id}"></div>`;
  d.addEventListener('click',()=>toggleSel(item.id));
  d.addEventListener('contextmenu',e=>showCtx(e,item));
  // 3D tilt with smooth spring
  let tiltX=0,tiltY=0,rafId=null;
  d.addEventListener('mousemove',e=>{
    const r=d.getBoundingClientRect();
    const tx=(e.clientX-r.left)/r.width-.5;
    const ty=(e.clientY-r.top)/r.height-.5;
    tiltX+=(tx-tiltX)*.2; tiltY+=(ty-tiltY)*.2;
    if(!rafId) rafId=requestAnimationFrame(function applyTilt(){
      d.style.transform=`translateY(-7px) scale(1.025) rotateX(${-tiltY*10}deg) rotateY(${tiltX*10}deg)`;
      rafId=null;
    });
  });
  d.addEventListener('mouseleave',()=>{
    tiltX=0; tiltY=0;
    d.style.transition='transform .4s cubic-bezier(.2,0,.1,1)';
    d.style.transform='';
    setTimeout(()=>{d.style.transition='';},400);
  });
  return d;
}

let _thumbObserver=null;
function ensureThumbObserver(){
  if(_thumbObserver) return _thumbObserver;
  _thumbObserver=new IntersectionObserver((entries)=>{
    entries.forEach(entry=>{
      if(!entry.isIntersecting) return;
      const el=entry.target;
      _thumbObserver.unobserve(el);
      const id=el.dataset.thumbId, type=el.dataset.thumbType, name=el.dataset.thumbName||'';
      const img=new Image();
      img.onload=()=>{
        el.innerHTML=`
          <img src="${img.src}" alt="" loading="lazy" style="animation:fadeIn .35s ease">
          <div class="card-hover-overlay"><div class="card-hover-name">${esc(name)}</div></div>
          <div class="card-badge badge-${type}">${{video:'VIDEO',photo:'PHOTO'}[type]}</div>
          <div class="card-sel" id="sel-${id}">✓</div>`;
        if(S.selected.has(Number(id))){
          const s=document.getElementById('sel-'+id);
          if(s){s.style.background='var(--acc)';s.style.borderColor='var(--acc)';s.style.color='#000';}
        }
      };
      img.onerror=()=>{};
      img.src=`/api/thumb/${id}`;
    });
  },{root:document.getElementById('media-area'),rootMargin:'600px 0px',threshold:0.01});
  return _thumbObserver;
}
function loadThumbs(items){
  const obs=ensureThumbObserver();
  items.filter(i=>i.type==='video'||i.type==='photo').forEach(item=>{
    const th=document.getElementById('th-'+item.id); if(!th) return;
    th.dataset.thumbId=item.id; th.dataset.thumbType=item.type; th.dataset.thumbName=item.orig_name||'';
    obs.observe(th);
  });
}

async function refreshMedia(){
  if(!S.currentChat) return;
  const btn=document.getElementById('refresh-media-btn');
  if(btn){ btn.disabled=true; btn.textContent='⏳ Refreshing…'; }
  S.media=[]; S.minId=0; S.selected.clear();
  S.typeCounts={all:0,video:0,photo:0,audio:0,document:0,favorite:0};
  document.getElementById('media-grid').innerHTML='';
  document.getElementById('empty-state').style.display='none';
  await loadMedia(true);
  if(btn){ btn.disabled=false; btn.textContent='🔄 Refresh'; }
}
async function loadMore(){
  const btn=document.getElementById('load-more-btn');
  if(btn){ btn.disabled=true; btn.dataset.prevText=btn.textContent; btn.textContent='⏳ Loading…'; }
  await loadMedia();
  if(btn){ btn.disabled=false; if(btn.textContent==='⏳ Loading…') btn.textContent=btn.dataset.prevText||'↻ Load More'; }
}

/* ===================== FILTER / SORT ===================== */
function setFilter(btn){
  const f=btn.dataset.f; S.filter=f;
  document.querySelectorAll('.ftab').forEach(t=>t.classList.remove('active'));
  btn.classList.add('active');
  applyFilter();
}
function applyFilter(){
  document.querySelectorAll('.media-card').forEach(c=>{
    let show;
    if(S.filter==='all') show=true;
    else if(S.filter==='favorite') show=c.dataset.fav==='1';
    else show=c.dataset.type===S.filter;
    c.style.display=show?'':'none';
  });
  const any=document.querySelector('.media-card:not([style*="display: none"])');
  const es=document.getElementById('empty-state');
  if(!any&&S.media.length){
    es.style.display='flex';
    const label=S.filter==='favorite'?'favorited items':S.filter+'s';
    es.innerHTML='<div class="empty-icon">'+(S.filter==='favorite'?'★':'🔍')+'</div><div class="empty-title">No '+label+' found</div><div class="empty-sub">'+(S.filter==='favorite'?'Star media to save it here':'This chat has no '+S.filter+' files')+'</div>';
  } else if(any) es.style.display='none';
}
async function toggleFavorite(id,btn){
  const r=await fetch('/api/favorite',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({id})});
  const d=await r.json().catch(()=>({ok:false}));
  if(!d.ok){ toast('Could not update favorite','e'); return; }
  btn.classList.toggle('on',d.favorite);
  const card=btn.closest('.media-card');
  if(card) card.dataset.fav=d.favorite?'1':'0';
  const item=S.media.find(m=>m.id===id);
  if(item) item.favorite=d.favorite;
  recomputeCounts();
  if(S.filter==='favorite') applyFilter();
}
function recomputeCounts(){
  const c={all:0,video:0,photo:0,audio:0,document:0,favorite:0};
  S.media.forEach(i=>{
    c.all++; if(c[i.type]!==undefined) c[i.type]++; if(i.favorite) c.favorite++;
  });
  S.typeCounts=c; updateCounts();
}
function updateCounts(){
  Object.entries(S.typeCounts).forEach(([t,n])=>{
    const el=document.getElementById('cnt-'+t);
    if(el) el.textContent=n>0?'('+n+')':'';
  });
}
function sortMedia(v){
  S.sortBy=v;
  const grid=document.getElementById('media-grid');
  const cards=[...grid.querySelectorAll('.media-card')];
  cards.sort((a,b)=>{
    const ia=S.media.find(m=>m.id==a.dataset.id);
    const ib=S.media.find(m=>m.id==b.dataset.id);
    if(!ia||!ib) return 0;
    if(v==='date-desc') return new Date(ib.date)-new Date(ia.date);
    if(v==='date-asc')  return new Date(ia.date)-new Date(ib.date);
    if(v==='size-desc') return ib.size_mb-ia.size_mb;
    if(v==='size-asc')  return ia.size_mb-ib.size_mb;
    return 0;
  });
  cards.forEach((c,i)=>{
    c.style.animationDelay=i*.02+'s';
    c.style.animation='none';
    requestAnimationFrame(()=>{c.style.animation='';});
    grid.appendChild(c);
  });
}

/* ===================== SELECTION ===================== */
function toggleSel(id){
  if(S.selected.has(id)) S.selected.delete(id); else S.selected.add(id);
  const c=document.querySelector(`.media-card[data-id="${id}"]`);
  if(c) c.classList.toggle('selected',S.selected.has(id));
  const sel=document.getElementById('sel-'+id);
  if(sel){
    if(S.selected.has(id)){sel.style.background='var(--acc)';sel.style.borderColor='var(--acc)';sel.style.color='#000';}
    else{sel.style.background='';sel.style.borderColor='';sel.style.color='';}
  }
  updateSel();
}
function selectAll(){
  getVisible().forEach(i=>S.selected.add(i.id));
  document.querySelectorAll('.media-card:not([style*="display: none"])').forEach(c=>c.classList.add('selected'));
  document.querySelectorAll('.card-sel').forEach(s=>{s.style.background='var(--acc)';s.style.borderColor='var(--acc)';s.style.color='#000';});
  updateSel();
}
function clearSel(){
  S.selected.clear();
  document.querySelectorAll('.media-card.selected').forEach(c=>c.classList.remove('selected'));
  document.querySelectorAll('.card-sel').forEach(s=>{s.style.background='';s.style.borderColor='';s.style.color='';});
  updateSel();
}
function updateSel(){
  const n=S.selected.size;
  document.getElementById('sel-info').textContent=n?`${n} selected`:'0 selected';
  document.getElementById('dl-sel-btn').disabled=n===0;
}
function getVisible(){
  return S.filter==='all'?S.media:S.media.filter(m=>m.type===S.filter);
}

/* ===================== DOWNLOAD ===================== */
async function dlSelected(){
  if(!S.selected.size||!S.currentChat) return;
  const r=await fetch('/api/download',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({ids:[...S.selected],chat_id:S.currentChat.id})});
  const d=await r.json();
  toast(`Queued ${d.queued} files${d.skipped?' ('+d.skipped+' already done)':''}`,d.queued?'s':'w');
  clearSel();
}
async function dlAll(){
  if(!S.media.length||!S.currentChat){toast('Load a chat first','w');return;}
  const ids=getVisible().map(m=>m.id);
  const r=await fetch('/api/download',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({ids,chat_id:S.currentChat.id})});
  const d=await r.json();
  toast(`Queued ${d.queued} files${d.skipped?' ('+d.skipped+' already done)':''}`,d.queued?'s':'w');
}
async function dlOne(id){
  if(!S.currentChat) return;
  const r=await fetch('/api/download',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({ids:[id],chat_id:S.currentChat.id})});
  const d=await r.json();
  if(d.skipped) toast('Already downloaded','w'); else toast('Download started','s');
}
async function dlPreviewItem(){
  if(S.previewItem){ closePreview(); await dlOne(S.previewItem.id); }
}
async function cancelDl(id){
  if(id!=null){
    await fetch(`/api/download/cancel/${id}`,{method:'POST'});
  } else {
    await fetch('/api/download/cancel_all',{method:'POST'});
  }
}
async function togglePause(){
  const btn=document.getElementById('pause-btn');
  if(S.paused){
    await fetch('/api/download/resume',{method:'POST'});
    S.paused=false; if(btn) btn.textContent='⏸ Pause';
    toast('Downloads resumed','s');
  } else {
    await fetch('/api/download/pause',{method:'POST'});
    S.paused=true; if(btn) btn.textContent='▶ Resume';
    toast('Downloads paused — in-progress files will finish','w');
  }
}

/* ===================== CONCURRENT DOWNLOAD ROWS ===================== */
function renderDlFileRows(){
  const wrap=document.getElementById('dl-file-rows');
  if(!wrap) return;
  wrap.innerHTML='';
  S.activeDl.forEach((row,id)=>{
    const el=document.createElement('div');
    el.className='dl-file-row'; el.id='dl-file-row-'+id;
    el.innerHTML=
      '<span class="dl-file-name" title="'+escHtml(row.name)+'">'+escHtml(row.name)+'</span>'+
      '<div class="prog-track"><div class="prog-fill" id="dl-file-bar-'+id+'" style="width:'+row.pct+'%"></div></div>'+
      '<span class="dl-file-pct" id="dl-file-pct-'+id+'">'+row.pct+'%</span>'+
      '<span class="dl-file-spd" id="dl-file-spd-'+id+'">'+(row.spd||0)+' MB/s</span>'+
      '<button class="icon-btn" style="width:20px;height:20px" onclick="cancelDl('+id+')" title="Cancel this file">✕</button>';
    wrap.appendChild(el);
  });
}
function updateDlFileRow(id){
  const row=S.activeDl.get(id); if(!row) return;
  const bar=document.getElementById('dl-file-bar-'+id);
  const pct=document.getElementById('dl-file-pct-'+id);
  const spd=document.getElementById('dl-file-spd-'+id);
  if(bar) bar.style.width=row.pct+'%';
  if(pct) pct.textContent=row.pct+'%';
  if(spd) spd.textContent=(row.spd||0)+' MB/s';
}
function escHtml(s){
  return String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

/* ===================== DOWNLOADS TAB ===================== */
function switchTab(name){
  if(name==='settings'){ showSettings(); return; } // modal, not a persistent view - don't change active tab

  const grid=document.getElementById('media-grid');
  const empty=document.getElementById('empty-state');
  const lm=document.getElementById('load-more-wrap');
  const dv=document.getElementById('downloads-view');
  const sb=document.getElementById('stats-bar');
  const toolbar=document.getElementById('toolbar');

  grid.style.display='none'; lm.style.display='none'; dv.style.display='none'; sb.style.display='none'; empty.style.display='none';
  toolbar.style.display = (name==='media') ? '' : 'none';

  document.querySelectorAll('.main-tab').forEach(t=>t.classList.toggle('active', t.dataset.tab===name));
  moveTabIndicator(name);

  if(name==='media'){
    grid.style.display='';
    if(!S.currentChat) empty.style.display='flex';
    else { lm.style.display=S.lastHasMore?'flex':'none'; applyFilter(); }
  } else if(name==='downloads'){
    dv.style.display='flex';
    renderDownloadsView();
    checkGpuStatus();
  } else if(name==='stats'){
    sb.style.display='flex';
    S.statsVisible=true;
    refreshStats();
  }
}
function moveTabIndicator(name){
  const btn=document.querySelector('.main-tab[data-tab="'+name+'"]');
  const ind=document.getElementById('main-tab-indicator');
  if(!btn||!ind) return;
  ind.style.left=btn.offsetLeft+'px';
  ind.style.width=btn.offsetWidth+'px';
}
window.addEventListener('resize',()=>{
  const active=document.querySelector('.main-tab.active');
  if(active) moveTabIndicator(active.dataset.tab);
});
async function checkGpuStatus(){
  if(S.gpuChecked) return;
  S.gpuChecked=true;
  const note=document.getElementById('gpu-status-note');
  try{
    const d=await fetch('/api/gpu_status').then(r=>r.json());
    if(note) note.textContent = d.available
      ? `⚡ GPU acceleration active: ${d.label} — upscales will be much faster.`
      : 'No GPU encoder detected — using CPU (slower). NVIDIA/Intel/AMD drivers with hardware encoding will be used automatically if present.';
  }catch(e){ if(note) note.textContent=''; }
}
function updateDlNavBadge(){
  const b=document.getElementById('dl-nav-badge');
  const n=S.activeDl.size;
  if(!b) return;
  b.textContent=n; b.style.display=n>0?'flex':'none';
}
function isVideoFile(name){
  return /\\.(mp4|mkv|mov|avi|webm|m4v|flv|wmv)$/i.test(name||'');
}
function renderDownloadsView(){
  const dv=document.getElementById('downloads-view');
  if(dv.style.display==='none') return;
  const aWrap=document.getElementById('dlv-active-list');
  document.getElementById('dlv-active-count').textContent=S.activeDl.size;
  if(S.activeDl.size===0){
    aWrap.innerHTML='<div class="dlv-empty">Nothing downloading right now</div>';
  } else {
    aWrap.innerHTML='';
    S.activeDl.forEach((row,id)=>{
      const el=document.createElement('div'); el.className='dlv-row';
      el.innerHTML=`<span class="dlv-name" title="${escHtml(row.name)}">${escHtml(row.name)}</span>
        <div class="prog-track" style="flex:1"><div class="prog-fill" style="width:${row.pct||0}%"></div></div>
        <span class="dlv-meta">${row.pct||0}% · ${(row.spd||0)} MB/s</span>
        <button class="icon-btn" style="width:22px;height:22px" onclick="cancelDl(${id})" title="Cancel">✕</button>`;
      aWrap.appendChild(el);
    });
  }
  document.getElementById('dlv-queued-count').textContent=S.queueRemaining;
  const cWrap=document.getElementById('dlv-completed-list');
  document.getElementById('dlv-completed-count').textContent=S.completedLog.length;
  if(!S.completedLog.length){
    cWrap.innerHTML='<div class="dlv-empty">No completed downloads yet this session</div>';
  } else {
    cWrap.innerHTML=S.completedLog.slice().reverse().slice(0,200).map(row=>`
      <div class="dlv-row" id="dlv-row-${row.id}">
        <span class="dlv-name" title="${escHtml(row.name)}">✅ ${escHtml(row.name)}</span>
        <span class="dlv-meta">${row.size_mb} MB</span>
        <span class="dlv-meta">${esc(row.time)}</span>
        ${isVideoFile(row.name)?`<button class="tb-btn" id="dlv-upscale-btn-${row.id}" style="padding:4px 10px;font-size:11px" onclick="upscale4k('${row.id}')" title="Fast GPU resize to 4K">⬆ Upscale to 4K</button>
        <button class="tb-btn" id="dlv-ai-upscale-btn-${row.id}" style="padding:4px 10px;font-size:11px" onclick="aiUpscale4k('${row.id}')" title="Slower - true AI detail enhancement via Real-ESRGAN">🧠 AI Upscale</button>`:''}
      </div>`).join('');
  }
}
async function upscale4k(id){
  const item=S.completedLog.find(r=>String(r.id)===String(id));
  if(!item){ toast('Item not found','e'); return; }
  const check=await fetch('/api/ffmpeg_status').then(r=>r.json()).catch(()=>({available:false}));
  if(!check.available){
    toast('ffmpeg not found. Install it from ffmpeg.org and add it to your PATH to use upscaling.','e',9000);
    return;
  }
  S.upscaleMode.set(String(id),'fast');
  const btn=document.getElementById('dlv-upscale-btn-'+id);
  if(btn){ btn.disabled=true; btn.textContent='⏳ Starting…'; }
  const r=await fetch('/api/upscale',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({id:item.id,path:item.path})});
  const d=await r.json().catch(()=>({ok:false}));
  if(!d.ok){
    toast('Upscale failed to start: '+(d.error||'unknown error'),'e',8000);
    if(btn){ btn.disabled=false; btn.textContent='⬆ Upscale to 4K'; }
  } else {
    toast('Upscaling to 4K started — this can take a while for long videos','s',6000);
  }
}
async function aiUpscale4k(id){
  const item=S.completedLog.find(r=>String(r.id)===String(id));
  if(!item){ toast('Item not found','e'); return; }
  const check=await fetch('/api/ai_upscale_status').then(r=>r.json()).catch(()=>({available:false}));
  if(!check.available){
    toast('Real-ESRGAN not installed. See the README "AI Upscale setup" section — one-time download, not bundled with the app.','e',12000);
    return;
  }
  const ffCheck=await fetch('/api/ffmpeg_status').then(r=>r.json()).catch(()=>({available:false}));
  if(!ffCheck.available){
    toast('ffmpeg not found. Install it from ffmpeg.org and add it to your PATH.','e',9000);
    return;
  }
  if(!confirm('AI upscaling processes every frame individually — much slower than the fast 4K resize, and best for short clips. Continue?')) return;
  S.upscaleMode.set(String(id),'ai');
  const btn=document.getElementById('dlv-ai-upscale-btn-'+id);
  if(btn){ btn.disabled=true; btn.textContent='⏳ Starting…'; }
  const r=await fetch('/api/ai_upscale',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({id:item.id,path:item.path})});
  const d=await r.json().catch(()=>({ok:false}));
  if(!d.ok){
    toast('AI upscale failed to start: '+(d.error||'unknown error'),'e',8000);
    if(btn){ btn.disabled=false; btn.textContent='🧠 AI Upscale'; }
  } else {
    toast('AI upscaling started — this processes every frame and will take a while','s',7000);
  }
}

/* ===================== CARD PROGRESS ===================== */
function setCardProg(id,pct){
  const el=document.getElementById('prog-'+id);
  if(el) el.style.width=pct+'%';
}
function markCardDone(id){
  const c=document.querySelector(`.media-card[data-id="${id}"]`);
  if(c){
    c.classList.add('done');
    const btn=c.querySelector('.card-btn:not(.preview-btn)');
    if(btn){btn.textContent='✓ Done';btn.classList.add('done-btn');}
    setCardProg(id,100);
    // Flash the card green
    c.style.transition='box-shadow .3s ease';
    c.style.boxShadow='0 0 0 2px #22c55e80,0 0 30px #22c55e40';
    setTimeout(()=>{c.style.boxShadow='';c.style.transition='';setCardProg(id,0);},3000);
  }
}

/* ===================== PREVIEW ===================== */
function previewItem(id){
  const item=S.media.find(m=>m.id===id); if(!item) return;
  S.previewItem=item;
  const wrap=document.getElementById('preview-wrap');
  const streamUrl=`/api/stream/${id}?type=${encodeURIComponent(item.type)}&name=${encodeURIComponent(item.orig_name||'')}`;
  if(item.type==='photo'){
    wrap.innerHTML=`<img src="/api/thumb/${id}" style="width:100%;max-height:60vh;object-fit:contain;border-radius:10px;animation:fadeIn .3s ease">`;
  } else if(item.type==='video'){
    wrap.innerHTML=`<video controls preload="metadata" style="width:100%;max-height:60vh;border-radius:10px;background:#000;animation:fadeIn .3s ease"><source src="${streamUrl}" type="${item.mime||'video/mp4'}"><p style="color:var(--tx3);text-align:center;padding:24px">Preview unavailable — download to watch.</p></video>`;
  } else if(item.type==='audio'){
    wrap.innerHTML=`<div style="background:var(--bg2);border-radius:12px;padding:32px;text-align:center;animation:fadeIn .3s ease"><div style="font-size:56px;margin-bottom:16px;animation:float 2s ease-in-out infinite">🎵</div><audio controls preload="metadata" style="width:100%;margin-top:8px"><source src="${streamUrl}" type="${item.mime||'audio/mpeg'}"></audio></div>`;
  } else {
    wrap.innerHTML=`<div style="background:var(--bg2);border-radius:12px;padding:48px;text-align:center;animation:fadeIn .3s ease"><div style="font-size:56px;animation:float 2s ease-in-out infinite">📄</div><div style="color:var(--tx3);font-size:13px;margin-top:12px">No preview available for this file type</div></div>`;
  }
  document.getElementById('prev-name').textContent=item.orig_name||`${item.type}_${item.id}`;
  document.getElementById('prev-size').textContent=item.size_mb>0?formatSize(item.size_mb):'';
  document.getElementById('prev-date').textContent=item.date?new Date(item.date).toLocaleDateString():'';
  document.getElementById('prev-type').textContent=item.mime||item.type;
  document.getElementById('preview-modal').style.display='flex';
}
function closePreview(){
  document.getElementById('preview-modal').style.display='none';
  document.getElementById('preview-wrap').innerHTML='';
  S.previewItem=null;
}

/* ===================== SPEED GRAPHS ===================== */
function drawSpeedGraph(){
  // Main DL panel graph
  const c=document.getElementById('speed-canvas'); if(!c) return;
  const ctx=c.getContext('2d');
  ctx.clearRect(0,0,c.width,c.height);
  const pts=S.speedHist, max=Math.max(...pts,.1), n=pts.length; if(n<2) return;
  const w=c.width,h=c.height,p=2;
  const g=ctx.createLinearGradient(0,0,0,h);
  g.addColorStop(0,'#38bdf838'); g.addColorStop(1,'#38bdf804');
  ctx.beginPath(); ctx.moveTo(p,h-p);
  for(let i=0;i<n;i++){
    const x=p+i*(w-p*2)/(n-1), y=h-p-(pts[i]/max)*(h-p*2);
    i?ctx.lineTo(x,y):ctx.moveTo(x,y);
  }
  ctx.lineTo(w-p,h-p); ctx.closePath(); ctx.fillStyle=g; ctx.fill();
  ctx.beginPath();
  for(let i=0;i<n;i++){
    const x=p+i*(w-p*2)/(n-1), y=h-p-(pts[i]/max)*(h-p*2);
    i?ctx.lineTo(x,y):ctx.moveTo(x,y);
  }
  ctx.strokeStyle='#38bdf8'; ctx.lineWidth=1.5;
  ctx.shadowColor='#38bdf8'; ctx.shadowBlur=6; ctx.stroke(); ctx.shadowBlur=0;

  // Mini stats chart
  const mc=document.getElementById('mini-speed-chart'); if(!mc) return;
  const mctx=mc.getContext('2d');
  mctx.clearRect(0,0,mc.width,mc.height);
  if(n<2) return;
  const mw=mc.width,mh=mc.height,mp=2;
  const mg=mctx.createLinearGradient(0,0,0,mh);
  mg.addColorStop(0,'#22c55e30'); mg.addColorStop(1,'#22c55e04');
  mctx.beginPath(); mctx.moveTo(mp,mh-mp);
  for(let i=0;i<n;i++){
    const x=mp+i*(mw-mp*2)/(n-1), y=mh-mp-(pts[i]/max)*(mh-mp*2);
    i?mctx.lineTo(x,y):mctx.moveTo(x,y);
  }
  mctx.lineTo(mw-mp,mh-mp); mctx.closePath(); mctx.fillStyle=mg; mctx.fill();
  mctx.beginPath();
  for(let i=0;i<n;i++){
    const x=mp+i*(mw-mp*2)/(n-1), y=mh-mp-(pts[i]/max)*(mh-mp*2);
    i?mctx.lineTo(x,y):mctx.moveTo(x,y);
  }
  mctx.strokeStyle='#22c55e'; mctx.lineWidth=1.2;
  mctx.shadowColor='#22c55e'; mctx.shadowBlur=4; mctx.stroke(); mctx.shadowBlur=0;
}

/* ===================== STATS ===================== */
async function refreshStats(){
  if(!S.statsVisible&&!S.dlActive) return;
  try{
    const d=await fetch('/api/stats').then(r=>r.json());
    animateNumber('st-files',d.files);
    document.getElementById('st-size').textContent=d.mb+' MB';
    document.getElementById('st-spd').textContent=d.avg_spd+' MB/s';
    document.getElementById('st-time').textContent=d.elapsed;
    // mini bars
    const maxFiles=Math.max(S.sessionMaxFiles,d.files,1);
    S.sessionMaxFiles=Math.max(S.sessionMaxFiles,d.files);
    const mf=document.getElementById('smf-files');
    if(mf) mf.style.width=Math.min((d.files/maxFiles)*100,100)+'%';
    const ms=document.getElementById('smf-spd');
    if(ms) ms.style.width=Math.min((d.avg_spd/Math.max(S.sessionMaxSpd,1))*100,100)+'%';
    drawSpeedGraph();
    renderStatsBreakdown();
  }catch(e){}
}
function renderStatsBreakdown(){
  const tc=S.typeCounts||{};
  const total=Math.max(tc.all||0,1);
  ['video','photo','audio','document','favorite'].forEach(t=>{
    const n=tc[t]||0;
    const bar=document.getElementById('sb-'+t);
    const cnt=document.getElementById('sb-'+t+'-n');
    if(bar) bar.style.width=Math.min((n/total)*100,100)+'%';
    if(cnt) cnt.textContent=n;
  });
}
async function checkForUpdate(){
  try{
    const d=await fetch('/api/check_update').then(r=>r.json());
    if(d.ok && d.update_available){
      toast('🆕 APEX v'+d.latest+' is available (you have v'+d.current+')','w',10000);
      addNotif('🆕','Update available','v'+d.latest+' — click to view on GitHub');
      const link=document.getElementById('update-link');
      if(link){ link.href=d.url||'#'; link.style.display='inline'; }
    }
  }catch(e){ /* offline or repo not configured yet - fail silently */ }
}
let _prevNums={};
function animateNumber(id,target){
  const el=document.getElementById(id); if(!el) return;
  const prev=_prevNums[id]||0;
  if(prev===target) return;
  _prevNums[id]=target;
  const start=performance.now(), dur=500, from=prev;
  (function tick(now){
    const t=Math.min((now-start)/dur,1);
    const ease=1-Math.pow(1-t,3);
    el.textContent=Math.round(from+(target-from)*ease);
    if(t<1) requestAnimationFrame(tick);
    else el.textContent=target;
  })(start);
}

/* ===================== SIDEBAR TOGGLE ===================== */
function toggleSidebar(){
  S.sidebarOpen=!S.sidebarOpen;
  document.getElementById('sidebar').classList.toggle('collapsed',!S.sidebarOpen);
  document.getElementById('logo-wrap').style.display=S.sidebarOpen?'flex':'none';
}

/* ===================== NOTIFICATIONS ===================== */
function addNotif(icon,title,body){
  const time=new Date().toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit'});
  S.notifs.unshift({icon,title,body,time}); S.unreadNotifs++;
  const b=document.getElementById('notif-badge');
  if(b){b.textContent=S.unreadNotifs>9?'9+':S.unreadNotifs;b.style.display='block';}
  const list=document.getElementById('notif-list');
  if(list){
    list.innerHTML=S.notifs.slice(0,20).map(n=>
      `<div class="notif-item"><div class="notif-ic">${n.icon}</div>
       <div class="notif-body"><strong>${esc(n.title)}</strong><br>${esc(n.body)}</div>
       <div class="notif-time">${n.time}</div></div>`).join('');
  }
}
function toggleNotif(){
  const p=document.getElementById('notif-panel');
  p.classList.toggle('show');
  if(p.classList.contains('show')){
    S.unreadNotifs=0;
    const b=document.getElementById('notif-badge'); if(b) b.style.display='none';
  }
}
function clearNotifs(){
  S.notifs=[]; S.unreadNotifs=0;
  const b=document.getElementById('notif-badge'); if(b) b.style.display='none';
  const list=document.getElementById('notif-list');
  if(list) list.innerHTML='<div style="padding:20px;text-align:center;color:var(--tx3);font-size:12px">No notifications</div>';
  document.getElementById('notif-panel').classList.remove('show');
}

/* ===================== CONTEXT MENU ===================== */
function showCtx(e,item){
  e.preventDefault(); S.ctxItem=item;
  const m=document.getElementById('ctx'); m.style.display='block';
  let x=e.clientX,y=e.clientY;
  if(x+190>window.innerWidth) x-=190;
  if(y+200>window.innerHeight) y-=200;
  m.style.left=x+'px'; m.style.top=y+'px';
}
function hideCtx(){ const m=document.getElementById('ctx'); if(m) m.style.display='none'; }
function ctxDl(){ if(S.ctxItem) dlOne(S.ctxItem.id); hideCtx(); }
function ctxPreview(){ if(S.ctxItem) previewItem(S.ctxItem.id); hideCtx(); }
function ctxSel(){ if(S.ctxItem) toggleSel(S.ctxItem.id); hideCtx(); }
function ctxCopy(){ if(S.ctxItem&&navigator.clipboard) navigator.clipboard.writeText(S.ctxItem.orig_name||String(S.ctxItem.id)).catch(()=>{}); toast('Copied!','s'); hideCtx(); }
function ctxCopyDate(){ if(S.ctxItem){ const d=new Date(S.ctxItem.date).toLocaleString(); if(navigator.clipboard) navigator.clipboard.writeText(d).catch(()=>{}); toast('Date copied!','s');} hideCtx(); }
function ctxMarkDone(){ if(S.ctxItem) markCardDone(S.ctxItem.id); hideCtx(); }

/* ===================== SETTINGS ===================== */
function showSettings(){
  var modal=document.getElementById('settings-modal');
  if(!modal){console.error('[APEX] settings-modal not found');return;}
  modal.style.display='flex';
  setTimeout(function(){
    var el=document.getElementById('s-id');
    if(el&&!el.value) el.focus();
  },100);
  fetch('/api/config').then(function(r){return r.json();}).then(function(cfg){
    var e;
    e=document.getElementById('s-id');     if(e) e.value=cfg.api_id||'';
    e=document.getElementById('s-hash');   if(e) e.value='';
    e=document.getElementById('s-folder'); if(e) e.value=cfg.download_folder||'';
    e=document.getElementById('s-bw');     if(e) e.value=cfg.bandwidth_kbps||0;
    e=document.getElementById('s-concurrent'); if(e) e.value=cfg.max_concurrent||0;
    e=document.getElementById('s-autowatch');  if(e) e.checked=!!cfg.auto_watch;
    setPr(cfg.preset||'Turbo');
  }).catch(function(e){console.warn('[APEX] config load failed:',e);});
}
function closeSettings(){
  var modal=document.getElementById('settings-modal');
  if(modal) modal.style.display='none';
}
function setPr(p){
  S.preset=p;
  ['Ultra5G','Turbo','Balanced','Safe'].forEach(n=>{
    const el=document.getElementById('pr-'+n);
    if(el) el.classList.toggle('on',n===p);
  });
}
async function saveSettings(){
  const id=document.getElementById('s-id').value.trim();
  const hash=document.getElementById('s-hash').value.trim();
  const folder=document.getElementById('s-folder').value.trim();
  const bw=parseInt(document.getElementById('s-bw').value)||0;
  const concurrent=Math.max(0,Math.min(16,parseInt(document.getElementById('s-concurrent').value)||0));
  const autowatch=!!document.getElementById('s-autowatch').checked;
  if(!id||!id.match(/^[0-9]+$/)){toast('Enter a valid numeric API ID','e');return;}
  const cfg={api_id:id,download_folder:folder,preset:S.preset,bandwidth_kbps:bw,
    max_concurrent:concurrent,auto_watch:autowatch};
  if(hash) cfg.api_hash=hash;
  await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(cfg)});
  closeSettings(); toast('Settings saved — reconnecting...','s');
  setTimeout(()=>fetch('/api/connect',{method:'POST'}),800);
}
function searchMedia(){
  var q=document.getElementById('media-search-inp');
  if(!q) return;
  var qv=q.value.toLowerCase().trim();
  const grid=document.getElementById('media-grid');
  if(!qv||!S.currentChat){
    document.querySelectorAll('.media-card').forEach(c=>{ c.style.display=''; });
    applyFilter();
    setBotStatus(S.media.length+' items loaded'+(S.currentChat?' from '+S.currentChat.name:''));
    return;
  }
  let matches=0;
  document.querySelectorAll('.media-card').forEach(c=>{
    const item=S.media.find(m=>String(m.id)===c.dataset.id);
    const name=(item&&item.orig_name||'').toLowerCase();
    const hit=name.includes(qv)||(item&&item.type||'').toLowerCase().includes(qv);
    c.style.display=hit?'':'none';
    if(hit) matches++;
  });
  setBotStatus(matches+' results for "'+qv+'"');
}
function reconnect(){
  setConn('connecting','Reconnecting...');
  fetch('/api/reconnect',{method:'POST'}).catch(function(){});
  toast('Reconnecting to Telegram...','w');
}
async function clearHistory(){
  await fetch('/api/clear_history',{method:'POST'}); toast('History cleared','s');
  document.querySelectorAll('.media-card.done').forEach(c=>{
    c.classList.remove('done');
    const btn=c.querySelector('.card-btn:not(.preview-btn)');
    if(btn){btn.textContent='⬇ DL';btn.classList.remove('done-btn');}
  });
}
function exportHistory(){ window.location.href='/api/export_history'; }

/* ===================== UTILS ===================== */
function openFolder(){ fetch('/api/open_folder',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({})}); }
function esc(s){ return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
function setText(id,v){ const e=document.getElementById(id); if(e) e.textContent=v; }
function setBotStatus(t){ setText('bot-status',t); }
function formatSize(mb){ return mb>=1024?(mb/1024).toFixed(2)+' GB':mb.toFixed(1)+' MB'; }

function toast(msg,type='s',dur=3500){
  const c=document.getElementById('toasts');
  const el=document.createElement('div'); el.className=`toast ${type}`;
  const icons={s:'✅',e:'❌',w:'⚠️'};
  el.innerHTML=`<span>${icons[type]||'💬'}</span><span class="toast-msg">${esc(msg)}</span><span class="toast-x" onclick="this.parentElement.remove()">✕</span>`;
  c.prepend(el);
  setTimeout(()=>{el.classList.add('out');setTimeout(()=>el.remove(),300);},dur);
}

function handleKeys(e){
  if(e.target.tagName==='INPUT'||e.target.tagName==='TEXTAREA') return;
  if(e.ctrlKey&&e.key==='a'){e.preventDefault();selectAll();}
  if(e.ctrlKey&&e.key==='d'){e.preventDefault();dlSelected();}
  if(e.key==='Escape'){clearSel();hideCtx();closePreview();}
  if(e.key==='F5'&&S.currentChat){e.preventDefault();openChat(S.currentChat.id,S.currentChat.name);}
  if(e.ctrlKey&&e.key==='o'){e.preventDefault();openFolder();}
  if(e.ctrlKey&&e.key==='\\\\'){e.preventDefault();toggleSidebar();}
}
</script>
</body>
</html>"""



def find_free_port():
    import socket
    with socket.socket() as s:
        s.bind(('',0)); return s.getsockname()[1]

def main():
    port = int(os.environ.get("APEX_PORT") or find_free_port())
    headless = os.environ.get("APEX_HEADLESS") == "1"
    try: import cryptg  # noqa
    except ImportError: print("[WARN] cryptg not installed - downloads will be slower. Run: pip install cryptg")
    if not PIL_OK: print("[WARN] pillow missing - thumbnails disabled")

    def run_flask():
        app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False, threaded=True)

    import threading
    t = threading.Thread(target=run_flask, daemon=True, name="apex_flask")
    t.start()
    import time; time.sleep(2.0)

    import time as _time
    url = f"http://127.0.0.1:{port}/?v={int(_time.time())}"
    print(f"[APEX v10] Running at {url}")
    # Machine-readable line an Electron/desktop wrapper can watch stdout for,
    # instead of guessing when the server is ready.
    print(f"APEX_READY:{port}", flush=True)

    if headless:
        # Spawned by a desktop shell (e.g. Electron) which opens its own
        # window - don't also launch a browser here.
        print("[APEX v10] Headless mode - waiting for external UI to connect.")
        print("[APEX v10] Press Ctrl+C to stop.")
        try:
            while True: time.sleep(1)
        except KeyboardInterrupt:
            print("\n[APEX v10] Shutting down.")
        return

    _launched = False
    if sys.platform == "win32":
        import subprocess as _sp
        _browsers = [
            os.path.join(os.environ.get("LOCALAPPDATA",""), "Google\\Chrome\\Application\\chrome.exe"),
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
        for _b in _browsers:
            if os.path.exists(_b):
                try:
                    _sp.Popen([_b, f"--app={url}", "--window-size=1580,970",
                        "--window-position=50,30", "--no-first-run",
                        "--no-default-browser-check", "--disable-extensions"])
                    _launched = True
                    print(f"[APEX v10] Opened with: {os.path.basename(_b)}")
                    break
                except Exception as _e:
                    print(f"[APEX v10] {_b} failed: {_e}")
    if not _launched:
        import webbrowser
        webbrowser.open(url)
        print("[APEX v10] Opened in system browser.")
    print("[APEX v10] Press Ctrl+C to stop.")
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        print("\n[APEX v10] Shutting down.")

if __name__ == "__main__":
    main()
