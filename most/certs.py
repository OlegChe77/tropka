"""Самоподписанный сертификат для HTTPS в локальной сети."""
from __future__ import annotations

import datetime as dt
import ipaddress
import ssl
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

VALID_DAYS = 397  # дольше браузеры не любят


def ensure_cert(folder: Path, ips: list[str]) -> tuple[Path, Path]:
    """Вернуть (cert, key). Новый сертификат — только если старого нет,
    он скоро истекает или в нём нет текущего IP (телефон тогда предупредит заново)."""
    cert_path, key_path = folder / "cert.pem", folder / "key.pem"
    if _usable(cert_path, key_path, ips):
        return cert_path, key_path

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Tropka local")])
    now = dt.datetime.now(dt.timezone.utc)
    alt: list[x509.GeneralName] = [
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
    ]
    alt += [x509.IPAddress(ipaddress.ip_address(ip)) for ip in ips if ip != "127.0.0.1"]
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=VALID_DAYS))
        .add_extension(x509.SubjectAlternativeName(alt), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(key, hashes.SHA256())
    )
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path


def _usable(cert_path: Path, key_path: Path, ips: list[str]) -> bool:
    if not (cert_path.exists() and key_path.exists()):
        return False
    try:
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        have = {str(a) for a in san.get_values_for_type(x509.IPAddress)}
    except (ValueError, x509.ExtensionNotFound):
        return False
    left = cert.not_valid_after_utc - dt.datetime.now(dt.timezone.utc)
    return left > dt.timedelta(days=30) and set(ips) <= have


def server_context(cert_path: Path, key_path: Path) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert_path, key_path)
    return ctx
