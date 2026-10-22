using MySqlConnector;

public sealed class DatabaseSetup(string connectionString)
{
    private readonly SemaphoreSlim gate = new(1, 1);

    public static readonly string[] MigrationIds =
    [
        "001_create_samples",
        "002_add_category",
        "003_index_category"
    ];

    private static readonly string[] MigrationSql =
    [
        "CREATE TABLE IF NOT EXISTS samples (id VARCHAR(80) PRIMARY KEY,name VARCHAR(160) NOT NULL)",
        "ALTER TABLE samples ADD COLUMN IF NOT EXISTS category VARCHAR(80) NOT NULL DEFAULT 'general'",
        "CREATE INDEX IF NOT EXISTS sample_category ON samples(category)"
    ];

    public async Task<MySqlConnection> Open()
    {
        var connection = new MySqlConnection(connectionString);
        try
        {
            await connection.OpenAsync();
            await using var versionCommand = new MySqlCommand("SELECT VERSION()", connection);
            var version = Convert.ToString(await versionCommand.ExecuteScalarAsync()) ?? string.Empty;

            // A connection succeeding is not enough: the configured endpoint must
            // actually be a MariaDB server.
            if (!version.Contains("MariaDB", StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidOperationException("provider_mismatch");
            }

            return connection;
        }
        catch
        {
            await connection.DisposeAsync();
            throw;
        }
    }

    private static async Task EnsureHistory(MySqlConnection connection)
    {
        await using var command = new MySqlCommand(
            "CREATE TABLE IF NOT EXISTS schema_migrations (sequence_id INT AUTO_INCREMENT PRIMARY KEY, migration_id VARCHAR(80) NOT NULL UNIQUE)",
            connection);
        await command.ExecuteNonQueryAsync();
    }

    private static async Task<bool> HistoryTableExists(MySqlConnection connection)
    {
        await using var command = new MySqlCommand(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = 'schema_migrations'",
            connection);
        var value = await command.ExecuteScalarAsync();
        return Convert.ToInt64(value) != 0;
    }

    private static async Task<List<string>> ReadHistory(MySqlConnection connection)
    {
        var rows = new List<string>();
        await using var command = new MySqlCommand(
            "SELECT migration_id FROM schema_migrations ORDER BY sequence_id",
            connection);
        await using var reader = await command.ExecuteReaderAsync();
        while (await reader.ReadAsync())
        {
            rows.Add(reader.GetString(0));
        }

        return rows;
    }

    private static async Task<List<string>> ReadExistingHistory(MySqlConnection connection)
    {
        return await HistoryTableExists(connection)
            ? await ReadHistory(connection)
            : [];
    }

    public async Task<List<string>> History()
    {
        await gate.WaitAsync();
        try
        {
            await using var connection = await Open();
            await EnsureHistory(connection);
            return await ReadHistory(connection);
        }
        finally
        {
            gate.Release();
        }
    }

    public async Task<(List<string> Applied, List<string> All)> Apply(string[]? ids)
    {
        // Validate everything that can be validated without touching the
        // database first. In particular, malformed batches never apply an
        // earlier item from the same request.
        ValidateRequestShape(ids);

        await gate.WaitAsync();
        try
        {
            await using var connection = await Open();
            var existing = await ReadExistingHistory(connection);
            ValidateHistory(existing);
            ValidateAgainstHistory(ids!, existing);

            if (ids!.Length == 0)
            {
                return ([], existing);
            }

            var applied = new List<string>();
            var appliedSet = existing.ToHashSet(StringComparer.Ordinal);
            var hasNewMigration = ids.Any(id => !appliedSet.Contains(id));

            if (!hasNewMigration)
            {
                return (applied, existing);
            }

            // MariaDB DDL commits independently. Run each statement and add
            // its history row only after the statement succeeds. If a process
            // stops between those operations, the idempotent statement can be
            // safely retried on the next request.
            await EnsureHistory(connection);
            foreach (var id in ids)
            {
                if (appliedSet.Contains(id))
                {
                    continue;
                }

                var index = Array.IndexOf(MigrationIds, id);
                await using (var command = new MySqlCommand(MigrationSql[index], connection))
                {
                    await command.ExecuteNonQueryAsync();
                }

                await using (var command = new MySqlCommand(
                    "INSERT INTO schema_migrations (migration_id) VALUES (@migration_id)", connection))
                {
                    command.Parameters.AddWithValue("@migration_id", id);
                    await command.ExecuteNonQueryAsync();
                }

                appliedSet.Add(id);
                existing.Add(id);
                applied.Add(id);
            }

            return (applied, existing);
        }
        finally
        {
            gate.Release();
        }
    }

    public async Task<List<Dictionary<string, string>>> Samples()
    {
        await gate.WaitAsync();
        try
        {
            await using var connection = await Open();
            var rows = new List<Dictionary<string, string>>();
            await using var command = new MySqlCommand(
                "SELECT id, name, category FROM samples ORDER BY id",
                connection);
            await using var reader = await command.ExecuteReaderAsync();
            while (await reader.ReadAsync())
            {
                rows.Add(new Dictionary<string, string>
                {
                    ["id"] = reader.GetString(0),
                    ["name"] = reader.GetString(1),
                    ["category"] = reader.GetString(2)
                });
            }

            return rows;
        }
        finally
        {
            gate.Release();
        }
    }

    private static void ValidateRequestShape(string[]? ids)
    {
        if (ids is null)
        {
            throw new ArgumentException("migration list is required");
        }

        var seen = new HashSet<string>(StringComparer.Ordinal);
        var previousIndex = -1;
        foreach (var id in ids)
        {
            if (id is null)
            {
                throw new ArgumentException("migration id is required");
            }

            var index = Array.IndexOf(MigrationIds, id);
            if (index < 0 || !seen.Add(id))
            {
                throw new ArgumentException("invalid migration id");
            }

            // The request itself is an ordered migration batch. This also
            // prevents a replay from disguising an out-of-order new item.
            if (index <= previousIndex)
            {
                throw new ArgumentException("migrations are out of order");
            }

            previousIndex = index;
        }
    }

    private static void ValidateAgainstHistory(string[] ids, IReadOnlyList<string> history)
    {
        var applied = history.ToHashSet(StringComparer.Ordinal);
        var nextIndex = history.Count;
        foreach (var id in ids)
        {
            if (applied.Contains(id))
            {
                continue;
            }

            var index = Array.IndexOf(MigrationIds, id);
            if (index != nextIndex)
            {
                throw new ArgumentException("migration prefix is not contiguous");
            }

            nextIndex++;
        }
    }

    private static void ValidateHistory(IReadOnlyList<string> history)
    {
        if (history.Count > MigrationIds.Length)
        {
            throw new InvalidOperationException("invalid migration history");
        }

        for (var index = 0; index < history.Count; index++)
        {
            if (!string.Equals(history[index], MigrationIds[index], StringComparison.Ordinal))
            {
                throw new InvalidOperationException("invalid migration history");
            }
        }
    }
}
