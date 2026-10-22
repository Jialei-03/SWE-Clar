using System.Net;
using System.Security.Cryptography.X509Certificates;
using System.Security.Cryptography;
using Microsoft.AspNetCore.Server.Kestrel.Https;

public static class CertificateSetup
{
    private static X509Certificate2? clientCa;

    public static bool IsConfigured { get; private set; }

    public static void Configure(WebApplicationBuilder builder)
    {
        var serverPath = Environment.GetEnvironmentVariable("SERVER_PFX") ?? string.Empty;
        var caPath = Environment.GetEnvironmentVariable("CLIENT_CA_PEM") ?? string.Empty;
        var serverPassword = Environment.GetEnvironmentVariable("SERVER_PFX_PASSWORD");
        var port = int.Parse(Environment.GetEnvironmentVariable("API_PORT") ?? "8080");

        var server = new X509Certificate2(serverPath, serverPassword);
        var ca = X509Certificate2.CreateFromPem(File.ReadAllText(caPath));
        clientCa = ca;

        builder.WebHost.ConfigureKestrel(options => options.Listen(
            IPAddress.Loopback,
            port,
            listen => listen.UseHttps(https =>
            {
                https.ServerCertificate = server;
                // The certificate is requested during TLS but is not required
                // for ordinary routes. /secure enforces it at the application
                // boundary as well.
                https.ClientCertificateMode = ClientCertificateMode.AllowCertificate;
                https.ClientCertificateValidation = (certificate, _, _) =>
                    certificate is not null && Validate(certificate, ca);
            })));

        IsConfigured = true;
    }

    public static bool IsValidClientCertificate(X509Certificate2 certificate)
    {
        try
        {
            var ca = clientCa;
            return ca is not null && Validate(certificate, ca);
        }
        catch
        {
            return false;
        }
    }

    public static bool Validate(X509Certificate2? certificate, X509Certificate2 ca)
    {
        if (certificate is null)
        {
            return false;
        }

        using var chain = new X509Chain();
        chain.ChainPolicy.TrustMode = X509ChainTrustMode.CustomRootTrust;
        chain.ChainPolicy.CustomTrustStore.Add(ca);
        chain.ChainPolicy.RevocationMode = X509RevocationMode.NoCheck;
        // Restrict the chain for the purpose for which this API accepts a
        // client certificate. No machine or OS trust store is modified.
        chain.ChainPolicy.ApplicationPolicy.Add(new Oid("1.3.6.1.5.5.7.3.2"));
        return chain.Build(certificate);
    }
}
