"""Make the key pair for web push (R8d). Run once, put both lines in
.env.production, and rebuild:

    python vapid_keys.py

Keep VAPID_PRIVATE_KEY secret. Making a new pair later signs everyone's
devices out of push (they turn it on again from the bell's settings).
"""
import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()


if __name__ == '__main__':
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    print(f'VAPID_PUBLIC_KEY={b64(public)}')
    print(f'VAPID_PRIVATE_KEY={b64(key.private_numbers().private_value.to_bytes(32, "big"))}')
