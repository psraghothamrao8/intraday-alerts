"""
Tests for state encryption and decryption (spec 04 §7.2).
Verifies:
1. Python encrypt -> decrypt round trip.
2. Fixed test vector matches exactly between Python and WebCrypto (docs/test-crypto.html).
"""
import base64
import json
import subprocess
from pathlib import Path
from engine.publish.crypto import encrypt_payload, decrypt_payload, derive_key, AAD
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Test Vector constants
TEST_PASSPHRASE = "test-passphrase-vector-2026"
TEST_SALT_B64 = "MDEyMzQ1Njc4OWFiY2RlZg=="
TEST_IV_B64 = "MTIzNDU2Nzg5MDEy"
TEST_CT_B64 = "nXYF/nb4850/oLj7/wOMFu/AI2LC7AOabhVOrpcgyrzARXZ7OovNNPzGPw9CZ7Q="
TEST_PLAINTEXT = {"test": "vector", "value": 42}


def test_crypto_round_trip():
    passphrase = "super-secret-random-passphrase-123!"
    data = {
        "today": {"pnl": 1.25, "trades": [{"symbol": "KPITTECH", "side": "LONG"}]},
        "scoreboard": [{"strategy": "S1", "win_rate": 0.65}]
    }

    salt_b64, iv_b64, ct_b64 = encrypt_payload(data, passphrase)
    decrypted = decrypt_payload(salt_b64, iv_b64, ct_b64, passphrase)

    assert decrypted == data


def test_fixed_test_vector_python():
    # 1. Decrypting the fixed test vector produces expected plaintext
    decrypted = decrypt_payload(TEST_SALT_B64, TEST_IV_B64, TEST_CT_B64, TEST_PASSPHRASE)
    assert decrypted == TEST_PLAINTEXT

    # 2. Encrypting with fixed salt and iv produces the exact test vector ciphertext
    salt = base64.b64decode(TEST_SALT_B64)
    iv = base64.b64decode(TEST_IV_B64)
    s_b64, i_b64, c_b64 = encrypt_payload(TEST_PLAINTEXT, TEST_PASSPHRASE, salt=salt, iv=iv)

    assert s_b64 == TEST_SALT_B64
    assert i_b64 == TEST_IV_B64
    assert c_b64 == TEST_CT_B64


def test_webcrypto_test_vector_via_node():
    """Verify that WebCrypto (docs/crypto.js) decrypts the exact test vector and prints PASS."""
    script = f"""
    const {{ webcrypto }} = require('crypto');
    global.crypto = webcrypto;
    const fs = require('fs');
    eval(fs.readFileSync('docs/crypto.js', 'utf8'));
    const env = {{
      salt: '{TEST_SALT_B64}',
      iv: '{TEST_IV_B64}',
      ct: '{TEST_CT_B64}'
    }};
    decryptState(env, '{TEST_PASSPHRASE}').then(res => {{
      if (res.test === 'vector' && res.value === 42) {{
        console.log('PASS');
      }} else {{
        console.log('FAIL');
        process.exit(1);
      }}
    }}).catch(err => {{
      console.error(err);
      process.exit(1);
    }});
    """
    res = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    assert "PASS" in res.stdout
