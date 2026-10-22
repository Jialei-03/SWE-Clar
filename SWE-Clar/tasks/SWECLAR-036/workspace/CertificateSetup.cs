using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using Microsoft.AspNetCore.Server.Kestrel.Https;
using System.Net;

public static class CertificateSetup
{
    public static void Configure(WebApplicationBuilder builder)
    {
        var server = new X509Certificate2(Environment.GetEnvironmentVariable("SERVER_PFX")!, Environment.GetEnvironmentVariable("SERVER_PFX_PASSWORD"));
        var ca = X509Certificate2.CreateFromPem(File.ReadAllText(Environment.GetEnvironmentVariable("CLIENT_CA_PEM")!));
        var port = int.Parse(Environment.GetEnvironmentVariable("API_PORT")!);
        builder.WebHost.ConfigureKestrel(options => options.Listen(IPAddress.Loopback, port, listen => listen.UseHttps(https =>
        {
            https.ServerCertificate = server;
            https.ClientCertificateMode = ClientCertificateMode.AllowCertificate;
            https.ClientCertificateValidation = (certificate, _, _) => Validate(certificate, ca);
        })));
    }
    public static bool Validate(X509Certificate2 certificate, X509Certificate2 ca)
    {
        using var chain = new X509Chain();
        chain.ChainPolicy.TrustMode = X509ChainTrustMode.CustomRootTrust;
        chain.ChainPolicy.CustomTrustStore.Add(ca);
        chain.ChainPolicy.RevocationMode = X509RevocationMode.NoCheck;
        chain.ChainPolicy.ApplicationPolicy.Add(new Oid("1.3.6.1.5.5.7.3.2"));
        return chain.Build(certificate);
    }
}
