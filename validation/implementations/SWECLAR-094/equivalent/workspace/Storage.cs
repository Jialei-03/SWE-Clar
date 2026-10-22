using Microsoft.Data.Sqlite;
public sealed class Storage : IDisposable {
    public readonly SqliteConnection Connection;
    public readonly object Sync = new();
    public Storage(string path) {
        Connection = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = path }.ToString());
        Connection.Open();
        using var command = Connection.CreateCommand();
        command.CommandText = """
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS transactions (id TEXT PRIMARY KEY, amount REAL NOT NULL, type TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS notes (seq INTEGER PRIMARY KEY AUTOINCREMENT, transaction_id TEXT NOT NULL REFERENCES transactions(id), note_id TEXT NOT NULL, text TEXT NOT NULL, active INTEGER NOT NULL, UNIQUE(transaction_id,note_id));
            CREATE TABLE IF NOT EXISTS responses (request_id TEXT PRIMARY KEY, status INTEGER NOT NULL, body TEXT NOT NULL);
            """;
        command.ExecuteNonQuery();
    }
    public void Dispose() => Connection.Dispose();
}
public record ApiResponse(int Status, string Json);
