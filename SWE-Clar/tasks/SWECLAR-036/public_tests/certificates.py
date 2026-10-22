"""Generate fresh synthetic TLS materials, never use original certificates."""
from datetime import datetime,timedelta,timezone
import ipaddress,secrets
from cryptography import x509
from cryptography.x509.oid import NameOID,ExtendedKeyUsageOID
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
def certificates(root):
    now=datetime.now(timezone.utc)
    def key():return rsa.generate_private_key(public_exponent=65537,key_size=2048)
    def name(text):return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,text)])
    ca_key=key();ca_name=name('Synthetic test CA')
    ca=x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=2)).add_extension(x509.BasicConstraints(ca=True,path_length=0),critical=True).add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),critical=False).add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),critical=False).add_extension(x509.KeyUsage(digital_signature=False,content_commitment=False,key_encipherment=False,data_encipherment=False,key_agreement=False,key_cert_sign=True,crl_sign=True,encipher_only=None,decipher_only=None),critical=True).sign(ca_key,hashes.SHA256())
    (root/'ca.pem').write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    def issue(label,server=False,untrusted=False):
        k=key();subject=name(label);issuer=subject if untrusted else ca_name;signing=k if untrusted else ca_key
        b=x509.CertificateBuilder().subject_name(subject).issuer_name(issuer).public_key(k.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(hours=1)).not_valid_after(now+timedelta(days=1)).add_extension(x509.BasicConstraints(ca=False,path_length=None),critical=True).add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH if server else ExtendedKeyUsageOID.CLIENT_AUTH]),critical=False)
        b=b.add_extension(x509.SubjectKeyIdentifier.from_public_key(k.public_key()),critical=False).add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(signing.public_key()),critical=False).add_extension(x509.KeyUsage(digital_signature=True,content_commitment=False,key_encipherment=True,data_encipherment=False,key_agreement=False,key_cert_sign=False,crl_sign=False,encipher_only=None,decipher_only=None),critical=True)
        if server:b=b.add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False)
        cert=b.sign(signing,hashes.SHA256());(root/(label+'.pem')).write_bytes(cert.public_bytes(serialization.Encoding.PEM));(root/(label+'.key')).write_bytes(k.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        return k,cert
    server_key,server_cert=issue('server',True);issue('client');issue('untrusted',untrusted=True)
    password=secrets.token_hex(18);(root/'server.pfx').write_bytes(pkcs12.serialize_key_and_certificates(b'synthetic-server',server_key,server_cert,[ca],serialization.BestAvailableEncryption(password.encode())))
    return password

