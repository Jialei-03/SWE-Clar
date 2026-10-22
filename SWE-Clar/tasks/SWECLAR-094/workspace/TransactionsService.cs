using System.Text.Json;
public sealed class TransactionsService(Storage storage, string[] autoRemoveTypes) {
    public ApiResponse Execute(string method,string path,JsonElement body,string requestId) {
        // The HTTP host and database schema are ready. Implement the transaction/note service.
        return new ApiResponse(404, JsonSerializer.Serialize(new { error="route_not_found" }));
    }
}
