import json, base64
from nacl.public import PrivateKey, PublicKey, SealedBox
from nacl.exceptions import CryptoError
import nacl, hashlib

# Schluesselpaar: privat bleibt beim Worker, oeffentlich darf jeder haben
priv = PrivateKey.generate(); pub = priv.public_key
key_id = hashlib.sha256(bytes(pub)).hexdigest()[:16]

def seal(pub, name, value):          # braucht NUR den oeffentlichen Schluessel
    return SealedBox(pub).encrypt(json.dumps({"name": name, "value": value}).encode())

def open_(priv, name, blob):         # braucht den privaten Schluessel
    d = json.loads(SealedBox(priv).decrypt(blob))
    if d["name"] != name: raise ValueError("secret belongs to another name")
    return d["value"]

c1 = seal(pub, "ERP_ODBC", "Driver=...;PWD=geheim")
c2 = seal(pub, "ERP_ODBC", "Driver=...;PWD=geheim")
print("pynacl", nacl.__version__, "| key_id", key_id, "| Laenge Chiffrat", len(c1), "Bytes, Klartext", len(json.dumps({"name":"ERP_ODBC","value":"Driver=...;PWD=geheim"})))
print("1 entschluesselt richtig:", open_(priv, "ERP_ODBC", c1) == "Driver=...;PWD=geheim")
print("2 gleiche Eingabe, verschiedenes Chiffrat:", c1 != c2)
try: SealedBox(pub).decrypt(c1); print("3 FEHLER: oeffentlicher Schluessel konnte entschluesseln")
except Exception as e: print("3 oeffentlicher Schluessel kann nicht entschluesseln:", type(e).__name__)
t = bytearray(c1); t[-1] ^= 1
try: open_(priv, "ERP_ODBC", bytes(t)); print("4 FEHLER: Manipulation unbemerkt")
except CryptoError: print("4 ein gekipptes Bit wird erkannt: CryptoError")
try: open_(priv, "CRM_ODBC", c1); print("5 FEHLER: Vertauschen unbemerkt")
except ValueError as e: print("5 Chiffrat unter anderem Namen wird abgelehnt:", e)
try: open_(PrivateKey.generate(), "ERP_ODBC", c1); print("6 FEHLER: fremder Schluessel konnte entschluesseln")
except CryptoError: print("6 fremder privater Schluessel scheitert: CryptoError")
