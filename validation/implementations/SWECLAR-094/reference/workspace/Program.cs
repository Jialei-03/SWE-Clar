using System.Text.Json;
var builder = WebApplication.CreateBuilder(args);
var app = builder.Build();
using var storage = new Storage(Environment.GetEnvironmentVariable("TRANSACTIONS_DB") ?? "transactions.sqlite");
var service = new TransactionsService(storage, (Environment.GetEnvironmentVariable("AUTO_REMOVE_NOTE_TYPES") ?? "").Split(',', StringSplitOptions.RemoveEmptyEntries));
app.MapGet("/health", () => Results.Json(new { ok = true }));
app.MapFallback(async (HttpContext context) => {
    JsonElement body = default;
    if (context.Request.Method == "POST") {
        try { using var document = await JsonDocument.ParseAsync(context.Request.Body); body = document.RootElement.Clone(); }
        catch (JsonException) { context.Response.StatusCode = 400; await context.Response.WriteAsJsonAsync(new { error = "invalid_json" }); return; }
    }
    var response = service.Execute(context.Request.Method, context.Request.Path.Value ?? "/", body, context.Request.Headers["Idempotency-Key"].ToString());
    context.Response.StatusCode = response.Status;
    context.Response.ContentType = "application/json";
    await context.Response.WriteAsync(response.Json);
});
app.Run();
