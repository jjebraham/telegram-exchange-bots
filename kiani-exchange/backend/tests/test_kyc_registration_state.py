from app import database


def test_level1_user_cannot_be_marked_fully_approved(tmp_path, monkeypatch):
    db_path = tmp_path / "users.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))

    database.init_db()

    # Reproduce the legacy registration write: the API used to insert
    # kyc_status='Approved' while the numeric verification level was still 1.
    with database.get_db() as conn:
        conn.execute(
            "INSERT INTO users (id, phone_number, kyc_status, verification_level) VALUES (?, ?, ?, ?)",
            (1, "09120000001", "Approved", 1),
        )
        level1 = conn.execute(
            "SELECT kyc_status, verification_level FROM users WHERE id = 1"
        ).fetchone()

    assert level1["kyc_status"] == "Pending"
    assert level1["verification_level"] == 1

    # The real admin KYC approval path raises the level and marks the user
    # Approved. The guard must not undo a legitimate Level 2 approval.
    with database.get_db() as conn:
        conn.execute(
            "UPDATE users SET verification_level = 2, kyc_status = 'Approved' WHERE id = 1"
        )
        level2 = conn.execute(
            "SELECT kyc_status, verification_level FROM users WHERE id = 1"
        ).fetchone()

    assert level2["kyc_status"] == "Approved"
    assert level2["verification_level"] == 2
