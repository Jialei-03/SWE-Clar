using System.Security.Cryptography.X509Certificates;
using System.Text.Json;

var builder = WebApplication.CreateBuilder(args);
builder.Logging.ClearProviders();
CertificateSetup.Configure(builder);
var database = new DatabaseSetup(Environment.GetEnvironmentVariable("MARIADB_CONNECTION") ?? string.Empty);
var app = builder.Build();

IResult Error(string code, int status = 400) => Results.Json(new { error = code }, statusCode: status);

app.MapGet("/health", async () =>
{
    try
    {
        var ids = await database.History();
        return Results.Json(new
        {
            database_connected = true,
            migration_count = ids.Count,
            tls_configured = CertificateSetup.IsConfigured
        });
    }
    catch
    {
        // Do not return exception text: connection exceptions can contain
        // configuration details. A failed probe is not a connected database.
        return Results.Json(new
        {
            database_connected = false,
            migration_count = 0,
            tls_configured = CertificateSetup.IsConfigured
        });
    }
});

app.MapPost("/connect", async (HttpRequest request) =>
{
    JsonElement body;
    try
    {
        body = await request.ReadFromJsonAsync<JsonElement>();
    }
    catch (JsonException)
    {
        return Error("database_connection_failed");
    }
    catch (BadHttpRequestException)
    {
        return Error("database_connection_failed");
    }
    catch
    {
        return Error("database_connection_failed");
    }

    if (body.ValueKind != JsonValueKind.Object ||
        !body.TryGetProperty("provider", out var provider) ||
        provider.ValueKind != JsonValueKind.String ||
        !string.Equals(provider.GetString(), "MariaDB", StringComparison.OrdinalIgnoreCase))
    {
        return Error("database_connection_failed");
    }

    try
    {
        await using var connection = await database.Open();
        return Results.Json(new { connected = true, provider = "mariadb" });
    }
    catch
    {
        return Error("database_connection_failed", 503);
    }
});

app.MapPost("/migrations", async (HttpRequest request) =>
{
    string[]? ids;
    try
    {
        ids = await request.ReadFromJsonAsync<string[]>();
    }
    catch (JsonException)
    {
        return Error("invalid_migrations");
    }
    catch (BadHttpRequestException)
    {
        return Error("invalid_migrations");
    }
    catch
    {
        return Error("invalid_migrations");
    }

    try
    {
        var result = await database.Apply(ids);
        return Results.Json(new { applied = result.Applied, all = result.All });
    }
    catch (ArgumentException)
    {
        return Error("invalid_migrations");
    }
    catch
    {
        return Error("migration_failed", 503);
    }
});

app.MapGet("/samples", async () =>
{
    try
    {
        return Results.Json(await database.Samples());
    }
    catch
    {
        return Error("api_not_ready", 503);
    }
});

app.MapGet("/secure", async (HttpContext context) =>
{
    // AllowCertificate makes the TLS client certificate optional for the
    // connection. It is mandatory for this route, and is checked from the
    // TLS connection rather than from request headers.
    X509Certificate2? certificate;
    try
    {
        certificate = context.Connection.ClientCertificate ??
            await context.Connection.GetClientCertificateAsync();
    }
    catch
    {
        return Error("certificate_required", 403);
    }

    if (certificate is null || !CertificateSetup.IsValidClientCertificate(certificate))
    {
        return Error("certificate_required", 403);
    }

    try
    {
        var history = await database.History();
        return Results.Json(new { message = "certificate accepted", migration_count = history.Count });
    }
    catch
    {
        return Error("api_not_ready", 503);
    }
});

app.MapFallback(() => Error("unknown_endpoint", 404));
app.Run();
