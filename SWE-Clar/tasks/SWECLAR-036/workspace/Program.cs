using System.Text.Json;
var builder = WebApplication.CreateBuilder(args);
builder.Logging.ClearProviders();
CertificateSetup.Configure(builder);
var database = new DatabaseSetup(Environment.GetEnvironmentVariable("MARIADB_CONNECTION")!);
var app = builder.Build();
IResult Error(string code, int status = 400) => Results.Json(new { error = code }, statusCode: status);
app.MapGet("/health", async () =>
{
    try { var ids = await database.History(); return Results.Json(new { database_connected = true, migration_count = ids.Count, tls_configured = true }); }
    catch { return Results.Json(new { database_connected = false, migration_count = 0, tls_configured = true }); }
});
app.MapPost("/connect", async (HttpRequest request) =>
{
    try
    {
        var body = await request.ReadFromJsonAsync<JsonElement>();
        if (!body.TryGetProperty("provider", out var provider) || provider.ValueKind != JsonValueKind.String || !string.Equals(provider.GetString(), "MariaDB", StringComparison.OrdinalIgnoreCase)) return Error("database_connection_failed");
        return Results.Json(new { connected = body.TryGetProperty("connection_ok", out var flag) && flag.ValueKind == JsonValueKind.True, provider = "mariadb" });
    }
    catch { return Error("database_connection_failed", 503); }
});
app.MapPost("/migrations", async (HttpRequest request) =>
{
    try
    {
        var ids = await request.ReadFromJsonAsync<string[]>(); var result = await database.Apply(ids);
        return Results.Json(new { applied = result.Applied, all = result.All });
    }
    catch (ArgumentException) { return Error("invalid_migrations"); }
    catch (JsonException) { return Error("invalid_migrations"); }
    catch (BadHttpRequestException) { return Error("invalid_migrations"); }
    catch { return Error("migration_failed", 503); }
});
app.MapGet("/samples", async () =>
{
    try { return Results.Json(await database.Samples()); }
    catch { return Error("api_not_ready", 503); }
});
app.MapGet("/secure", async (HttpContext context) =>
{
    // TODO: enforce the protected endpoint certificate requirement.
    try { return Results.Json(new { message = "certificate accepted", migration_count = (await database.History()).Count }); }
    catch { return Error("api_not_ready", 503); }
});
app.MapFallback(() => Error("unknown_endpoint", 404));
app.Run();
