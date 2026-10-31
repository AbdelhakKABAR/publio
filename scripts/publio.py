#!/usr/bin/env python3
"""Publio Studio — publication automatique sur TikTok (Content Posting API).

Commandes :
  python scripts/publio.py connect CODE   -> échange le code de connexion contre des jetons
  python scripts/publio.py publish        -> publie les vidéos de queue/schedule.json dont l'heure est passée

Secrets attendus (variables d'environnement) :
  TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, PUBLIO_KEY (phrase secrète pour chiffrer les jetons)
"""
import base64, hashlib, json, math, os, subprocess, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone

API = "https://open.tiktokapis.com"
REDIRECT_URI = "https://abdelhakkabar.github.io/publio/callback.html"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKENS = os.path.join(ROOT, "data", "tokens.enc")
SCHEDULE = os.path.join(ROOT, "queue", "schedule.json")
HISTORY = os.path.join(ROOT, "data", "history.json")

CLIENT_KEY = os.environ.get("TIKTOK_CLIENT_KEY", "")
CLIENT_SECRET = os.environ.get("TIKTOK_CLIENT_SECRET", "")
PUBLIO_KEY = os.environ.get("PUBLIO_KEY", "")


def log(*a):
    print("[publio]", *a, flush=True)


# ---------- chiffrement des jetons (openssl AES-256) ----------
def save_tokens(tok):
    os.makedirs(os.path.dirname(TOKENS), exist_ok=True)
    data = json.dumps(tok).encode()
    out = subprocess.run(
        ["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-iter", "200000", "-salt", "-a", "-A",
         "-pass", "env:PUBLIO_KEY"], input=data, capture_output=True, check=True).stdout
    open(TOKENS, "wb").write(out + b"\n")


def load_tokens():
    if not os.path.exists(TOKENS):
        sys.exit("Aucun compte TikTok connecté. Lance d'abord le workflow « Connecter TikTok ».")
    out = subprocess.run(
        ["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter", "200000", "-a", "-A",
         "-pass", "env:PUBLIO_KEY"], input=open(TOKENS, "rb").read().strip(),
        capture_output=True, check=True).stdout
    return json.loads(out)


# ---------- HTTP ----------
def http(method, url, body=None, headers=None, form=False, raw=None):
    headers = dict(headers or {})
    data = raw
    if body is not None:
        if form:
            data = urllib.parse.urlencode(body).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json; charset=UTF-8"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            txt = r.read().decode() or "{}"
            return r.status, json.loads(txt) if txt.strip().startswith("{") else {"raw": txt}
    except urllib.error.HTTPError as e:
        txt = e.read().decode()
        try:
            return e.code, json.loads(txt)
        except Exception:
            return e.code, {"raw": txt}


def api(path, token, body):
    st, js = http("POST", API + path, body, {"Authorization": f"Bearer {token}"})
    err = (js.get("error") or {})
    if st >= 400 or (err.get("code") not in (None, "ok")):
        raise RuntimeError(f"{path} -> HTTP {st} {json.dumps(js)}")
    return js.get("data", {})


# ---------- jetons ----------
def connect(code):
    st, js = http("POST", API + "/v2/oauth/token/", {
        "client_key": CLIENT_KEY, "client_secret": CLIENT_SECRET,
        "code": urllib.parse.unquote(code.strip()), "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI}, form=True)
    if "access_token" not in js:
        sys.exit(f"Échec de la connexion : {json.dumps(js)}")
    js["obtained_at"] = int(time.time())
    save_tokens(js)
    log("Compte TikTok connecté. Scopes :", js.get("scope"))
    try:
        info = api("/v2/post/publish/creator_info/query/", js["access_token"], {})
        log("Compte :", info.get("creator_nickname"), "— options :", info.get("privacy_level_options"))
    except Exception as e:
        log("Info compte indisponible :", e)


def fresh_token():
    tok = load_tokens()
    if time.time() < tok.get("obtained_at", 0) + int(tok.get("expires_in", 0)) - 600:
        return tok["access_token"]
    st, js = http("POST", API + "/v2/oauth/token/", {
        "client_key": CLIENT_KEY, "client_secret": CLIENT_SECRET,
        "grant_type": "refresh_token", "refresh_token": tok["refresh_token"]}, form=True)
    if "access_token" not in js:
        sys.exit(f"Impossible de rafraîchir le jeton (reconnecte TikTok) : {json.dumps(js)}")
    js["obtained_at"] = int(time.time())
    save_tokens(js)
    log("Jeton rafraîchi.")
    return js["access_token"]


# ---------- publication ----------
def download(url, dest):
    log("Téléchargement", url)
    urllib.request.urlretrieve(url, dest)
    return dest


def chunks_for(size):
    MB = 1024 * 1024
    if size <= 64 * MB:
        return size, 1
    chunk = 10 * MB
    return chunk, size // chunk  # le dernier morceau contient le reste


def publish_one(token, item):
    src = item["video"]
    path = src if os.path.exists(os.path.join(ROOT, src)) else None
    path = os.path.join(ROOT, src) if path else download(src, "/tmp/publio_video.mp4")
    size = os.path.getsize(path)

    info = api("/v2/post/publish/creator_info/query/", token, {})
    allowed = info.get("privacy_level_options", [])
    privacy = item.get("privacy") or os.environ.get("PUBLIO_PRIVACY", "SELF_ONLY")
    if allowed and privacy not in allowed:
        log(f"Confidentialité {privacy} non autorisée ({allowed}) -> SELF_ONLY")
        privacy = "SELF_ONLY" if "SELF_ONLY" in allowed else allowed[0]
    log(f"Compte : {info.get('creator_nickname')} — confidentialité : {privacy}")

    chunk, count = chunks_for(size)
    mode = item.get("mode", "direct")  # direct = publication directe, draft = brouillon dans TikTok
    if mode == "draft":
        path_init = "/v2/post/publish/inbox/video/init/"
        body = {"source_info": {"source": "FILE_UPLOAD", "video_size": size,
                                "chunk_size": chunk, "total_chunk_count": count}}
    else:
        path_init = "/v2/post/publish/video/init/"
        body = {"post_info": {"title": item.get("caption", "")[:2200], "privacy_level": privacy,
                              "disable_comment": bool(item.get("disable_comment", False)),
                              "disable_duet": bool(item.get("disable_duet", False)),
                              "disable_stitch": bool(item.get("disable_stitch", False)),
                              "is_aigc": bool(item.get("is_aigc", True))},
                "source_info": {"source": "FILE_UPLOAD", "video_size": size,
                                "chunk_size": chunk, "total_chunk_count": count}}
    init = api(path_init, token, body)
    pid, up = init["publish_id"], init["upload_url"]

    with open(path, "rb") as f:
        for i in range(count):
            start = i * chunk
            end = size - 1 if i == count - 1 else start + chunk - 1
            f.seek(start)
            part = f.read(end - start + 1)
            st, js = http("PUT", up, raw=part, headers={
                "Content-Type": "video/mp4", "Content-Length": str(len(part)),
                "Content-Range": f"bytes {start}-{end}/{size}"})
            log(f"Envoi morceau {i+1}/{count} ({len(part)} octets) -> HTTP {st} {js}")
            if st not in (200, 201, 206):
                raise RuntimeError(f"Envoi morceau {i+1}/{count} -> HTTP {st} {js}")
    log("Vidéo envoyée, publish_id", pid)

    for _ in range(40):
        time.sleep(15)
        s = api("/v2/post/publish/status/fetch/", token, {"publish_id": pid})
        status = s.get("status")
        log("Statut :", status, json.dumps(s))
        if status in ("PUBLISH_COMPLETE", "SEND_TO_USER_INBOX"):
            return pid, status
        if status == "FAILED":
            raise RuntimeError(f"Échec TikTok : {s.get('fail_reason')}")
    return pid, "PROCESSING"


def publish_due():
    if not os.path.exists(SCHEDULE):
        log("Rien à publier."); return
    queue = json.load(open(SCHEDULE, encoding="utf-8"))
    now = datetime.now(timezone.utc)
    due = [q for q in queue if q.get("status", "pending") == "pending"
           and datetime.fromisoformat(q["time"]).astimezone(timezone.utc) <= now]
    if not due:
        log("Aucune vidéo à l'heure."); return
    token = fresh_token()
    history = json.load(open(HISTORY)) if os.path.exists(HISTORY) else []
    for item in due[:3]:  # max 3 par passage pour respecter les limites
        try:
            pid, st = publish_one(token, item)
            item.update(status="published", publish_id=pid, result=st)
            # Une fois envoyée à TikTok, la vidéo n'a plus besoin de rester sur GitHub.
            local = os.path.join(ROOT, item["video"])
            if not item["video"].startswith("http") and os.path.isfile(local):
                os.remove(local)
                item["video_deleted"] = True
                log("Vidéo supprimée du dépôt :", item["video"])
        except Exception as e:
            log("ERREUR :", e)
            item["attempts"] = item.get("attempts", 0) + 1
            item["last_error"] = str(e)[:500]
            if item["attempts"] >= 3:
                item["status"] = "failed"
        item["updated_at"] = now.isoformat()
        history.append({k: item.get(k) for k in ("time", "video", "status", "publish_id", "last_error")})
    json.dump(queue, open(SCHEDULE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    os.makedirs(os.path.dirname(HISTORY), exist_ok=True)
    json.dump(history[-500:], open(HISTORY, "w"), ensure_ascii=False, indent=2)


if __name__ == "__main__":
    for v in ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "PUBLIO_KEY"):
        if not os.environ.get(v):
            sys.exit(f"Secret manquant : {v} (à ajouter dans Settings > Secrets and variables > Actions)")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "publish"
    if cmd == "connect":
        connect(sys.argv[2])
    else:
        publish_due()
