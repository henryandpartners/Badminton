"""CI smoke tests for the badminton tracker.

- test_app_boots: runs the whole Streamlit script and asserts it renders all
  five tabs with no uncaught exception (uses a throwaway RSA key so the GSheets
  connection object can be constructed without real credentials).
- test_ocr_reads_and_matches: exercises the local OCR slip engine end-to-end,
  which also proves the `tesseract-ocr` binary is installed.
"""

import io
import os
import pathlib

import pandas as pd
from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _write_dummy_secrets() -> None:
    """Write a .streamlit/secrets.toml with a valid (throwaway) RSA key.

    The key is generated fresh and used only so st.connection(...) can build the
    service-account client. No network calls are made during the boot test.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()
    pem_escaped = pem.replace("\n", "\\n")

    secrets_dir = ROOT / ".streamlit"
    secrets_dir.mkdir(exist_ok=True)
    (secrets_dir / "secrets.toml").write_text(
        f"""[connections.gsheets]
spreadsheet = "https://docs.google.com/spreadsheets/d/TEST/edit"
worksheet = "Players"
type = "service_account"
project_id = "test"
private_key_id = "test"
private_key = "{pem_escaped}"
client_email = "test@test.iam.gserviceaccount.com"
client_id = "123"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "https://example.com"
universe_domain = "googleapis.com"
"""
    )


def test_app_boots():
    from streamlit.testing.v1 import AppTest

    _write_dummy_secrets()
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()

    assert at.exception == [] or not at.exception, f"app raised: {at.exception}"
    assert len(at.tabs) == 5, f"expected 5 tabs, got {len(at.tabs)}"


def test_ocr_reads_and_matches():
    import app

    img = Image.new("RGB", (480, 220), "white")
    d = ImageDraw.Draw(img)
    d.text((20, 40), "Transfer Successful", fill="black")
    d.text((20, 90), "Amount  187.50 THB", fill="black")
    d.text((20, 140), "Ref: 2026063012345", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    amounts = app.extract_amounts_from_image(buf.getvalue())
    assert 187.5 in amounts, f"OCR did not read 187.50; got {amounts}"

    ledger = pd.DataFrame(
        [
            {"Player": "Som", "AmountDue": 187.50, "PaymentStatus": "Pending", "Date": "2026-06-30"},
            {"Player": "Nok", "AmountDue": 200.00, "PaymentStatus": "Pending", "Date": "2026-06-30"},
        ]
    )
    matches = app.match_amounts_to_pending(ledger, amounts)
    assert len(matches) == 1, f"expected 1 match, got {len(matches)}"
    assert matches[0][1]["Player"] == "Som"
