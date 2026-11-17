"""Print fresh secrets for a local env file or hosting secret store. Never commit the output."""

import secrets

from cryptography.fernet import Fernet

print("SERVICE_TOKEN=" + secrets.token_urlsafe(48))
print("KEY_HASH_SECRET=" + secrets.token_urlsafe(48))
print("KEY_ENCRYPTION_SECRET=" + Fernet.generate_key().decode())
print("POSTGRES_PASSWORD=" + secrets.token_urlsafe(32))
