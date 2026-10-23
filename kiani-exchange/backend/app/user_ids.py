"""Keep user IDs increasing so deleted accounts' login tokens cannot match new users."""


def initialize(connection):
    connection.execute('''CREATE TABLE IF NOT EXISTS user_id_sequences (
        name TEXT PRIMARY KEY, last_id INTEGER NOT NULL CHECK (last_id >= 0))''')
    connection.execute("INSERT OR IGNORE INTO user_id_sequences(name,last_id) VALUES ('users',0)")
    connection.execute('''UPDATE user_id_sequences
        SET last_id=MAX(last_id,(SELECT COALESCE(MAX(id),0) FROM users)) WHERE name='users' ''')


def allocate_user_id(connection):
    # The caller holds a write transaction through the user INSERT and commit.
    initialize(connection)
    connection.execute("UPDATE user_id_sequences SET last_id=last_id+1 WHERE name='users'")
    return int(connection.execute("SELECT last_id FROM user_id_sequences WHERE name='users'").fetchone()[0])
