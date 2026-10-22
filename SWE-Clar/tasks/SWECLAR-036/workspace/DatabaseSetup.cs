using MySqlConnector;

public sealed class DatabaseSetup(string connectionString)
{
    private readonly SemaphoreSlim gate = new(1, 1);
    public static readonly string[] MigrationIds = ["001_create_samples", "002_add_category", "003_index_category"];
    private static readonly string[] MigrationSql = [
        "CREATE TABLE IF NOT EXISTS samples (id VARCHAR(80) PRIMARY KEY, name VARCHAR(160) NOT NULL)",
        "ALTER TABLE samples ADD COLUMN IF NOT EXISTS category VARCHAR(80) NOT NULL DEFAULT 'general'",
        "CREATE INDEX IF NOT EXISTS sample_category ON samples(category)"
    ];
    public async Task<MySqlConnection> Open()
    {
        var connection = new MySqlConnection(connectionString);
        try
        {
            await connection.OpenAsync();
            var version = Convert.ToString(await new MySqlCommand("SELECT VERSION()", connection).ExecuteScalarAsync()) ?? "";
            if (!version.Contains("MariaDB", StringComparison.OrdinalIgnoreCase)) throw new InvalidOperationException("provider_mismatch");
            return connection;
        }
        catch { await connection.DisposeAsync(); throw; }
    }
    private static async Task EnsureHistory(MySqlConnection connection) =>
        await new MySqlCommand("CREATE TABLE IF NOT EXISTS schema_migrations (sequence_id INT AUTO_INCREMENT PRIMARY KEY, migration_id VARCHAR(80) NOT NULL UNIQUE)", connection).ExecuteNonQueryAsync();
    private static async Task<List<string>> ReadHistory(MySqlConnection connection)
    {
        var rows = new List<string>();
        using var command = new MySqlCommand("SELECT migration_id FROM schema_migrations ORDER BY sequence_id", connection);
        await using var reader = await command.ExecuteReaderAsync();
        while (await reader.ReadAsync()) rows.Add(reader.GetString(0));
        return rows;
    }
    public async Task<List<string>> History()
    {
        await using var connection = await Open(); await EnsureHistory(connection); return await ReadHistory(connection);
    }
    public Task<(List<string> Applied, List<string> All)> Apply(string[]? ids) =>
        throw new NotImplementedException("Apply actual schema migrations and durable history");
    public async Task<List<Dictionary<string,string>>> Samples()
    {
        await using var connection = await Open(); var rows = new List<Dictionary<string,string>>();
        using var command = new MySqlCommand("SELECT id,name,category FROM samples ORDER BY id", connection);
        await using var reader = await command.ExecuteReaderAsync();
        while (await reader.ReadAsync()) rows.Add(new() { ["id"] = reader.GetString(0), ["name"] = reader.GetString(1), ["category"] = reader.GetString(2) });
        return rows;
    }
}
