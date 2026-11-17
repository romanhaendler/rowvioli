import json, base64
from nacl.public import PrivateKey, PublicKey, SealedBox
from nacl.exceptions import CryptoError
import nacl, hashlib

# Key pair: the private key stays with the worker, anyone may have the public one
priv = PrivateKey.generate(); pub = priv.public_key
key_id = hashlib.sha256(bytes(pub)).hexdigest()[:16]

def seal(pub, name, value):          # needs ONLY the public key
    return SealedBox(pub).encrypt(json.dumps({"name": name, "value": value}).encode())

def open_(priv, name, blob):         # needs the private key
    d = json.loads(SealedBox(priv).decrypt(blob))
    if d["name"] != name: raise ValueError("secret belongs to another name")
    return d["value"]

c1 = seal(pub, "ERP_ODBC", "Driver=...;PWD=secret")
c2 = seal(pub, "ERP_ODBC", "Driver=...;PWD=secret")
print("pynacl", nacl.__version__, "| key_id", key_id, "| length of ciphertext", len(c1), "bytes, plaintext", len(json.dumps({"name":"ERP_ODBC","value":"Driver=...;PWD=secret"})))
print("1 decrypts correctly:", open_(priv, "ERP_ODBC", c1) == "Driver=...;PWD=secret")
print("2 same input, different ciphertext:", c1 != c2)
try: SealedBox(pub).decrypt(c1); print("3 ERROR: the public key could decrypt")
except Exception as e: print("3 the public key cannot decrypt:", type(e).__name__)
t = bytearray(c1); t[-1] ^= 1
try: open_(priv, "ERP_ODBC", bytes(t)); print("4 ERROR: tampering went unnoticed")
except CryptoError: print("4 a flipped bit is detected: CryptoError")
try: open_(priv, "CRM_ODBC", c1); print("5 ERROR: swapping went unnoticed")
except ValueError as e: print("5 ciphertext under another name is rejected:", e)
try: open_(PrivateKey.generate(), "ERP_ODBC", c1); print("6 ERROR: a foreign key could decrypt")
except CryptoError: print("6 a foreign private key fails: CryptoError")
