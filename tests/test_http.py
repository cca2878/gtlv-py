import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import ssl
import tempfile
import threading
import unittest
import urllib.error

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from gtlv._http import HttpClient


class HttpTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=1))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256())
        )
        self.cert_path = root / "cert.pem"
        self.cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path = root / "key.pem"
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"ok": true}')

            def log_message(self, format, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(self.cert_path), str(key_path))
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.url = "https://localhost:{}/".format(self.server.server_port)

    def stop_server(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()

    async def test_default_client_rejects_untrusted_tls(self):
        with self.assertRaises(urllib.error.URLError) as caught:
            await HttpClient().get(self.url)
        self.assertIsInstance(caught.exception.reason, ssl.SSLCertVerificationError)

    async def test_explicit_private_ca_still_checks_hostname(self):
        context = ssl.create_default_context(cafile=str(self.cert_path))
        client = HttpClient(ssl_context=context)
        response = await client.get(self.url)
        self.assertEqual(response.json(), {"ok": True})
        with self.assertRaises(urllib.error.URLError) as caught:
            await client.get(self.url.replace("localhost", "127.0.0.1"))
        self.assertIsInstance(caught.exception.reason, ssl.SSLCertVerificationError)

    def test_default_store_excludes_revoked_roots(self):
        context = HttpClient().ssl_context
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        names = {value for cert in context.get_ca_certs() for rdn in cert["subject"] for kind, value in rdn if kind == "commonName"}
        self.assertNotIn("emSign ECC Root CA - G3", names)
        self.assertNotIn("AAA Certificate Services", names)
